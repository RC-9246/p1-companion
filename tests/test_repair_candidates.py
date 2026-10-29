"""Execute sealed probes; proposals cannot change policy, source scope or verdicts."""
import ast,hashlib,importlib.util,json,os,subprocess,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('repair_candidates',ROOT/'services/repair_candidates/manager.py');M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)
SOURCE=(ROOT/'release/astrbot_plugin_affect/reply_chunks.py').read_text()
def proposal(original=SOURCE,replacement=None):
 n=next(n for n in ast.parse(SOURCE).body if isinstance(n,ast.FunctionDef) and n.name=='casual_tail')
 return {'schema':1,'target':'qq_format','function':'casual_tail','base_sha256':M.sha(original.encode()),'replacement':replacement or ast.get_source_segment(SOURCE,n),'fault':'punctuation_regression'}
class CandidateTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name).resolve();self.target=self.root/M.TARGET;self.target.parent.mkdir(parents=True);self.target.write_text(SOURCE)
  self.calls=[];self.m=M.Manager(self.root,self.root/'guardian',self.command)
  self.checkpoint=self.root/'checkpoint';(self.checkpoint/'plugins/astrbot_plugin_affect').mkdir(parents=True);self.checkpoint.chmod(0o700)
  self.patch=patch.object(M.U,'CHECKPOINT',self.checkpoint);self.patch.start();self.addCleanup(self.patch.stop)
 def command(self,argv,**kwargs):
  self.calls.append(argv)
  if argv[:2]==['docker','run']:
   raw=next(x for x in argv if x.endswith(',dst=/candidate.py,readonly'));source=raw.split('src=',1)[1].split(',dst=',1)[0]
   return subprocess.run([sys.executable,str(ROOT/'services/repair_candidates/worker.py'),source,str(ROOT/'services/repair_candidates/probes.json')],capture_output=True,text=True,timeout=10)
  if argv[:2]==['docker','inspect']:return subprocess.CompletedProcess(argv,0,json.dumps({'Running':True,'OOMKilled':False}))
  return subprocess.CompletedProcess(argv,0,'')
 def seal(self,bad=False):
  if bad:self.target.write_text(SOURCE.replace('return text[:-1]','return text'))
  (self.checkpoint/'plugins/astrbot_plugin_affect/reply_chunks.py').write_bytes(self.target.read_bytes())
  (self.checkpoint/'manifest.json').write_text(json.dumps({'astrbot_plugin_affect/reply_chunks.py':M.sha(self.target.read_bytes())}))
  self.m.seal(ROOT/'services/repair_candidates',True,'sha256:'+'a'*64)
 def test_healthy_baseline_cannot_publish_unnecessary_patch(self):
  self.seal();v=self.m.process(proposal(),True);self.assertEqual(v['state'],'blocked');self.assertFalse(any(x[:2]==['docker','restart'] for x in self.calls))
 def test_real_fault_reproduced_and_candidate_passes_546_checks(self):
  self.seal(True);v=self.m.process(proposal(self.target.read_text()),True)
  self.assertEqual(v['state'],'observing');self.assertEqual(self.target.read_text(),M.build_candidate((self.m.home/'jobs'/v['job']/'before.py').read_text(),proposal((self.m.home/'jobs'/v['job']/'before.py').read_text())))
  proof=json.loads((self.m.home/'jobs'/v['job']/'verification.json').read_text());self.assertFalse(proof['baseline']['ok']);self.assertTrue(proof['candidate']['ok']);self.assertEqual(proof['candidate']['checked'],546)
  excluded=M.R.candidate_source_exclusions(self.root,json.loads((self.checkpoint/'manifest.json').read_text()),home=self.m.home,trusted_uid=os.getuid())
  self.assertEqual(excluded,{'astrbot_plugin_affect/reply_chunks.py'})
  self.m.rollback(v);self.assertEqual(self.m.status()['state'],'rolled_back');self.assertIn('return text\n',self.target.read_text());self.assertFalse(M.R.candidate_source_exclusions(self.root,{},home=self.m.home,trusted_uid=os.getuid()))
 def test_expired_observation_restores_before_code_without_db_changes(self):
  self.seal(True);v=self.m.process(proposal(self.target.read_text()),True);data=self.root/'chat.db';data.write_bytes(b'newer conversation preserved')
  v['published_at']-=500;v['watch_until']-=500;self.m.record(v)
  self.assertEqual(self.m.tick(True)['state'],'rolled_back');self.assertEqual(data.read_bytes(),b'newer conversation preserved')
 def test_source_change_or_pause_denies_before_executable_probe(self):
  self.seal();self.target.write_text(SOURCE+'\n# changed\n')
  with self.assertRaisesRegex(RuntimeError,'sealed_source'):self.m.process(proposal())
  self.assertFalse(self.calls);(self.root/'astrbot/data/plugin_data/affect').mkdir(parents=True,exist_ok=True);(self.root/'astrbot/data/plugin_data/affect/maintenance.disabled').touch()
  self.assertEqual(self.m.tick(True)['state'],'paused')
 def test_attempt_reservation_survives_failure_and_cooldown(self):
  self.seal();bad=proposal(replacement='def casual_tail(text):\n return open(text).read()')
  with self.assertRaisesRegex(RuntimeError,'repair_call_denied'):self.m.process(bad)
  with self.assertRaisesRegex(RuntimeError,'retry_limit'):self.m.process(proposal())
  self.assertEqual(len(json.loads((self.m.home/'attempts.json').read_text())),1)
 def test_missing_initialized_journal_and_resource_pressure_never_execute_patch(self):
  self.seal()
  with patch.object(self.m,'resource_ok',return_value=False),self.assertRaisesRegex(RuntimeError,'resource_pressure'):self.m.process(proposal())
  self.assertFalse(self.calls);self.m.process(proposal());(self.m.home/'attempts.json').unlink()
  before=len(self.calls)
  with self.assertRaisesRegex(RuntimeError,'journal_missing'):self.m.process(proposal())
  self.assertEqual(len(self.calls),before)
 def test_ast_rejects_network_imports_signature_changes_and_test_patches(self):
  candidates=['def casual_tail(text):\n import os\n return text','def casual_tail(text):\n return text.__class__','def casual_tail(text,other=None):\n return text','def casual_tail(text):\n text[0]=1\n return text','def casual_tail(text):\n return "new_private_content"','def casual_tail(text):\n return CHAT_STYLE']
  for replacement in candidates:
   with self.subTest(replacement=replacement),self.assertRaises(RuntimeError):M.build_candidate(SOURCE,proposal(replacement=replacement))
  bad=proposal();bad['target']='policy'
  with self.assertRaisesRegex(RuntimeError,'target_denied'):M.build_candidate(SOURCE,bad)
 def test_probe_source_change_cannot_redefine_acceptance(self):
  self.seal();p=self.m.home/'kit/worker.py';p.chmod(0o600);p.write_text('print("pass")')
  with self.assertRaisesRegex(RuntimeError,'trusted_probe_changed'):self.m.process(proposal())
 @unittest.skipUnless(os.geteuid()==0,'root checkpoint registration acceptance')
 def test_guardian_registration_and_rollback_preserve_existing_checkpoint(self):
  spec=importlib.util.spec_from_file_location('candidate_install_test',ROOT/'scripts/install_repair_candidates.py');installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)
  cp=self.checkpoint;(cp/'fixed').mkdir();(cp/'fixed-manifest.json').write_text('{}');(cp/'fixed-metadata.json').write_text('{}');point=self.root/'receipt';point.mkdir();files={}
  for key in M.R.candidate_fixed(self.root):
   path=self.root/'fixed-live'/key;path.parent.mkdir(exist_ok=True);path.write_text('synthetic trusted control');path.chmod(0o600);files[key]=path
  with patch.object(installer,'helpers',return_value=[M.U,M.R]),patch.object(M.R,'candidate_fixed',return_value=files):
   self.assertEqual(set(installer.register_recovery(self.root,point)),set(files))
   manifest=json.loads((cp/'fixed-manifest.json').read_text());self.assertEqual(set(manifest),set(files))
   installer.restore_registration(self.root,point)
  self.assertEqual(json.loads((cp/'fixed-manifest.json').read_text()),{});self.assertEqual(list((cp/'fixed').iterdir()),[])

if __name__=='__main__':unittest.main()
