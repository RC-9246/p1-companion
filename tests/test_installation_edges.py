"""Interrupted first-install inputs and absent optional monitoring integration."""
import importlib.util,json,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'deploy'))
import firstboot as F

class DockerKeyTests(unittest.TestCase):
 def attempt(self,root,kind):
  key=root/'keys/key.asc';repo=root/'sources/docker.sources';repo.parent.mkdir();calls=[]
  def path(value):
   return key if str(value)=='/etc/apt/keyrings/p1-companion-docker.asc' else repo if str(value)=='/etc/apt/sources.list.d/p1-companion-docker.sources' else Path(value)
  def command(args,*unused):
   calls.append(args)
   if args[0]=='dpkg':return 'arm64'
   if args[0]=='curl':
    p=Path(args[args.index('-o')+1]);p.write_text('-----BEGIN PGP PUBLIC KEY BLOCK-----\nsynthetic')
    if kind[0]=='interrupt':raise F.SetupError('synthetic_download_interrupted')
    if kind[0]=='complete':p.write_text(p.read_text()+'\n-----END PGP PUBLIC KEY BLOCK-----\n')
   return ''
  return key,repo,calls,[patch.object(F,'Path',side_effect=path),patch.object(F.shutil,'which',return_value=None),patch.object(F,'distribution',return_value=('debian','bookworm')),patch.object(F,'command',side_effect=command),patch.object(F.subprocess,'run',return_value=NS(stdout='not installed'))]
 def check_retry(self,kind):
  from contextlib import ExitStack
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp).resolve();mode=[kind];key,repo,calls,patches=self.attempt(root,mode)
   with ExitStack() as stack:
    for p in patches:stack.enter_context(p)
    with self.assertRaises(F.SetupError):F.install_docker(lambda *args:None)
    self.assertFalse(key.exists());self.assertFalse(repo.exists());self.assertEqual(list(key.parent.glob('.p1-docker-*')),[])
    mode[0]='complete';F.install_docker(lambda *args:None)
    self.assertTrue(key.read_text().strip().endswith('-----END PGP PUBLIC KEY BLOCK-----'));self.assertTrue(repo.is_file());self.assertEqual(key.stat().st_mode&0o777,0o644)
    F.install_docker(lambda *args:None);self.assertEqual(sum(x[0]=='curl' for x in calls),2)
 def test_interrupted_download_is_cleaned_and_can_retry(self):self.check_retry('interrupt')
 def test_successful_but_truncated_download_is_rejected_and_can_retry(self):self.check_retry('truncated')

class StandaloneMonitorTests(unittest.TestCase):
 def test_install_can_finish_without_optional_stack_healthcheck(self):
  import shutil
  spec=importlib.util.spec_from_file_location('standalone_monitor_test',ROOT/'scripts/install_monitor.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp).resolve();source=root/'project/services/monitor';shutil.copytree(ROOT/'services/monitor',source);(source.parents[1]/'evidence').mkdir();units=root/'units';units.mkdir();(root/'agent/backups').mkdir(parents=True);calls=[]
   def path(value):
    p=Path(value)
    if str(p)=='/etc/systemd/system':return units
    if str(p).startswith('/etc/systemd/system/'):return units/p.name
    if str(p)=='/usr/local/sbin/p1-healthcheck.py':return root/'absent-helper'
    return p
   def run(args,*unused):calls.append(args);return NS(returncode=1 if 'is-active' in args or 'is-enabled' in args else 0,stdout='',stderr='')
   class Socket:
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def connect_ex(self,*args):return 1
   with patch.object(m,'SOURCE',source),patch.object(m,'BASE',root/'agent'),patch.object(m,'DEST',root/'installed'),patch.object(m,'Path',side_effect=path),patch.object(m.os,'umask',return_value=0o022),patch.object(m.os,'geteuid',return_value=0),patch.object(m,'run',side_effect=run),patch.object(m,'health',return_value=True),patch.object(m.socket,'socket',return_value=Socket()),patch.object(m.subprocess,'Popen'),patch.object(sys,'argv',['install_monitor.py']):m.main()
   result=json.loads((source.parents[1]/'evidence/resource-panel-install.json').read_text());self.assertFalse(result['existing_stack_checked']);self.assertIsNone(result['existing_stack_healthy']);self.assertFalse(any('p1-healthcheck.py' in ' '.join(x) for x in calls));self.assertTrue(result['installed'])

if __name__=='__main__':unittest.main()
