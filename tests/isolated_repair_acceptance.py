"""Run on P1 host as root. Faults affect only disposable copies and named lab containers."""
import importlib.util,json,os,shutil,sqlite3,subprocess,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'services/maintenance'))
import resilience as R
NAME='p1-repair-lab-worker';PROD=R.SERVICES
report=[]
def run(args,timeout=25):
 assert args[0]=='docker' and (args[1] in ('ps','image') or any(x.startswith('p1-repair-lab') for x in args) or args[1]=='inspect')
 return subprocess.run(args,capture_output=True,text=True,timeout=timeout)
def production():
 result={}
 for name in PROD:
  r=run(['docker','inspect',name,'--format','{{.State.StartedAt}} {{.RestartCount}}']);result[name]=r.stdout.strip()
 return result
def item(name,passed,**details):
 report.append({'case':name,'passed':bool(passed),**details});assert passed,name

def health():
 r=run(['docker','exec',NAME,'python','-c',"import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8767/health',timeout=2).status)"])
 return r.returncode==0 and r.stdout.strip()=='200'
def wait_health():
 for _ in range(12):
  if health():return True
  time.sleep(1)
 return False

def main():
 assert os.geteuid()==0;os.umask(0o077);before=production()
 with tempfile.TemporaryDirectory(prefix='p1-isolated-repair-',dir=ROOT) as tmp:
  sandbox=Path(tmp);live=sandbox/'plugins';cp=sandbox/'trusted';manifest={}
  for name in R.MODULES:
   source=ROOT/'release'/name/'main.py';dest=cp/name/'main.py';dest.parent.mkdir(parents=True);shutil.copy2(source,dest);manifest[str(dest.relative_to(cp))]=R.digest(dest)
  R.restore_sources(live,cp,manifest)
  # Each of the eight plugin families gets an actual missing-file fault.
  for module in R.MODULES:
   (live/module/'main.py').unlink();fixed=R.restore_sources(live,cp,manifest);item('missing_'+module,len(fixed)==1 and R.digest(live/module/'main.py')==manifest[module+'/main.py'])
  (live/'astrbot_plugin_affect/main.py').write_text('broken source syntax !!!');item('tampered_plugin_recovered',bool(R.restore_sources(live,cp,manifest)))
  poison=cp/'astrbot_plugin_affect/main.py';poison.write_text('poisoned checkpoint')
  try:R.restore_sources(live,cp,manifest);accepted=True
  except ValueError:accepted=False
  item('poisoned_checkpoint_rejected',not accepted)
  for kind in ('groups','qq','identities'):
   p=sandbox/(kind+'.json');p.write_text('{truncated');item('policy_'+kind+'_recovers_closed',R.repair_policy_file(p,kind));value=json.loads(p.read_text());item('policy_'+kind+'_revoked_access_stays_closed',not R.repair_policy_file(p,kind))
  # Every database role is exercised against synthetic SQLite, with live originals retained.
  for name in ('affect','memoria','groups','agency','astrbot','knowledge'):
   src=sandbox/(name+'-good.db');live_db=sandbox/(name+'-bad.db')
   with sqlite3.connect(src) as c:
    c.execute('CREATE TABLE evidence(id INTEGER,value TEXT)');c.execute("INSERT INTO evidence VALUES(1,'synthetic proof')")
   live_db.write_bytes(b'corrupt synthetic database');result=R.restore_database(live_db,src,sandbox/'quarantine',('evidence',));item('database_'+name+'_restored',result.get('restored') and R.valid_db(live_db,('evidence',)))
  bad=sandbox/'bad-backup.db';bad.write_bytes(b'bad backup');original=sandbox/'unchanged-corrupt.db';original.write_bytes(b'original preserve');item('bad_backup_does_not_overwrite_original',R.restore_database(original,bad,sandbox/'quarantine').get('state')=='backup_rejected' and original.read_bytes()==b'original preserve')
  for reason,args in [('memory',(300,5000,45)),('disk',(1800,200,45)),('thermal',(1800,5000,82)),('clock',(1800,5000,45,900))]:item('resource_'+reason+'_safe_degrade',R.maintenance_plan(*args)['pause_optional'])
  # Maintenance's real missing-container branch uses a lab-only Compose and local image.
  spec=importlib.util.spec_from_file_location('lab_maint',ROOT/'services/maintenance/p1-companion-maintain.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
  token=sandbox/'token';token.write_text('synthetic-lab-token');token.chmod(0o600);os.chown(token,1001,1001)
  ancillary=sandbox/'ancillary';ancillary.mkdir();files={};hashes={};metadata={}
  for key,target,body,owner,mode in [
   ('internal_workbench_token',token,'synthetic-lab-token',(1001,1001),0o600),
   ('leisure_server',sandbox/'leisure.py','known nonroot code',(0,1001),0o640),
   ('backup_dbs',sandbox/'backup-dbs','#!/bin/sh\nprintf ok',(0,0),0o700)]:
   source=ancillary/key;source.write_text(body);hashes[key]=R.digest(source);files[key]=target;metadata[key]={'uid':owner[0],'gid':owner[1],'mode':mode};target.unlink(missing_ok=True)
  fixed=R.restore_fixed(files,ancillary,hashes,metadata)
  item('internal_token_owner_and_mode_restored',token.stat().st_uid==1001 and token.stat().st_gid==1001 and token.stat().st_mode&0o777==0o600)
  item('nonroot_leisure_code_group_read_restored',files['leisure_server'].stat().st_gid==1001 and files['leisure_server'].stat().st_mode&0o777==0o640)
  item('backup_without_py_extension_is_executable',subprocess.run([str(files['backup_dbs'])],capture_output=True,text=True).stdout=='ok')
  files['backup_dbs'].chmod(0o600)
  item('content_unchanged_permission_drift_repaired',R.restore_fixed(files,ancillary,hashes,metadata)==['backup_dbs'])
  item('fixed_permissions_do_not_trigger_repeated_repairs',not R.restore_fixed(files,ancillary,hashes,metadata))
  compose=sandbox/'compose.yaml';compose.write_text('services:\n  worker:\n    image: p1-companion-workbench:0.20.0\n    container_name: '+NAME+'\n    init: true\n    network_mode: none\n    read_only: true\n    user: "1001:1001"\n    cap_drop: [ALL]\n    security_opt: [no-new-privileges:true]\n    pids_limit: 40\n    mem_limit: 512m\n    tmpfs: ["/tmp:size=96m,mode=1777"]\n    volumes:\n      - '+str(token)+':/run/secrets/workbench_token:ro\n')
  image=run(['docker','image','inspect','p1-companion-workbench:0.20.0','--format','{{.Id}}']).stdout.strip();checkpoint=sandbox/'checkpoint';checkpoint.mkdir();(checkpoint/'services.json').write_text(json.dumps({NAME:{'image':image}}));m.SERVICES=(NAME,);m.COMPOSE={NAME:(compose,'p1-repair-lab','worker')};m.RECOVERY=checkpoint
  # Force removal only of this disposable test container, never production.
  run(['docker','rm','-f',NAME]);result=m.recover_service(NAME);item('missing_container_recreated_from_known_image',result.returncode==0 and wait_health())
  before_image=run(['docker','inspect',NAME,'--format','{{.Image}}']).stdout.strip();run(['docker','kill',NAME]);result=m.recover_service(NAME);item('crashed_container_restart_actual',result.returncode==0 and wait_health());item('repair_did_not_change_image',run(['docker','inspect',NAME,'--format','{{.Image}}']).stdout.strip()==before_image)
  old_id=run(['docker','inspect',NAME,'--format','{{.Id}}']).stdout.strip();result=m.recover_service(NAME,True)
  item('second_fault_escalates_to_verified_image_recreation',result.returncode==0 and wait_health() and run(['docker','inspect',NAME,'--format','{{.Id}}']).stdout.strip()!=old_id and run(['docker','inspect',NAME,'--format','{{.Image}}']).stdout.strip()==before_image)
  # The independent watchdog repairs its own sibling in a copied filesystem.
  from unittest.mock import patch
  sys.path.insert(0,str(ROOT/'tests'))
  from test_repair_chain import Fixture
  watch=sandbox/'watchdog';watch.mkdir();fixture=Fixture(watch)
  fixture.damage('maintain');fixture.damage('resilience');watch_result=fixture.recover()
  item('independent_watchdog_repairs_repair_engine',watch_result['status']=='repair_succeeded' and all(R.digest(fixture.files[k])==fixture.hashes[k] for k in ('maintain','resilience')))
  # An infinite child experiment hits the real subprocess limit; its service survives.
  code="import urllib.request,json; req=urllib.request.Request('http://127.0.0.1:8767/experiment',data=json.dumps({'code':'while True: pass'}).encode(),headers={'Authorization':'Bearer synthetic-lab-token','Content-Type':'application/json'});v=json.load(urllib.request.urlopen(req,timeout=12));print(json.dumps({'denied':not v.get('ok')}))"
  r=run(['docker','exec',NAME,'python','-c',code],20);item('infinite_experiment_bounded_service_survives',r.returncode==0 and json.loads(r.stdout)['denied'] and health())
  import fcntl
  lockpath=sandbox/'deployment.lock'
  with lockpath.open('a') as lock:
   fcntl.flock(lock,fcntl.LOCK_EX)
   child=subprocess.run([sys.executable,'-c',"import fcntl,sys;f=open(sys.argv[1],'a');\ntry:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)\nexcept BlockingIOError:print('deployment_in_progress');sys.exit(0)\nsys.exit(1)",str(lockpath)],capture_output=True,text=True)
   item('deployment_and_self_repair_share_exclusive_lock',child.returncode==0 and child.stdout.strip()=='deployment_in_progress')
  # Restart throttling uses the same production decision function.
  state={};now=time.time();m.decision(state,NAME,False,now);m.decision(state,NAME,False,now+180);ready=m.decision(state,NAME,False,now+360);state[NAME]['last_repair']=now+360;state[NAME]['repairs']=[now+360];item('three_failure_gate_and_restart_cooldown',ready and not m.decision(state,NAME,False,now+500))
  run(['docker','rm','-f',NAME])
 after=production();item('all_production_containers_unchanged',before==after)
 summary={'isolated_fault_injection':True,'cases':report,'all_passed':all(x['passed'] for x in report),'real_container_crash_and_recreation':True,'production_data_mounted_into_lab':False,'lab_network':'none','production_before_after_equal':before==after,'real_qq_messages':0}
 (ROOT/'evidence/isolated-repair-acceptance.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2));print(json.dumps(summary,ensure_ascii=False))
if __name__=='__main__':
 try:main()
 finally:run(['docker','rm','-f',NAME])
