"""Retire marked attachment excerpts from native history and backup snapshots."""
import hashlib,json,re,sqlite3,time
from contextlib import closing
TAG=re.compile(r'\[P1-DOC-TTL:([0-9a-f]{24}):(\d+)\]')
def retire(value,now=None,all_temporary=False,revoked=(),hashes=()):
 now=time.time() if now is None else now
 if isinstance(value,list):return [retire(x,now,all_temporary,revoked,hashes) for x in value]
 if isinstance(value,dict):return {k:retire(v,now,all_temporary,revoked,hashes) for k,v in value.items()}
 if isinstance(value,str) and hashes and hashlib.sha256(value.encode()).hexdigest() in hashes:return '[临时附件派生回复已删除或按保留期限清理]'
 if isinstance(value,str) and '[P1-DOC-TTL:' in value:
  try:parsed=json.loads(value)
  except (ValueError,TypeError):parsed=None
  if isinstance(parsed,(dict,list)):return json.dumps(retire(parsed,now,all_temporary,revoked,hashes),ensure_ascii=False)
  if any(all_temporary or id in revoked or int(t)<=now for id,t in TAG.findall(value)):return '[临时附件摘录已删除或按保留期限清理]'
 return value
def native_database(path,*,all_temporary=False):
 """Select marker-bearing rows only; replace individual excerpts, keep all ordinary history."""
 count=0
 from pathlib import Path
 revoked=set();derived={};agency=Path(path).parent/'plugin_data/affect/agency/agency.db'
 if agency.is_file():
  try:
   with closing(sqlite3.connect(agency.as_uri()+'?mode=ro',uri=True,timeout=2)) as ac:
    revoked={r[0] for r in ac.execute('SELECT id FROM revoked_source')}
    if ac.execute("SELECT 1 FROM sqlite_master WHERE name='document_lineage'").fetchone():
     for umo,digest,doc,expires in ac.execute('SELECT umo,digest,document,expires FROM document_lineage'):
      if all_temporary or doc in revoked or expires<=time.time():derived.setdefault(umo,set()).add(digest)
  except sqlite3.Error:pass
 with closing(sqlite3.connect(path,timeout=3)) as c,c:
  c.execute('PRAGMA secure_delete=ON')
  tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
  for table,key in (('conversations','conversation_id'),('platform_message_history','id')):
   if table not in tables:continue
   columns={r[1] for r in c.execute('PRAGMA table_info('+table+')')}
   if not {key,'content'}<=columns:continue
   scoped=table=='conversations' and 'user_id' in columns
   scan_derived=scoped and bool(derived)
   rows=c.execute('SELECT '+key+',content'+(',user_id' if scoped else '')+' FROM '+table+('' if scan_derived else ' WHERE content LIKE ?'),() if scan_derived else ('%[P1-DOC-TTL:%',))
   while True:
    batch=rows.fetchmany(100)
    if not batch:break
    for row in batch:
     id,raw=row[:2];hashes=derived.get(row[2],set()) if scoped else set()
     try:old=json.loads(raw)
     except (ValueError,TypeError):continue
     new=retire(old,all_temporary=all_temporary,revoked=revoked,hashes=hashes)
     if new!=old:c.execute('UPDATE '+table+' SET content=? WHERE '+key+'=?',(json.dumps(new,ensure_ascii=False),id));count+=1
 return count
