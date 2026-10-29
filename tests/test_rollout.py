"""Current deployment rollback contracts; real files and SQLite, no live daemon."""
import json,os,sys,tempfile,time,sqlite3,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'deploy'))
import install as rollout
class RolloutSafetyTests(unittest.TestCase):
 @unittest.skipUnless(os.geteuid()==0,'requires Linux/root UID restoration acceptance')
 def test_restored_private_assets_retain_nonroot_ownership_and_readability(self):
  with tempfile.TemporaryDirectory() as t:
   root,job=self.fixture(Path(t));p=root/'astrbot/data/plugin_data/affect/reviewed_assets';p.mkdir(parents=True);f=p/'reactions.json';f.write_text('synthetic private pack');p.chmod(0o700);f.chmod(0o600);os.chown(p,1001,1001);os.chown(f,1001,1001)
   rollout.snapshot(job);f.write_text('candidate');rollout.restore_paths(job)
   self.assertEqual((p.stat().st_uid,f.stat().st_uid),(1001,1001));self.assertEqual(f.stat().st_mode&0o777,0o600);self.assertEqual(f.read_text(),'synthetic private pack')
 def fixture(self,base):
  root=base/'agent';point=root/'backups/oneclick-fixture';point.mkdir(parents=True)
  rollout.atomic(point/'state.json',{'root':str(root),'status':'installing','steps':[],'core_project':'astrbot','deadline':0,'parent_pid':999999999,'parent_start':'gone'})
  return root,rollout.Job(point)
 def test_all_policy_sources_restore_without_changing_new_history(self):
  with tempfile.TemporaryDirectory() as t:
   root,job=self.fixture(Path(t));a=root/'astrbot/data/plugin_data/affect';a.mkdir(parents=True);p=a/'groups.json';p.write_text('{"version":1,"groups":[]}')
   rollout.snapshot(job);p.write_text('{"version":1,"groups":[{"bot":"10001","group":"30003"}]}');db=root/'astrbot/data/data_v4.db';db.write_bytes(b'newer native chat history')
   rollout.restore_paths(job);self.assertEqual(json.loads(p.read_text())['groups'],[]);self.assertEqual(db.read_bytes(),b'newer native chat history')
 def test_rollback_does_not_replace_contact_pause_or_enabled_state(self):
  with tempfile.TemporaryDirectory() as t:
   root,job=self.fixture(Path(t));a=root/'astrbot/data/plugin_data/affect';a.mkdir(parents=True);db=a/'affect.db'
   with sqlite3.connect(db) as c:c.executescript('CREATE TABLE companion_social(identity TEXT PRIMARY KEY,enabled INTEGER);CREATE TABLE companion_contact_pauses(identity TEXT PRIMARY KEY,until_at REAL);');c.execute("INSERT INTO companion_social VALUES('fixture',1)")
   rollout.snapshot(job)
   with sqlite3.connect(db) as c:c.execute("INSERT INTO companion_contact_pauses VALUES('fixture',?)",(time.time()+3600,))
   rollout.restore_paths(job)
   with sqlite3.connect(db) as c:self.assertEqual(c.execute('SELECT enabled FROM companion_social').fetchone()[0],1);self.assertGreater(c.execute('SELECT until_at FROM companion_contact_pauses').fetchone()[0],time.time()+3500)
 def test_restoration_restart_is_idempotent_after_displacement(self):
  with tempfile.TemporaryDirectory() as t:
   root,job=self.fixture(Path(t));p=root/'public-browser';p.mkdir();(p/'code').write_text('original');rollout.snapshot(job);(p/'code').write_text('candidate')
   real=rollout.os.replace;hit=[False]
   def replace(src,dst):
    real(src,dst)
    if Path(src)==p and not hit[0]:hit[0]=True;raise KeyboardInterrupt('power loss after rename')
   with patch.object(rollout.os,'replace',replace):
    with self.assertRaises(KeyboardInterrupt):rollout.restore_paths(job)
   job=rollout.Job(job.path);rollout.restore_paths(job);rollout.restore_paths(job);self.assertEqual((p/'code').read_text(),'original')
 def test_new_plugin_tree_removed_and_database_retained(self):
  with tempfile.TemporaryDirectory() as t:
   root,job=self.fixture(Path(t));rollout.snapshot(job)
   for name in rollout.PLUGINS:
    p=root/'astrbot/data/plugins'/name;p.mkdir(parents=True);(p/'main.py').write_text('new')
   db=root/'astrbot/data/data_v4.db';db.write_bytes(b'keep');rollout.restore_paths(job)
   self.assertTrue(all(not (root/'astrbot/data/plugins'/n).exists() for n in rollout.PLUGINS));self.assertEqual(db.read_bytes(),b'keep')
 def test_watchdog_ignores_committed_job_and_restores_uncommitted(self):
  with tempfile.TemporaryDirectory() as t:
   root,job=self.fixture(Path(t))
   with patch.object(rollout,'rollback') as revert:
    rollout.watchdog(job.path);revert.assert_called_once();revert.reset_mock();job.state['status']='committed';job.save();rollout.watchdog(job.path);revert.assert_not_called()
