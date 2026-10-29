"""Scoped durable agency. Additive schema; no permission data or model-written SQL."""
import hashlib,json,math,re,secrets,sqlite3,time
from contextlib import closing
from pathlib import Path

TOPICS={'animation':'动画 配乐 原画 分镜','reading':'读书 小说 文学 阅读','music':'音乐 配乐 钢琴 歌曲','cooking':'料理 做饭 食谱 烹饪','science':'科学 物理 储能 空调','technology':'技术 编程 电脑 软件','daily_life':'整理 生活 计划 学习','history':'历史 文物 博物馆'}
STATES={'queued','active','paused','blocked','done','abandoned','failed'}
TTL=7*86400

def clean(text,limit=2000):
 from .appraisal import scrub
 text=str(text)[:limit]
 return scrub(text)
def tokens(text):
 text=clean(text,12000).lower();words=re.findall(r'[a-z0-9_]{2,}|[\u3400-\u9fff]+',text);out=set()
 for w in words:
  if re.fullmatch(r'[\u3400-\u9fff]+',w):out.update(w[i:i+2] for i in range(len(w)-1))
  else:out.add(w)
 for group in (('配乐','音乐','bgm','ost'),('料理','做饭','烹饪','食谱'),('动画','动漫','animation'),('编程','代码','程序','code'),('失落','难过','伤心','sad'),('阅读','读书','小说','书籍'),('任务','目标','待办','项目')):
  if any(x in text for x in group):out.update(group)
 return out

def scoped(scope):
 if not isinstance(scope,str) or not re.fullmatch(r'(?:v1|g1):[0-9a-f]{64}',scope):raise ValueError('scope_required')
 return scope

class AgencyStore:
 def __init__(self,data):
  self.root=Path(data)/'agency';self.root.mkdir(mode=0o700,parents=True,exist_ok=True);self.path=self.root/'agency.db'
 def db(self):
  c=sqlite3.connect(self.path,timeout=2);c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON');c.execute('PRAGMA secure_delete=ON');return c
 def migrate(self):
  with closing(self.db()) as c,c:
   c.executescript('''PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS scope(scope TEXT PRIMARY KEY,level INTEGER NOT NULL DEFAULT 3,paused INTEGER NOT NULL DEFAULT 0,interest_join INTEGER NOT NULL DEFAULT 1,last_join REAL NOT NULL DEFAULT 0,next_at REAL NOT NULL DEFAULT 0,epoch INTEGER NOT NULL DEFAULT 0,preferences TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS interest(scope TEXT,topic TEXT,score REAL NOT NULL,evidence INTEGER NOT NULL,last REAL NOT NULL,PRIMARY KEY(scope,topic));
CREATE TABLE IF NOT EXISTS interest_evidence(scope TEXT NOT NULL,topic TEXT NOT NULL,ref TEXT NOT NULL,epoch INTEGER NOT NULL,at REAL NOT NULL,rating REAL NOT NULL,PRIMARY KEY(scope,topic,ref,epoch));
CREATE TABLE IF NOT EXISTS task(id TEXT PRIMARY KEY,scope TEXT NOT NULL,title TEXT NOT NULL,kind TEXT NOT NULL,status TEXT NOT NULL,priority INTEGER NOT NULL,step INTEGER NOT NULL DEFAULT 0,notes TEXT NOT NULL DEFAULT '',sources TEXT NOT NULL DEFAULT '[]',created REAL NOT NULL,updated REAL NOT NULL,due REAL NOT NULL DEFAULT 0,lease REAL NOT NULL DEFAULT 0,expires REAL NOT NULL DEFAULT 0,receipt TEXT NOT NULL DEFAULT '',epoch INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS task_scope ON task(scope,status,priority,updated);
CREATE TABLE IF NOT EXISTS task_control(id TEXT PRIMARY KEY,scope TEXT NOT NULL,epoch INTEGER NOT NULL,manual_hold INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS event(id TEXT PRIMARY KEY,scope TEXT NOT NULL,kind TEXT NOT NULL,text TEXT NOT NULL,source TEXT NOT NULL,at REAL NOT NULL,expires REAL NOT NULL DEFAULT 0,topic TEXT NOT NULL DEFAULT '',status TEXT NOT NULL DEFAULT 'observed',conflict TEXT NOT NULL DEFAULT '',epoch INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS event_scope ON event(scope,at);
CREATE TABLE IF NOT EXISTS document(id TEXT PRIMARY KEY,scope TEXT NOT NULL,name TEXT NOT NULL,ext TEXT NOT NULL,created REAL NOT NULL,expires REAL NOT NULL,bytes INTEGER NOT NULL,status TEXT NOT NULL,text TEXT NOT NULL,source TEXT NOT NULL,private INTEGER NOT NULL,epoch INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS document_coverage(id TEXT PRIMARY KEY,payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS document_lineage(scope TEXT NOT NULL,umo TEXT NOT NULL,digest TEXT NOT NULL,document TEXT NOT NULL,expires REAL NOT NULL,epoch INTEGER NOT NULL,PRIMARY KEY(scope,digest,document,epoch));
CREATE TABLE IF NOT EXISTS artifact(id TEXT PRIMARY KEY,scope TEXT NOT NULL,title TEXT NOT NULL,format TEXT NOT NULL,created REAL NOT NULL,expires REAL NOT NULL DEFAULT 0,sources TEXT NOT NULL,bytes INTEGER NOT NULL,epoch INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS action(id TEXT PRIMARY KEY,scope TEXT NOT NULL,kind TEXT NOT NULL,state TEXT NOT NULL,at REAL NOT NULL,seconds REAL NOT NULL DEFAULT 0,details TEXT NOT NULL DEFAULT '{}');
CREATE INDEX IF NOT EXISTS action_scope ON action(scope,at);
CREATE TABLE IF NOT EXISTS budget(day INTEGER PRIMARY KEY,ceiling INTEGER NOT NULL,used REAL NOT NULL DEFAULT 0,calls INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS topic(id TEXT PRIMARY KEY,scope TEXT NOT NULL,keywords TEXT NOT NULL,speaker TEXT NOT NULL,text TEXT NOT NULL,at REAL NOT NULL,count INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS feedback(id TEXT PRIMARY KEY,scope TEXT NOT NULL,rule TEXT NOT NULL,evidence TEXT NOT NULL,at REAL NOT NULL,expires REAL NOT NULL,active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS model_budget(day INTEGER PRIMARY KEY,used INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS model_budget_lanes(day INTEGER PRIMARY KEY,background INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS decision_health(scope TEXT NOT NULL,lane TEXT NOT NULL,reason TEXT NOT NULL,at REAL NOT NULL,checks INTEGER NOT NULL DEFAULT 1,PRIMARY KEY(scope,lane));
CREATE TABLE IF NOT EXISTS circuit(name TEXT PRIMARY KEY,failures INTEGER NOT NULL DEFAULT 0,until REAL NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS revoked_source(scope TEXT NOT NULL,id TEXT NOT NULL,at REAL NOT NULL,expires REAL NOT NULL,epoch INTEGER NOT NULL,PRIMARY KEY(scope,id));
''')
   c.execute("INSERT OR IGNORE INTO task_control SELECT id,scope,epoch,CASE WHEN status='paused' THEN 1 ELSE 0 END FROM task")
  self.path.chmod(0o600)
 def ensure(self,scope):
  scoped(scope)
  with closing(self.db()) as c:
   row=c.execute('SELECT * FROM scope WHERE scope=?',(scope,)).fetchone()
   if row and c.execute('SELECT COUNT(*) FROM interest WHERE scope=?',(scope,)).fetchone()[0]==len(TOPICS):return dict(row)
  with closing(self.db()) as c,c:
   c.execute('INSERT OR IGNORE INTO scope(scope) VALUES(?)',(scope,))
   for k in TOPICS:c.execute('INSERT OR IGNORE INTO interest VALUES(?,?,?,?,?)',(scope,k,.5,0,0))
   return dict(c.execute('SELECT * FROM scope WHERE scope=?',(scope,)).fetchone())
 def config(self,scope,**changes):
  self.ensure(scope)
  if any(k not in ('level','paused','interest_join') for k in changes):raise ValueError('not_a_control')
  for k,v in changes.items():
   if type(v) is not int or not 0<=v<=(3 if k=='level' else 1):raise ValueError('invalid_control')
  with closing(self.db()) as c,c:
   c.execute('BEGIN IMMEDIATE')
   if 'interest_join' in changes:
    cfg=dict(c.execute('SELECT * FROM scope WHERE scope=?',(scope,)).fetchone())
    routes=self._reply_routes(cfg);routes['p1']=changes['interest_join'];self._write_reply_routes(c,scope,cfg,routes)
   for k,v in changes.items():
    if k!='interest_join':c.execute('UPDATE scope SET '+k+'=? WHERE scope=?',(v,scope))
   cfg=c.execute('SELECT level,paused FROM scope WHERE scope=?',(scope,)).fetchone()
   if cfg['level']>=3 and not cfg['paused']:c.execute("UPDATE task SET status='queued',notes='',updated=? WHERE scope=? AND status='blocked' AND notes='blocked:level_3_required'",(time.time(),scope))
  return self.ensure(scope)
 @staticmethod
 def _reply_routes(cfg):
  default={'native':0,'p1':int(bool(cfg['interest_join'])),'interest':1,'background':1}
  try:p=json.loads(cfg['preferences'])
  except (ValueError,TypeError):return dict.fromkeys(default,0)
  if not isinstance(p,dict):return dict.fromkeys(default,0)
  if 'reply_routes_v1' not in p:return default
  r=p['reply_routes_v1']
  if not isinstance(r,dict) or set(r)!=set(default) or any(type(v) is not int or v not in (0,1) for v in r.values()):return dict.fromkeys(default,0)
  return dict(r)
 def reply_routes(self,scope):return self._reply_routes(self.ensure(scope))
 @staticmethod
 def _write_reply_routes(c,scope,cfg,routes):
  try:p=json.loads(cfg['preferences'])
  except (ValueError,TypeError):p={}
  if not isinstance(p,dict):p={}
  p['reply_routes_v1']=routes
  # A previous release ignores new controls. Keep its one-bit gate conservative
  # so reverting code cannot unexpectedly re-enable a disabled P1 sub-route.
  legacy=int(bool(routes['p1'] and routes['interest'] and routes['background']))
  c.execute('UPDATE scope SET preferences=?,interest_join=? WHERE scope=?',(json.dumps(p),legacy,scope))
 def route_config(self,scope,**changes):
  self.ensure(scope)
  if not changes or any(k not in ('native','p1','interest','background') or type(v) is not int or v not in (0,1) for k,v in changes.items()):raise ValueError('invalid_reply_route_control')
  with closing(self.db()) as c,c:
   c.execute('BEGIN IMMEDIATE');cfg=dict(c.execute('SELECT * FROM scope WHERE scope=?',(scope,)).fetchone())
   r=self._reply_routes(cfg);r.update(changes);self._write_reply_routes(c,scope,cfg,r)
  return self.reply_routes(scope)
 def preference(self,scope,key,value,expected_epoch=None):
  cfg=self.ensure(scope)
  if key=='pace_minutes' and type(value) is int and 8<=value<=30:pass
  elif key=='exploration' and type(value) in (int,float) and math.isfinite(value) and 0<=value<=1:pass
  elif key=='expression' and value in ('brief','balanced','listen_first'):pass
  else:raise ValueError('preference_not_allowed')
  with closing(self.db()) as c,c:
   c.execute('BEGIN IMMEDIATE');row=c.execute('SELECT preferences,epoch FROM scope WHERE scope=?',(scope,)).fetchone()
   if row['epoch']!=cfg['epoch'] or (expected_epoch is not None and row['epoch']!=expected_epoch):raise ValueError('scope_cleared')
   p=json.loads(row['preferences']);p[key]=value
   c.execute('UPDATE scope SET preferences=? WHERE scope=?',(json.dumps(p),scope))
  return p
 def interests(self,scope):
  self.ensure(scope)
  with closing(self.db()) as c:return [dict(r) for r in c.execute('SELECT topic,score,evidence,last FROM interest WHERE scope=? ORDER BY score DESC',(scope,))]
 def learn_interest(self,scope,topic,rating,evidence,expected_epoch=None):
  if topic not in TOPICS or type(rating) not in (int,float) or not math.isfinite(rating) or not 0<=rating<=1 or not evidence:raise ValueError('evidence_required')
  cfg=self.ensure(scope)
  with closing(self.db()) as c,c:
   c.execute('BEGIN IMMEDIATE');live=c.execute('SELECT epoch FROM scope WHERE scope=?',(scope,)).fetchone()
   if not live or live[0]!=cfg['epoch'] or (expected_epoch is not None and live[0]!=expected_epoch):raise ValueError('scope_cleared')
   added=c.execute('INSERT OR IGNORE INTO interest_evidence VALUES(?,?,?,?,?,?)',(scope,topic,hashlib.sha256(str(evidence).encode()).hexdigest(),live[0],time.time(),rating)).rowcount
   if not added:return False
   r=c.execute('SELECT score FROM interest WHERE scope=? AND topic=?',(scope,topic)).fetchone()
   c.execute('UPDATE interest SET score=?,evidence=evidence+1,last=? WHERE scope=? AND topic=?',(.9*r[0]+.1*rating,time.time(),scope,topic))
   c.execute('DELETE FROM interest_evidence WHERE scope=? AND at<?',(scope,time.time()-180*86400))
   return True
 def event(self,scope,kind,text,source,*,topic='',expires=0,status='observed',conflict='',expected_epoch=None):
  cfg=self.ensure(scope);text=clean(text);source=clean(source,300)
  if not text or not source:raise ValueError('source_required')
  if expected_epoch is not None and expected_epoch!=cfg['epoch']:raise ValueError('scope_cleared')
  key=hashlib.sha256(json.dumps([scope,kind,text,source],ensure_ascii=False).encode()).hexdigest()[:24]
  with closing(self.db()) as c,c:
   c.execute('BEGIN IMMEDIATE')
   current=c.execute('SELECT epoch FROM scope WHERE scope=?',(scope,)).fetchone()
   if not current or current[0]!=cfg['epoch']:raise ValueError('scope_cleared')
   if conflict:c.execute("UPDATE event SET status='superseded' WHERE scope=? AND epoch=? AND conflict=? AND status!='superseded'",(scope,cfg['epoch'],clean(conflict,80)))
   c.execute('INSERT OR IGNORE INTO event VALUES(?,?,?,?,?,?,?,?,?,?,?)',(key,scope,clean(kind,40),text,source,time.time(),expires,topic,status,clean(conflict,80),cfg['epoch']))
  return key
 def search(self,scope,query='',limit=8):
  cfg=self.ensure(scope);now=time.time();wanted=tokens(query)
  import heapq
  heap=[]
  with closing(self.db()) as c:
   cursor=c.execute("SELECT * FROM event WHERE scope=? AND epoch=? AND (expires=0 OR expires>?) AND status!='superseded'",(scope,cfg['epoch'],now))
   while True:
    chunk=cursor.fetchmany(256)
    if not chunk:break
    for x in chunk:
     row=dict(x);words=tokens(row['text'])
     if wanted and not words&wanted:continue
     weight=len(words&wanted)/max(1,len(wanted))+.12*2**(-max(0,now-row['at'])/604800)
     entry=(weight,row['id'],row)
     if len(heap)<max(1,min(limit,40))*4:heapq.heappush(heap,entry)
     elif entry[:2]>heap[0][:2]:heapq.heapreplace(heap,entry)
  rows=[x[2] for x in heap]
  for row in rows:
   words=tokens(row['text']);overlap=len(wanted&words)/max(1,len(wanted));source_weight=.06 if row['source'].startswith('delivered_exchange:') else (.04 if row['status']=='visited_page' or row['kind']=='experiment' else .01)
   row['relevance']=round(overlap+.12*2**(-(now-row['at'])/604800)+source_weight,3)
  ranked=sorted([r for r in rows if not wanted or tokens(r['text'])&wanted],key=lambda r:r['relevance'],reverse=True);selected=[];seen=set()
  for r in ranked:
   key=re.sub(r'\W+','',r['text'].lower())
   if key in seen:continue
   seen.add(key);selected.append(r)
   if len(selected)>=limit:break
  return selected
 def goal(self,scope,title,kind='research',priority=2,due=0,sources=None,expires=0,expected_epoch=None):
  cfg=self.ensure(scope)
  if kind not in ('research','reading','organize','reflection','experiment','reminder'):raise ValueError('invalid_goal')
  if type(priority) is not int or not 1<=priority<=5 or type(due) not in (int,float) or not math.isfinite(due) or due<0:raise ValueError('invalid_goal')
  if kind=='reminder' and not time.time()<due<=time.time()+366*86400:raise ValueError('reminder_time_required')
  title=clean(title,180).strip()
  if len(title)<2:raise ValueError('title_required')
  with closing(self.db()) as c,c:
   c.execute('BEGIN IMMEDIATE')
   live=c.execute('SELECT epoch FROM scope WHERE scope=?',(scope,)).fetchone()
   if not live or live[0]!=cfg['epoch'] or (expected_epoch is not None and live[0]!=expected_epoch):raise ValueError('scope_cleared')
   r=c.execute("SELECT id FROM task WHERE scope=? AND title=? AND status IN ('queued','active','paused')",(scope,title)).fetchone()
   if r:return r[0]
   if c.execute("SELECT COUNT(*) FROM task WHERE scope=? AND status IN ('queued','active','paused')",(scope,)).fetchone()[0]>=20:raise ValueError('too_many_goals')
   sources=list(dict.fromkeys(sources or []))
   docs=[]
   for source in sources:
    doc=c.execute('SELECT id,expires FROM document WHERE id=? AND scope=? AND epoch=? AND expires>?',(source,scope,cfg['epoch'],time.time())).fetchone()
    if not doc:raise ValueError('document_source_revoked')
    docs.append(doc)
   source_expiry=min((d['expires'] for d in docs),default=0)
   if source_expiry:expires=min(expires or source_expiry,source_expiry)
   key=secrets.token_hex(12);now=time.time();c.execute('INSERT INTO task(id,scope,title,kind,status,priority,sources,created,updated,due,expires,epoch) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(key,scope,title,kind,'queued',priority,json.dumps(sources or []),now,now,due,expires,cfg['epoch']));c.execute('INSERT INTO task_control VALUES(?,?,?,0)',(key,scope,cfg['epoch']));return key
 def due_reminders(self,scope,now=None):
  cfg=self.ensure(scope);now=time.time() if now is None else now
  with closing(self.db()) as c:return [dict(x) for x in c.execute("SELECT * FROM task WHERE scope=? AND epoch=? AND kind='reminder' AND (status='queued' OR (status='blocked' AND notes='blocked:delivery_policy' AND lease<=?)) AND due<=? AND (expires=0 OR expires>?) ORDER BY due LIMIT 4",(scope,cfg['epoch'],now,now,now))]
 def reschedule(self,scope,id,due):
  cfg=self.ensure(scope)
  if type(due) not in (int,float) or not math.isfinite(due) or not time.time()<due<=time.time()+366*86400:raise ValueError('reminder_time_required')
  with closing(self.db()) as c,c:
   c.execute('BEGIN IMMEDIATE')
   cur=c.execute("UPDATE task SET due=?,status='queued',notes='',lease=0,updated=? WHERE scope=? AND id=? AND epoch=? AND kind='reminder' AND status IN ('queued','paused','blocked')",(due,time.time(),scope,id,cfg['epoch']))
   if not cur.rowcount:raise ValueError('reminder_not_found_or_in_flight')
   return True
 def block_reminder(self,scope,id,reason):
  if reason not in ('level_3_required','delivery_policy'):raise ValueError('reminder_block_reason')
  with closing(self.db()) as c,c:c.execute("UPDATE task SET status='blocked',notes=?,lease=?,updated=? WHERE scope=? AND id=? AND kind='reminder'",('blocked:'+reason,time.time()+1800,time.time(),scope,id))
 def circuit_available(self,name,now=None):
  if name not in ('research','experiment','watch'):raise ValueError('circuit_name')
  now=time.time() if now is None else now
  with closing(self.db()) as c:
   r=c.execute('SELECT until FROM circuit WHERE name=?',(name,)).fetchone();return not r or r[0]<=now
 def circuit_result(self,name,ok,now=None):
  if name not in ('research','experiment','watch'):return
  now=time.time() if now is None else now
  with closing(self.db()) as c,c:
   c.execute('BEGIN IMMEDIATE');r=c.execute('SELECT failures FROM circuit WHERE name=?',(name,)).fetchone();failures=0 if ok else (r[0] if r else 0)+1
   until=0 if failures<3 else now+min(86400,300*2**min(failures-3,8))
   c.execute('INSERT INTO circuit VALUES(?,?,?) ON CONFLICT(name) DO UPDATE SET failures=excluded.failures,until=excluded.until',(name,failures,until))
 def task_current(self,scope,id,epoch,status):
  with closing(self.db()) as c:return c.execute('SELECT 1 FROM task t JOIN scope s ON t.scope=s.scope AND t.epoch=s.epoch WHERE t.scope=? AND t.id=? AND t.epoch=? AND t.status=? AND (t.expires=0 OR t.expires>?)',(scope,id,epoch,status,time.time())).fetchone() is not None
 def goals(self,scope):
  cfg=self.ensure(scope)
  with closing(self.db()) as c:return [dict(x) for x in c.execute('SELECT t.*,COALESCE(k.manual_hold,0) AS manual_hold FROM task t LEFT JOIN task_control k ON t.id=k.id AND t.epoch=k.epoch WHERE t.scope=? AND t.epoch=? AND (t.expires=0 OR t.expires>?) ORDER BY t.priority DESC,t.updated DESC LIMIT 40',(scope,cfg['epoch'],time.time()))]
 def planner_updates(self,scope,updates,epoch):
  if not isinstance(updates,list) or len(updates)>3:raise ValueError('invalid_goal')
  for item in updates:
   if not isinstance(item,dict) or not {'id','state','priority','note'}==set(item) or not re.fullmatch('[a-f0-9]{24}',str(item['id'])) or item['state'] not in ('queued','paused','abandoned') or type(item['priority']) is not int or not 1<=item['priority']<=5 or not isinstance(item['note'],str) or len(item['note'])>180:raise ValueError('invalid_goal')
  result=[];now=time.time()
  with closing(self.db()) as c,c:
   c.execute('BEGIN IMMEDIATE');cfg=c.execute('SELECT epoch,paused,level FROM scope WHERE scope=?',(scope,)).fetchone()
   if not cfg or cfg['epoch']!=epoch or cfg['paused'] or cfg['level']<2:raise ValueError('scope_cleared_or_paused')
   for item in updates:
    row=c.execute('SELECT t.*,COALESCE(k.manual_hold,0) AS manual_hold FROM task t LEFT JOIN task_control k ON t.id=k.id AND t.epoch=k.epoch WHERE t.id=? AND t.scope=? AND t.epoch=?',(item['id'],scope,epoch)).fetchone()
    reason='unavailable' if not row or row['kind']=='reminder' or row['status'] not in ('queued','paused','active') or row['expires'] and row['expires']<=now else 'manual_hold' if row['manual_hold'] else 'temporary_source' if any(not str(s).startswith('https://') for s in json.loads(row['sources'])) else 'in_flight' if row['status']=='active' and row['lease']>now-600 else ''
    if reason:result.append({'id':item['id'],'applied':False,'reason':reason});continue
    c.execute('UPDATE task SET status=?,priority=?,notes=?,lease=0,updated=? WHERE id=?',(item['state'],item['priority'],clean(item['note'],180),now,item['id']))
    c.execute('INSERT INTO task_control VALUES(?,?,?,0) ON CONFLICT(id) DO UPDATE SET manual_hold=0',(item['id'],scope,epoch));result.append({'id':item['id'],'applied':True})
  return result
 def update_goal(self,scope,id,state,notes='',sources=None,expected_epoch=None,manual_hold=None):
  cfg=self.ensure(scope)
  if state not in STATES:raise ValueError('invalid_state')
  with closing(self.db()) as c,c:
   c.execute('BEGIN IMMEDIATE')
   live=c.execute('SELECT epoch FROM scope WHERE scope=?',(scope,)).fetchone()[0]
   if live!=cfg['epoch'] or (expected_epoch is not None and live!=expected_epoch):raise ValueError('scope_cleared')
   r=c.execute('SELECT * FROM task WHERE scope=? AND id=? AND epoch=?',(scope,id,cfg['epoch'])).fetchone()
   if not r:raise ValueError('goal_not_found')
   edges=list(dict.fromkeys(sources if sources is not None else json.loads(r['sources'])))
   expiry=r['expires']
   for source in edges:
    if isinstance(source,str) and source.startswith('https://') and len(source)<=1000:continue
    doc=c.execute('SELECT expires FROM document WHERE id=? AND scope=? AND epoch=? AND expires>?',(source,scope,cfg['epoch'],time.time())).fetchone()
    if not doc:raise ValueError('document_source_revoked')
    expiry=min(expiry or doc[0],doc[0])
   c.execute('UPDATE task SET status=?,notes=?,sources=?,expires=?,step=step+1,updated=?,lease=? WHERE id=?',(state,clean(notes,3000),json.dumps(edges),expiry,time.time(),time.time() if state=='active' else 0,id))
   if manual_hold is not None:
    if type(manual_hold) is not bool:raise ValueError('invalid_goal')
    c.execute('INSERT INTO task_control VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET manual_hold=excluded.manual_hold',(id,scope,cfg['epoch'],int(manual_hold)))
 def topics(self,scope,speaker,text,now):
  self.ensure(scope);words=tokens(text);match=None
  with closing(self.db()) as c,c:
   recent=c.execute('SELECT * FROM topic WHERE scope=? AND at>? ORDER BY at DESC LIMIT 12',(scope,now-900)).fetchall()
   for row in recent:
    old=set(json.loads(row['keywords']));ratio=len(old&words)/max(1,min(len(old),len(words)))
    if (speaker==row['speaker'] and now-row['at']<12) or ratio>=.35:match=row;break
   id=match['id'] if match else secrets.token_hex(8)
   text=clean(((match['text']+' / ') if match and speaker==match['speaker'] and now-match['at']<12 else '')+text,1200)
   if match:c.execute('UPDATE topic SET keywords=?,speaker=?,text=?,at=?,count=count+1 WHERE id=?',(json.dumps(sorted(words)),speaker,text,now,id))
   else:c.execute('INSERT INTO topic VALUES(?,?,?,?,?,?,1)',(id,scope,json.dumps(sorted(words)),speaker,text,now))
   c.execute('DELETE FROM topic WHERE scope=? AND at<?',(scope,now-3600))
   return [dict(x) for x in c.execute('SELECT id,speaker,text,at,count FROM topic WHERE scope=? ORDER BY at DESC LIMIT 5',(scope,))]
 def reserve(self,scope,kind,seconds=120,*,energy=.5,curiosity=.5):
  cfg=self.ensure(scope);now=time.time();day=int((now+28800)//86400)
  if cfg['paused'] or cfg['level']<1:return None
  ceiling=int(18000+10800*max(0,min(1,(energy+curiosity)/2)))
  with closing(self.db()) as c,c:
   c.execute('BEGIN IMMEDIATE');c.execute('INSERT OR IGNORE INTO budget VALUES(?,?,0,0)',(day,ceiling));b=c.execute('SELECT * FROM budget WHERE day=?',(day,)).fetchone()
   if b['used']+seconds>b['ceiling'] or b['calls']>=120:return None
   key=secrets.token_hex(12);c.execute('UPDATE budget SET used=used+?,calls=calls+1 WHERE day=?',(seconds,day));c.execute('INSERT INTO action VALUES(?,?,?,?,?,?,?)',(key,scope,kind,'reserved',now,seconds,'{}'));return key
 def finish(self,id,state,seconds,details=None):
  if state not in ('complete','failed','interrupted','quiet','unknown'):raise ValueError('invalid_finish')
  with closing(self.db()) as c,c:
   c.execute('BEGIN IMMEDIATE');r=c.execute('SELECT * FROM action WHERE id=?',(id,)).fetchone()
   if not r or r['state']!='reserved':return
   charged=min(r['seconds'],max(0,seconds));day=int((r['at']+28800)//86400)
   c.execute('UPDATE budget SET used=MAX(0,used-?) WHERE day=?',(r['seconds']-charged,day));c.execute('UPDATE action SET state=?,seconds=?,details=? WHERE id=?',(state,charged,json.dumps(details or {},ensure_ascii=False),id))
 def set_day_hours(self,hours):
  if type(hours) not in (int,float) or not math.isfinite(hours) or not 5<=hours<=8:raise ValueError('daily_hours_5_to_8')
  day=int((time.time()+28800)//86400)
  with closing(self.db()) as c,c:
   c.execute('INSERT OR IGNORE INTO budget VALUES(?,?,0,0)',(day,int(hours*3600)))
   c.execute('UPDATE budget SET ceiling=MAX(CAST(used AS INTEGER),?) WHERE day=?',(int(hours*3600),day))
  return self.budget()
 def take_model_budget(self,limit=200,now=None,*,lane='foreground'):
  if type(limit) is not int or not 1<=limit<=200:raise ValueError('model_budget_limit')
  if lane not in ('foreground','background'):raise ValueError('model_budget_lane')
  day=int(((time.time() if now is None else now)+28800)//86400)
  with closing(self.db()) as c,c:
   c.execute('BEGIN IMMEDIATE');c.execute('INSERT OR IGNORE INTO model_budget VALUES(?,0)',(day,))
   # Preserve existing total use on migration; protect future real-time capacity.
   c.execute('INSERT OR IGNORE INTO model_budget_lanes VALUES(?,0)',(day,))
   if lane=='background' and c.execute('SELECT background FROM model_budget_lanes WHERE day=?',(day,)).fetchone()[0]>=40:return False
   n=c.execute('UPDATE model_budget SET used=used+1 WHERE day=? AND used<?',(day,limit)).rowcount
   if n and lane=='background':c.execute('UPDATE model_budget_lanes SET background=background+1 WHERE day=?',(day,))
   c.execute('DELETE FROM model_budget WHERE day<?',(day-8,));c.execute('DELETE FROM model_budget_lanes WHERE day<?',(day-8,));return bool(n)
 def budget(self):
  with closing(self.db()) as c:
   r=c.execute('SELECT * FROM budget WHERE day=?',(int((time.time()+28800)//86400),)).fetchone()
  return dict(r) if r else {'ceiling':18000,'used':0,'calls':0}
 def defer(self,scope,seconds):
  with closing(self.db()) as c,c:c.execute('UPDATE scope SET next_at=? WHERE scope=?',(time.time()+seconds,scope))
 def join(self,scope,now,commit=False):
  cfg=self.ensure(scope)
  routes=self._reply_routes(cfg)
  # Admission is not delivery. QQ's lane ledger owns quotas and cooldowns.
  return not (cfg['paused'] or cfg['level']<3 or not routes['p1'] or not routes['interest'])
 def diagnostic(self,scope,lane,reason):
  allowed={'admitted','quiet_hours','scope_or_lane_disabled','topic_not_available','model_budget','classifier_busy','classifier_rejected','classifier_unavailable','interest_daily_quota','interest_cooldown','interest_short_rate','account_short_rate','target_short_rate','background_global_quota','background_target_quota','background_target_interval','background_account_interval'}
  if reason not in allowed or lane not in ('interest','native','background'):raise ValueError('diagnostic_code')
  with closing(self.db()) as c,c:c.execute('INSERT INTO decision_health VALUES(?,?,?,?,1) ON CONFLICT(scope,lane) DO UPDATE SET reason=excluded.reason,at=excluded.at,checks=decision_health.checks+1',(scope,lane,reason,time.time()))
 def feedback(self,scope,rule,evidence):
  self.ensure(scope);rule=clean(rule,180);evidence=clean(evidence,400)
  rules={'brief':r'简短|短一点|少说|别太长|不要长篇','detailed':r'详细|展开|讲清|细一点','listen_first':r'先听|听完|别.{0,4}建议|不要.{0,4}建议','fewer_questions':r'(?:少|别|不要).{0,4}(?:追问|提问|问)','no_images':r'(?:不|别|不要).{0,6}(?:图|表情)','plain_qq':r'(?:不|别|不要).{0,6}(?:markdown|md|格式|修饰)'}
  rule={'先听完':'listen_first','先听':'listen_first','简短':'brief','详细':'detailed','少追问':'fewer_questions','不用图':'no_images','不要md':'plain_qq'}.get(rule,rule)
  if rule not in rules or not re.search(rules[rule],evidence,re.I):raise ValueError('closed_expression_rule_with_exact_evidence_required')
  key=secrets.token_hex(12)
  with closing(self.db()) as c,c:c.execute('INSERT INTO feedback VALUES(?,?,?,?,?,?,1)',(key,scope,rule,evidence,time.time(),time.time()+30*86400))
  return key
 def diagnostic_view(self,scope):
  cfg=self.ensure(scope);day=int((time.time()+28800)//86400)
  with closing(self.db()) as c:
   total=c.execute('SELECT used FROM model_budget WHERE day=?',(day,)).fetchone();background=c.execute('SELECT background FROM model_budget_lanes WHERE day=?',(day,)).fetchone()
   decisions=[dict(r) for r in c.execute('SELECT lane,reason,at,checks FROM decision_health WHERE scope=?',(scope,))]
   circuits=[dict(r) for r in c.execute('SELECT name,failures,until FROM circuit')]
  return {'control':cfg,'routes':self._reply_routes(cfg),'agency_model':{'used':total[0] if total else 0,'limit':200,'background_used':background[0] if background else 0,'background_limit':40,'day_basis':'Asia/Shanghai','normal_foreground_reply_counted_here':False},'last_decisions':decisions,'capability_circuits':circuits}
 def context(self,scope,query=''):
  cfg=self.ensure(scope)
  routes=self._reply_routes(cfg);cfg['interest_join']=routes['p1']
  with closing(self.db()) as c:
   feedback=[dict(x) for x in c.execute("SELECT id,rule,evidence,expires FROM feedback WHERE rule IN ('brief','detailed','listen_first','fewer_questions','no_images','plain_qq') AND scope=? AND active=1 AND expires>? ORDER BY at DESC LIMIT 5",(scope,time.time()))]
   actions=[dict(x) for x in c.execute('SELECT kind,state,at,seconds,details FROM action WHERE scope=? ORDER BY at DESC LIMIT 8',(scope,))]
   topics=[dict(x) for x in c.execute('SELECT id,speaker,text,at,count FROM topic WHERE scope=? AND at>? ORDER BY at DESC LIMIT 5',(scope,time.time()-1800))]
  goals=self.goals(scope)[:8]
  for g in goals:
   if any(not str(s).startswith('https://') for s in json.loads(g['sources'])):
    g['title']='临时附件关联任务';g['notes']='正文只通过有权限的临时文档/资料读取，不注入常规聊天或后台整理'
   else:g['notes']=g['notes'][:500]
  events=self.search(scope,query,5)
  for e in events:e['text']=e['text'][:600]
  with closing(self.db()) as c:has_cognition=c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='cognitive_item'").fetchone() is not None
  cognition=[]
  if has_cognition:
   from .experience import Experience
   cognition=Experience(self).view(scope,query,3)
  return {'control':cfg,'reply_routes':routes,'interests':self.interests(scope),'goals':goals,'events':events,'continuity':cognition,'explicit_feedback':feedback,'topics':topics,'recent_actions':actions,'shared_device_budget':self.budget()}
 def wipe(self,scope):
  self.ensure(scope)
  with closing(self.db()) as c,c:
   c.execute('BEGIN IMMEDIATE')
   epoch=c.execute('SELECT epoch FROM scope WHERE scope=?',(scope,)).fetchone()[0]
   for doc in c.execute('SELECT id,expires FROM document WHERE scope=?',(scope,)).fetchall():c.execute('INSERT OR REPLACE INTO revoked_source VALUES(?,?,?,?,?)',(scope,doc['id'],time.time(),doc['expires'],epoch))
   c.execute('DELETE FROM document_coverage WHERE id IN (SELECT id FROM document WHERE scope=?)',(scope,))
   c.execute('UPDATE scope SET epoch=epoch+1 WHERE scope=?',(scope,))
   for table in ('interest_evidence','interest','task_control','task','event','document','artifact','topic','feedback'):c.execute('DELETE FROM '+table+' WHERE scope=?',(scope,))
   tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
   for table in ('cognitive_item','cognitive_seen'):
    if table in tables:c.execute('DELETE FROM '+table+' WHERE scope=?',(scope,))
   c.execute("UPDATE action SET details='{}' WHERE scope=?",(scope,))
   import shutil
   shutil.rmtree(self.root/hashlib.sha256(scope.encode()).hexdigest(),ignore_errors=True)
 def document_lineage(self,scope):
  with closing(self.db()) as c:return [dict(r) for r in c.execute('SELECT digest,document,expires FROM document_lineage WHERE scope=?',(scope,))]
 def remember_document_reply(self,scope,umo,texts,sources,epoch):
  with closing(self.db()) as c,c:
   c.execute('BEGIN IMMEDIATE');live=c.execute('SELECT epoch FROM scope WHERE scope=?',(scope,)).fetchone()
   if not live or live[0]!=epoch:return False
   for source in sources:
    doc=c.execute('SELECT expires FROM document WHERE scope=? AND id=? AND epoch=? AND expires>?',(scope,source['id'],epoch,time.time())).fetchone()
    if not doc:continue
    for text in texts:
     if isinstance(text,str) and len(text.strip())>=30:c.execute('INSERT OR IGNORE INTO document_lineage VALUES(?,?,?,?,?,?)',(scope,str(umo),hashlib.sha256(text.encode()).hexdigest(),source['id'],doc[0],epoch))
   c.execute('DELETE FROM document_lineage WHERE scope=? AND expires<?',(scope,time.time()-90*86400));return True
 def revoked_sources(self,scope=None):
  with closing(self.db()) as c:
   rows=c.execute('SELECT id FROM revoked_source'+(' WHERE scope=?' if scope else ''),(scope,) if scope else ()).fetchall()
   return {r[0] for r in rows}
 def revoke_document(self,scope,id):
  with closing(self.db()) as c,c:
   c.execute('BEGIN IMMEDIATE');doc=c.execute('SELECT expires,epoch FROM document WHERE scope=? AND id=?',(scope,id)).fetchone()
   if not doc:return False
   c.execute('INSERT OR REPLACE INTO revoked_source VALUES(?,?,?,?,?)',(scope,id,time.time(),doc['expires'],doc['epoch']))
   c.execute("UPDATE document SET expires=1,status='revoked' WHERE scope=? AND id=?",(scope,id))
   doomed={id,'document:'+id};rows=[]
   for table in ('artifact','task'):
    rows.extend((table,dict(r)) for r in c.execute('SELECT id,sources FROM '+table+' WHERE scope=?',(scope,)))
   changed=True
   while changed:
    changed=False
    for table,row in rows:
     if row['id'] in doomed:continue
     if any(x in doomed for x in json.loads(row['sources'])):
      doomed.update((row['id'],table+':'+row['id']));changed=True
      c.execute('UPDATE '+table+' SET expires=1 WHERE scope=? AND id=?',(scope,row['id']))
   for source in doomed:c.execute('DELETE FROM event WHERE scope=? AND source=?',(scope,source))
   return True
 def directory(self,scope):
  self.ensure(scope);p=self.root/hashlib.sha256(scope.encode()).hexdigest();p.mkdir(mode=0o700,exist_ok=True);return p
 def cleanup(self,now=None):
  now=time.time() if now is None else now;removed=0
  with closing(self.db()) as c,c:
   for table in ('document','artifact'):
    rows=c.execute('SELECT id,scope FROM '+table+' WHERE expires>0 AND expires<=?',(now,)).fetchall()
    for row in rows:
     for p in self.directory(row['scope']).glob(row['id']+'.*'):p.unlink(missing_ok=True)
     c.execute('DELETE FROM '+table+' WHERE id=?',(row['id'],));removed+=1
     if table=='document':c.execute('DELETE FROM document_coverage WHERE id=?',(row['id'],))
   c.execute('DELETE FROM event WHERE expires>0 AND expires<=?',(now,));c.execute('DELETE FROM task WHERE expires>0 AND expires<=?',(now,));c.execute('DELETE FROM feedback WHERE expires<=?',(now,));c.execute('DELETE FROM topic WHERE at<?',(now-86400,));c.execute('DELETE FROM action WHERE at<?',(now-30*86400,))
   c.execute("UPDATE task SET status='queued',lease=0 WHERE kind!='reminder' AND status='active' AND lease>0 AND lease<?",(now-600,))
   c.execute('DELETE FROM task_control WHERE id NOT IN (SELECT id FROM task)')
  return removed
