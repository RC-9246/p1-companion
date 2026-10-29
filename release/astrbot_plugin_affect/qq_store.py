"""Additive QQ action ledger in the already-backed-up affect database."""
from contextlib import contextmanager
import hashlib,json,secrets,sqlite3,time
from pathlib import Path
from .qq_policy import reference,valid_target

class QQStore:
 def __init__(self,path):self.path=Path(path)
 @contextmanager
 def db(self):
  c=sqlite3.connect(self.path,timeout=4);c.row_factory=sqlite3.Row
  try:
   with c:yield c
  finally:c.close()
 def migrate(self):
  self.path.parent.mkdir(parents=True,exist_ok=True)
  with self.db() as c:c.executescript('''
CREATE TABLE IF NOT EXISTS p1_qq_targets(ref TEXT PRIMARY KEY,kind TEXT NOT NULL,bot TEXT NOT NULL,peer TEXT NOT NULL,identity TEXT NOT NULL,label TEXT NOT NULL,enabled INTEGER NOT NULL DEFAULT 1,generation INTEGER NOT NULL DEFAULT 1,next_at REAL NOT NULL,last_inbound REAL NOT NULL DEFAULT 0,last_outbound REAL NOT NULL DEFAULT 0,unanswered INTEGER NOT NULL DEFAULT 0,synced REAL NOT NULL,alive INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS p1_qq_messages(ref TEXT PRIMARY KEY,target TEXT NOT NULL,raw_id TEXT NOT NULL,sender TEXT NOT NULL,name TEXT NOT NULL,text TEXT NOT NULL,sensitive INTEGER NOT NULL,media INTEGER NOT NULL,sticker INTEGER NOT NULL,at REAL NOT NULL,UNIQUE(target,raw_id));
CREATE INDEX IF NOT EXISTS p1_qq_messages_target ON p1_qq_messages(target,at);
CREATE TABLE IF NOT EXISTS p1_qq_tombstones(target TEXT PRIMARY KEY,cleared_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS p1_qq_action_lanes(action TEXT PRIMARY KEY,lane TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS p1_qq_actions(id TEXT PRIMARY KEY,target TEXT NOT NULL,event TEXT NOT NULL,kind TEXT NOT NULL,at REAL NOT NULL,state TEXT NOT NULL,proactive INTEGER NOT NULL,receipt TEXT NOT NULL DEFAULT '',content TEXT NOT NULL DEFAULT '',UNIQUE(target,event,kind));
CREATE TABLE IF NOT EXISTS p1_qq_drafts(id TEXT PRIMARY KEY,owner TEXT NOT NULL,source TEXT NOT NULL,target TEXT NOT NULL,refs TEXT NOT NULL,expires REAL NOT NULL,state TEXT NOT NULL);
''')
  with self.db() as c:
   c.execute("UPDATE p1_qq_actions SET state='unknown' WHERE state='reserved' AND at<?",(time.time()-120,))
   c.execute('DELETE FROM p1_qq_actions WHERE at<?',(time.time()-30*86400,))
   c.execute('DELETE FROM p1_qq_action_lanes WHERE action NOT IN (SELECT id FROM p1_qq_actions)')
  self.path.chmod(0o600)
 def sync(self,targets,now,schedule):
  with self.db() as c:
   for r in targets:
    assert valid_target(r)
    c.execute('INSERT INTO p1_qq_targets(ref,kind,bot,peer,identity,label,next_at,synced) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(ref) DO UPDATE SET label=excluded.label,synced=excluded.synced,alive=1',(r['ref'],r['kind'],r['bot'],r['peer'],r['identity'],r['label'],schedule(r['kind']),now))
   refs={r['ref'] for r in targets}
   for row in c.execute('SELECT ref FROM p1_qq_targets WHERE alive=1').fetchall():
    if row[0] not in refs:c.execute('UPDATE p1_qq_targets SET alive=0,generation=generation+1 WHERE ref=? AND alive=1',(row[0],))
 def seed_legacy(self,row,legacy):
  if not legacy:return
  with self.db() as c:
   c.execute('UPDATE p1_qq_targets SET unanswered=?,last_inbound=? WHERE ref=?',(legacy['unanswered'],legacy['last_inbound'],row['ref']))
   for old in c.execute("SELECT * FROM companion_social_outbox WHERE identity=? AND at>? ORDER BY at DESC LIMIT 100",(row['identity'],time.time()-30*86400)).fetchall():
    id='legacy_'+hashlib.sha256(old['id'].encode()).hexdigest()[:20]
    c.execute('INSERT OR IGNORE INTO p1_qq_actions(id,target,event,kind,at,state,proactive,content) VALUES(?,?,?,?,?,?,?,?)',(id,row['ref'],'legacy:'+old['id'],'message',old['at'],old['state'],1,old['content']))
 def targets(self):
  with self.db() as c:return [dict(r) for r in c.execute('SELECT * FROM p1_qq_targets WHERE alive=1 ORDER BY next_at LIMIT 300')]
 def known_refs(self):
  with self.db() as c:return {r[0] for r in c.execute('SELECT ref FROM p1_qq_targets')}
 def target(self,ref):
  with self.db() as c:
   r=c.execute('SELECT * FROM p1_qq_targets WHERE ref=?',(ref,)).fetchone();return dict(r) if r else None
 def observe(self,target,raw_id,sender,name,text,sensitive,media,sticker,now,inbound=True,expected_generation=None):
  ref=reference('m',target,raw_id)
  with self.db() as c:
   c.execute('BEGIN IMMEDIATE')
   row=c.execute('SELECT generation FROM p1_qq_targets WHERE ref=?',(target,)).fetchone()
   tomb=c.execute('SELECT cleared_at FROM p1_qq_tombstones WHERE target=?',(target,)).fetchone()
   if (expected_generation is not None and (not row or row[0]!=expected_generation)) or (tomb and now<=tomb[0]):return None
   changed=c.execute('INSERT OR IGNORE INTO p1_qq_messages VALUES(?,?,?,?,?,?,?,?,?,?)',(ref,target,str(raw_id),str(sender),name,text,int(sensitive),int(media),int(sticker),now)).rowcount
   if changed and inbound:c.execute('UPDATE p1_qq_targets SET last_inbound=?,unanswered=0,generation=generation+1 WHERE ref=?',(now,target))
   c.execute('DELETE FROM p1_qq_messages WHERE at<?',(now-7*86400,))
   c.execute('DELETE FROM p1_qq_messages WHERE target=? AND ref NOT IN (SELECT ref FROM p1_qq_messages WHERE target=? ORDER BY at DESC LIMIT 100)',(target,target))
  return ref
 def clear_target(self,target):
  with self.db() as c:
   c.execute('BEGIN IMMEDIATE')
   c.execute('INSERT INTO p1_qq_tombstones VALUES(?,?) ON CONFLICT(target) DO UPDATE SET cleared_at=excluded.cleared_at',(target,time.time()))
   c.execute('UPDATE p1_qq_targets SET generation=generation+1,unanswered=0 WHERE ref=?',(target,))
   c.execute('DELETE FROM p1_qq_messages WHERE target=?',(target,))
   c.execute('DELETE FROM p1_qq_drafts WHERE source=? OR target=?',(target,target))
 def messages(self,target,limit=12):
  with self.db() as c:return list(reversed([dict(r) for r in c.execute('SELECT * FROM p1_qq_messages WHERE target=? ORDER BY at DESC LIMIT ?',(target,min(24,max(1,limit))))]))
 def message(self,ref):
  with self.db() as c:
   r=c.execute('SELECT * FROM p1_qq_messages WHERE ref=?',(ref,)).fetchone();return dict(r) if r else None
 def toggle(self,ref,enabled):
  with self.db() as c:c.execute('UPDATE p1_qq_targets SET enabled=?,generation=generation+1,unanswered=0 WHERE ref=?',(int(enabled),ref))
 def defer(self,ref,at):
  with self.db() as c:c.execute('UPDATE p1_qq_targets SET next_at=? WHERE ref=?',(at,ref))
 def eligible(self,row,now,p):
  if not row['enabled'] or row['next_at']>now or row['unanswered']>=p['max_unanswered']:return False
  if row['last_inbound'] and now-row['last_inbound']<(90 if row['kind']=='group' else 1800):return False
  return self.can_action(row,now,p,True)
 def can_action(self,row,now,p,proactive,kind='message',lane='background'):
  return self.block_reason(row,now,p,proactive,kind,lane) is None
 def block_reason(self,row,now,p,proactive=True,kind='message',lane='background'):
  with self.db() as c:
   all_rows=c.execute("SELECT a.target,a.at,COALESCE(l.lane,'background') AS lane FROM p1_qq_actions a LEFT JOIN p1_qq_action_lanes l ON a.id=l.action WHERE a.at>? AND a.state IN ('reserved','sent','unknown') AND a.proactive=1",(now-86400,)).fetchall()
   realtime=lane in ('interest','native') and row['kind']=='group'
   rows=[r for r in all_rows if (r['lane'] in ('interest','native'))==realtime]
   own=[r for r in rows if r['target']==row['ref']]
   if proactive and realtime:
    if len(own)>=p.get('interest_daily',999):return 'interest_daily_quota'
    if own and now-max(r['at'] for r in own)<p.get('interest_cooldown_seconds',90):return 'interest_cooldown'
    if sum(now-r['at']<120 for r in own)>=p.get('interest_per_120_seconds',2):return 'interest_short_rate'
    if sum(now-r['at']<60 for r in all_rows)>=p.get('account_proactive_per_minute',3):return 'account_short_rate'
   elif proactive:
    if len(rows)>=p['global_daily']:return 'background_global_quota'
    if len(own)>=p[row['kind']+'_daily']:return 'background_target_quota'
    if own and now-max(r['at'] for r in own)<p[row['kind']+'_min_minutes']*60:return 'background_target_interval'
    if rows and now-max(r['at'] for r in rows)<300:return 'background_account_interval'
   if kind=='favorite':
    if c.execute("SELECT COUNT(*) FROM p1_qq_actions WHERE kind='favorite' AND at>? AND state IN ('reserved','sent','unknown')",(now-86400,)).fetchone()[0]>=p['favorite_daily']:return 'favorite_quota'
   if c.execute("SELECT COUNT(*) FROM p1_qq_actions WHERE target=? AND at>? AND state IN ('reserved','sent','unknown')",(row['ref'],now-60)).fetchone()[0]>=4:return 'target_short_rate'
   return None
 def reserve(self,row,event,kind,now,p,proactive=False,content='',lane='background'):
  if lane not in ('background','interest','native','reminder'):raise ValueError('invalid_action_lane')
  with self.db() as c:
   c.execute('BEGIN IMMEDIATE');current=c.execute('SELECT * FROM p1_qq_targets WHERE ref=?',(row['ref'],)).fetchone()
   if not current or (proactive and not current['enabled']) or not current['alive'] or current['generation']!=row['generation']:return None
   if not self.can_action(row,now,p,proactive,kind,lane):return None
   if not proactive and c.execute("SELECT COUNT(*) FROM p1_qq_actions WHERE event=? AND state IN ('reserved','sent','unknown')",(event,)).fetchone()[0]>=2:return None
   id=secrets.token_hex(12)
   previous=c.execute('SELECT id,state FROM p1_qq_actions WHERE target=? AND event=? AND kind=?',(row['ref'],event,kind)).fetchone()
   if previous and previous['state']=='cancelled':
    id=previous['id'];c.execute("UPDATE p1_qq_actions SET at=?,state='reserved',receipt='',content=?,proactive=? WHERE id=?",(now,content,int(proactive),id))
   elif previous:return None
   else:
    try:c.execute('INSERT INTO p1_qq_actions(id,target,event,kind,at,state,proactive,content) VALUES(?,?,?,?,?,?,?,?)',(id,row['ref'],event,kind,now,'reserved',int(proactive),content))
    except sqlite3.IntegrityError:return None
   c.execute('INSERT INTO p1_qq_action_lanes VALUES(?,?) ON CONFLICT(action) DO UPDATE SET lane=excluded.lane',(id,lane))
   if proactive and lane not in ('interest','native'):c.execute('UPDATE p1_qq_targets SET unanswered=unanswered+1 WHERE ref=?',(row['ref'],))
   return id
 def finish(self,id,state,receipt='',now=None):
  assert state in ('sent','unknown','cancelled')
  with self.db() as c:
   row=c.execute("SELECT target,proactive FROM p1_qq_actions WHERE id=? AND state='reserved'",(id,)).fetchone()
   if not row:return
   c.execute("UPDATE p1_qq_actions SET state=?,receipt=? WHERE id=?",(state,str(receipt),id))
   if state=='sent':c.execute('UPDATE p1_qq_targets SET last_outbound=? WHERE ref=?',(time.time() if now is None else now,row['target']))
   lane=c.execute('SELECT lane FROM p1_qq_action_lanes WHERE action=?',(id,)).fetchone()
   if state=='cancelled' and row['proactive'] and (not lane or lane[0] not in ('interest','native')):c.execute('UPDATE p1_qq_targets SET unanswered=MAX(0,unanswered-1) WHERE ref=?',(row['target'],))
 def recent_sent(self,target):
  with self.db() as c:return [dict(r) for r in c.execute("SELECT content,at FROM p1_qq_actions WHERE target=? AND proactive=1 AND state='sent' ORDER BY at DESC LIMIT 3",(target,))]
 def draft(self,owner,source,target,refs,now):
  id=secrets.token_hex(6)
  with self.db() as c:
   c.execute('DELETE FROM p1_qq_drafts WHERE expires<?',(now,));c.execute('INSERT INTO p1_qq_drafts VALUES(?,?,?,?,?,?,?)',(id,owner,source,target,json.dumps(refs),now+600,'pending'))
  return id
 def claim_draft(self,id,owner,now):
  with self.db() as c:
   c.execute('BEGIN IMMEDIATE');r=c.execute("SELECT * FROM p1_qq_drafts WHERE id=? AND owner=? AND expires>? AND state='pending'",(id,owner,now)).fetchone()
   if not r:return None
   c.execute("UPDATE p1_qq_drafts SET state='claimed' WHERE id=?",(id,));return dict(r)
