"""Read-only assistant interface regressions. No live runtime or model access."""
import hashlib,importlib.util,json,math,os,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
R=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('assistant_context',R/'ai/companion.py');M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)

class ContextTests(unittest.TestCase):
 def fixture(self,p):
  for rel in ('AGENTS.md','ai/PROJECT.json','ai/companion.py','ai/mcp_server.py'):
   q=p/rel;q.parent.mkdir(parents=True,exist_ok=True);q.write_text('public source\n')
  manifest={str(q.relative_to(p)):hashlib.sha256(q.read_bytes()).hexdigest() for q in p.rglob('*') if q.is_file()}
  (p/'source-manifest.json').write_text(json.dumps(manifest));return manifest
 def test_describe_does_not_launch_subprocess_or_check_runtime(self):
  with patch.object(M.subprocess,'run') as run:
   result=M.describe();self.assertTrue(result['ok']);self.assertFalse(result['live_runtime_checked']);self.assertFalse(result['writes']);run.assert_not_called()
 def test_machine_manifest_entrypoints_resolve(self):
  d=M.describe()['project']
  for path in [*d['start_here'],*d['entrypoints'].values()]:self.assertTrue((R/path).is_file(),path)
  self.assertEqual(d['interfaces']['engineering_mcp']['tools'],6)
  self.assertFalse(d['completion_limits']['all_twenty_directions_fully_complete'])
 def test_plan_is_metadata_never_execution(self):
  with patch.object(M.subprocess,'run') as run:
   result=M.plan();self.assertFalse(result['executed']);self.assertFalse(result['writes']);run.assert_not_called()
  step=result['steps'][1];self.assertTrue(step['writes']);self.assertTrue(step['actual_user_authorization_required']);self.assertIn('deploy/wizard.py',step['argv']);self.assertEqual(result['mode'],'fresh_host')
  self.assertIn('--apply',M.plan(mode='existing_core')['steps'][2]['argv']);self.assertTrue(M.plan(mode='existing_companion')['steps'][2]['never_reinstall'])
 def test_invalid_plan_roots_rejected(self):
  for value in ('relative','/','/srv','/srv/a/../b','/tmp/a;id','/tmp/a $(id)','/tmp/a\n'):
   with self.assertRaises(M.AccessError):M.plan(value)
 def test_source_hash_matches_then_tampering_fails(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp).resolve();self.fixture(p);self.assertTrue(M.verify(p)['ok']);(p/'AGENTS.md').write_text('modified')
   value=M.verify(p);self.assertFalse(value['ok']);self.assertIn('source_hash_mismatch',value['errors'])
 def test_missing_ai_entries_in_manifest_do_not_pass(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp).resolve();(p/'source-manifest.json').write_text(json.dumps({'README.md':'a'*64}));self.assertFalse(M.verify(p)['ok'])
 def test_malicious_manifest_escape_rejected_without_content_leak(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp).resolve();v=self.fixture(p);v['../../private']= 'a'*64;(p/'source-manifest.json').write_text(json.dumps(v));r=M.verify(p);self.assertFalse(r['ok']);self.assertNotIn('private',json.dumps(r))
 def test_source_symlink_rejected(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp).resolve();self.fixture(p);(p/'AGENTS.md').unlink();(p/'AGENTS.md').symlink_to(p/'ai/companion.py');self.assertFalse(M.verify(p)['ok'])
 def test_oversized_or_malformed_source_manifest_sanitized(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp).resolve()
   for raw in ('private-secret-invalid-json','x'*1048577,'[]'):
    (p/'source-manifest.json').write_text(raw);r=M.verify(p);self.assertFalse(r['ok']);self.assertNotIn('private-secret',json.dumps(r))
 def test_bounded_reader_rejects_final_and_parent_symlinks(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp).resolve();(p/'real').mkdir();(p/'real/status.json').write_text('{}');(p/'alias').symlink_to(p/'real');(p/'file.json').symlink_to(p/'real/status.json')
   for q in (p/'alias/status.json',p/'file.json'):
    with self.assertRaises(M.AccessError):M.bounded_json(q,p)
 def test_bounded_reader_rejects_overlarge_files_and_nonobjects(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp).resolve();q=p/'a.json'
   for raw in ('[]','x'*20):
    q.write_text(raw)
    with self.assertRaises(M.AccessError):M.bounded_json(q,p,10)
 def test_public_text_resource_rejects_symlink(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp).resolve();(p/'guide').symlink_to('/etc/hosts')
   with self.assertRaises(M.AccessError):M.bounded_text(p/'guide',p)
 def test_symlink_loop_rejected_without_resolving_or_reading(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp).resolve();self.fixture(p);q=p/'AGENTS.md';q.unlink();q.symlink_to(q)
   self.assertFalse(M.verify(p)['ok'])
   with self.assertRaises(M.AccessError):M.bounded_text(q,p)
   with self.assertRaises(M.AccessError):M.root_path(str(q))
 def test_handoff_matches_schema_required_keys_and_does_not_claim_work(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp).resolve();self.fixture(p);v=M.handoff(p);schema=json.loads((R/'ai/handoff.schema.json').read_text())
   self.assertEqual(set(v),set(schema['required']));self.assertEqual(v['phase'],'not_started');self.assertFalse(v['private_runtime_data_included']);self.assertEqual(v['observations'],[]);self.assertEqual(v['tests'],[])
 def test_mcp_config_defaults_to_offline_and_uses_argv(self):
  c=M.mcp_config()['mcpServers']['p1_companion_engineering'];self.assertIsInstance(c['args'],list);self.assertNotIn('--live-root',c['args']);self.assertTrue(Path(c['command']).is_absolute())
  self.assertEqual(M.mcp_config('/srv/test-agent')['mcpServers']['p1_companion_engineering']['args'][-2:],['--live-root','/srv/test-agent'])
 def test_cli_describe_stdout_is_only_json(self):
  r=subprocess.run([sys.executable,str(R/'ai/companion.py'),'describe'],capture_output=True,text=True,timeout=10)
  self.assertEqual(r.returncode,0);self.assertEqual(json.loads(r.stdout)['kind'],'public_project_context')

class HealthTests(unittest.TestCase):
 def write(self,p,name,value):
  q=p/'astrbot/data/plugin_data/affect'/name;q.parent.mkdir(parents=True,exist_ok=True);q.write_text(json.dumps(value));return q
 def test_health_is_closed_schema_and_exact_booleans(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp).resolve();secret='synthetic-cookie-secret'
   self.write(p,'companion_health.json',{'at':100,'agency_ready':True,'learning_ready':secret,'private_persona':secret})
   self.write(p,'maintenance_health.json',{'at':1000,'services':{'astrbot':True,'snowluma':False,'other':secret},'databases':{'affect':True,'other':secret},'repairs':[{'secret':secret}],'disabled':False,'api_key':secret})
   r=M.health(p,now=1010);self.assertNotIn(secret,json.dumps(r));self.assertTrue(r['maintenance']['services']['astrbot']);self.assertFalse(r['maintenance']['services']['snowluma']);self.assertIsNone(r['startup_report']['modules']['learning_ready']);self.assertEqual(r['maintenance']['last_repair_count'],1);self.assertFalse(r['account_login_verified']);self.assertFalse(r['startup_report']['continuous_runtime_probe'])
 def test_stale_service_and_database_flags_become_unknown(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp).resolve();self.write(p,'maintenance_health.json',{'at':1,'services':{'astrbot':True},'databases':{'affect':True}})
   r=M.health(p,now=1000);self.assertFalse(r['maintenance']['fresh']);self.assertIsNone(r['maintenance']['services']['astrbot']);self.assertIsNone(r['maintenance']['databases']['affect'])
 def test_clock_skew_boolean_nan_and_infinite_timestamps_are_unknown(self):
  for at in (True,float('nan'),float('inf'),2000,-1,'1000',10**1000):
   self.assertIsNone(M.age(at,1000))
 def test_missing_reports_are_not_healthy_zeroes(self):
  with tempfile.TemporaryDirectory() as tmp:
   r=M.health(Path(tmp).resolve(),now=1000);self.assertFalse(r['ok']);self.assertIsNone(r['maintenance']['age_seconds']);self.assertIsNone(r['maintenance']['services']['astrbot'])
 def test_no_config_or_db_opened(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp).resolve();self.write(p,'companion_health.json',{'at':1});original=M.os.open;opened=[]
   def narrow(path,*args,**kwargs):
    opened.append(Path(path).name);return original(path,*args,**kwargs)
   with patch.object(M.os,'open',side_effect=narrow):M.health(p,now=100)
   self.assertTrue(set(opened).issubset({'companion_health.json','maintenance_health.json','repair_watchdog_health.json'}))
 def test_recovery_summary_only_publishes_closed_fields(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp).resolve();secret='synthetic-recovery-secret'
   self.write(p,'repair_watchdog_health.json',{'schema':1,'at':1000,'status':'repair_succeeded','pending':False,'engine_verified':True,'restored_files':3,'rolling_24h_attempts':1,'private_path':secret,'traceback':secret})
   r=M.health(p,now=1010);self.assertNotIn(secret,json.dumps(r));self.assertTrue(r['recovery_chain']['fresh']);self.assertEqual(r['recovery_chain']['status'],'repair_succeeded');self.assertEqual(r['recovery_chain']['restored_files'],3)
 def test_recovery_summary_stale_or_invalid_schema_is_unknown(self):
  for value in ({'schema':1,'at':1},{'schema':True,'at':1000},{'schema':2,'at':1000}):
   r=M.recovery_summary({**value,'status':'healthy','engine_verified':True,'rolling_24h_attempts':1},1400)
   self.assertFalse(r['fresh']);self.assertIsNone(r['status']);self.assertIsNone(r['engine_verified']);self.assertIsNone(r['rolling_24h_attempts'])
 def test_recovery_summary_invalid_types_and_arbitrary_status_filtered(self):
  for status in ('synthetic-secret',[],{}):
   r=M.recovery_summary({'schema':1,'at':1000,'status':status,'engine_verified':'true','pending':1,'restored_files':11,'rolling_24h_attempts':True},1001)
   self.assertIsNone(r['status']);self.assertIsNone(r['engine_verified']);self.assertIsNone(r['pending']);self.assertIsNone(r['restored_files']);self.assertIsNone(r['rolling_24h_attempts'])
 def test_runtime_report_symlink_does_not_expose_other_file(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp).resolve();q=self.write(p,'maintenance_health.json',{'at':1000});q.unlink();q.symlink_to('/etc/hosts');r=M.health(p,now=1001);self.assertFalse(r['ok'])

class DoctorTests(unittest.TestCase):
 def test_doctor_uses_only_fixed_read_only_command_and_filters_child_output(self):
  payload={'ok':False,'read_only':True,'errors':['existing_companion_data_use_manual_upgrade','secret_alphanumeric_token'],'warnings':['QQ_and_model_must_already_work'],'api_key':'synthetic-secret'}
  r=subprocess.CompletedProcess([],1,json.dumps(payload)+'\nignored banner','synthetic-secret')
  with patch.object(M,'verify',return_value={'ok':True}),patch.object(M.subprocess,'run',return_value=r) as run:
   out=M.doctor('/srv/test-agent')
  args=run.call_args.args[0];self.assertIn('--check',args);self.assertNotIn('--apply',args);self.assertEqual(Path(args[1]),M.SOURCE/'deploy/install.py');self.assertNotIn('synthetic-secret',json.dumps(out));self.assertNotIn('secret_alphanumeric_token',json.dumps(out));self.assertEqual(out['errors'],['existing_companion_data_use_manual_upgrade','unrecognized_preflight_code']);self.assertEqual(out['warnings'],['QQ_and_model_must_already_work'])
 def test_failed_integrity_prevents_any_doctor_subprocess(self):
  with patch.object(M,'verify',return_value={'ok':False}),patch.object(M.subprocess,'run') as run:
   out=M.doctor('/srv/test-agent');self.assertFalse(out['ok']);run.assert_not_called()
 def test_timeout_is_sanitized(self):
  with patch.object(M,'verify',return_value={'ok':True}),patch.object(M.subprocess,'run',side_effect=subprocess.TimeoutExpired(['secret'],60,output='private-data')):
   out=M.doctor('/srv/test-agent');self.assertFalse(out['ok']);self.assertNotIn('private-data',json.dumps(out));self.assertEqual(out['errors'],['doctor_unavailable_or_timeout'])

if __name__=='__main__':unittest.main()
