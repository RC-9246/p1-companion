"""Promote only the installed, verified release into a root-owned recovery checkpoint."""
import hashlib,importlib.util,json,os,shutil,subprocess,time
from pathlib import Path
BASE=Path('/srv/p1-agent');DATA=BASE/'astrbot/data';STAGE=DATA/'companion_v020_lab';ROOT=Path('/var/lib/p1-companion/recovery')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 assert os.geteuid()==0;os.umask(0o077);ROOT.mkdir(parents=True,exist_ok=True,mode=0o700)
 spec=importlib.util.spec_from_file_location('maint',STAGE/'services/maintenance/p1-companion-maintain.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
 pending=ROOT/('next-'+str(time.time_ns()));pending.mkdir(mode=0o700)
 manifest=json.loads((STAGE/'evidence/release-manifest.json').read_text())
 for rel,digest in manifest.items():
  source=DATA/'plugins'/rel;assert sha(source)==digest
  target=pending/'plugins'/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target);target.chmod(0o600)
 (pending/'manifest.json').write_text(json.dumps(manifest,sort_keys=True))
 fixed={};metadata={};(pending/'fixed').mkdir()
 for key,source in m.FIXED.items():
  assert source.is_file(),key;shutil.copy2(source,pending/'fixed'/key);(pending/'fixed'/key).chmod(0o600);fixed[key]=sha(source)
  s=source.stat();metadata[key]={'uid':s.st_uid,'gid':s.st_gid,'mode':s.st_mode&0o777}
 (pending/'fixed-manifest.json').write_text(json.dumps(fixed,sort_keys=True))
 (pending/'fixed-metadata.json').write_text(json.dumps(metadata,sort_keys=True))
 services={}
 for name in m.SERVICES:
  r=subprocess.run(['docker','inspect',name,'--format','{{.Image}}'],capture_output=True,text=True,check=True);services[name]={'image':r.stdout.strip()}
 (pending/'services.json').write_text(json.dumps(services))
 current=ROOT/'current'
 if current.exists():os.replace(current,ROOT/('previous-'+str(time.time_ns())))
 os.replace(pending,current)
 for p in current.rglob('*'):
  p.chmod(0o700 if p.is_dir() else 0o600)
 print(json.dumps({'recovery_checkpoint_promoted':True,'plugin_files':len(manifest),'fixed_files':len(fixed),'services':len(services),'private_snapshot_exported':False}))
if __name__=='__main__':main()
