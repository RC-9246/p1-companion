"""Additive scoped experience ledger in the already-backed-up affect DB."""
from contextlib import closing
import json,sqlite3,time
from .policy import checked,delivery_signal
class Store:
 def __init__(self,path):self.path=path
 def db(self):
  c=sqlite3.connect(self.path,timeout=4);c.row_factory=sqlite3.Row;return c
 def migrate(self):
  with closing(self.db()) as c,c:
   c.executescript('''
CREATE TABLE IF NOT EXISTS p1_learning_links(parent TEXT NOT NULL,child TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS p1_learning_meta(scope TEXT PRIMARY KEY,epoch INTEGER NOT NULL DEFAULT 1,enabled INTEGER NOT NULL DEFAULT 1,last_attempt REAL NOT NULL DEFAULT 0,last_seq INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS p1_learning_turns(seq INTEGER PRIMARY KEY AUTOINCREMENT,scope TEXT NOT NULL,event TEXT NOT NULL,speaker TEXT NOT NULL,text TEXT NOT NULL,reply TEXT NOT NULL,at REAL NOT NULL,UNIQUE(scope,event));
CREATE INDEX IF NOT EXISTS p1_learning_turn_scope ON p1_learning_turns(scope,seq);
CREATE TABLE IF NOT EXISTS p1_learning_items(id INTEGER PRIMARY KEY AUTOINCREMENT,scope TEXT NOT NULL,kind TEXT NOT NULL,key TEXT NOT NULL,value TEXT NOT NULL,status TEXT NOT NULL,confidence REAL NOT NULL,source TEXT NOT NULL,quote TEXT NOT NULL,speaker TEXT NOT NULL,seq INTEGER NOT NULL,updated REAL NOT NULL,revision INTEGER NOT NULL DEFAULT 1,shown INTEGER NOT NULL DEFAULT 0,UNIQUE(scope,kind,key));
CREATE TABLE IF NOT EXISTS p1_learning_evidence(scope TEXT NOT NULL,kind TEXT NOT NULL,key TEXT NOT NULL,value TEXT NOT NULL,source TEXT NOT NULL,speaker TEXT NOT NULL,at REAL NOT NULL,PRIMARY KEY(scope,kind,key,value,source));
CREATE TABLE IF NOT EXISTS p1_learning_revisions(id INTEGER PRIMARY KEY AUTOINCREMENT,item INTEGER NOT NULL,scope TEXT NOT NULL,old TEXT NOT NULL,action TEXT NOT NULL,at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS p1_learning_checks(scope TEXT NOT NULL,event TEXT NOT NULL,item INTEGER NOT NULL,revision INTEGER NOT NULL,signal INTEGER NOT NULL,at REAL NOT NULL,PRIMARY KEY(scope,event,item));
''')
 def meta(self,scope):
  checked(scope)
  with closing(self.db()) as c,c:
   c.execute('INSERT OR IGNORE INTO p1_learning_meta(scope) VALUES(?)',(scope,));return dict(c.execute('SELECT * FROM p1_learning_meta WHERE scope=?',(scope,)).fetchone())
 def record(self,scope,event,speaker,text,reply='',now=None):
  checked(scope);now=now or time.time()
  with closing(self.db()) as c,c:
   c.execute('INSERT OR IGNORE INTO p1_learning_meta(scope) VALUES(?)',(scope,))
   if not c.execute('SELECT enabled FROM p1_learning_meta WHERE scope=?',(scope,)).fetchone()[0]:return False
   cur=c.execute('INSERT OR IGNORE INTO p1_learning_turns(scope,event,speaker,text,reply,at) VALUES(?,?,?,?,?,?)',(scope,event,speaker,text[:1200],reply[:800],now));inserted=bool(cur.rowcount)
   c.execute('DELETE FROM p1_learning_turns WHERE scope=? AND (at<? OR seq NOT IN (SELECT seq FROM p1_learning_turns WHERE scope=? ORDER BY seq DESC LIMIT 100))',(scope,now-30*86400,scope))
   return inserted
 def claim(self,scope,urgent=False,shared=False,now=None):
  checked(scope);now=now or time.time()
  with closing(self.db()) as c,c:
   c.execute('BEGIN IMMEDIATE');m=c.execute('SELECT * FROM p1_learning_meta WHERE scope=?',(scope,)).fetchone()
   if not m or not m['enabled'] or now-m['last_attempt']<(60 if urgent else (3600 if shared else 1800)):return None
   count=c.execute('SELECT COUNT(*),MAX(seq) FROM p1_learning_turns WHERE scope=? AND seq>?',(scope,m['last_seq'])).fetchone()
   if not count[1] or (not urgent and count[0]<(24 if shared else 6)):return None
   c.execute('UPDATE p1_learning_meta SET last_attempt=?,last_seq=? WHERE scope=?',(now,count[1],scope));return m['epoch'],count[1],m['last_seq']
 def turns(self,scope,upper=None):
  checked(scope)
  with closing(self.db()) as c:return [dict(x) for x in reversed(c.execute('SELECT event AS id,seq,speaker,text,reply,at FROM p1_learning_turns WHERE scope=? AND seq<=? AND at>? ORDER BY seq DESC LIMIT 24',(scope,upper or 2**62,time.time()-30*86400)).fetchall())]
 def cards(self,scope,active=True):
  checked(scope)
  with closing(self.db()) as c:
   m=c.execute('SELECT enabled FROM p1_learning_meta WHERE scope=?',(scope,)).fetchone()
   if active and m and not m[0]:return []
   order="CASE kind WHEN 'preference' THEN 0 WHEN 'lesson' THEN 1 ELSE 2 END," if active else ''
   return [dict(x) for x in c.execute('SELECT * FROM p1_learning_items WHERE scope=? AND status '+("='active' AND updated>" if active else "!='revoked' AND updated>")+ '? ORDER BY '+order+'updated DESC,id DESC LIMIT 24',(scope,time.time()-90*86400))]
 def save(self,scope,epoch,items,now=None):
  checked(scope);now=now or time.time();saved=[]
  with closing(self.db()) as c,c:
   c.execute('BEGIN IMMEDIATE');m=c.execute('SELECT * FROM p1_learning_meta WHERE scope=?',(scope,)).fetchone()
   if not m or m['epoch']!=epoch or not m['enabled']:return []
   for v in sorted(items,key=lambda x:x['seq']):
    old=c.execute('SELECT * FROM p1_learning_items WHERE scope=? AND kind=? AND key=?',(scope,v['kind'],v['key'])).fetchone()
    if old and old['seq']>=v['seq']:continue
    c.execute('INSERT OR IGNORE INTO p1_learning_evidence VALUES(?,?,?,?,?,?,?)',(scope,v['kind'],v['key'],v['value'],v['source'],v['speaker'],now))
    status='active'
    if v['kind']=='correction':status='pending'
    if v['kind']=='jargon':
     distinct=c.execute('SELECT COUNT(DISTINCT speaker) FROM p1_learning_evidence WHERE scope=? AND kind=? AND key=? AND value=? AND at>?',(scope,v['kind'],v['key'],v['value'],now-30*86400)).fetchone()[0]
     status='active' if distinct>=2 else 'pending'
    if old and old['value']!=v['value'] and v['kind'] in ('jargon','correction'):status='pending'
    # Do not replace a useful active definition with an unreviewed conflicting one.
    if old and old['status']=='active' and status=='pending':continue
    if old:
     c.execute('INSERT INTO p1_learning_revisions(item,scope,old,action,at) VALUES(?,?,?,?,?)',(old['id'],scope,json.dumps(dict(old)),'learn',now))
     c.execute('UPDATE p1_learning_items SET value=?,status=?,confidence=?,source=?,quote=?,speaker=?,seq=?,updated=?,revision=revision+1 WHERE id=?',(v['value'],status,v['confidence'],v['source'],v['quote'],v['speaker'],v['seq'],now,old['id']));saved.append(old['id'])
    else:
     cur=c.execute('INSERT INTO p1_learning_items(scope,kind,key,value,status,confidence,source,quote,speaker,seq,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(scope,v['kind'],v['key'],v['value'],status,v['confidence'],v['source'],v['quote'],v['speaker'],v['seq'],now));saved.append(cur.lastrowid)
   c.execute('DELETE FROM p1_learning_evidence WHERE at<?',(now-90*86400,))
   c.execute('DELETE FROM p1_learning_revisions WHERE scope=? AND id NOT IN (SELECT id FROM p1_learning_revisions WHERE scope=? ORDER BY id DESC LIMIT 100)',(scope,scope))
  return saved
 def control(self,scope,action,item=0):
  checked(scope);self.meta(scope)
  with closing(self.db()) as c,c:
   c.execute('BEGIN IMMEDIATE');c.execute('UPDATE p1_learning_meta SET epoch=epoch+1 WHERE scope=?',(scope,))
   if action in ('on','off'):
    c.execute('UPDATE p1_learning_meta SET enabled=? WHERE scope=?',(int(action=='on'),scope));return True
   if action=='clear':
    for t in ('p1_learning_items','p1_learning_turns','p1_learning_evidence','p1_learning_revisions','p1_learning_checks'):c.execute('DELETE FROM '+t+' WHERE scope=?',(scope,))
    return True
   old=c.execute('SELECT * FROM p1_learning_items WHERE scope=? AND id=?',(scope,item)).fetchone()
   if not old:return False
   if action=='rollback':
    prev=c.execute("SELECT id,old FROM p1_learning_revisions WHERE scope=? AND item=? AND action='learn' ORDER BY id DESC LIMIT 1",(scope,item)).fetchone()
    if not prev:return False
    v=json.loads(prev['old']);c.execute("UPDATE p1_learning_revisions SET action='rolled' WHERE id=?",(prev['id'],));value,status,quote,source=v['value'],v['status'],v['quote'],v['source']
   elif action in ('forget','confirm'):value,status,quote,source=old['value'],'revoked' if action=='forget' else 'active',old['quote'],old['source']
   else:return False
   c.execute('INSERT INTO p1_learning_revisions(item,scope,old,action,at) VALUES(?,?,?,?,?)',(item,scope,json.dumps(dict(old)),action,time.time()))
   if action=='forget':c.execute('DELETE FROM p1_learning_checks WHERE scope=? AND item=?',(scope,item))
   # Keep the latest watermark so an older in-flight extraction cannot undo review.
   c.execute('UPDATE p1_learning_items SET value=?,status=?,quote=?,source=?,revision=revision+1,updated=? WHERE id=?',(value,status,quote,source,time.time(),item));return True
 def shown(self,scope,ids):
  checked(scope)
  with closing(self.db()) as c,c:
   for id in ids:c.execute('UPDATE p1_learning_items SET shown=shown+1 WHERE scope=? AND id=?',(scope,id))

 def observe_delivery(self,scope,event,cards,reply,prompt='',now=None):
  checked(scope);now=time.time() if now is None else now
  with closing(self.db()) as c,c:
   m=c.execute('SELECT enabled FROM p1_learning_meta WHERE scope=?',(scope,)).fetchone()
   if not m or not m[0]:return
   for card in cards:
    signal=delivery_signal(card['key'],card['value'],reply,prompt)
    if signal is None:continue
    # A reply prepared under a revoked/replaced revision cannot evaluate its replacement.
    current=c.execute("SELECT revision,status FROM p1_learning_items WHERE scope=? AND id=?",(scope,card['id'])).fetchone()
    if not current or current['status']!='active' or current['revision']!=card['revision']:continue
    c.execute('INSERT OR IGNORE INTO p1_learning_checks VALUES(?,?,?,?,?,?)',(scope,str(event)[:160],card['id'],card['revision'],int(signal),now))
   c.execute('DELETE FROM p1_learning_checks WHERE scope=? AND (at<? OR rowid NOT IN (SELECT rowid FROM p1_learning_checks WHERE scope=? ORDER BY at DESC LIMIT 500))',(scope,now-30*86400,scope))

 def effects(self,scope):
  checked(scope)
  with closing(self.db()) as c:
   return [dict(r) for r in c.execute("SELECT i.id,i.key,i.value,i.revision,COUNT(x.item) AS checked,COALESCE(SUM(x.signal),0) AS repeated FROM p1_learning_items i LEFT JOIN p1_learning_checks x ON x.scope=i.scope AND x.item=i.id AND x.revision=i.revision AND x.at>? WHERE i.scope=? AND i.status='active' GROUP BY i.id ORDER BY i.updated DESC",(time.time()-30*86400,scope))]

 def link(self,parent,child):
  checked(parent);checked(child)
  with closing(self.db()) as c,c:c.execute('INSERT OR IGNORE INTO p1_learning_links VALUES(?,?)',(parent,child))
 def group_scopes(self,parent):
  checked(parent)
  with closing(self.db()) as c:return [parent]+[r[0] for r in c.execute('SELECT child FROM p1_learning_links WHERE parent=?',(parent,))]
 def invalidate(self,scope,erase=False):
  checked(scope);self.meta(scope)
  if erase:return self.control(scope,'clear')
  with closing(self.db()) as c,c:c.execute('UPDATE p1_learning_meta SET epoch=epoch+1 WHERE scope=?',(scope,))

 def release(self,scope,epoch,upper,previous):
  checked(scope)
  with closing(self.db()) as c,c:c.execute('UPDATE p1_learning_meta SET last_seq=? WHERE scope=? AND epoch=? AND last_seq=?',(previous,scope,epoch,upper))
