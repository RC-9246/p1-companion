"""Scoped durable agency. Additive schema; no permission data or model-written SQL."""
import hashlib,json,math,re,secrets,sqlite3,time
from contextlib import closing
from pathlib import Path

TOPICS={'animation':'动画 配乐 原画 分镜','reading':'读书 小说 文学 阅读','music':'音乐 配乐 钢琴 歌曲','cooking':'料理 做饭 食谱 烹饪','science':'科学 物理 储能 空调','technology':'技术 编程 电脑 软件','daily_life':'整理 生活 计划 学习','history':'历史 文物 博物馆'}
STATES={'queued','active','paused','done','abandoned','failed'}
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
CREATE TABLE IF NOT EXISTS task(id TEXT PRIMARY KEY,scope TEXT NOT NULL,title TEXT NOT NULL,kind TEXT NOT NULL,status TEXT NOT NULL,priority INTEGER NOT NULL,step INTEGER NOT NULL DEFAULT 0,notes TEXT NOT NULL DEFAULT '',sources TEXT NOT NULL DEFAULT '[]',created REAL NOT NULL,updated REAL NOT NULL,due REAL NOT NULL DEFAULT 0,lease REAL NOT NULL DEFAULT 0,expires REAL NOT NULL DEFAULT 0,receipt TEXT NOT NULL DEFAULT '',epoch INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS task_scope ON task(scope,status,priority,updated);
CREATE TABLE IF NOT EXISTS event(id TEXT PRIMARY KEY,scope TEXT NOT NULL,kind TEXT NOT NULL,text TEXT NOT NULL,source TEXT NOT NULL,at REAL NOT NULL,expires REAL NOT NULL DEFAULT 0,topic TEXT NOT NULL DEFAULT '',status TEXT NOT NULL DEFAULT 'observed',conflict TEXT NOT NULL DEFAULT '',epoch INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS event_scope ON event(scope,at);
CREATE TABLE IF NOT EXISTS document(id TEXT PRIMARY KEY,scope TEXT NOT NULL,name TEXT NOT NULL,ext TEXT NOT NULL,created REAL NOT NULL,expires REAL NOT NULL,bytes INTEGER NOT NULL,status TEXT NOT NULL,text TEXT NOT NULL,source TEXT NOT NULL,private INTEGER NOT NULL,epoch INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS artifact(id TEXT PRIMARY KEY,scope TEXT NOT NULL,title TEXT NOT NULL,format TEXT NOT NULL,created REAL NOT NULL,expires REAL NOT NULL DEFAULT 0,sources TEXT NOT NULL,bytes INTEGER NOT NULL,epoch INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS action(id TEXT PRIMARY KEY,scope TEXT NOT NULL,kind TEXT NOT NULL,state TEXT NOT NULL,at REAL NOT NULL,seconds REAL NOT NULL DEFAULT 0,details TEXT NOT NULL DEFAULT '{}');
CREATE INDEX IF NOT EXISTS action_scope ON action(scope,at);
CREATE TABLE IF NOT EXISTS budget(day INTEGER PRIMARY KEY,ceiling INTEGER NOT NULL,used REAL NOT NULL DEFAULT 0,calls INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS topic(id TEXT PRIMARY KEY,scope TEXT NOT NULL,keywords TEXT NOT NULL,speaker TEXT NOT NULL,text TEXT NOT NULL,at REAL NOT NULL,count INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS feedback(id TEXT PRIMARY KEY,scope TEXT NOT NULL,rule TEXT NOT NULL,evidence TEXT NOT NULL,at REAL NOT NULL,expires REAL NOT NULL,active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS model_budget(day INTEGER PRIMARY KEY,used INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS circuit(name TEXT PRIMARY KEY,failures INTEGER NOT NULL DEFAULT 0,until REAL NOT NULL DEFAULT 0);
''')
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
   for k,v in changes.items():c.execute('UPDATE scope SET '+k+'=? WHERE scope=?',(v,scope))
  return self.ensure(scope)
 def preference(self,scope,key,value):
  cfg=self.ensure(scope);p=json.loads(cfg['preferences'])
  if key=='pace_minutes' and type(value) is int and 8<=value<=30:pass
  elif key=='exploration' and type(value) in (int,float) and math.isfinite(value) and 0<=value<=1:pass
  elif key=='expression' and value in ('brief','balanced','listen_first'):pass
  else:raise ValueError('preference_not_allowed')
  p[key]=value
  with closing(self.db()) as c,c:c.execute('UPDATE scope SET preferences=? WHERE scope=?',(json.dumps(p),scope))
  return p
 def interests(self,scope):
  self.ensure(scope)
  with closing(self.db()) as c:return [dict(r) for r in c.execute('SELECT topic,score,evidence,last FROM interest WHERE scope=? ORDER BY score DESC',(scope,))]
 def learn_interest(self,scope,topic,rating,evidence):
  if topic not in TOPICS or type(rating) not in (int,float) or not math.isfinite(rating) or not 0<=rating<=1 or not evidence:raise ValueError('evidence_required')
  self.ensure(scope)
  with closing(self.db()) as c,c:
   r=c.execute('SELECT score FROM interest WHERE scope=? AND topic=?',(scope,topic)).fetchone()
   c.execute('UPDATE interest SET score=?,evidence=evidence+1,last=? WHERE scope=? AND topic=?',(.9*r[0]+.1*rating,time.time(),scope,topic))
 def event(self,scope,kind,text,source,*,topic='',expires=0,status='observed',conflict='',expected_epoch=None):
  cfg=self.ensure(scope);text=clean(text);source=clean(source,300)
  if not text or not source:raise ValueError('source_required')
  if expected_epoch is not None and expected_epoch!=cfg['epoch']:raise ValueError('scope_cleared')
  key=hashlib.sha256(json.dumps([scope,kind,text,source],ensure_ascii=False).encode()).hexdigest()[:24]
  with closing(self.db()) as c,c:
   if conflict:c.execute("UPDATE event SET status='superseded' WHERE scope=? AND conflict=? AND status!='superseded'",(scope,clean(conflict,80)))
   c.execute('INSERT OR IGNORE INTO event VALUES(?,?,?,?,?,?,?,?,?,?,?)',(key,scope,clean(kind,40),text,source,time.time(),expires,topic,status,clean(conflict,80),cfg['epoch']))
  return key
 def search(self,scope,query='',limit=8):
  cfg=self.ensure(scope);now=time.time();wanted=tokens(query)
  with closing(self.db()) as c:rows=[dict(x) for x in c.execute("SELECT * FROM event WHERE scope=? AND epoch=? AND (expires=0 OR expires>?) AND status!='superseded' ORDER BY at DESC LIMIT 300",(scope,cfg['epoch'],now))]
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
 def goal(self,scope,title,kind='research',priority=2,due=0,sources=None,expires=0):
  cfg=self.ensure(scope)
  if kind not in ('research','reading','organize','reflection','experiment','reminder'):raise ValueError('invalid_goal')
  if type(priority) is not int or not 1<=priority<=5 or type(due) not in (int,float) or not math.isfinite(due) or due<0:raise ValueError('invalid_goal')
  if kind=='reminder' and not time.time()<due<=time.time()+366*86400:raise ValueError('reminder_time_required')
  title=clean(title,180).strip()
  if len(title)<2:raise ValueError('title_required')
  with closing(self.db()) as c,c:
   r=c.execute("SELECT id FROM task WHERE scope=? AND title=? AND status IN ('queued','active','paused')",(scope,title)).fetchone()
   if r:return r[0]
   if c.execute("SELECT COUNT(*) FROM task WHERE scope=? AND status IN ('queued','active','paused')",(scope,)).fetchone()[0]>=20:raise ValueError('too_many_goals')
   source_expiry=c.execute('SELECT MIN(expires) FROM document WHERE scope=? AND expires>?',(scope,time.time())).fetchone()[0]
   if source_expiry:expires=min(expires or source_expiry,source_expiry)
   key=secrets.token_hex(12);now=time.time();c.execute('INSERT INTO task(id,scope,title,kind,status,priority,sources,created,updated,due,expires,epoch) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(key,scope,title,kind,'queued',priority,json.dumps(sources or []),now,now,due,expires,cfg['epoch']));return key
 def due_reminders(self,scope,now=None):
  self.ensure(scope);now=time.time() if now is None else now
  with closing(self.db()) as c:return [dict(x) for x in c.execute("SELECT * FROM task WHERE scope=? AND kind='reminder' AND status='queued' AND due<=? AND (expires=0 OR expires>?) ORDER BY due LIMIT 4",(scope,now,now))]
 def goals(self,scope):
  self.ensure(scope)
  with closing(self.db()) as c:return [dict(x) for x in c.execute('SELECT * FROM task WHERE scope=? ORDER BY priority DESC,updated DESC LIMIT 40',(scope,))]
 def update_goal(self,scope,id,state,notes='',sources=None):
  cfg=self.ensure(scope)
  if state not in STATES:raise ValueError('invalid_state')
  with closing(self.db()) as c,c:
   r=c.execute('SELECT * FROM task WHERE scope=? AND id=? AND epoch=?',(scope,id,cfg['epoch'])).fetchone()
   if not r:raise ValueError('goal_not_found')
   active_expiry=c.execute('SELECT MIN(expires) FROM document WHERE scope=? AND expires>?',(scope,time.time())).fetchone()[0]
   if active_expiry:c.execute('UPDATE task SET expires=CASE WHEN expires=0 THEN ? ELSE MIN(expires,?) END WHERE id=?',(active_expiry,active_expiry,id))
   c.execute('UPDATE task SET status=?,notes=?,sources=?,step=step+1,updated=?,lease=? WHERE id=?',(state,clean(notes,3000),json.dumps(sources if sources is not None else json.loads(r['sources'])),time.time(),time.time() if state=='active' else 0,id))
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
 def take_model_budget(self,limit=200,now=None):
  if type(limit) is not int or not 1<=limit<=200:raise ValueError('model_budget_limit')
  day=int(((time.time() if now is None else now)+28800)//86400)
  with closing(self.db()) as c,c:
   c.execute('BEGIN IMMEDIATE');c.execute('INSERT OR IGNORE INTO model_budget VALUES(?,0)',(day,))
   n=c.execute('UPDATE model_budget SET used=used+1 WHERE day=? AND used<?',(day,limit)).rowcount
   c.execute('DELETE FROM model_budget WHERE day<?',(day-8,));return bool(n)
 def budget(self):
  with closing(self.db()) as c:
   r=c.execute('SELECT * FROM budget WHERE day=?',(int((time.time()+28800)//86400),)).fetchone()
  return dict(r) if r else {'ceiling':18000,'used':0,'calls':0}
 def defer(self,scope,seconds):
  with closing(self.db()) as c,c:c.execute('UPDATE scope SET next_at=? WHERE scope=?',(time.time()+seconds,scope))
 def join(self,scope,now,commit=False):
  cfg=self.ensure(scope)
  if cfg['paused'] or cfg['level']<3 or not cfg['interest_join'] or now-cfg['last_join']<1200:return False
  with closing(self.db()) as c,c:
   n=c.execute("SELECT COUNT(*) FROM action WHERE scope=? AND kind='interest_join' AND state IN ('reserved','complete','unknown') AND at>?",(scope,now-86400)).fetchone()[0]
   if n>=4:return False
   if commit:
    changed=c.execute('UPDATE scope SET last_join=? WHERE scope=? AND last_join=?',(now,scope,cfg['last_join'])).rowcount
    if not changed:return False
    c.execute('INSERT INTO action VALUES(?,?,?,?,?,?,?)',(secrets.token_hex(12),scope,'interest_join','reserved',now,0,'{}'))
  return True
 def feedback(self,scope,rule,evidence):
  self.ensure(scope);rule=clean(rule,180);evidence=clean(evidence,400)
  rules={'brief':r'简短|短一点|少说|别太长|不要长篇','detailed':r'详细|展开|讲清|细一点','listen_first':r'先听|听完|别.{0,4}建议|不要.{0,4}建议','fewer_questions':r'(?:少|别|不要).{0,4}(?:追问|提问|问)','no_images':r'(?:不|别|不要).{0,6}(?:图|表情)','plain_qq':r'(?:不|别|不要).{0,6}(?:markdown|md|格式|修饰)'}
  rule={'先听完':'listen_first','先听':'listen_first','简短':'brief','详细':'detailed','少追问':'fewer_questions','不用图':'no_images','不要md':'plain_qq'}.get(rule,rule)
  if rule not in rules or not re.search(rules[rule],evidence,re.I):raise ValueError('closed_expression_rule_with_exact_evidence_required')
  key=secrets.token_hex(12)
  with closing(self.db()) as c,c:c.execute('INSERT INTO feedback VALUES(?,?,?,?,?,?,1)',(key,scope,rule,evidence,time.time(),time.time()+30*86400))
  return key
 def context(self,scope,query=''):
  cfg=self.ensure(scope)
  with closing(self.db()) as c:
   feedback=[dict(x) for x in c.execute("SELECT id,rule,evidence,expires FROM feedback WHERE rule IN ('brief','detailed','listen_first','fewer_questions','no_images','plain_qq') AND scope=? AND active=1 AND expires>? ORDER BY at DESC LIMIT 5",(scope,time.time()))]
   actions=[dict(x) for x in c.execute('SELECT kind,state,at,seconds,details FROM action WHERE scope=? ORDER BY at DESC LIMIT 8',(scope,))]
   topics=[dict(x) for x in c.execute('SELECT id,speaker,text,at,count FROM topic WHERE scope=? AND at>? ORDER BY at DESC LIMIT 5',(scope,time.time()-1800))]
  goals=self.goals(scope)[:8]
  for g in goals:g['notes']=g['notes'][:500]
  events=self.search(scope,query,5)
  for e in events:e['text']=e['text'][:600]
  return {'control':cfg,'interests':self.interests(scope),'goals':goals,'events':events,'explicit_feedback':feedback,'topics':topics,'recent_actions':actions,'shared_device_budget':self.budget()}
 def wipe(self,scope):
  self.ensure(scope)
  with closing(self.db()) as c,c:
   c.execute('UPDATE scope SET epoch=epoch+1 WHERE scope=?',(scope,))
   for table in ('interest','task','event','document','artifact','action','topic','feedback'):c.execute('DELETE FROM '+table+' WHERE scope=?',(scope,))
  import shutil
  shutil.rmtree(self.root/hashlib.sha256(scope.encode()).hexdigest(),ignore_errors=True)
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
   c.execute('DELETE FROM event WHERE expires>0 AND expires<=?',(now,));c.execute('DELETE FROM task WHERE expires>0 AND expires<=?',(now,));c.execute('DELETE FROM feedback WHERE expires<=?',(now,));c.execute('DELETE FROM topic WHERE at<?',(now-86400,));c.execute('DELETE FROM action WHERE at<?',(now-30*86400,))
   c.execute("UPDATE task SET status='queued',lease=0 WHERE kind!='reminder' AND status='active' AND lease>0 AND lease<?",(now-600,))
  return removed
