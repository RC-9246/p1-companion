"""Persistent group-only data. Every content/state operation requires a group scope."""
import hashlib,json,math,os,re,sqlite3,statistics,time
from contextlib import contextmanager
from datetime import datetime
from zoneinfo import ZoneInfo
try:
    from ..astrbot_plugin_affect.reactions import REACTION_COOLDOWN_SECONDS,REACTION_MIN_TURNS
except ImportError:
    from astrbot_plugin_affect.reactions import REACTION_COOLDOWN_SECONDS,REACTION_MIN_TURNS

def scope_key(bot,group):
    if not str(bot) or not str(group):raise ValueError('group_scope_required')
    return 'g1:'+hashlib.sha256(json.dumps(['qq_snowluma',str(bot),str(group)],separators=(',',':')).encode()).hexdigest()
def event_key(scope,raw):return hashlib.sha256((scope+'\0'+str(raw)).encode()).hexdigest()[:24]
def checked(scope):
    if not isinstance(scope,str) or not re.fullmatch(r'g1:[0-9a-f]{64}',scope):raise ValueError('invalid_group_scope')
    return scope
def clean(text,limit=1000):
    try:
        from ..astrbot_plugin_affect.appraisal import scrub
    except ImportError:
        from astrbot_plugin_affect.appraisal import scrub
    return scrub(re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]','',str(text)))[:limit]
def stamp(at):
    return datetime.fromtimestamp(at,ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds') if at else None
def terms(text):
    text=str(text).lower();ch=''.join(re.findall(r'[\u4e00-\u9fff]',text))
    return set(re.findall(r'[a-z0-9_]{2,}',text))|{ch[i:i+2] for i in range(len(ch)-1)}

class Store:
    def __init__(self,path):self.path=__import__('pathlib').Path(path)
    @contextmanager
    def db(self):
        c=sqlite3.connect(self.path,timeout=4);c.row_factory=sqlite3.Row
        try:
            with c:yield c
        finally:c.close()
    def migrate(self):
        self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700);os.chmod(self.path.parent,0o700)
        with self.db() as c:
            c.execute('PRAGMA journal_mode=WAL')
            c.executescript('''
CREATE TABLE IF NOT EXISTS group_schema(version INTEGER NOT NULL);
INSERT INTO group_schema SELECT 1 WHERE NOT EXISTS(SELECT 1 FROM group_schema);
CREATE TABLE IF NOT EXISTS group_reactions(scope TEXT NOT NULL,event TEXT NOT NULL,asset TEXT NOT NULL,at REAL NOT NULL,turn INTEGER NOT NULL,status TEXT NOT NULL,PRIMARY KEY(scope,event));
CREATE TABLE IF NOT EXISTS group_meta(scope TEXT PRIMARY KEY,epoch INTEGER NOT NULL DEFAULT 1,hydrated INTEGER NOT NULL DEFAULT 0,last_seen REAL NOT NULL DEFAULT 0,last_bot REAL NOT NULL DEFAULT 0,last_member TEXT NOT NULL DEFAULT '',summary_at REAL NOT NULL DEFAULT 0,summary_seq INTEGER NOT NULL DEFAULT 0,attempt_at REAL NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS group_messages(seq INTEGER PRIMARY KEY AUTOINCREMENT,scope TEXT NOT NULL,event TEXT NOT NULL,speaker TEXT NOT NULL,display TEXT NOT NULL,role TEXT NOT NULL,text TEXT NOT NULL,at REAL,seen REAL NOT NULL,reply TEXT NOT NULL,mentions TEXT NOT NULL,source TEXT NOT NULL,UNIQUE(scope,event));
CREATE INDEX IF NOT EXISTS group_messages_scope ON group_messages(scope,seq);
CREATE TABLE IF NOT EXISTS group_notes(scope TEXT PRIMARY KEY,epoch INTEGER NOT NULL,at REAL NOT NULL,notes TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS group_persona(scope TEXT PRIMARY KEY,profile TEXT NOT NULL,state TEXT NOT NULL,updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS group_members(scope TEXT NOT NULL,member TEXT NOT NULL,state TEXT NOT NULL,updated REAL NOT NULL,PRIMARY KEY(scope,member));
CREATE TABLE IF NOT EXISTS group_affect_events(scope TEXT NOT NULL,event TEXT NOT NULL,at REAL NOT NULL,PRIMARY KEY(scope,event));
''')
        os.chmod(self.path,0o600)
    def meta(self,scope):
        checked(scope)
        with self.db() as c:
            row=c.execute('SELECT * FROM group_meta WHERE scope=?',(scope,)).fetchone()
            if row:return dict(row)
            c.execute('INSERT OR IGNORE INTO group_meta(scope) VALUES(?)',(scope,))
            return dict(c.execute('SELECT * FROM group_meta WHERE scope=?',(scope,)).fetchone())
    def add(self,scope,event,speaker,display,text,at=None,reply='',mentions=None,role='member',source='live',recipient='',expected_epoch=None):
        checked(scope);now=time.time()
        if at is not None and (isinstance(at,bool) or not math.isfinite(at) or not 0<at<=now+300):at=None
        if role not in ('member','saki'):raise ValueError('invalid_role')
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            c.execute('INSERT OR IGNORE INTO group_meta(scope) VALUES(?)',(scope,))
            if expected_epoch is not None and c.execute('SELECT epoch FROM group_meta WHERE scope=?',(scope,)).fetchone()[0]!=expected_epoch:return False
            out=c.execute('INSERT OR IGNORE INTO group_messages(scope,event,speaker,display,role,text,at,seen,reply,mentions,source) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                (scope,event,speaker,clean(display,24),role,clean(text),at,now,reply,json.dumps(mentions or []),source))
            inserted=bool(out.rowcount)
            if inserted:
                c.execute('UPDATE group_meta SET last_seen=? WHERE scope=?',(now,scope))
                if role=='saki' and source=='live':c.execute('UPDATE group_meta SET last_bot=?,last_member=? WHERE scope=?',(at or now,recipient,scope))
                c.execute('DELETE FROM group_messages WHERE scope=? AND seq NOT IN (SELECT seq FROM group_messages WHERE scope=? ORDER BY seq DESC LIMIT 500)',(scope,scope))
                c.execute('DELETE FROM group_messages WHERE scope=? AND seen<?',(scope,now-7*86400))
            return inserted
    def history(self,scope,query='',exclude='',now=None):
        checked(scope);now=time.time() if now is None else now
        with self.db() as c:
            rows=[dict(r) for r in c.execute('SELECT * FROM group_messages WHERE scope=? AND event!=? AND seen>=? ORDER BY seq DESC LIMIT 150',(scope,exclude,now-7*86400))]
            note=c.execute('SELECT n.notes,n.at FROM group_notes n JOIN group_meta m ON n.scope=m.scope AND n.epoch=m.epoch WHERE n.scope=?',(scope,)).fetchone()
        recent=list(reversed(rows[:24]));selected={r['event'] for r in recent};wanted=terms(query)
        for r in sorted(rows[24:],key=lambda r:len(terms(r['text'])&wanted),reverse=True)[:4]:
            if len(terms(r['text'])&wanted)>=2 and r['event'] not in selected:recent.append(r);selected.add(r['event'])
        recent.sort(key=lambda r:r['seq'])
        result=[];budget=0
        for r in reversed(recent):
            text=r['text'][:600]
            if budget+len(text)>6500:continue
            budget+=len(text)
            result.append({'id':r['event'],'seq':r['seq'],'speaker':r['speaker'],'name':r['display'],'role':r['role'],'text':text,'sent_at':stamp(r['at']),'seconds_ago':round(max(0,now-r['at'])) if r['at'] else None,'reply_to':r['reply'] or None,'mentions':json.loads(r['mentions']),'source':r['source']})
        result.reverse();timed=[r['at'] for r in reversed(rows) if r['at'] and r['source']=='live'];gaps=[b-a for a,b in zip(timed,timed[1:]) if 0<=b-a<3600]
        median=statistics.median(gaps[-20:]) if gaps else 30
        meta=self.meta(scope);notes=json.loads(note['notes']) if note and now-note['at']<30*86400 else []
        return {'messages':result,'notes':notes,'flow':{'median_gap_seconds':round(median,1),'messages_last_minute':sum(r['at'] is not None and 0<=now-r['at']<=60 for r in rows),'seconds_since_saki':round(now-meta['last_bot']) if meta['last_bot'] else None,'follow_window_seconds':min(600,max(60,45+median*3))},'epoch':meta['epoch'],'watermark':max((r['seq'] for r in rows),default=0)}
    def hydrated(self,scope,expected_epoch=None):
        checked(scope)
        with self.db() as c:c.execute('UPDATE group_meta SET hydrated=1 WHERE scope=? AND (? IS NULL OR epoch=?)',(scope,expected_epoch,expected_epoch))
    def bump(self,scope,erase=False):
        checked(scope)
        with self.db() as c:
            c.execute('UPDATE group_meta SET epoch=epoch+1 WHERE scope=?',(scope,))
            if erase:
                for table in ('group_messages','group_notes','group_persona','group_members','group_affect_events','group_reactions'):c.execute('DELETE FROM '+table+' WHERE scope=?',(scope,))
                c.execute("UPDATE group_meta SET hydrated=1,last_bot=0,last_member='',summary_at=0,summary_seq=0,attempt_at=0 WHERE scope=?",(scope,))
    def claim_summary(self,scope,now):
        checked(scope)
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE');m=c.execute('SELECT * FROM group_meta WHERE scope=?',(scope,)).fetchone()
            latest=c.execute('SELECT COALESCE(MAX(seq),0),COUNT(*) FROM group_messages WHERE scope=? AND seq>?',(scope,m['summary_seq'] if m else 0)).fetchone()
            if not m or latest[1]<24 or now-m['attempt_at']<900:return None
            batch=c.execute('SELECT seq FROM group_messages WHERE scope=? AND seq>? ORDER BY seq LIMIT 24',(scope,m['summary_seq'])).fetchall()
            c.execute('UPDATE group_meta SET attempt_at=? WHERE scope=?',(now,scope));return m['epoch'],batch[-1]['seq']
    def summary_batch(self,scope,epoch,through):
        checked(scope)
        with self.db() as c:
            m=c.execute('SELECT epoch,summary_seq FROM group_meta WHERE scope=?',(scope,)).fetchone()
            if not m or m['epoch']!=epoch:return None
            rows=c.execute('SELECT * FROM group_messages WHERE scope=? AND seq>? AND seq<=? ORDER BY seq',(scope,m['summary_seq'],through)).fetchall()
            notes=c.execute('SELECT notes FROM group_notes WHERE scope=? AND epoch=?',(scope,epoch)).fetchone()
        return {'messages':[{'id':r['event'],'seq':r['seq'],'speaker':r['speaker'],'name':r['display'],'role':r['role'],'text':r['text'],'sent_at':stamp(r['at']),'reply_to':r['reply'],'mentions':json.loads(r['mentions'])} for r in rows],'notes':json.loads(notes[0]) if notes else []}
    def save_notes(self,scope,epoch,seq,notes,now):
        checked(scope)
        with self.db() as c:
            if c.execute('SELECT epoch FROM group_meta WHERE scope=?',(scope,)).fetchone()[0]!=epoch:return False
            c.execute('INSERT INTO group_notes VALUES(?,?,?,?) ON CONFLICT(scope) DO UPDATE SET epoch=excluded.epoch,at=excluded.at,notes=excluded.notes',(scope,epoch,now,json.dumps(notes,ensure_ascii=False)))
            c.execute('UPDATE group_meta SET summary_at=?,summary_seq=? WHERE scope=?',(now,seq,scope));return True
    def affect(self,scope,member):
        checked(scope)
        with self.db() as c:
            group=c.execute('SELECT profile,state FROM group_persona WHERE scope=?',(scope,)).fetchone();person=c.execute('SELECT state FROM group_members WHERE scope=? AND member=?',(scope,member)).fetchone()
        return (json.loads(group['state']) if group else None,json.loads(person['state']) if person else None,json.loads(group['profile']) if group else None)
    def commit_affect(self,scope,event,member,group,person,profile,now,epoch):
        checked(scope)
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute('SELECT epoch FROM group_meta WHERE scope=?',(scope,)).fetchone()[0]!=epoch:return False
            if c.execute('INSERT OR IGNORE INTO group_affect_events VALUES(?,?,?)',(scope,event,now)).rowcount==0:return False
            c.execute('INSERT INTO group_persona VALUES(?,?,?,?) ON CONFLICT(scope) DO UPDATE SET profile=excluded.profile,state=excluded.state,updated=excluded.updated',(scope,json.dumps(profile),json.dumps(group),now))
            c.execute('INSERT INTO group_members VALUES(?,?,?,?) ON CONFLICT(scope,member) DO UPDATE SET state=excluded.state,updated=excluded.updated',(scope,member,json.dumps(person),now))
            c.execute('DELETE FROM group_members WHERE scope=? AND (updated<? OR member NOT IN (SELECT member FROM group_members WHERE scope=? ORDER BY updated DESC LIMIT 100))',(scope,now-30*86400,scope))
            c.execute('DELETE FROM group_affect_events WHERE scope=? AND at<?',(scope,now-30*86400));return True
    def counts(self,scope):
        checked(scope)
        with self.db() as c:return {k:c.execute('SELECT COUNT(*) FROM '+table+' WHERE scope=?',(scope,)).fetchone()[0] for k,table in (('messages','group_messages'),('members','group_members'),('personas','group_persona'))}
    def seed_affect(self,scope,profile,state,now):
        checked(scope);self.meta(scope)
        with self.db() as c:c.execute('INSERT OR IGNORE INTO group_persona VALUES(?,?,?,?)',(scope,json.dumps(profile),json.dumps(state),now))
    def can_react(self,scope,now):
        checked(scope)
        with self.db() as c:
            rows=c.execute('SELECT at,turn FROM group_reactions WHERE scope=? AND at>? ORDER BY at DESC',(scope,now-86400)).fetchall()
            row=c.execute('SELECT state FROM group_persona WHERE scope=?',(scope,)).fetchone();turns=json.loads(row[0])['interactions'] if row else 0
        return len(rows)<4 and (not rows or (now-rows[0]['at']>=REACTION_COOLDOWN_SECONDS and turns-rows[0]['turn']>=REACTION_MIN_TURNS))
    def recent_reactions(self,scope,limit=4):
        checked(scope)
        if type(limit) is not int or not 1<=limit<=8:raise ValueError('invalid_recent_limit')
        with self.db() as c:return [r[0] for r in c.execute('SELECT asset FROM group_reactions WHERE scope=? ORDER BY at DESC LIMIT ?',(scope,limit))]
    def reserve_reaction(self,scope,event,asset,now):
        checked(scope)
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            rows=c.execute('SELECT at,turn FROM group_reactions WHERE scope=? AND at>? ORDER BY at DESC',(scope,now-86400)).fetchall()
            row=c.execute('SELECT state FROM group_persona WHERE scope=?',(scope,)).fetchone();turns=json.loads(row[0])['interactions'] if row else 0
            if len(rows)>=4 or (rows and (now-rows[0]['at']<REACTION_COOLDOWN_SECONDS or turns-rows[0]['turn']<REACTION_MIN_TURNS)):return False
            return bool(c.execute('INSERT OR IGNORE INTO group_reactions VALUES(?,?,?,?,?,?)',(scope,event,asset,now,turns,'attempted')).rowcount)
    def reaction_done(self,scope,event,success):
        checked(scope)
        with self.db() as c:c.execute('UPDATE group_reactions SET status=? WHERE scope=? AND event=?',('delivered' if success else 'unknown',scope,event))

    def note_activity(self,scope,event,kind,topic,now,epoch):
        """A genuine scoped activity changes group mood, never member relationships."""
        checked(scope)
        if kind not in ('rest','reflection'):raise ValueError('unsupported_group_activity')
        try:from ..astrbot_plugin_affect.emotion_model import react
        except ImportError:from astrbot_plugin_affect.emotion_model import react
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT state FROM group_persona WHERE scope=?',(scope,)).fetchone()
            meta=c.execute('SELECT epoch FROM group_meta WHERE scope=?',(scope,)).fetchone()
            if not row or not meta or meta[0]!=epoch:return False
            if not c.execute('INSERT OR IGNORE INTO group_affect_events VALUES(?,?,?)',(scope,event,now)).rowcount:return False
            state,_=react(json.loads(row[0]),now,{'confidence':1},activity={'kind':kind,'topic':topic,'interest':.5})
            c.execute('UPDATE group_persona SET state=?,updated=? WHERE scope=?',(json.dumps(state),now,scope));return True
