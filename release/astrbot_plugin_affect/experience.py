"""Scoped concerns, positions and episodes, grounded in observable exchanges.

These are role/application state, not a person's psychological diagnosis. They
cannot grant permissions, supply executable instructions or establish an action
without a receipt. All writes participate in the agency scope transaction.
"""
import hashlib,json,re,time
from contextlib import closing
from .agency_store import clean,tokens

KINDS={'concern','stance','episode'}
STATUSES={'open','eased','resolved','paused','abandoned','uncertain'}

class Experience:
 def __init__(self,store):self.store=store
 def migrate(self):
  with closing(self.store.db()) as c,c:c.executescript('''
CREATE TABLE IF NOT EXISTS cognitive_item(id TEXT PRIMARY KEY,scope TEXT NOT NULL,kind TEXT NOT NULL,subject TEXT NOT NULL,summary TEXT NOT NULL,status TEXT NOT NULL,weight REAL NOT NULL,sources TEXT NOT NULL,created REAL NOT NULL,updated REAL NOT NULL,expires REAL NOT NULL,epoch INTEGER NOT NULL,version INTEGER NOT NULL DEFAULT 1);
CREATE INDEX IF NOT EXISTS cognitive_scope ON cognitive_item(scope,epoch,kind,updated);
CREATE TABLE IF NOT EXISTS cognitive_seen(scope TEXT NOT NULL,event TEXT NOT NULL,epoch INTEGER NOT NULL,PRIMARY KEY(scope,event,epoch));
''')
 def put(self,scope,kind,subject,summary,status,evidence,epoch,*,receipt='',now=None,actor=''):
  if kind not in KINDS or status not in STATUSES:raise ValueError('experience_type_or_status')
  subject=clean(subject,80).strip();summary=clean(summary,600).strip()
  if len(subject)<2 or not evidence or not isinstance(evidence,list) or len(evidence)>6:raise ValueError('experience_source_required')
  if kind=='episode' and not receipt:raise ValueError('episode_receipt_required')
  if any(not isinstance(e,dict) or e.get('kind') not in ('user_quote','delivered_reply','tool_receipt','role_reference') or not isinstance(e.get('ref'),str) or not e['ref'] for e in evidence):raise ValueError('experience_source_shape')
  now=time.time() if now is None else now
  key=hashlib.sha256(json.dumps([scope,kind,subject,receipt if kind=='episode' else '',actor if kind=='concern' else ''],ensure_ascii=False).encode()).hexdigest()[:24]
  with closing(self.store.db()) as c,c:
   c.execute('BEGIN IMMEDIATE');row=c.execute('SELECT epoch FROM scope WHERE scope=?',(scope,)).fetchone()
   if not row or row[0]!=epoch:raise ValueError('scope_cleared')
   old=c.execute('SELECT * FROM cognitive_item WHERE scope=? AND id=? AND epoch=?',(scope,key,epoch)).fetchone()
   # User silence never changes relationship, state or importance here.
   if old:
    sources=json.loads(old['sources']);known={s['ref'] for s in sources}
    if all(s['ref'] in known for s in evidence):return key
    sources=(sources+[s for s in evidence if s['ref'] not in known])[-6:]
    c.execute('UPDATE cognitive_item SET summary=?,status=?,sources=?,updated=?,expires=?,version=version+1 WHERE id=?',(summary,status,json.dumps(sources,ensure_ascii=False),now,now+180*86400,key))
   else:c.execute('INSERT INTO cognitive_item VALUES(?,?,?,?,?,?,?,?,?,?,?,?,1)',(key,scope,kind,subject,summary,status,.5,json.dumps(evidence,ensure_ascii=False),now,now,now+180*86400,epoch))
   cap=500 if kind=='episode' else 50
   c.execute("DELETE FROM cognitive_item WHERE scope=? AND kind=? AND id NOT IN (SELECT id FROM cognitive_item WHERE scope=? AND kind=? ORDER BY (status='open') DESC,updated DESC LIMIT ?)",(scope,kind,scope,kind,cap))
   return key
 def view(self,scope,query='',limit=4,*,now=None,actor=None):
  now=time.time() if now is None else now;cfg=self.store.ensure(scope);wanted=tokens(query)
  # Per-kind caps bound this to 600 rows. A run of recent episodes must not hide
  # an older unresolved concern before relevance scoring can examine it.
  with closing(self.store.db()) as c:rows=[dict(r) for r in c.execute('SELECT * FROM cognitive_item WHERE scope=? AND epoch=? AND expires>? ORDER BY updated DESC',(scope,cfg['epoch'],now))]
  if actor is not None:rows=[r for r in rows if r['kind']!='concern' or any(e.get('actor','')==actor for e in json.loads(r['sources']))]
  def rank(r):
   overlap=len(wanted&tokens(r['subject']+' '+r['summary']))
   return overlap*2+(1 if r['status']=='open' else 0)+.2*2**(-(now-r['updated'])/604800)
  generic=bool(re.fullmatch(r'\s*(?:最近呢|后来呢|后来怎么样了|那件事呢|说到哪了|接着说|怎么样了)[？?。\s]*',query))
  if wanted and not generic:rows=[r for r in rows if wanted&tokens(r['subject']+' '+r['summary'])]
  rows.sort(key=rank,reverse=True)
  return [{'id':r['id'],'kind':r['kind'],'subject':r['subject'],'summary':r['summary'],'status':r['status'],'updated_at':r['updated'],'version':r['version'],'sources':json.loads(r['sources'])} for r in rows[:max(1,min(limit,12))]]
 def observe(self,scope,event,text,appraisal,epoch,actor=''):
  """A classifier may propose only a subject and exact evidence from this turn."""
  cue=(appraisal or {}).get('continuity')
  if not cue or appraisal.get('confidence',0)<.75:return None
  quote=cue.get('quote','');subject=cue.get('subject','');status=cue.get('status','')
  if not quote or quote not in text or status not in STATUSES:return None
  ref=cue.get('ref')
  if ref:
   with closing(self.store.db()) as c:prior=c.execute("SELECT subject,sources FROM cognitive_item WHERE scope=? AND id=? AND kind='concern' AND epoch=? AND expires>?",(scope,ref,epoch,time.time())).fetchone()
   if not prior or not any(e.get('actor','')==actor for e in json.loads(prior['sources'])):return None
   subject=prior['subject']
  elif not subject or subject not in quote:return None
  evidence=[{'kind':'user_quote','ref':event,'quote':clean(quote,160),'actor':actor}]
  with closing(self.store.db()) as c:
   if c.execute('SELECT 1 FROM cognitive_seen WHERE scope=? AND event=? AND epoch=?',(scope,event,epoch)).fetchone():return None
  result=self.put(scope,'concern',subject,quote,status,evidence,epoch,actor=actor)
  with closing(self.store.db()) as c,c:c.execute('INSERT OR IGNORE INTO cognitive_seen VALUES(?,?,?)',(scope,event,epoch))
  return result
 def hint(self,scope,query=''):
  rows=self.view(scope,query,3)
  if not rows:return ''
  return '[P1-CONTINUITY:v1]\n'+json.dumps(rows,ensure_ascii=False)+'\n这是本范围有来源的在意事项与可修正看法，只在相关时自然承接，不背诵状态。已解决的不要继续当作待办；没有新进展不反复追问。角色立场、用户原话、实际工具观察与原作知识互不冒充。可以保留具体意见，也可根据新证据改变；不必每轮补邀约或问句。'
 def activity(self,scope,receipt,topic,note,coverage,sources,epoch,*,question='',opinion=''):
  """Only a caller holding a real tool result may record activity, never a plan."""
  if not receipt or coverage not in ('visited_page','search_snippet_not_full_page','sampled_video_frames_only_not_audio','experiment_output'):raise ValueError('activity_receipt_or_coverage')
  if not isinstance(sources,list) or not sources or any(not isinstance(s,str) or not s for s in sources):raise ValueError('activity_sources')
  evidence=[{'kind':'tool_receipt','ref':receipt,'coverage':coverage,'sources':sources[:6],'quote':clean(note,200),'actor':'self'}]
  ids=[self.put(scope,'episode',topic,clean(note,450)+'\n覆盖：'+coverage,'resolved',evidence,epoch,receipt=receipt)]
  if question and isinstance(question,str):ids.append(self.put(scope,'concern',topic,'自己想继续了解：'+clean(question,200),'open',evidence,epoch,actor='self'))
  if opinion and isinstance(opinion,str):ids.append(self.put(scope,'stance',topic,clean(opinion,300)+'\n依据覆盖：'+coverage,'uncertain',evidence,epoch))
  return ids
 def clear(self,scope):
  with closing(self.store.db()) as c,c:
   c.execute('DELETE FROM cognitive_item WHERE scope=?',(scope,));c.execute('DELETE FROM cognitive_seen WHERE scope=?',(scope,))
