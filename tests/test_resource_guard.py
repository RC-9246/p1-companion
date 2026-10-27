"""Synthetic pressure, exact process boundaries and cooperative cleanup tests."""
import ast,asyncio,importlib.util,json,os,subprocess,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch,Mock,AsyncMock
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('guard',ROOT/'services/resource_guard/guard.py');G=importlib.util.module_from_spec(spec);spec.loader.exec_module(G)
spec=importlib.util.spec_from_file_location('guard_install',ROOT/'scripts/install_resource_guard.py');I=importlib.util.module_from_spec(spec);spec.loader.exec_module(I)
def sample(free=1800,some=0,full=0):return {'MemTotal':3840*G.MIB,'MemAvailable':free*G.MIB,'some':some,'full':full}
def classify(s,old=None,at=100):return G.classify(s,old or {},'boot',at)
def native():return {'pid':50,'ppid':10,'uid':1001,'start':'123','exe':G.EXE,'cmd':b'chromium\0--headless\0','cgroup':'fixed-cgroup','namespace':'pid:[123]'}
def init():return {'pid':10,'cgroup':'fixed-cgroup','namespace':'pid:[123]'}

class Policy(unittest.TestCase):
 def test_available_memory_not_page_cache_or_free_counter(self):self.assertEqual(classify(sample())['mode'],'normal')
 def test_pressure_pauses_before_critical(self):self.assertEqual(classify(sample(700))['mode'],'pressure')
 def test_critical_requires_two_samples(self):
  one=classify(sample(300));self.assertEqual(one['mode'],'pressure');self.assertEqual(classify(sample(300),one,130)['mode'],'critical')
 def test_emergency_threshold_is_immediate(self):self.assertEqual(classify(sample(100))['mode'],'critical')
 def test_recovery_requires_three_good_samples(self):
  old=classify(sample(100))
  for at in (130,160):old=classify(sample(),old,at);self.assertNotEqual(old['mode'],'normal')
  self.assertEqual(classify(sample(),old,190)['mode'],'normal')
 def test_psi_does_not_block_a_host_with_ample_memory(self):self.assertEqual(classify(sample(1800,20,25))['mode'],'normal')
 def test_pressure_psi_with_low_memory(self):self.assertEqual(classify(sample(900,20,0))['mode'],'pressure')
 def test_reboot_resets_transient_hysteresis(self):self.assertEqual(G.classify(sample(),{'boot':'other','mode':'critical'},'boot',100)['mode'],'normal')
 def test_clock_backwards_cannot_reuse_hysteresis(self):self.assertEqual(classify(sample(),{'boot':'boot','uptime':200,'mode':'critical'},100)['mode'],'normal')
 def test_only_orphaned_root_browser_matches(self):self.assertTrue(G.orphan_candidate(native(),init()))
 def test_active_browser_parent_never_killed(self):self.assertFalse(G.orphan_candidate({**native(),'ppid':25},init()))
 def test_renderers_qq_and_host_browsers_are_excluded(self):
  for change in ({'cmd':b'chromium\0--headless\0--type=renderer\0'},{'uid':1000},{'exe':'/opt/QQ/qq'},{'cgroup':'foreign'},{'namespace':'pid:[456]'},{'cmd':b'chromium\0'}):self.assertFalse(G.orphan_candidate({**native(),**change},init()))
 def test_pid_reuse_prevents_signal(self):
  with patch.object(G.os,'pidfd_open',return_value=66,create=True),patch.object(G.os,'close'),patch.object(G,'process',return_value={**native(),'start':'changed'}),patch.object(G.signal,'pidfd_send_signal',create=True) as send:
   self.assertFalse(G.terminate_orphan(native(),init()));send.assert_not_called()
 def test_exact_recheck_sends_sigterm_on_pidfd(self):
  with patch.object(G.os,'pidfd_open',return_value=66,create=True),patch.object(G.os,'close'),patch.object(G,'process',side_effect=[native(),init()]),patch.object(G.signal,'pidfd_send_signal',create=True) as send:
   self.assertTrue(G.terminate_orphan(native(),init()));self.assertEqual(send.call_args.args,(66,G.signal.SIGTERM))
 def test_foreign_container_cannot_gain_core_limits(self):
  row={'Id':'a'*64,'Image':'sha256:'+'b'*64,'Config':{'Labels':{'com.docker.compose.project':'astrbot','com.docker.compose.service':'astrbot'}},'State':{'Running':True}}
  binding={'image':row['Image'],'project':'astrbot','service':'astrbot'};self.assertTrue(G.bound(row,binding));self.assertFalse(G.bound(row,{**binding,'image':'sha256:'+'c'*64}));self.assertFalse(G.bound(row,{**binding,'project':'other'}))
 def test_existing_user_memory_limit_preserved(self):
  with patch.object(G,'run') as run:self.assertEqual(G.limit_core({'HostConfig':{'Memory':123}},'astrbot')['state'],'existing_limit_preserved');run.assert_not_called()
 def test_limit_not_reduced_close_to_current_usage(self):
  with patch.object(G,'usage',return_value=1500*G.MIB),patch.object(G,'run') as run:self.assertEqual(G.limit_core({'HostConfig':{'Memory':0}},'astrbot')['state'],'insufficient_headroom_no_change');run.assert_not_called()
 def test_docker_success_requires_limit_readback(self):
  row={'Id':'a'*64,'HostConfig':{'Memory':0}}
  with patch.object(G,'usage',return_value=200*G.MIB),patch.object(G,'run',side_effect=[Mock(returncode=0),Mock(returncode=0,stdout=json.dumps([{'HostConfig':{'Memory':0}}]))]):self.assertEqual(G.limit_core(row,'astrbot')['state'],'limit_failed')
 def test_cgroup_v1_skips_unknown_limit_measurement(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t);(p/'10').mkdir();(p/'10/cgroup').write_text('7:memory:/docker/abc\n');self.assertIsNone(G.cgroup({'State':{'Pid':10}},p,p))
 def test_cgroup_path_traversal_rejected(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t);(p/'10').mkdir();(p/'10/cgroup').write_text('0::/../bad\n')
   with self.assertRaises(ValueError):G.cgroup({'State':{'Pid':10}},p,p)
 def test_guard_state_does_not_follow_symlinks(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t).resolve();real=p/'actual';real.write_text('{}');link=p/'link';link.symlink_to(real)
   with self.assertRaises(ValueError):G.atomic(link,{'changed':True})
   self.assertEqual(real.read_text(),'{}')
 def test_installer_dry_run_never_starts_services(self):
  r=subprocess.run([sys.executable,str(ROOT/'scripts/install_resource_guard.py')],capture_output=True,text=True);self.assertEqual(r.returncode,0);self.assertTrue(json.loads(r.stdout)['dry_run'])
 def test_installer_rejects_root_symlink(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t).resolve();link=p/'alias';link.symlink_to(p)
   with self.assertRaises(RuntimeError):I.validate_root(link)
 def test_corrupt_or_clock_reversed_journal_does_not_reset_retry_budget(self):
  for j in ({'attempts':[float('nan')]},{'orphans':[]},{'boot':'boot','uptime':200},{'boot':'boot','attempts':[200]}):
   with self.assertRaises(ValueError):G.validate_journal(j,'boot',100)

def leisure_scope():
 tree=ast.parse((ROOT/'services/leisure/server.py').read_text());nodes=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in ('resource_mode','resource_cleanup')]
 scope={'Path':Path,'json':json,'time':time,'STATE':Path('/unused')};exec(compile(ast.Module(body=nodes,type_ignores=[]),'leisure_resource_subset','exec'),scope);return scope

@unittest.skipUnless(sys.platform=='linux' and os.geteuid()==0,'root-owned isolated Linux restore fixture')
class FileRollback(unittest.TestCase):
 def fixture(self,base):
  root=base/'agent';data=root/'astrbot/data/plugin_data/affect';(data/'leisure_state').mkdir(parents=True);point=root/'backups/resource-guard-123';(point/'files').mkdir(parents=True);state=base/'guard-state';state.mkdir();target=base/'managed.py';target.write_text('new version');(point/'files/agency').write_text('original version');s=target.stat()
  saved={'root':str(root),'files':{'agency':{'path':str(target),'exists':True,'sha256':I.digest(b'original version'),'uid':s.st_uid,'gid':s.st_gid,'mode':0o640}},'containers':{},'units':{},'code_changes':{}}
  (point/'before.json').write_text(json.dumps(saved));db=data/'affect.db';db.write_bytes(b'newer-history');return root,point,state,target,db
 def test_real_file_rollback_restores_code_and_keeps_new_history(self):
  with tempfile.TemporaryDirectory() as t:
   root,point,state,target,db=self.fixture(Path(t).resolve())
   with patch.object(I,'STATE',state),patch.object(I,'locations',return_value={'agency':target}),patch.object(I,'run',return_value=Mock(returncode=0)):I.rollback(point)
   self.assertEqual(target.read_text(),'original version');self.assertEqual(target.stat().st_mode&0o777,0o640);self.assertEqual(db.read_bytes(),b'newer-history');self.assertTrue((point/'rolled_back').exists())
 def test_post_install_edits_block_destructive_restore(self):
  with tempfile.TemporaryDirectory() as t:
   root,point,state,target,db=self.fixture(Path(t).resolve());(point/'committed').touch();(point/'after-files.json').write_text(json.dumps({str(target):I.digest(b'new version')}));target.write_text('later user edit')
   with patch.object(I,'STATE',state),patch.object(I,'locations',return_value={'agency':target}),patch.object(I,'run') as run:
    with self.assertRaisesRegex(RuntimeError,'post_install_changes'):I.rollback(point)
    run.assert_not_called()
   self.assertEqual(target.read_text(),'later user edit');self.assertEqual(db.read_bytes(),b'newer-history')
 def test_native_installer_watchdog_stops_only_matching_owned_pid(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t);child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])
   try:
    record=I.owner_identity(child.pid);(p/'owner.json').write_text(json.dumps({**record,'start':'wrong'}));I.stop_owner(p);self.assertIsNone(child.poll())
    (p/'owner.json').write_text(json.dumps(record));I.stop_owner(p);child.wait(timeout=5);self.assertEqual(child.returncode,-G.signal.SIGTERM)
   finally:
    if child.poll() is None:child.terminate();child.wait(timeout=5)
class Cooperative(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.s=leisure_scope();self.browser=Mock(ctx=object(),qr=None,job=None);self.browser.lock=asyncio.Lock();self.browser.save=AsyncMock();self.browser.close=AsyncMock();self.browser.stop=AsyncMock();self.s['B']=self.browser;self.s['resource_mode']=lambda:'pressure'
 async def test_idle_browser_saved_before_close(self):
  result=await self.s['resource_cleanup']();self.assertTrue(result['closed']);self.browser.save.assert_awaited_once();self.browser.close.assert_awaited_once_with(save=False)
 async def test_failed_save_keeps_live_session(self):
  self.browser.save.side_effect=OSError('synthetic');
  with self.assertRaises(OSError):await self.s['resource_cleanup']()
  self.browser.close.assert_not_awaited()
 async def test_login_qr_is_preserved(self):
  self.browser.qr={'expires':time.monotonic()+120};self.assertEqual((await self.s['resource_cleanup']())['state'],'login_in_progress');self.browser.close.assert_not_awaited()
 async def test_active_video_preserved_at_noncritical_pressure(self):
  self.browser.job=Mock();self.browser.job.done.return_value=False;self.assertEqual((await self.s['resource_cleanup']())['state'],'active_video_preserved');self.browser.stop.assert_not_awaited()
 async def test_critical_pressure_may_stop_only_optional_video(self):
  self.s['resource_mode']=lambda:'critical';self.browser.job=Mock();self.browser.job.done.return_value=False;self.assertTrue((await self.s['resource_cleanup']())['closed']);self.browser.stop.assert_awaited_once()
 async def test_inflight_private_operation_not_interrupted(self):
  await self.browser.lock.acquire();self.assertEqual((await self.s['resource_cleanup']())['state'],'busy');self.browser.close.assert_not_awaited();self.browser.lock.release()
 async def test_expired_or_wrong_boot_lease_never_permanently_pauses(self):
  scope=leisure_scope()
  with tempfile.TemporaryDirectory() as t:
   scope['STATE']=Path(t);p=Path(t)/'resource-lease.json';p.write_text(json.dumps({'version':1,'boot':'wrong','mode':'critical','until':time.monotonic()+50}));self.assertEqual(scope['resource_mode'](),'normal')
 async def test_normal_mode_does_not_close_anything(self):
  self.s['resource_mode']=lambda:'normal';self.assertFalse((await self.s['resource_cleanup']())['closed']);self.browser.close.assert_not_awaited()

if __name__=='__main__':unittest.main()
