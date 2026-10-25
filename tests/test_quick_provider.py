import importlib.util,json,sys,tempfile,unittest
from pathlib import Path
R=Path(__file__).resolve().parents[1]
P=next(p for p in (R/'tools/configure_quick_provider.py',R/'scripts/configure_quick_provider.py') if p.exists())
spec=importlib.util.spec_from_file_location('quick_config',P);M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)
class QuickProvider(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.d=Path(self.tmp.name)/'project/astrbot/data';self.d.mkdir(parents=True)
  self.cfg={'provider_sources':[{'id':'source','api_base':'https://api.deepseek.com','key':['synthetic-private-key']}],
   'provider':[{'id':'normal','provider_source_id':'source','enable':True,'model':'deepseek-flash','modalities':['text','image','tool_use'],'custom_extra_body':{'max_tokens':32768}}],
   'agent_runner':{'config':{'model':{'provider_id':'normal'}}}}
  self.save();self.before=(self.d/'cmd_config.json').read_bytes()
 def save(self):(self.d/'cmd_config.json').write_text(json.dumps(self.cfg))
 def tearDown(self):self.tmp.cleanup()
 def test_dry_run_does_not_write_or_expose_key(self):
  r=M.configure(self.d);self.assertTrue(r['dry_run']);self.assertFalse(r['changed']);self.assertEqual((self.d/'cmd_config.json').read_bytes(),self.before)
  self.assertNotIn('synthetic-private-key',json.dumps(r));self.assertFalse((self.d.parents[1]/'backups').exists())
 def test_apply_changes_only_alias_preserves_default_and_private_restore_point(self):
  r=M.configure(self.d,apply=True);after=json.loads((self.d/'cmd_config.json').read_text());alias=after['provider'].pop()
  self.assertEqual(after,self.cfg);self.assertEqual(alias['id'],M.ALIAS);self.assertEqual(alias['provider_source_id'],'source');self.assertEqual(alias['modalities'],self.cfg['provider'][0]['modalities'])
  self.assertEqual(alias['custom_extra_body'],{'thinking':{'type':'disabled'},'max_tokens':2048})
  backup=Path(r['private_backup'])/'cmd_config-before.json';self.assertEqual(backup.read_bytes(),self.before);self.assertEqual(backup.stat().st_mode&0o777,0o600)
  self.assertFalse(M.configure(self.d,apply=True)['changed']);self.assertNotIn('synthetic-private-key',json.dumps(r))
 def test_existing_alias_conflict_and_other_destinations_are_rejected_without_write(self):
  for url in ('http://api.deepseek.com','https://example.com','https://user:pass@api.deepseek.com','https://api.deepseek.com:444','https://api.deepseek.com/?q=secret'):
   self.cfg['provider_sources'][0]['api_base']=url;self.save();before=(self.d/'cmd_config.json').read_bytes()
   with self.assertRaises(AssertionError):M.configure(self.d,apply=True)
   self.assertEqual((self.d/'cmd_config.json').read_bytes(),before)
  self.cfg['provider_sources'][0]['api_base']='https://api.deepseek.com';self.cfg['provider'].append({'id':M.ALIAS});self.save()
  with self.assertRaises(AssertionError):M.configure(self.d,apply=True)
if __name__=='__main__':unittest.main()
