"""Install the optional root guardian after the verified maintenance checkpoint exists."""
import argparse,hashlib,importlib.util,json,os,shutil,subprocess,sys,time
from pathlib import Path
R=Path(__file__).resolve().parents[1]
def helpers():
 loaded=[]
 for name,path in [('guardian_install_updater',R/'services/updater/manager.py'),('guardian_install_resilience',R/'services/maintenance/resilience.py')]:
  spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);loaded.append(module)
 return loaded
def register_recovery(root,point):
 u,r=helpers();cp=u.CHECKPOINT;u.protected(cp)
 with u.exclusive(u.lifecycle_lock(root)):
  manifest=u.read(cp/'fixed-manifest.json');metadata=u.read(cp/'fixed-metadata.json');files=r.candidate_fixed(root)
  assert not set(files)&set(manifest),'existing_guardian_checkpoint_requires_reviewed_upgrade'
  for name in ('fixed-manifest.json','fixed-metadata.json'):(point/('before-'+name)).write_bytes((cp/name).read_bytes())
  for key,path in files.items():
   assert path.is_file() and not path.is_symlink() and path.stat().st_uid==0 and not path.stat().st_mode&0o022,'guardian_source_untrusted'
   raw=path.read_bytes();r.atomic_bytes(cp/'fixed'/key,raw);manifest[key]=hashlib.sha256(raw).hexdigest();st=path.stat();metadata[key]={'uid':st.st_uid,'gid':st.st_gid,'mode':st.st_mode&0o777}
  u.atom(cp/'fixed-metadata.json',metadata);u.atom(cp/'fixed-manifest.json',manifest)
 return list(files)
def restore_registration(root,point):
 u,r=helpers();cp=u.CHECKPOINT
 if not all((point/('before-'+name)).exists() for name in ('fixed-manifest.json','fixed-metadata.json')):return
 with u.exclusive(u.lifecycle_lock(root)):
  for name in ('fixed-metadata.json','fixed-manifest.json'):r.atomic_bytes(cp/name,(point/('before-'+name)).read_bytes())
  for key in r.candidate_fixed(root):(cp/'fixed'/key).unlink(missing_ok=True)
def install(root,auto_pure=False):
 assert os.geteuid()==0 and sys.platform.startswith('linux'),'linux_root_required'
 assert (Path('/var/lib/p1-companion/recovery/current')/'manifest.json').is_file(),'install_and_verify_maintenance_first'
 assert b'candidate_fixed' in Path('/usr/local/sbin/p1-companion-maintain.py').read_bytes(),'upgrade_main_maintenance_before_guardian_install'
 dest=Path('/usr/local/lib/p1-companion/candidates')
 assert not dest.exists(),'existing_guardian_requires_reviewed_upgrade_and_reseal'
 assert not any(p.is_symlink() for p in (dest,*dest.parents)),'guardian_parent_untrusted'
 units=[Path('/etc/systemd/system/p1-companion-candidates.'+x) for x in ('service','timer')]
 assert not any(p.exists() or p.is_symlink() for p in units),'existing_guardian_units_require_reviewed_upgrade'
 sources={**{n:R/'services/repair_candidates'/n for n in ('manager.py','worker.py','probes.json')},'updater.py':R/'services/updater/manager.py','resilience.py':R/'services/maintenance/resilience.py'}
 for name,p in sources.items():
  assert p.is_file() and not p.is_symlink()
  if p.suffix=='.py':compile(p.read_bytes(),str(p),'exec')
 point=root/'backups'/('candidate-guardian-install-'+str(time.time_ns()));point.mkdir(mode=0o700,parents=True)
 (point/'receipt.json').write_text(json.dumps({'schema':1,'root':str(root),'source_sha256':{n:hashlib.sha256(p.read_bytes()).hexdigest() for n,p in sources.items()},'state':'installing','previous_guardian':False}))
 try:
  dest.mkdir(mode=0o700,parents=True)
  for name,p in sources.items():
   assert p.is_file() and not p.is_symlink();target=dest/name
   assert not target.is_symlink();shutil.copyfile(p,target);target.chmod(0o600)
  args=[sys.executable,str(dest/'manager.py'),'--root',str(root),'seal','--kit',str(dest)]
  if auto_pure:args+=['--auto-pure']
  subprocess.run(args,check=True,capture_output=True,timeout=30)
  # Installation is explicit administrator work. Runtime proposals cannot alter units.
  service='[Unit]\nDescription=Bounded Companion pure-function repair guardian\nAfter=docker.service\n[Service]\nType=oneshot\nUMask=0077\nExecStart='+sys.executable+' '+str(dest/'manager.py')+' --root '+str(root)+' tick --publish\nTimeoutStartSec=180\nNice=15\n'
  timer='[Unit]\nDescription=Check bounded Companion repair proposals\n[Timer]\nOnActiveSec=1min\nOnUnitActiveSec=1min\nPersistent=true\n[Install]\nWantedBy=timers.target\n'
  for name,text in [('service',service),('timer',timer)]:
   p=Path('/etc/systemd/system/p1-companion-candidates.'+name);assert not p.is_symlink();p.write_text(text);p.chmod(0o644)
  registered=register_recovery(root,point)
  subprocess.run(['systemctl','daemon-reload'],check=True,timeout=20);subprocess.run(['systemctl','enable','--now','p1-companion-candidates.timer'],check=True,capture_output=True,timeout=25)
  (point/'receipt.json').write_text(json.dumps({'schema':1,'root':str(root),'state':'installed','previous_guardian':False,'auto_pure':auto_pure,'sealed_control_files':registered,'source_sha256':{n:hashlib.sha256(p.read_bytes()).hexdigest() for n,p in sources.items()}}))
  return {'installed':True,'auto_pure':auto_pure,'target':'qq_format','new_code_other_modules':'reviewed_release_required','public_ports':0,'private_recovery_receipt':str(point)}
 except BaseException as exc:
  subprocess.run(['systemctl','disable','--now','p1-companion-candidates.timer'],capture_output=True,timeout=25)
  subprocess.run(['systemctl','stop','p1-companion-candidates.service'],capture_output=True,timeout=25)
  restore_registration(root,point)
  for unit in units:
   if unit.is_file() and not unit.is_symlink():unit.unlink()
  if dest.is_dir() and not dest.is_symlink():os.replace(dest,point/'failed-source')
  subprocess.run(['systemctl','daemon-reload'],capture_output=True,timeout=20)
  (point/'receipt.json').write_text(json.dumps({'schema':1,'root':str(root),'state':'installation_rolled_back','error':type(exc).__name__,'runtime_databases_changed':False}))
  raise

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=Path('/srv/p1-agent'));p.add_argument('--apply',action='store_true');p.add_argument('--auto-pure',action='store_true');a=p.parse_args()
 if not a.apply:print(json.dumps({'dry_run':True,'root':str(a.root),'auto_pure':a.auto_pure}));return
 sys.path.insert(0,str(R/'services/updater'));from manager import root_path
 print(json.dumps(install(root_path(str(a.root)),a.auto_pure)))
if __name__=='__main__':main()
