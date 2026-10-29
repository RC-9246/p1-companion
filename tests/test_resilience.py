import importlib.util,json,sqlite3,sys,tempfile,time,unittest
from pathlib import Path
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'services/maintenance'))
import resilience as M
class RecoveryTests(unittest.TestCase):
 def setUp(self):self.t=tempfile.TemporaryDirectory();self.root=Path(self.t.name).resolve()
 def tearDown(self):self.t.cleanup()
 def test_optional_guardian_control_files_are_restorable_after_deletion(self):
  cp=self.root/'trusted';cp.mkdir();files={};manifest={};metadata={}
  for key,unused in M.candidate_fixed(self.root).items():
   target=self.root/'installed'/key;target.parent.mkdir(exist_ok=True);source=cp/key;source.write_bytes(b'synthetic sealed control file');manifest[key]=M.digest(source);files[key]=target
   metadata[key]={'uid':__import__('os').getuid(),'gid':__import__('os').getgid(),'mode':0o444 if 'kit' in key else 0o600}
  self.assertEqual(set(M.restore_fixed(files,cp,manifest,metadata)),set(files))
  self.assertFalse(M.restore_fixed(files,cp,manifest,metadata))
  for key,path in files.items():self.assertEqual(path.stat().st_mode&0o777,metadata[key]['mode'])
 def test_source_recovery_requires_exact_hash_and_known_module(self):
  cp=self.root/'checkpoint';live=self.root/'live';p=cp/'astrbot_plugin_affect/main.py';p.parent.mkdir(parents=True);p.write_text('known good');manifest={'astrbot_plugin_affect/main.py':M.digest(p)}
  self.assertEqual(len(M.restore_sources(live,cp,manifest)),1);self.assertEqual((live/'astrbot_plugin_affect/main.py').read_text(),'known good')
  p.write_text('poisoned')
  with self.assertRaises(ValueError):M.restore_sources(live,cp,manifest)
  with self.assertRaises(ValueError):M.restore_sources(live,cp,{'../../escape': 'a'*64})
 def test_no_valid_backup_leaves_original_untouched(self):
  p=self.root/'bad.db';p.write_bytes(b'corrupt but recoverable original');before=p.read_bytes();backup=self.root/'bad-backup.db';backup.write_bytes(b'bad')
  self.assertEqual(M.restore_database(p,backup,self.root/'quarantine')['state'],'backup_rejected');self.assertEqual(p.read_bytes(),before)
 def test_valid_restore_preserves_original_and_prevents_reminder_replay(self):
  p=self.root/'bad.db';p.write_bytes(b'corrupt');b=self.root/'good.db'
  with sqlite3.connect(b) as c:
   c.executescript("CREATE TABLE task(id TEXT,kind TEXT,status TEXT,due REAL,notes TEXT,lease REAL);INSERT INTO task VALUES('r','reminder','active',1,'',1);CREATE TABLE action(id TEXT,state TEXT);INSERT INTO action VALUES('a','reserved');")
  result=M.restore_database(p,b,self.root/'quarantine',('task',));self.assertTrue(result['restored']);self.assertTrue(list((self.root/'quarantine').iterdir()))
  with sqlite3.connect(p) as c:self.assertEqual(c.execute('SELECT status FROM task').fetchone()[0],'abandoned');self.assertEqual(c.execute('SELECT state FROM action').fetchone()[0],'unknown')
 def test_recovered_memories_do_not_silently_reintroduce_forgotten_facts(self):
  p=self.root/'mem.db';p.write_bytes(b'corrupt');b=self.root/'good.db'
  with sqlite3.connect(b) as c:c.executescript("CREATE TABLE memoria_records(status TEXT,confidence REAL);INSERT INTO memoria_records VALUES('active',1);")
  M.restore_database(p,b,self.root/'quarantine',('memoria_records',))
  with sqlite3.connect(p) as c:self.assertEqual(c.execute('SELECT status,confidence FROM memoria_records').fetchone(),('candidate',.65))
 def test_recovered_learning_drops_old_outcome_checks_and_holds_preferences(self):
  p=self.root/'learning.db';p.write_bytes(b'corrupt');b=self.root/'good.db'
  with sqlite3.connect(b) as c:c.executescript("CREATE TABLE p1_learning_items(status TEXT);INSERT INTO p1_learning_items VALUES('active');CREATE TABLE p1_learning_checks(signal INTEGER);INSERT INTO p1_learning_checks VALUES(1);")
  M.restore_database(p,b,self.root/'quarantine',('p1_learning_items',))
  with sqlite3.connect(p) as c:self.assertEqual(c.execute('SELECT status FROM p1_learning_items').fetchone()[0],'pending');self.assertEqual(c.execute('SELECT COUNT(*) FROM p1_learning_checks').fetchone()[0],0)
 def test_broken_policy_recovers_closed_and_valid_revocation_is_respected(self):
  p=self.root/'groups.json';p.write_text('{bad');self.assertTrue(M.repair_policy_file(p,'groups'));self.assertEqual(json.loads(p.read_text())['groups'],[]);self.assertFalse(M.repair_policy_file(p,'groups'))
 def test_resource_guard_reduces_optional_work_without_deleting_user_data(self):
  for args in [(300,10000,45),(1800,200,45),(1800,10000,81)]:
   p=M.maintenance_plan(*args);self.assertTrue(p['pause_optional']);self.assertFalse(p['delete_user_files'])
  self.assertFalse(M.maintenance_plan(1800,10000,45)['pause_optional'])
 def test_fixed_files_reject_unknown_targets_and_tampered_snapshots(self):
  cp=self.root/'checkpoint';cp.mkdir();(cp/'mcp').write_text('known');target=self.root/'server.py'
  self.assertEqual(M.restore_fixed({'mcp':target},cp,{'mcp':M.digest(cp/'mcp')}),['mcp'])
  with self.assertRaises(ValueError):M.restore_fixed({'mcp':target},cp,{'other':'f'*64})
 def test_fixed_metadata_repairs_mode_drift_even_with_identical_content(self):
  import os,stat
  cp=self.root/'cp';cp.mkdir();source=cp/'backup_dbs';source.write_text('known script');target=self.root/'backup';target.write_text('known script');target.chmod(0o600)
  meta={'backup_dbs':{'uid':os.geteuid(),'gid':os.getegid(),'mode':0o700}};files={'backup_dbs':target};manifest={'backup_dbs':M.digest(source)}
  self.assertEqual(M.restore_fixed(files,cp,manifest,meta),['backup_dbs']);self.assertEqual(stat.S_IMODE(target.stat().st_mode),0o700)
  self.assertEqual(M.restore_fixed(files,cp,manifest,meta),[])
  for v in ({'uid':0,'gid':0,'mode':0o777},{'uid':True,'gid':0,'mode':0o600}):
   with self.assertRaises(ValueError):M.restore_fixed(files,cp,manifest,{'backup_dbs':v})
 def test_fixed_service_dependencies_include_both_proxy_and_token_consumers(self):
  self.assertEqual(set(M.fixed_dependents(['leisure_policy'])),{'p1-leisure','p1-leisure-egress'})
  self.assertEqual(set(M.fixed_dependents(['internal_workbench_token'])),{'p1-workbench','astrbot'})
  self.assertEqual(set(M.fixed_dependents(['internal_browser_token'])),{'p1-browser','astrbot'})
  self.assertEqual(M.fixed_dependents(['unknown_model_service']),[])

class AgencyRecoveryPrivacy(unittest.TestCase):
 def test_old_agency_snapshot_cannot_resurrect_canceled_reminders_or_forgotten_content(self):
  import sys
  sys.path.insert(0,str(R/'release'))
  from astrbot_plugin_affect.agency_store import AgencyStore
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);store=AgencyStore(root/'source');store.migrate();scope='v1:'+'f'*64;store.ensure(scope)
   store.goal(scope,'旧提醒','reminder',due=time.time()+3600);store.event(scope,'fact','本应忘记的事实','receipt:old')
   live=root/'broken.db';live.write_bytes(b'bad');M.restore_database(live,store.path,root/'quarantine',('scope','task'))
   with sqlite3.connect(live) as c:
    self.assertEqual(c.execute('SELECT COUNT(*) FROM event').fetchone()[0],0)
    self.assertEqual(c.execute('SELECT status FROM task').fetchone()[0],'abandoned')
    self.assertEqual(c.execute('SELECT paused FROM scope').fetchone()[0],1)

class WatchdogCheckpointContract(unittest.TestCase):
 def test_watchdog_keys_and_paths_match_the_checkpoint_writer(self):
  def load(name,file):
   sp=importlib.util.spec_from_file_location(name,R/'services/maintenance'/file);m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m);return m
  maint=load('maint_contract','p1-companion-maintain.py');watch=load('watch_contract','p1-companion-watchdog.py')
  self.assertTrue(set(watch.FILES)<=set(maint.FIXED))
  for key,path in watch.FILES.items():self.assertEqual(path,maint.FIXED[key])
