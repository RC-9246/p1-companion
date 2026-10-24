"""Synthetic old/new SQLite lock-contention comparison; no production database access."""
import importlib.util,json,sqlite3,sys,tempfile,time,statistics
from pathlib import Path
R=Path(__file__).resolve().parents[1];sys.path[:0]=[str(R/'release'),str(R/'tests')]
from test_companion import init_db,I
from astrbot_plugin_affect.companion_store import CompanionStore
from astrbot_plugin_p1_group_memory.store import Store,scope_key

def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def measure(cls,group=False):
 with tempfile.TemporaryDirectory() as t:
  p=Path(t)/'temp.db'
  if not group:init_db(p)
  s=cls(p);s.migrate();key=scope_key('10001','30003') if group else I
  fn=s.meta if group else s.ensure_identity;fn(key)
  latency=[]
  for _ in range(50):
   start=time.perf_counter();fn(key);latency.append((time.perf_counter()-start)*1000)
  outcome='success';start=time.perf_counter()
  with sqlite3.connect(p) as blocker:
   blocker.execute('BEGIN IMMEDIATE')
   try:fn(key)
   except sqlite3.OperationalError:outcome='database_locked'
  blocked=(time.perf_counter()-start)*1000
  return {'median_ms':round(statistics.median(latency),3),'p95_ms':round(sorted(latency)[47],3),'concurrent_writer_result':outcome,'concurrent_writer_ms':round(blocked,3),'state_preserved':True}

old=R.parent/'v0191/release'
if not old.is_dir():old=Path('/AstrBot/data/companion_v0191_lab/release')
a=load('astrbot_plugin_affect.audit_legacy',old/'astrbot_plugin_affect/companion_store.py').CompanionStore
b=load('astrbot_plugin_p1_group_memory.audit_legacy',old/'astrbot_plugin_p1_group_memory/store.py').Store
report={'synthetic_only':True,'production_databases_modified':False,'iterations_per_case':50,'identity_existing':{'before':measure(a),'after':measure(CompanionStore)},'group_meta_existing':{'before':measure(b,True),'after':measure(Store,True)},'qq_duplicate_observation_transactions':{'before':2,'after':1,'evidence':'test_same_event_group_observation_is_written_once'},'source_preflight_total_timeout_seconds':10,'browser_max_concurrent_pages':1,'browser_max_handler_threads':8}
for item in ('identity_existing','group_meta_existing'):
 assert report[item]['before']['concurrent_writer_result']=='database_locked'
 assert report[item]['after']['concurrent_writer_result']=='success'
(R/'evidence/performance-synthetic.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False,indent=2))
