"""Recovery-chain faults use private temporary files and a fake systemd transport."""
import fcntl,hashlib,importlib.util,json,os,stat,subprocess,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
R=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('repair_watchdog',R/'services/maintenance/p1-companion-watchdog.py');W=importlib.util.module_from_spec(spec);spec.loader.exec_module(W)

class Crash(BaseException):pass
class Fixture:
 def __init__(self,path):
  self.base=Path(path).resolve();self.root=self.base/'checkpoint';self.data=self.base/'data';self.data.mkdir(mode=0o700)
  (self.root/'fixed').mkdir(parents=True,mode=0o700);self.root.chmod(0o700)
  self.uid=os.getuid();self.gid=os.getgid();self.now=[1700000000.,100000.,'lab-boot'];self.calls=[];self.fail_start=False;self.no_report=False;self.crash=None;self.while_running=None
  self.files={};self.hashes={};self.metadata={}
  for key,target in W.FILES.items():
   q=self.base/'live'/target.name;q.parent.mkdir(exist_ok=True)
   if q.suffix=='.service':raw=b'[Unit]\nDescription=lab\n[Service]\nType=oneshot\nExecStart=/bin/true\n'
   elif q.suffix=='.timer':raw=b'[Unit]\nDescription=lab\n[Timer]\nOnActiveSec=1h\n'
   else:raw=b'#!/usr/bin/env python3\nvalue=1\n'
   source=self.root/'fixed'/key;source.write_bytes(raw);source.chmod(0o600)
   mode=0o644 if key.startswith('unit_') else 0o700
   q.write_bytes(raw);q.chmod(mode);self.files[key]=q;self.hashes[key]=W.digest(raw);self.metadata[key]={'uid':self.uid,'gid':self.gid,'mode':mode}
  self.seal();self.units={W.SERVICE:{'Id':W.SERVICE,'ActiveState':'inactive','Result':'success','UnitFileState':'static'}}
  self.units.update({t:{'Id':t,'ActiveState':'active','Result':'success','UnitFileState':'enabled'} for t in W.TIMERS})
  self.report();self.ctx=W.Context(self.root,self.data,self.files,self.uid,self.gid,self.run,lambda:tuple(self.now))
 def seal(self):
  for name,value in [('fixed-manifest.json',self.hashes),('fixed-metadata.json',self.metadata)]:
   p=self.root/name;p.write_text(json.dumps(value));p.chmod(0o600)
 def report(self):
  W.atomic_json(self.data/'maintenance_health.json',{'at':self.now[0],'disabled':False,'ttl_sweep':True,'services':{'lab':True},'databases':{}},self.uid,self.gid)
 def run(self,args,timeout=20):
  self.calls.append(args)
  if args[1]=='show':return subprocess.CompletedProcess(args,0,'\n\n'.join('\n'.join(k+'='+v for k,v in unit.items()) for unit in self.units.values()))
  if args[1]=='enable':self.units[args[-1]].update(ActiveState='active',UnitFileState='enabled')
  if args[1]=='reset-failed':self.units[W.SERVICE].update(ActiveState='inactive',Result='success')
  if args[1]=='start':
   # The engine must be able to obtain its own lock; otherwise a no-op success is unsafe.
   with (self.data/'maintenance.lock').open('a') as lock:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
   if self.while_running:self.while_running()
   if self.crash=='before':raise Crash()
   if self.fail_start:return subprocess.CompletedProcess(args,1,'')
   self.now[0]+=1;self.now[1]+=1
   if not self.no_report:self.report()
   if self.crash=='after':raise Crash()
  return subprocess.CompletedProcess(args,0,'')
 def damage(self,key='maintain'):
  self.files[key].write_bytes(b'broken code !!!')
 def ledger(self):return W.Journal(self.data,self.uid,self.gid).load()
 def recover(self):return W.recover(self.ctx)
 def actions(self):return [x for x in self.calls if x[1]!='show']

class RecoveryChainTests(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.f=Fixture(self.tmp.name)
 def tearDown(self):self.tmp.cleanup()
 def test_healthy_pass_changes_no_service(self):
  self.assertEqual(self.f.recover()['status'],'healthy');self.assertEqual(self.f.actions(),[])
 def test_each_of_ten_missing_control_files_restored_with_metadata(self):
  for key in self.f.files:
   with self.subTest(key=key):
    self.f.now[1]+=86401;self.f.files[key].unlink();r=self.f.recover();self.assertEqual(r['status'],'repair_succeeded');self.assertEqual(W.digest(self.f.files[key].read_bytes()),self.f.hashes[key]);self.assertEqual(stat.S_IMODE(self.f.files[key].stat().st_mode),self.f.metadata[key]['mode'])
 def test_permission_only_drift_fixed(self):
  self.f.files['maintain'].chmod(0o600);self.assertEqual(self.f.recover()['status'],'repair_succeeded');self.assertEqual(stat.S_IMODE(self.f.files['maintain'].stat().st_mode),0o700)
 def test_bad_late_checkpoint_prevents_all_partial_writes(self):
  self.f.damage();last=list(self.f.files)[-1];(self.f.root/'fixed'/last).write_bytes(b'poison');self.assertEqual(self.f.recover()['status'],'checkpoint_rejected');self.assertEqual(self.f.files['maintain'].read_bytes(),b'broken code !!!');self.assertFalse(self.f.actions())
 def test_syntax_invalid_but_hash_matching_checkpoint_rejected(self):
  p=self.f.root/'fixed/maintain';p.write_bytes(b'invalid syntax !!!');self.f.hashes['maintain']=W.digest(p.read_bytes());self.f.seal();self.assertEqual(self.f.recover()['status'],'checkpoint_rejected')
 def test_invalid_unit_checkpoint_rejected_before_changes(self):
  key=next(k for k in self.f.files if k.endswith('_timer'));p=self.f.root/'fixed'/key;p.write_bytes(b'not an ini file');self.f.hashes[key]=W.digest(p.read_bytes());self.f.seal();self.assertEqual(self.f.recover()['status'],'checkpoint_rejected')
 def test_world_writable_checkpoint_metadata_rejected(self):
  self.f.metadata['maintain']['mode']=0o777;self.f.seal();self.assertEqual(self.f.recover()['status'],'checkpoint_rejected')
 def test_untrusted_owner_metadata_rejected(self):
  self.f.metadata['maintain']['uid']+=1;self.f.seal();self.assertEqual(self.f.recover()['status'],'checkpoint_rejected')
 def test_checkpoint_symlink_rejected(self):
  p=self.f.root/'fixed/maintain';p.unlink();p.symlink_to(self.f.files['maintain']);self.assertEqual(self.f.recover()['status'],'checkpoint_rejected')
 def test_target_leaf_symlink_replaced_without_touching_destination(self):
  extra=self.f.base/'unrelated';extra.write_text('preserve');p=self.f.files['maintain'];p.unlink();p.symlink_to(extra);self.assertEqual(self.f.recover()['status'],'repair_succeeded');self.assertFalse(p.is_symlink());self.assertEqual(extra.read_text(),'preserve')
 def test_pause_prevents_actions_and_journal_creation(self):
  self.f.damage();(self.f.data/'maintenance.disabled').touch();self.assertEqual(self.f.recover()['status'],'paused');self.assertFalse(self.f.actions());self.assertFalse((self.f.data/'.watchdog-journal-a.json').exists())
 def test_shared_deployment_lock_blocks_repair(self):
  self.f.damage()
  with (self.f.data/'maintenance.lock').open('a') as lock:
   fcntl.flock(lock,fcntl.LOCK_EX);self.assertEqual(self.f.recover()['status'],'busy')
  self.assertFalse(self.f.actions())
 def test_second_watchdog_during_engine_run_is_busy(self):
  nested=[];self.f.damage();self.f.while_running=lambda:nested.append(self.f.recover()['status']);self.assertEqual(self.f.recover()['status'],'repair_succeeded');self.assertEqual(nested,['busy'])
 def test_cooldown_and_rolling_daily_cap_survive_reruns(self):
  self.f.damage();self.f.recover();self.f.damage();self.assertEqual(self.f.recover()['status'],'cooldown')
  self.f.now[1]+=1801;self.assertEqual(self.f.recover()['status'],'repair_succeeded');self.f.damage();self.f.now[1]+=1801;self.assertEqual(self.f.recover()['status'],'daily_budget_exhausted')
 def test_wall_clock_forward_does_not_reset_same_boot_budget(self):
  self.f.damage();self.f.recover();self.f.damage();self.f.now[0]+=86400*365;self.assertEqual(self.f.recover()['status'],'cooldown')
 def test_wall_clock_backward_uses_uptime(self):
  self.f.damage();self.f.recover();self.f.damage();self.f.now[0]-=1000;self.assertEqual(self.f.recover()['status'],'cooldown');self.f.now[1]+=1801;self.assertEqual(self.f.recover()['status'],'repair_succeeded')
 def test_cross_boot_backward_clock_does_not_erase_budget(self):
  self.f.damage();self.f.recover();self.f.now=[self.f.now[0]-10,1,'new-boot'];self.assertEqual(self.f.recover()['status'],'clock_guard')
 def test_one_bad_journal_slot_recovered_without_resetting_attempts(self):
  self.f.damage();self.f.recover();(self.f.data/'.watchdog-journal-a.json').write_text('bad');self.assertEqual(self.f.recover()['status'],'healthy');self.assertEqual(len(self.f.ledger()['attempts']),1)
 def test_both_bad_journal_slots_refuse_new_actions(self):
  self.f.damage();self.f.recover();self.f.damage();calls=len(self.f.actions())
  for name in ('a','b'):(self.f.data/('.watchdog-journal-'+name+'.json')).write_text('bad')
  self.assertEqual(self.f.recover()['status'],'journal_corrupt');self.assertEqual(len(self.f.actions()),calls)
 def test_missing_both_slots_after_initialization_fails_closed(self):
  self.f.damage();self.f.recover()
  for name in ('a','b'):(self.f.data/('.watchdog-journal-'+name+'.json')).unlink()
  self.assertEqual(self.f.recover()['status'],'journal_corrupt')
 def test_reservation_durable_before_first_file_mutation(self):
  original=W.atomic_bytes;seen=[];self.f.damage()
  def hook(path,*args):
   if path==self.f.files['maintain']:seen.append(self.f.ledger()['attempts'][-1]['outcome'])
   return original(path,*args)
  with patch.object(W,'atomic_bytes',side_effect=hook):self.assertEqual(self.f.recover()['status'],'repair_succeeded')
  self.assertEqual(seen,['pending'])
 def test_child_crash_before_engine_resumes_same_attempt_once(self):
  self.f.damage();self.f.crash='before'
  with self.assertRaises(Crash):self.f.recover()
  self.assertEqual(self.f.ledger()['attempts'][-1]['outcome'],'pending');self.f.crash=None;self.assertEqual(self.f.recover()['status'],'repair_succeeded');self.assertEqual(len(self.f.ledger()['attempts']),1);self.assertTrue(self.f.ledger()['attempts'][-1]['resume'])
 def test_crash_after_engine_verified_without_second_start(self):
  self.f.damage();self.f.crash='after'
  with self.assertRaises(Crash):self.f.recover()
  before=len(self.f.actions());self.f.crash=None;self.assertEqual(self.f.recover()['status'],'pending_recovery_verified');self.assertEqual(len(self.f.actions()),before)
 def test_repeated_crash_is_not_replayed_indefinitely(self):
  self.f.damage();self.f.crash='before'
  for _ in range(2):
   with self.assertRaises(Crash):self.f.recover()
  count=len(self.f.actions());self.assertEqual(self.f.recover()['status'],'pending_recovery_failed');self.assertEqual(len(self.f.actions()),count)
 def test_exit_zero_without_new_engine_report_is_not_success(self):
  self.f.damage();self.f.no_report=True;r=self.f.recover();self.assertEqual(r['status'],'repair_failed');self.assertFalse(r['engine_verified'])
 def test_systemd_failure_is_not_success(self):
  self.f.damage();self.f.fail_start=True;r=self.f.recover();self.assertEqual(r['status'],'repair_failed');self.assertTrue(r['pending'])
 def test_stopped_timer_reenabled_through_closed_action(self):
  self.f.units[W.TIMERS[0]].update(ActiveState='inactive',UnitFileState='disabled');self.assertEqual(self.f.recover()['status'],'repair_succeeded');self.assertIn(['systemctl','enable','--now',W.TIMERS[0]],self.f.actions())
 def test_post_write_corruption_blocks_engine_start(self):
  original=W.atomic_bytes;self.f.damage()
  def hook(path,*args):
   result=original(path,*args)
   if path==self.f.files['maintain']:path.write_bytes(b'bad after write')
   return result
  with patch.object(W,'atomic_bytes',side_effect=hook):r=self.f.recover()
  self.assertEqual(r['status'],'repair_failed');self.assertFalse(self.f.actions())
 def test_inspect_is_read_only_even_on_first_use(self):
  before={str(p):p.read_bytes() for p in self.f.base.rglob('*') if p.is_file()};r=W.inspect(self.f.ctx);self.assertTrue(r['ok']);self.assertFalse(r['writes']);self.assertEqual(before,{str(p):p.read_bytes() for p in self.f.base.rglob('*') if p.is_file()})
 def test_oversized_and_bool_timestamps_are_invalid(self):
  for v in (True,-1,10**1000,float('nan'),float('inf')):self.assertFalse(W.valid_number(v))

if __name__=='__main__':unittest.main()
