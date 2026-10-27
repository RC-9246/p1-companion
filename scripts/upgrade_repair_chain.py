"""Upgrade only the independent recovery watchdog, with a private rollback point.

No bot/container restart, SQL operation, model call or account change. A temporary
on-disk systemd guard can restore an uncommitted upgrade after process loss/reboot.
"""
import argparse,contextlib,fcntl,hashlib,json,os,re,secrets,shutil,stat,subprocess,sys,time,types
from pathlib import Path
SOURCE=Path(__file__).resolve().parents[1]/'services/maintenance/p1-companion-watchdog.py'
CURRENT=Path('/var/lib/p1-companion/recovery/current')
LIVE=Path('/usr/local/sbin/p1-companion-watchdog.py')
TIMERS=('p1-companion-maintain.timer','p1-companion-watchdog.timer')
UNITS=('p1-companion-maintain.service','p1-companion-watchdog.service')
UNITDIR=Path('/etc/systemd/system')
class UpgradeError(RuntimeError):pass

def check(ok,code):
 if not ok:raise UpgradeError(code)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):
 raw=Path(p).read_bytes();check(len(raw)<=262144,'private_record_too_large');return json.loads(raw)
def atom(p,raw,mode=0o600,uid=0,gid=0):
 p=Path(p);p.parent.mkdir(mode=0o700,parents=True,exist_ok=True);tmp=p.with_name(p.name+'.'+secrets.token_hex(4)+'.next')
 try:
  with tmp.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
  os.chown(tmp,uid,gid);tmp.chmod(mode);os.replace(tmp,p)
 finally:tmp.unlink(missing_ok=True)
def write(p,value):atom(p,(json.dumps(value,sort_keys=True)+'\n').encode())
def run(args,timeout=25):
 try:r=subprocess.run(args,capture_output=True,text=True,timeout=timeout)
 except (OSError,subprocess.TimeoutExpired):raise UpgradeError('bounded_command_unavailable') from None
 return r
def good(args,timeout=25):
 r=run(args,timeout);check(r.returncode==0,'closed_command_failed');return r

def root_path(value):
 p=Path(value);check(p.is_absolute() and len(p.parts)>=3 and '..' not in p.parts and re.fullmatch('/[A-Za-z0-9_./-]+',str(p)),'invalid_root')
 check(not any(x.is_symlink() for x in (p,*p.parents)) and p==p.resolve(),'root_symlink_denied');return p

def sources(base):
 d=base/'astrbot/data'
 standard=d/'companion_services/maintenance/p1-companion-watchdog.py'
 legacy=d/'companion_neutral_v020_lab/services/maintenance/p1-companion-watchdog.py'
 # The earlier private deployment predates companion_services. Accept its
 # one known neutral staging copy; never discover arbitrary write targets.
 auxiliary=legacy if not standard.exists() and legacy.is_file() else standard
 return [LIVE,auxiliary,d/'companion_v020_lab/services/maintenance/p1-companion-watchdog.py']
def tree_hashes(path):
 check(not path.is_symlink(),'checkpoint_symlink_denied')
 result={}
 for p in path.rglob('*'):
  check(not p.is_symlink(),'checkpoint_symlink_denied')
  if p.is_file():result[str(p.relative_to(path))]=sha(p)
 return result

def timer_states():return {t:{'enabled':run(['systemctl','is-enabled','--quiet',t]).returncode==0,'active':run(['systemctl','is-active','--quiet',t]).returncode==0} for t in TIMERS}
def restore_timers(states):
 for t in TIMERS:
  good(['systemctl','enable' if states[t]['enabled'] else 'disable',t])
  good(['systemctl','start' if states[t]['active'] else 'stop',t])
def quiesce():
 good(['systemctl','stop',*TIMERS])
 for unit in UNITS:
  end=time.monotonic()+75
  while run(['systemctl','is-active',unit]).stdout.strip() in ('active','activating','deactivating','reloading'):
   check(time.monotonic()<end,'maintenance_did_not_quiesce');time.sleep(.5)

@contextlib.contextmanager
def exclusive(path):
 check(not path.is_symlink(),'lock_symlink_denied');path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
 with path.open('a') as f:
  try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:raise UpgradeError('another_operation_in_progress') from None
  yield

def validate_point(point,base):
 point=Path(point).resolve();check(point.parent==base/'backups' and re.fullmatch('recovery-chain-[0-9-]+',point.name),'invalid_recovery_point')
 check(point.stat().st_uid==0 and not point.stat().st_mode&0o077,'untrusted_recovery_point')
 info=read(point/'receipt.json');check(isinstance(info,dict) and type(info.get('schema')) is int and info['schema']==1 and info['root']==str(base),'recovery_root_mismatch')
 check(info['checkpoint_before']==tree_hashes(point/'checkpoint'),'backup_checkpoint_changed')
 check(set(info['before'])=={str(p) for p in sources(base)},'recovery_target_denied')
 for index,p in enumerate(sources(base)):
  row=info['before'][str(p)]
  check(isinstance(row,dict) and set(row)=={'slot','sha256','uid','gid','mode'} and row['slot']==str(index),'backup_metadata_invalid')
  check(all(type(row[k]) is int for k in ('uid','gid','mode')) and 0<=row['uid']<2**31 and 0<=row['gid']<2**31 and 0<row['mode']<=0o777 and not row['mode']&0o022,'backup_permissions_invalid')
  check(not (point/'before'/row['slot']).is_symlink() and sha(point/'before'/row['slot'])==row['sha256'],'source_backup_changed')
 check(set(info['timers'])==set(TIMERS) and all(set(v)=={'enabled','active'} and all(type(x) is bool for x in v.values()) for v in info['timers'].values()),'timer_state_invalid')
 check(isinstance(info['after_source_sha256'],str) and re.fullmatch('[a-f0-9]{64}',info['after_source_sha256']),'candidate_digest_invalid')
 check(set(info['guard_hashes'])=={'.service','.timer'} and all(re.fullmatch('[a-f0-9]{64}',x) for x in info['guard_hashes'].values()),'guard_digest_invalid')
 check(re.fullmatch('p1-repair-upgrade-[0-9-]+',info['guard']),'guard_name_invalid')
 return point,info

def cleanup_guard(point,info):
 name=info['guard'];run(['systemctl','stop',name+'.timer']);run(['systemctl','disable',name+'.timer'])
 for suffix in ('.service','.timer'):
  path=UNITDIR/(name+suffix)
  if path.exists():
   check(sha(path)==info['guard_hashes'][suffix],'guard_unit_changed');path.unlink()
 run(['systemctl','daemon-reload'])

def compatible_checkpoint(info):
 if not CURRENT.exists():return True
 current=tree_hashes(CURRENT);before=info['checkpoint_before']
 # The upgrade can only change this sealed file and its manifest entry.
 for rel,digest in current.items():
  if rel not in ('fixed/watchdog','fixed-manifest.json') and before.get(rel)!=digest:return False
 if (CURRENT/'fixed-manifest.json').is_file():
  now=read(CURRENT/'fixed-manifest.json');old=info['old_fixed_manifest']
  if {k:v for k,v in now.items() if k!='watchdog'}!={k:v for k,v in old.items() if k!='watchdog'}:return False
 return True

def restore(point,base,manual=False):
 point,info=validate_point(point,base)
 if (point/'rolled_back').exists():cleanup_guard(point,info);return
 if (point/'committed').exists() and not manual:cleanup_guard(point,info);return
 if manual and (point/'committed').exists():
  after=read(point/'after.json');check(CURRENT.exists() and tree_hashes(CURRENT)==after['checkpoint'],'later_checkpoint_requires_manual_review')
  check(all(p.exists() and sha(p)==after['sources'][str(p)] for p in sources(base)),'later_source_changes_require_manual_review')
 else:check(compatible_checkpoint(info),'intervening_checkpoint_requires_manual_review')
 for p in sources(base):
  if p.exists():check(sha(p) in (info['before'][str(p)]['sha256'],info['after_source_sha256']),'intervening_source_requires_manual_review')
 quiesce()
 data=base/'astrbot/data/plugin_data/affect'
 with exclusive(data/'maintenance.lock'):
  for p in sources(base):
   row=info['before'][str(p)];atom(p,(point/'before'/row['slot']).read_bytes(),row['mode'],row['uid'],row['gid'])
  if CURRENT.exists():shutil.rmtree(CURRENT)
  shutil.copytree(point/'checkpoint',CURRENT)
  check(tree_hashes(CURRENT)==info['checkpoint_before'],'checkpoint_restore_verification_failed')
  atom(point/'rolled_back',b'1\n')
 restore_timers(info['timers']);cleanup_guard(point,info)


def boot():return Path('/proc/sys/kernel/random/boot_id').read_text().strip()
def uptime():return float(Path('/proc/uptime').read_text().split()[0])
def pid_start(pid):
 try:return Path('/proc',str(pid),'stat').read_text().rsplit(')',1)[1].split()[19]
 except (OSError,IndexError):return None

def arm_guard(point,info):
 name=info['guard'];helper=point/'rollback-helper.py';shutil.copy2(Path(__file__),helper);helper.chmod(0o700)
 service=('[Unit]\nDescription=Recover an uncommitted Companion watchdog upgrade\n[Service]\nType=oneshot\nUser=root\nUMask=0077\nExecStart=/usr/bin/python3 '+str(helper)+' --root '+info['root']+' --recover '+str(point)+'\nTimeoutStartSec=180\n')
 timer='[Unit]\nDescription=Bounded Companion upgrade recovery\n[Timer]\nOnBootSec=2min\nOnUnitActiveSec=3min\n[Install]\nWantedBy=timers.target\n'
 info['guard_hashes']={'.service':hashlib.sha256(service.encode()).hexdigest(),'.timer':hashlib.sha256(timer.encode()).hexdigest()}
 write(point/'receipt.json',info)
 for suffix,raw in (('.service',service),('.timer',timer)):atom(UNITDIR/(name+suffix),raw.encode(),0o644)
 good(['systemctl','daemon-reload']);good(['systemctl','enable','--now',name+'.timer'])

def candidate(raw):
 module=types.ModuleType('validated_watchdog_candidate');exec(compile(raw,'watchdog_candidate','exec'),module.__dict__);return module

def apply(base):
 check(os.geteuid()==0,'root_required');os.umask(0o077)
 raw=SOURCE.read_text().replace('/srv/p1-agent',str(base)).encode();new=candidate(raw);data=base/'astrbot/data/plugin_data/affect'
 check(not CURRENT.is_symlink() and CURRENT.stat().st_uid==0 and not CURRENT.stat().st_mode&0o022,'checkpoint_not_protected')
 new.inspect_checkpoint(CURRENT,new.FILES,0)
 old_manifest=read(CURRENT/'fixed-manifest.json');check(sha(LIVE)==old_manifest['watchdog'],'existing_watchdog_drift')
 check(all(p.is_file() and not p.is_symlink() for p in sources(base)),'existing_maintenance_layout_required')
 if sha(LIVE)==hashlib.sha256(raw).hexdigest():return {'changed':False,'bot_restarted':False}
 before_states=timer_states();point=base/'backups'/('recovery-chain-'+time.strftime('%Y%m%d-%H%M%S')+'-'+str(time.time_ns())+'-'+str(os.getpid()))
 point.mkdir(mode=0o700,parents=True);before={}
 with exclusive(data/'maintenance.lock'):
  shutil.copytree(CURRENT,point/'checkpoint');(point/'before').mkdir(mode=0o700)
  for n,p in enumerate(sources(base)):
   s=p.stat();shutil.copy2(p,point/'before'/str(n));before[str(p)]={'slot':str(n),'sha256':sha(p),'uid':s.st_uid,'gid':s.st_gid,'mode':stat.S_IMODE(s.st_mode)}
  info={'schema':1,'root':str(base),'before':before,'checkpoint_before':tree_hashes(CURRENT),'old_fixed_manifest':old_manifest,'timers':before_states,
        'after_source_sha256':hashlib.sha256(raw).hexdigest(),'guard':'p1-repair-upgrade-'+point.name.removeprefix('recovery-chain-'),
        'boot':boot(),'parent_pid':os.getpid(),'parent_start':pid_start(os.getpid()),'deadline_uptime':uptime()+180}
  try:arm_guard(point,info)
  except BaseException:
   cleanup_guard(point,info);raise
 try:
  quiesce()
  with exclusive(data/'maintenance.lock'):
   check(tree_hashes(CURRENT)==info['checkpoint_before'],'checkpoint_changed_during_prepare')
   for p in sources(base):
    row=before[str(p)];atom(p,raw,row['mode'],row['uid'],row['gid'])
   atom(CURRENT/'fixed/watchdog',raw)
   manifest=dict(old_manifest);manifest['watchdog']=hashlib.sha256(raw).hexdigest();write(CURRENT/'fixed-manifest.json',manifest)
   report=new.inspect(new.Context(root=CURRENT,data=data,files=new.FILES))
   check(report.get('ok') is True and not report['planned_files'],'new_watchdog_inspection_failed')
   write(point/'after.json',{'checkpoint':tree_hashes(CURRENT),'sources':{str(p):sha(p) for p in sources(base)}})
  restore_timers(before_states)
  check(timer_states()==before_states,'timer_restoration_verification_failed')
  atom(point/'committed',b'1\n');cleanup_guard(point,info)
  return {'changed':True,'recovery_point':str(point),'bot_restarted':False,'database_modified':False,'checkpoint_verified':True,'temporary_upgrade_guard_removed':True}
 except BaseException:
  restore(point,base);raise

def main():
 p=argparse.ArgumentParser();p.add_argument('--root',default='/srv/p1-agent');p.add_argument('--apply',action='store_true');p.add_argument('--rollback',type=Path);p.add_argument('--recover',type=Path);a=p.parse_args()
 try:
  base=root_path(a.root)
  if not a.apply and not a.rollback and not a.recover:
   print(json.dumps({'dry_run':True,'scope':'watchdog_and_sealed_copy_only','root':str(base),'bot_restart':False,'database_restore':False,'apply_requires_existing_maintenance':True}));return 0
  check(os.geteuid()==0,'root_required')
  if a.recover:
   point,info=validate_point(a.recover,base)
   if not (point/'committed').exists() and boot()==info['boot'] and pid_start(info['parent_pid'])==info['parent_start'] and uptime()<info['deadline_uptime']:return 0
  with exclusive(base/'backups/repair-chain-upgrade.lock'):
   if a.rollback or a.recover:
    restore(a.rollback or a.recover,base,manual=bool(a.rollback));result={'restored':not (Path(a.rollback or a.recover)/'committed').exists() or bool(a.rollback),'bot_restarted':False,'database_restored':False}
   else:result=apply(base)
  print(json.dumps(result));return 0
 except (UpgradeError,OSError,ValueError,subprocess.SubprocessError) as exc:
  print(json.dumps({'ok':False,'error':str(exc) if isinstance(exc,UpgradeError) else type(exc).__name__,'inspect_private_recovery_point':True}));return 1
if __name__=='__main__':raise SystemExit(main())
