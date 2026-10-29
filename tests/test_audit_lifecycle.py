"""Regression cases from the lifecycle audit; synthetic files/containers only."""
import importlib.util,json,os,sqlite3,sys,tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
import test_core_updater as CU
import test_modules as CM

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'services/maintenance'))
import resilience as R
spec=importlib.util.spec_from_file_location('audit_maintenance',ROOT/'services/maintenance/p1-companion-maintain.py')
M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)

class RecoveryBoundaryTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name).resolve()
 def fixture(self):
  cp=self.root/'seal';cp.mkdir();src=cp/'mcp_server';src.write_text('verified source')
  live=self.root/'live/server.py';live.parent.mkdir();live.write_text('drift')
  return cp,src,live
 def test_preplaced_temp_link_is_not_followed(self):
  cp,src,live=self.fixture();victim=self.root/'outside';victim.write_text('original')
  live.with_name(live.name+'.repair-next').symlink_to(victim)
  R.restore_fixed({'mcp_server':live},cp,{'mcp_server':R.digest(src)})
  self.assertEqual(victim.read_text(),'original');self.assertFalse(live.is_symlink());self.assertEqual(live.read_text(),'verified source')
 def test_parent_link_is_rejected_without_writing(self):
  cp,src,live=self.fixture();live.unlink();live.parent.rmdir();outside=self.root/'outside';outside.mkdir();live.parent.symlink_to(outside)
  with self.assertRaises((ValueError,OSError)):R.restore_fixed({'mcp_server':live},cp,{'mcp_server':R.digest(src)})
  self.assertFalse((outside/'server.py').exists())
 def test_source_restore_ignores_old_predictable_temp_link(self):
  cp=self.root/'seal';src=cp/'astrbot_plugin_affect/main.py';src.parent.mkdir(parents=True);src.write_text('safe')
  live=self.root/'live/astrbot_plugin_affect/main.py';live.parent.mkdir(parents=True);victim=self.root/'other';victim.write_text('keep')
  live.with_name('main.py.repair-next').symlink_to(victim)
  R.restore_sources(self.root/'live',cp,{'astrbot_plugin_affect/main.py':R.digest(src)})
  self.assertEqual(victim.read_text(),'keep');self.assertEqual(live.read_text(),'safe')
 def db_fixture(self):
  live=self.root/'bad.db';live.write_bytes(b'corrupt');p=self.root/'backups/verified-companion/20261029-010000';p.mkdir(parents=True)
  with sqlite3.connect(p/'fake.db') as c:c.execute('CREATE TABLE facts(x)')
  return live
 def test_stop_failure_cannot_replace_database(self):
  live=self.db_fixture();calls=[]
  def run(argv,*args):
   calls.append(argv)
   return NS(returncode=1 if argv[1]=='stop' else 0,stdout=json.dumps({'Id':'same','State':{'Running':True}}))
  with patch.object(M,'BASE',self.root),patch.object(M,'DBS',{'fake':(live,('facts',))}),patch.object(M,'run',run):
   repairs=[];M.ensure_databases({'db-fake':{'failures':2,'last_repair':0,'repairs':[]}},10000,repairs)
  self.assertEqual(live.read_bytes(),b'corrupt');self.assertEqual(repairs[0]['state'],'stop_not_verified')
  self.assertFalse(any(c[1]=='start' for c in calls))
 def test_stop_success_but_still_running_is_rejected(self):
  live=self.db_fixture()
  with patch.object(M,'BASE',self.root),patch.object(M,'DBS',{'fake':(live,('facts',))}),patch.object(M,'run',return_value=NS(returncode=0,stdout=json.dumps({'Id':'same','State':{'Running':True}}))):
   repairs=[];M.ensure_databases({'db-fake':{'failures':2,'last_repair':0,'repairs':[]}},10000,repairs)
  self.assertEqual(live.read_bytes(),b'corrupt')
 def test_snapshot_failure_still_restarts_original_running_container(self):
  live=self.db_fixture();calls=[];reads=0
  def run(argv,*unused):
   nonlocal reads
   calls.append(argv)
   if argv[1]=='inspect':reads+=1
   return NS(returncode=0,stdout=json.dumps({'Id':'same','State':{'Running':reads==1}}))
  with patch.object(M,'BASE',self.root),patch.object(M,'DBS',{'fake':(live,('facts',))}),patch.object(M,'run',run),patch.object(M,'snapshot',side_effect=OSError('synthetic')):
   with self.assertRaises(OSError):M.ensure_databases({'db-fake':{'failures':2,'last_repair':0,'repairs':[]}},10000,[])
  self.assertTrue(any(c[1]=='start' for c in calls));self.assertEqual(live.read_bytes(),b'corrupt')
 def test_maintenance_rejects_stale_health(self):
  (self.root/'companion_health.json').write_text(json.dumps({'at':1,'phase':'ready',**{k:True for k in CU.U.HEALTH_KEYS}}))
  with patch.object(M,'DATA',self.root),patch.object(M,'run',return_value=NS(returncode=0,stdout=json.dumps({'Running':True,'StartedAt':'2020-01-01T00:00:00Z'}))):self.assertFalse(M.healthy('astrbot'))
 def test_actual_upgrade_probe_accepts_serving_but_rejects_stale(self):
  import urllib.request
  health=self.root/'health.json';docker=CU.U.Docker.__new__(CU.U.Docker)
  docker.inspect=lambda name:{'State':{'Running':True,'StartedAt':'2020-01-01T00:00:00Z'}}
  def execute(argv,timeout):
   with patch('pathlib.Path',return_value=health),patch.object(urllib.request,'urlopen',return_value=NS(close=lambda:None)):
    try:exec(argv[5],{})
    except AssertionError:raise CU.U.UpdateError('bounded_command_failed')
   return ''
  for phase,at,want in [('ready',time.time(),True),('serving',time.time(),True),('serving',1,False)]:
   health.write_text(json.dumps({'at':at,'phase':phase,**{k:True for k in CU.U.HEALTH_KEYS}}))
   with patch.object(CU.U,'run',side_effect=execute):self.assertEqual(docker.probe('astrbot','astrbot'),want)

class TransactionRegressionTests(unittest.TestCase):
 def test_manual_rollback_crash_resumes(self):
  c=CU.TransactionTests();c.setUp();self.addCleanup(c.doCleanups)
  self.assertEqual(c.apply()['state'],'observing');self.assertEqual(c.engine.tick()['state'],'succeeded');original=c.docker.remove
  def crash(name):
   original(name)
   if name=='astrbot':raise KeyboardInterrupt('synthetic crash')
  with patch.object(c.docker,'remove',side_effect=crash):
   with self.assertRaises(KeyboardInterrupt):c.engine.tick(True)
  self.assertEqual(c.info()['state'],'rolling_back')
  self.assertEqual(c.engine.tick()['state'],'rolled_back');self.assertIn('astrbot',c.docker.items);self.assertEqual(c.facts(),['before'])
 def test_modules_and_upgrade_share_lifecycle_lock(self):
  c=CM.CompositionTests();c.setUp();self.addCleanup(c.doCleanups)
  with CU.U.exclusive(CU.U.lifecycle_lock(c.root)):
   with self.assertRaisesRegex(RuntimeError,'operation_busy'):c.c.apply(['core'])
  self.assertTrue(all(x['State']['Running'] for x in c.d.items.values()))
 def test_remove_failure_recreates_original_stopped_services_without_starting(self):
  c=CM.CompositionTests();c.setUp();self.addCleanup(c.doCleanups);c.c.apply(['core']);c.d.calls=[];c.d.fail_stop='p1-workbench'
  self.assertEqual(c.c.apply(['core'],remove=True)['state'],'rolled_back')
  for name in CM.M.ALL_SERVICES:
   self.assertIn(name,c.d.items);self.assertFalse(c.d.items[name]['State']['Running'])
  self.assertFalse(any(x[0]=='start' for x in c.d.calls))

if __name__=='__main__':unittest.main()
