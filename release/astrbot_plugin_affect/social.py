"""One persistent, conservative scheduler. No transport or model access in this module."""
from contextlib import closing
from datetime import datetime
import hashlib
import json
import secrets
import sqlite3
import re
from zoneinfo import ZoneInfo

from .appraisal import scrub
from .identity import make_identity_key

POLICY = dict(enabled=False, min_minutes=180, max_minutes=480, quiet_start=23,
              quiet_end=8, max_unanswered=2, max_daily=2, timezone='Asia/Shanghai')


def policy(path):
    p = dict(POLICY)
    try:
        v = json.loads(path.read_text())
        if type(v.get('enabled')) is bool:
            p['enabled'] = v['enabled']
    except (OSError, ValueError, TypeError):
        pass
    # Runtime model outputs cannot change frequency, quiet hours or recipient limits.
    return p


def in_quiet(now, p=POLICY):
    hour = datetime.fromtimestamp(now, ZoneInfo(p['timezone'])).hour
    return hour >= p['quiet_start'] or hour < p['quiet_end']


def interval():
    return secrets.SystemRandom().uniform(180 * 60, 480 * 60)

def requested_pause(text,appraisal):
    """Only reduce contact permission from a direct, semantically confirmed human boundary."""
    if (not isinstance(text,str) or appraisal.get('confidence',0)<.75
            or appraisal.get('intent')!='boundary' or appraisal.get('target')!='self' or appraisal.get('interaction',{}).get('need')!='space'):
        return None
    from .dialogue import FRAME
    if FRAME.search(text) or any(x in text for x in ('“','”','「','」','"','例如','假设','翻译','台词','引用','如果','假如','如何','怎么','```')):return None
    if not re.search(r'(?:不用|不要|别|不必).{0,8}(?:找我|联系我|打扰我|给我发消息|主动发消息)',text):return None
    for words,hours in ((('两天','2天'),48),(('三天','3天'),72),(('一周','7天'),168),(('今天','今晚','一天','1天'),24)):
        if any(x in text for x in words):return hours*3600
    return 'off' if any(x in text for x in ('以后','再也','关闭主动','不要再主动联系','别再主动联系')) else 24*3600


def valid_target(row, allowed):
    parts = row['umo'].split(':')
    return (len(parts) == 3 and parts[:2] == ['qq_snowluma', 'FriendMessage']
            and parts[2] == row['user_id'] and row['identity'] in allowed
            and make_identity_key('qq_snowluma', row['bot_id'], row['user_id']) == row['identity'])


def decide(raw, evidence, discoveries):
    """Strict JSON. A model can decline; it cannot invent supporting events or permissions."""
    if not isinstance(raw, str) or len(raw) > 6000:
        raise ValueError('invalid_decision')
    d = json.loads(raw)
    if (not isinstance(d, dict) or set(d) != {'contact','reason','evidence','message'}
            or type(d.get('contact')) is not bool):
        raise ValueError('invalid_decision')
    if not d['contact']:
        return {'contact': False, 'reason': 'quiet_choice', 'message': ''}
    if d.get('reason') not in ('follow_up', 'discovery'):
        raise ValueError('invalid_reason')
    ids = d.get('evidence')
    if (not isinstance(ids, list) or not 1 <= len(ids) <= 3
            or any(type(i) is not int or i < 0 or i >= len(evidence) for i in ids)):
        raise ValueError('unsupported_contact')
    if d['reason'] == 'discovery' and not discoveries:
        raise ValueError('unverified_discovery')
    text = d.get('message')
    if not isinstance(text, str) or not 1 <= len(text.strip()) <= 500 or scrub(text) != text:
        raise ValueError('invalid_message')
    if any(x in text for x in ('[[', '[P1-', '怎么不回', '为什么不回', '不理我', '必须回复', '你再不回')):
        raise ValueError('pressure_or_control')
    # URLs and browse claims require actual, matching browser evidence.
    import re
    urls = re.findall(r'https?://[^\s<>）)]+', text)
    if any(url.rstrip('。，,') not in {x['url'] for x in discoveries} for url in urls):
        raise ValueError('unverified_url')
    if not discoveries and any(x in text for x in ('我刚查', '我刚才查', '我刚看到', '刚才看到', '我搜到', '我浏览')):
        raise ValueError('unverified_browse_claim')
    if (discoveries and all(x.get('kind')=='search_snippet_not_full_page' for x in discoveries)
            and any(x in text for x in ('我读了原文','看完原文','我刚打开','我浏览了','我看完这篇'))):
        raise ValueError('search_is_not_full_page')
    if discoveries and all(x.get('kind')=='sampled_video_frames_only_not_audio' for x in discoveries) and any(x in text for x in ('看完视频','看完了视频','听到','听完','视频里说','视频讲解了')):
        raise ValueError('sampled_frames_are_not_audio_or_complete_video')
    return {'contact': True, 'reason': d['reason'], 'message': text.strip()}


class SocialStore:
    def __init__(self, path):
        self.path = path

    def db(self):
        c = sqlite3.connect(self.path, timeout=2)
        c.row_factory = sqlite3.Row
        return c

    def migrate(self):
        with closing(self.db()) as c, c:
            c.execute('CREATE TABLE IF NOT EXISTS companion_meta (key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            old=c.execute("SELECT value FROM companion_meta WHERE key='social_schema'").fetchone()
            if old and old[0]!='1':
                raise ValueError('unsupported_social_schema')
            c.execute("INSERT OR IGNORE INTO companion_meta VALUES ('social_schema','1')")
            c.executescript('''
            CREATE TABLE IF NOT EXISTS companion_social (
              identity TEXT PRIMARY KEY, umo TEXT NOT NULL, user_id TEXT NOT NULL, bot_id TEXT NOT NULL,
              enabled INTEGER NOT NULL DEFAULT 1, last_inbound REAL NOT NULL, version INTEGER NOT NULL DEFAULT 0,
              next_at REAL NOT NULL, unanswered INTEGER NOT NULL DEFAULT 0, lease_until REAL NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS companion_social_receipts (event TEXT PRIMARY KEY, at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS companion_social_outbox (
              id TEXT PRIMARY KEY, identity TEXT NOT NULL, version INTEGER NOT NULL, at REAL NOT NULL,
              state TEXT NOT NULL, reason TEXT NOT NULL, content TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS companion_watches (
              identity TEXT NOT NULL, url TEXT NOT NULL, last_hash TEXT NOT NULL DEFAULT '',
              checked_at REAL NOT NULL DEFAULT 0, PRIMARY KEY(identity,url));
            CREATE TABLE IF NOT EXISTS companion_contact_pauses(identity TEXT PRIMARY KEY,until_at REAL NOT NULL);
            ''')

    def enroll(self, identity, umo, user_id, bot_id, now):
        with closing(self.db()) as c, c:
            c.execute('INSERT OR IGNORE INTO companion_social(identity,umo,user_id,bot_id,last_inbound,next_at) VALUES (?,?,?,?,?,?)',
                      (identity, umo, user_id, bot_id, now, now + interval()))

    def observe(self, identity, umo, user_id, bot_id, event, now):
        self.enroll(identity, umo, user_id, bot_id, now)
        with closing(self.db()) as c, c:
            c.execute('BEGIN IMMEDIATE')
            fresh = c.execute('INSERT OR IGNORE INTO companion_social_receipts VALUES (?,?)', (event, now)).rowcount
            if fresh:
                c.execute('UPDATE companion_social SET last_inbound=?,version=version+1,next_at=?,unanswered=0 WHERE identity=?',
                          (now, now + interval(), identity))
            c.execute('DELETE FROM companion_social_receipts WHERE at<?', (now - 7 * 86400,))

    def get(self, identity):
        with closing(self.db()) as c:
            r = c.execute('SELECT * FROM companion_social WHERE identity=?', (identity,)).fetchone()
            return dict(r) if r else None

    def rows(self):
        with closing(self.db()) as c:
            return [dict(r) for r in c.execute('SELECT * FROM companion_social LIMIT 20')]

    def toggle(self, identity, enabled, now):
        with closing(self.db()) as c, c:
            c.execute('DELETE FROM companion_contact_pauses WHERE identity=?',(identity,))
            c.execute('UPDATE companion_social SET enabled=?,version=version+1,next_at=?,unanswered=0 WHERE identity=?',
                      (int(enabled), now + interval(), identity))

    def pause(self,identity,until):
        if type(until) not in (int,float) or not 0<until<253402300799:raise ValueError('invalid_pause')
        with closing(self.db()) as c,c:
            c.execute('INSERT INTO companion_contact_pauses VALUES(?,?) ON CONFLICT(identity) DO UPDATE SET until_at=MAX(until_at,excluded.until_at)',(identity,until))
            c.execute('UPDATE companion_social SET version=version+1 WHERE identity=?',(identity,))

    def paused_until(self,identity):
        with closing(self.db()) as c:
            row=c.execute('SELECT until_at FROM companion_contact_pauses WHERE identity=?',(identity,)).fetchone()
            return row[0] if row else 0

    def eligible(self, row, now, p, allowed, check_due=True):
        if (not p['enabled'] or not valid_target(row, allowed) or not row['enabled']
                or row['unanswered'] >= p['max_unanswered'] or in_quiet(now, p)
                or now - row['last_inbound'] < 180 * 60
                or (check_due and row['next_at'] > now)):
            return False
        with closing(self.db()) as c:
            pause=c.execute('SELECT until_at FROM companion_contact_pauses WHERE identity=?',(row['identity'],)).fetchone()
            if pause and pause[0]>now:return False
            n = c.execute("SELECT count(*) FROM companion_social_outbox WHERE identity=? AND at>? AND state IN ('reserved','sent','unknown')",
                          (row['identity'], now - 86400)).fetchone()[0]
        return n < p['max_daily']

    def claim(self, row, now):
        with closing(self.db()) as c, c:
            c.execute('BEGIN IMMEDIATE')
            return c.execute('UPDATE companion_social SET lease_until=? WHERE identity=? AND version=? AND lease_until<?',
                             (now + 120, row['identity'], row['version'], now)).rowcount == 1

    def defer(self, identity, now):
        with closing(self.db()) as c, c:
            c.execute('UPDATE companion_social SET next_at=?,lease_until=0 WHERE identity=?', (now + interval(), identity))
            c.execute("UPDATE companion_social_outbox SET state='unknown' WHERE state='reserved' AND at<?", (now - 120,))
            c.execute('DELETE FROM companion_social_outbox WHERE at<?', (now - 30 * 86400,))

    def reserve(self, row, decision, now):
        key = secrets.token_hex(16)
        with closing(self.db()) as c, c:
            c.execute('BEGIN IMMEDIATE')
            current = c.execute('SELECT * FROM companion_social WHERE identity=?', (row['identity'],)).fetchone()
            pause=c.execute('SELECT until_at FROM companion_contact_pauses WHERE identity=?',(row['identity'],)).fetchone()
            if pause and pause[0]>now:return None
            if (not current or current['version'] != row['version'] or not current['enabled']
                    or current['next_at'] != row['next_at'] or current['unanswered'] >= 2):
                return None
            count = c.execute("SELECT count(*) FROM companion_social_outbox WHERE identity=? AND at>? AND state IN ('reserved','sent','unknown')", (row['identity'], now - 86400)).fetchone()[0]
            if count >= 2:
                return None
            c.execute('INSERT INTO companion_social_outbox VALUES (?,?,?,?,?,?,?)',
                      (key, row['identity'], row['version'], now, 'reserved', decision['reason'], decision['message']))
            c.execute('UPDATE companion_social SET unanswered=unanswered+1,next_at=? WHERE identity=?',
                      (now + interval(), row['identity']))
        return key

    def finish(self, key, state):
        assert state in ('sent', 'unknown', 'cancelled')
        with closing(self.db()) as c, c:
            changed = c.execute("UPDATE companion_social_outbox SET state=? WHERE id=? AND state='reserved'", (state, key)).rowcount
            if changed and state == 'cancelled':
                c.execute('UPDATE companion_social SET unanswered=max(0,unanswered-1) WHERE identity=(SELECT identity FROM companion_social_outbox WHERE id=?)', (key,))

    def recent_sent(self, identity, now):
        with closing(self.db()) as c:
            return [dict(r) for r in c.execute("SELECT at,content FROM companion_social_outbox WHERE identity=? AND state='sent' AND at>? ORDER BY at DESC LIMIT 2", (identity, now - 7 * 86400))]

    def watches(self, identity):
        with closing(self.db()) as c:
            return [dict(r) for r in c.execute('SELECT * FROM companion_watches WHERE identity=? LIMIT 3', (identity,))]

    def watch(self, identity, url):
        with closing(self.db()) as c, c:
            count = c.execute('SELECT count(*) FROM companion_watches WHERE identity=?', (identity,)).fetchone()[0]
            if count >= 3:
                raise ValueError('watch_limit')
            c.execute('INSERT OR IGNORE INTO companion_watches(identity,url) VALUES (?,?)', (identity, url))

    def watched(self, identity, url, text, now):
        digest = hashlib.sha256(text.encode()).hexdigest()
        with closing(self.db()) as c, c:
            old = c.execute('SELECT last_hash FROM companion_watches WHERE identity=? AND url=?', (identity, url)).fetchone()
            c.execute('UPDATE companion_watches SET last_hash=?,checked_at=? WHERE identity=? AND url=?', (digest, now, identity, url))
            return bool(old and old[0] and old[0] != digest)
