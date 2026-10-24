"""Filesystem contract for the neutral installer, in a disposable container only.
Docker/systemd are synthetic here; real recovery is separately fault-injected.
"""
import contextlib,io,json,os,pathlib,runpy,subprocess,sys,tempfile
from types import SimpleNamespace as N
from unittest.mock import patch
R=pathlib.Path(__file__).resolve().parents[1];RealPath=pathlib.PosixPath
assert os.geteuid()==0
with tempfile.TemporaryDirectory(prefix='portable-maintenance-') as tmp:
 root=RealPath(tmp)/'agent';data=root/'astrbot/data';data.mkdir(parents=True);(data/'cmd_config.json').write_text('{"platform_settings":{"id_whitelist":[]}}')
 # Bootstrap only writes temporary project state. It never starts a service.
 with patch.object(sys,'argv',[str(R/'scripts/bootstrap.py'),'--root',str(root),'--bot-id','10001','--owner-id','20002','--apply']),contextlib.redirect_stdout(io.StringIO()):runpy.run_path(str(R/'scripts/bootstrap.py'),run_name='__main__')
 for name in ('astrbot','snowluma'):(root/name/'compose.yaml').write_text('services:\n  '+name+':\n    image: synthetic\n') if (root/name).exists() else None
 if not (root/'snowluma').exists():(root/'snowluma').mkdir();(root/'snowluma/compose.yaml').write_text('services:\n  snowluma:\n    image: synthetic\n')
 h={k:True for k in ('agency_ready','group_memory_ready','group_affect_ready','learning_ready','qq_plain_ready')};(data/'plugin_data/affect/companion_health.json').write_text(json.dumps(h))
 trap=RealPath(tmp)/'host';calls=[]
 for part in ('usr/local/sbin','etc/systemd/system'):(trap/part).mkdir(parents=True,exist_ok=True)
 def mapped_path(*parts):
  p=RealPath(*parts)
  for prefix in ('/usr/local','/etc/systemd','/var/lib/p1-companion'):
   if str(p)==prefix or str(p).startswith(prefix+'/'):return trap/str(p).lstrip('/')
  return p
 def command(args,**kwargs):
  calls.append(args)
  if args[:2]==['docker','inspect']:return N(returncode=0,stdout='{"Running":true,"Health":{"Status":"healthy"}}',stderr='')
  if args[0]=='python3' and args[-1].endswith('checkpoint_recovery.py'):
   assert (data/'companion_v020_lab/evidence/release-manifest.json').is_file()
   return N(returncode=0,stdout='synthetic checkpoint invocation',stderr='')
  assert args[0]=='systemctl',args
  return N(returncode=0,stdout='',stderr='')
 with patch.object(pathlib,'Path',mapped_path),patch.object(subprocess,'run',command),patch.object(sys,'argv',[str(R/'scripts/install_maintenance.py'),'--root',str(root),'--apply']),contextlib.redirect_stdout(io.StringIO()):runpy.run_path(str(R/'scripts/install_maintenance.py'),run_name='__main__')
 for file in (trap/'usr/local').rglob('*'):
  if file.is_file() and (file.suffix=='.py' or file.name=='p1-backup-dbs'):compile(file.read_text(),str(file),'exec')
 assert (trap/'etc/systemd/system/p1-companion-maintain.timer').exists();assert (trap/'etc/systemd/system/p1-companion-snapshot.timer').exists()
 assert any(x[:2]==['systemctl','enable'] for x in calls)
 os.chown(data/'plugin_data/affect/leisure_state',0,0)
 print(json.dumps({'neutral_installer_filesystem_contract':True,'generated_python_compiles':True,'host_paths_redirected_to_tmp':True,'native_docker_or_systemd_called':False,'checkpoint_call_and_source_manifest_present':True,'backup_and_maintenance_units_written':True,'network_calls':0,'production_mounts':False,'limit':'Does not substitute for the real isolated recovery and live service tests.'}))
