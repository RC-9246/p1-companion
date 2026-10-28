#!/usr/bin/env python3
"""Closed-action whole-stack recovery. Neither shell commands nor paths come from a model."""
import fcntl,hashlib,json,os,sqlite3,subprocess,sys,time,shutil
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent));sys.path.insert(0,'/usr/local/lib/p1-companion')
from resilience import SERVICES,restore_sources,restore_database,valid_db,snapshot_database,repair_policy_file,maintenance_plan,restore_fixed,fixed_dependents
BASE=Path('/srv/p1-agent');AST=BASE/'astrbot/data';DATA=AST/'plugin_data/affect';STATE=DATA/'maintenance_state.json';RECOVERY=Path('/var/lib/p1-companion/recovery/current')
MODULE_POLICY_SCHEMA=1
def module_disabled_services(base=BASE,policy_root=Path('/var/lib/p1-companion-modules')):
 path=policy_root/hashlib.sha256(str(base).encode()).hexdigest()[:16]/'desired.json'
 optional=set(SERVICES)-{'astrbot','snowluma'}
 if not path.exists():return set(),True
 try:
  s=path.stat()
  if any(p.is_symlink() for p in (path,*path.parents)) or s.st_uid!=0 or s.st_mode&0o077 or s.st_size>65536:raise ValueError('untrusted_module_policy')
  v=json.loads(path.read_bytes());names=v['disabled_services']
  if v.get('schema')!=1 or v.get('root')!=str(base) or not isinstance(names,list) or not all(isinstance(x,str) for x in names) or not set(names)<=optional:raise ValueError('invalid_module_policy')
  return set(names),True
 except (OSError,ValueError,KeyError,TypeError):return optional,False
DBS={'affect':(DATA/'affect.db',('affect_state','companion_state')),'memoria':(AST/'plugin_data/memoria/memoria.db',('memoria_records',)),'groups':(AST/'plugin_data/p1_groups/groups.db',('group_meta',)),'agency':(DATA/'agency/agency.db',('scope','task')),'astrbot':(AST/'data_v4.db',('conversations',)),'knowledge':(AST/'knowledge_base/kb.db',())}

COMPOSE={
 'astrbot':(BASE/'astrbot/compose.yaml','astrbot','astrbot'),'snowluma':(BASE/'snowluma/compose.yaml','snowluma','snowluma'),
 'p1-n8n':(AST/'companion_services/workflows/compose.yaml','p1-workflows','workflows'),
 'p1-browser':(Path('/srv/p1-agent/public-browser/compose.yaml'),'p1-companion','browser'),
 'p1-browser-egress':(Path('/srv/p1-agent/public-browser/compose.yaml'),'p1-companion','egress'),
 'p1-leisure':(AST/'companion_services/leisure/compose.yaml','p1-leisure','leisure'),
 'p1-leisure-egress':(AST/'companion_services/leisure/compose.yaml','p1-leisure','egress'),
 'p1-workbench':(AST/'companion_services/workbench/compose.yaml','p1-workbench','workbench')}
FIXED={'mcp_server':AST/'companion_services/mcp/server.py',**{'internal_'+name:DATA/name for name in ('browser_token','leisure_token','workbench_token')},**{'leisure_'+name.replace('.py',''):AST/'companion_services/leisure'/name for name in ('server.py','policy.py','private_api.py','quota.py','egress.py')},
 'maintain':Path('/usr/local/sbin/p1-companion-maintain.py'),'resilience':Path('/usr/local/lib/p1-companion/resilience.py'),'watchdog':Path('/usr/local/sbin/p1-companion-watchdog.py'),
 'backup_agency':Path('/usr/local/sbin/p1-companion-backup-agency.py'),'backup_dbs':Path('/usr/local/sbin/p1-backup-dbs'),'core_health':Path('/usr/local/sbin/p1-healthcheck.py'),
 **{'unit_'+name.replace('.','_'):Path('/etc/systemd/system')/name for name in ('p1-companion-maintain.service','p1-companion-maintain.timer','p1-companion-watchdog.service','p1-companion-watchdog.timer')},
 **{'compose_'+key:row[0] for key,row in COMPOSE.items()}}
def recover_service(name,force_recreate=False):
 if name not in SERVICES:raise ValueError('unknown_service')
 inspected=run(['docker','inspect',name,'--format','{{.Id}}'])
 if inspected.returncode==0 and not force_recreate:return run(['docker','restart','--time','8',name],45)
 path,project,service=COMPOSE[name];known=read(RECOVERY/'services.json',{}).get(name)
 if not known or not path.is_file() or run(['docker','image','inspect',known['image'],'--format','{{.Id}}']).returncode:return type('Result',(),{'returncode':1})()
 override=RECOVERY/('override-'+name+'.json');atomic(override,{'services':{service:{'image':known['image']}}})
 result=run(['docker','compose','-p',project,'--project-directory',str(path.parent),'-f',str(path),'-f',str(override),'up','-d','--no-deps','--pull','never',*(['--force-recreate'] if force_recreate else []),service],65)
 if result.returncode==0 and name=='astrbot':run(['docker','network','connect','p1-companion-control','astrbot'])
 return result

def run(args,timeout=15):return subprocess.run(args,capture_output=True,text=True,timeout=timeout)
def atomic(path,data):
 p=path.with_name(path.name+'.next');p.write_text(json.dumps(data,sort_keys=True));p.chmod(0o600);os.replace(p,path)
def read(path,default):
 try:return json.loads(Path(path).read_text())
 except (OSError,ValueError):return default

def healthy(name):
 r=run(['docker','inspect',name,'--format','{{json .State}}'])
 if r.returncode:return False
 v=json.loads(r.stdout);ok=v.get('Running') is True and v.get('Health',{}).get('Status','healthy')=='healthy' and not v.get('OOMKilled')
 if name=='astrbot' and ok:
  try:
   stamp=read(DATA/'companion_health.json',{});ok=all(stamp.get(k) for k in ('group_memory_ready','group_affect_ready','learning_ready','qq_plain_ready','agency_ready'))
  except Exception:ok=False
 return ok

def decision(state,name,ok,now):
 item=state.setdefault(name,{'failures':0,'last_repair':0,'repairs':[]})
 item['repairs']=[t for t in item['repairs'] if now-t<86400]
 item['failures']=0 if ok else item['failures']+1
 return bool(not ok and item['failures']>=3 and now-item['last_repair']>1800 and len(item['repairs'])<2)
def cleanup():
 sys.path.insert(0,str(AST/'plugins'))
 from astrbot_plugin_affect.agency_store import AgencyStore
 s=AgencyStore(DATA)
 if s.path.exists() and valid_db(s.path,('scope',)):s.cleanup()
 from astrbot_plugin_affect.retention import native_database
 path=AST/'data_v4.db'
 if path.is_file() and valid_db(path,('conversations',)):native_database(path)
def snapshot(name,now):
 p=BASE/'backups'/('companion-auto-repair-'+time.strftime('%Y%m%d-%H%M%S',time.localtime(now))+'-'+name);p.mkdir(mode=0o700)
 rows=[]
 for service in SERVICES:
  r=run(['docker','inspect',service,'--format','{{.Image}} {{.RestartCount}}']);rows.append({'service':service,'image_and_restart':r.stdout.strip(),'healthy':healthy(service)})
 atomic(p/'before.json',{'service':name,'at':now,'services':rows});return p

def ensure_databases(state,now,repairs):
 integrity={k:valid_db(path,required) for k,(path,required) in DBS.items()}
 ready={k:decision(state,'db-'+k,ok,now) for k,ok in integrity.items()}
 bad=[k for k,ok in integrity.items() if not ok]
 if bad and all(ready[k] for k in bad):
  candidates=sorted((BASE/'backups/verified-companion').glob('*'),reverse=True)
  selected={k:next((q/(k+'.db') for q in candidates if valid_db(q/(k+'.db'),DBS[k][1])),None) for k in bad}
  # No corrupt backup is ever promoted. Keep live state untouched if none validates.
  if all(selected.values()):
   run(['docker','stop','--time','10','astrbot'],45);point=snapshot('databases',now)
   try:
    for k in bad:
     result=restore_database(DBS[k][0],selected[k],point/'quarantine',DBS[k][1],now);repairs.append({'module':k,**result});entry=state['db-'+k];entry['last_repair']=now;entry['repairs'].append(now)
   finally:run(['docker','start','astrbot'],25)
  else:repairs.append({'module':'database','state':'no_verified_backup','restored':False})
 # Snapshot only healthy databases, in six-hour generations, fourteen retained.
 if not bad and now-state.get('_last_verified_backup',0)>21600:
  folder=BASE/'backups/verified-companion'/time.strftime('%Y%m%d-%H%M%S');folder.mkdir(mode=0o700,parents=True)
  for k,(path,required) in DBS.items():
   if path.exists() and valid_db(path,required):snapshot_database(path,folder/(k+'.db'))
  # No raw attachment excerpts are included in a recovery snapshot.
  sys.path.insert(0,str(AST/'plugins'))
  from astrbot_plugin_affect.retention import native_database
  if (folder/'astrbot.db').is_file():native_database(folder/'astrbot.db',all_temporary=True)
  if (folder/'agency.db').is_file():
   with sqlite3.connect(folder/'agency.db') as c:
    c.execute('DELETE FROM document')
    for table in ('event','task','artifact'):c.execute('DELETE FROM '+table+' WHERE expires>0')
  for q in sorted(folder.parent.iterdir(),reverse=True)[14:]:
   if q.is_dir() and len(q.name)==15:shutil.rmtree(q)
  state['_last_verified_backup']=now
 return integrity

def resources():
 available=999999;temperature=0
 try:
  info=dict(line.split(':',1) for line in Path('/proc/meminfo').read_text().splitlines());available=int(info['MemAvailable'].split()[0])//1024
  values=[int(p.read_text())/1000 for p in Path('/sys/class/thermal').glob('thermal_zone*/temp')];temperature=max(values or [0])
 except (OSError,ValueError):pass
 clock_skew=0
 try:
  previous=read(DATA/'resource_health.json',{});uptime=float(Path('/proc/uptime').read_text().split()[0]);old=previous.get('uptime',uptime);clock_skew=(time.time()-previous.get('at',time.time()))-(uptime-old) if uptime>=old else 0
 except (OSError,ValueError):pass
 return {**maintenance_plan(available,shutil.disk_usage(DATA).free//1048576,temperature,clock_skew),'uptime':float(Path('/proc/uptime').read_text().split()[0])}
def main():
 os.umask(0o077);DATA.mkdir(parents=True,exist_ok=True)
 with (DATA/'maintenance.lock').open('w') as lock:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:return
  state=read(STATE,{});now=time.time();repairs=[];integrity={};request=read(DATA/'maintenance_request.json',{});(DATA/'maintenance_request.json').unlink(missing_ok=True);disabled=(DATA/'maintenance.disabled').exists()
  module_off,module_policy_valid=module_disabled_services()
  if not disabled:
   try:
    repaired_fixed=restore_fixed(FIXED,RECOVERY/'fixed',read(RECOVERY/'fixed-manifest.json',{}),read(RECOVERY/'fixed-metadata.json',{}))
    if repaired_fixed:
     repairs.append({'module':'fixed_services','files':repaired_fixed})
     if any(k.startswith('unit_') for k in repaired_fixed):run(['systemctl','daemon-reload']);run(['systemctl','enable','--now','p1-companion-maintain.timer','p1-companion-watchdog.timer'])
     for service in fixed_dependents(repaired_fixed):
      if service not in module_off:run(['docker','restart','--time','8',service],45)
   except (ValueError,OSError):repairs.append({'module':'fixed_services','state':'checkpoint_rejected'})
   manifest=read(RECOVERY/'manifest.json',{})
   if manifest:
    try:
     fixed=restore_sources(AST/'plugins',RECOVERY/'plugins',manifest)
     if fixed:
      repairs.append({'module':'plugin_sources','restored_files':len(fixed),'verified_snapshot':True});run(['docker','restart','--time','10','astrbot'],45)
    except (ValueError,OSError):repairs.append({'module':'plugin_sources','state':'checkpoint_rejected'})
   for name,kind in [('groups.json','groups'),('qq_policy.json','qq'),('allowed_identities.json','identities')]:
    if repair_policy_file(DATA/name,kind):repairs.append({'module':kind,'state':'recovered_with_access_closed'})
   integrity=ensure_databases(state,now,repairs)
   for name in SERVICES:
    if name in module_off:continue
    ok=healthy(name)
    if decision(state,name,ok,now):
     point=snapshot(name,now);state[name]['last_repair']=now;state[name]['repairs'].append(now);atomic(STATE,state)
     recreate=len(state[name]['repairs'])>=2;r=recover_service(name,recreate);success=False
     for _ in range(6):
      time.sleep(3)
      if healthy(name):success=True;break
     result={'service':name,'action':'recreate_verified_image' if recreate else 'restart_existing_image','ok':bool(r.returncode==0 and success),'at':now};atomic(point/'after.json',result);repairs.append(result)
  try:cleanup();ttl=True
  except Exception:ttl=False
  resource=resources();atomic(DATA/'resource_health.json',{'at':now,**resource})
  # A resource stop is distinct from the user's own pause file; the AI cannot erase it.
  atomic(STATE,state);atomic(DATA/'maintenance_health.json',{'at':now,'ttl_sweep':ttl,'diagnostic_requested':request.get('kind')=='diagnostic_only','repairs':repairs,'databases':integrity,'services':{name:healthy(name) for name in SERVICES if name not in module_off},'intentionally_disabled_services':sorted(module_off),'module_policy_valid':module_policy_valid,'resource':resource,'disabled':disabled,'repair_policy':'known_sources_or_fixed_restarts_or_verified_database_snapshot','kernel_hardware_account_captcha':'requires_external_recovery_or_human'})
if __name__=='__main__':main()
