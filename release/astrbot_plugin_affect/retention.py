"""Retire marked attachment excerpts from native history and backup snapshots."""
import json,re,sqlite3,time
from contextlib import closing
TAG=re.compile(r'\[P1-DOC-TTL:([0-9a-f]{24}):(\d+)\]')
def retire(value,now=None,all_temporary=False):
 now=time.time() if now is None else now
 if isinstance(value,list):return [retire(x,now,all_temporary) for x in value]
 if isinstance(value,dict):return {k:retire(v,now,all_temporary) for k,v in value.items()}
 if isinstance(value,str) and '[P1-DOC-TTL:' in value:
  try:parsed=json.loads(value)
  except (ValueError,TypeError):parsed=None
  if isinstance(parsed,(dict,list)):return json.dumps(retire(parsed,now,all_temporary),ensure_ascii=False)
  if any(all_temporary or int(t)<=now for _,t in TAG.findall(value)):return '[临时附件摘录已按保留期限清理]'
 return value
def native_database(path,*,all_temporary=False):
 """Select marker-bearing rows only; replace individual excerpts, keep all ordinary history."""
 count=0
 with closing(sqlite3.connect(path,timeout=3)) as c,c:
  c.execute('PRAGMA secure_delete=ON')
  tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
  for table,key in (('conversations','conversation_id'),('platform_message_history','id')):
   if table not in tables:continue
   rows=c.execute('SELECT '+key+',content FROM '+table+' WHERE content LIKE ? LIMIT 200',('%[P1-DOC-TTL:%',)).fetchall()
   for id,raw in rows:
    try:old=json.loads(raw)
    except (ValueError,TypeError):continue
    new=retire(old,all_temporary=all_temporary)
    if new!=old:c.execute('UPDATE '+table+' SET content=? WHERE '+key+'=?',(json.dumps(new,ensure_ascii=False),id));count+=1
 return count
