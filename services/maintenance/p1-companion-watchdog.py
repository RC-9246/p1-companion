#!/usr/bin/env python3
"""Independent, bounded recovery of the recovery chain; stdlib only.

Only sealed files and named systemd units are accepted. No model commands,
conversation DB reads, image pulls or account actions occur in this watchdog.
"""
import argparse,configparser,fcntl,hashlib,json,os,re,secrets,stat,subprocess,time
from pathlib import Path
BASE=Path('/srv/p1-agent')
DATA=BASE/'astrbot/data/plugin_data/affect'
ROOT=Path('/var/lib/p1-companion/recovery/current')
FILES={
 'maintain':Path('/usr/local/sbin/p1-companion-maintain.py'),
 'resilience':Path('/usr/local/lib/p1-companion/resilience.py'),
 'watchdog':Path('/usr/local/sbin/p1-companion-watchdog.py'),
 'core_health':Path('/usr/local/sbin/p1-healthcheck.py'),
 'backup_dbs':Path('/usr/local/sbin/p1-backup-dbs'),
 'backup_agency':Path('/usr/local/sbin/p1-companion-backup-agency.py'),
 **{'unit_'+u.replace('.','_'):Path('/etc/systemd/system')/u for u in (
  'p1-companion-maintain.service','p1-companion-maintain.timer',
  'p1-companion-watchdog.service','p1-companion-watchdog.timer')}}
SERVICE='p1-companion-maintain.service'
TIMERS=('p1-companion-maintain.timer','p1-companion-watchdog.timer')
STATUS_CODES={'healthy','paused','busy','checkpoint_rejected','journal_corrupt','clock_guard',
 'repair_succeeded','repair_failed','cooldown','daily_budget_exhausted','pending_recovery_verified',
 'pending_recovery_failed','generation_changed','unit_query_failed','deferred_verification','state_unavailable'}

def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':')).encode()
def digest(raw):return hashlib.sha256(raw).hexdigest()
class Rejected(ValueError):pass

def no_parent_links(path):
 if any(p.is_symlink() for p in Path(path).parents):raise Rejected('parent_symlink')
def owned_bytes(path,uid,limit=2097152):
 path=Path(path);no_parent_links(path)
 s=path.lstat()
 if not stat.S_ISREG(s.st_mode) or s.st_uid!=uid or s.st_mode&0o022:raise Rejected('untrusted_file')
 fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
 with os.fdopen(fd,'rb') as f:raw=f.read(limit+1)
 if len(raw)>limit:raise Rejected('file_limit')
 return raw

def atomic_bytes(path,raw,uid,gid,mode):
 path=Path(path);no_parent_links(path);path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
 temp=path.with_name(path.name+'.'+secrets.token_hex(6)+'.next')
 try:
  with temp.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
  s=temp.stat()
  if (s.st_uid,s.st_gid)!=(uid,gid):os.chown(temp,uid,gid)
  temp.chmod(mode);os.replace(temp,path)
  fd=os.open(path.parent,os.O_RDONLY|getattr(os,'O_DIRECTORY',0))
  try:os.fsync(fd)
  finally:os.close(fd)
 finally:temp.unlink(missing_ok=True)
def atomic_json(path,value,uid,gid):atomic_bytes(path,canonical(value),uid,gid,0o600)

def clock():
 return (time.time(),float(Path('/proc/uptime').read_text().split()[0]),Path('/proc/sys/kernel/random/boot_id').read_text().strip())
def valid_number(v):return type(v) in (int,float) and 0<=v<=2**53

def validate_payload(value):
 if not isinstance(value,dict) or set(value)!={'version','attempts'} or type(value['version']) is not int or value['version']!=1:raise Rejected('journal_shape')
 rows=value['attempts']
 if not isinstance(rows,list) or len(rows)>32:raise Rejected('journal_limit')
 for row in rows:
  if not isinstance(row,dict) or set(row)!={'wall','uptime','boot','outcome','resume','generation','report_before'}:raise Rejected('attempt_shape')
  if not valid_number(row['wall']) or not valid_number(row['uptime']):raise Rejected('attempt_clock')
  if not isinstance(row['boot'],str) or not re.fullmatch('[A-Za-z0-9_-]{1,64}',row['boot']):raise Rejected('attempt_boot')
  if row['outcome'] not in ('pending','complete','failed') or type(row['resume']) is not bool:raise Rejected('attempt_outcome')
  if any(not isinstance(row[k],str) or not re.fullmatch('[a-f0-9]{64}',row[k]) for k in ('generation','report_before')):raise Rejected('attempt_digest')
 return value

def elapsed(row,now):
 wall,uptime,boot=now
 value=uptime-row['uptime'] if boot==row['boot'] else wall-row['wall']
 if not valid_number(value):raise Rejected('clock_guard')
 return value

class Journal:
 def __init__(self,data,uid,gid):
  self.data=Path(data);self.uid=uid;self.gid=gid;self.seq=0;self.degraded=False
  self.paths=[self.data/('.watchdog-journal-'+x+'.json') for x in ('a','b')]
  self.marker=self.data/'.watchdog-journal-initialized'
 def load(self):
  valid=[];existing=False
  for p in self.paths:
   try:
    raw=owned_bytes(p,self.uid,65536);existing=True;v=json.loads(raw)
    if not isinstance(v,dict) or set(v)!={'seq','payload','sha256'} or type(v['seq']) is not int or not 0<=v['seq']<2**53:raise Rejected('journal_envelope')
    if digest(canonical({'seq':v['seq'],'payload':v['payload']}))!=v['sha256']:raise Rejected('journal_checksum')
    validate_payload(v['payload']);valid.append(v)
   except FileNotFoundError:pass
   except (OSError,ValueError,TypeError,OverflowError):existing=True
  if not valid:
   if existing or self.marker.exists() or self.marker.is_symlink():raise Rejected('journal_corrupt')
   return {'version':1,'attempts':[]}
  best=max(valid,key=lambda x:x['seq']);self.seq=best['seq']
  if any(x['seq']==self.seq and x['sha256']!=best['sha256'] for x in valid):raise Rejected('journal_diverged')
  self.degraded=len(valid)!=2 or any(x['seq']!=self.seq for x in valid)
  return best['payload']
 def save(self,payload):
  validate_payload(payload);self.seq+=1
  v={'seq':self.seq,'payload':payload};v['sha256']=digest(canonical(v))
  for p in self.paths:atomic_json(p,v,self.uid,self.gid)
  atomic_bytes(self.marker,b'1\n',self.uid,self.gid,0o600);self.degraded=False

def inspect_checkpoint(root,files,uid):
 root=Path(root);no_parent_links(root)
 s=root.lstat()
 if not stat.S_ISDIR(s.st_mode) or s.st_uid!=uid or s.st_mode&0o022:raise Rejected('checkpoint_owner')
 manifest=json.loads(owned_bytes(root/'fixed-manifest.json',uid,131072))
 metadata=json.loads(owned_bytes(root/'fixed-metadata.json',uid,131072))
 if not isinstance(manifest,dict) or not isinstance(metadata,dict):raise Rejected('checkpoint_shape')
 recipes=[];identity=[]
 for key,target in files.items():
  expected=manifest.get(key);wanted=metadata.get(key)
  if not isinstance(expected,str) or not re.fullmatch('[a-f0-9]{64}',expected):raise Rejected('checkpoint_digest')
  if not isinstance(wanted,dict) or set(wanted)!={'uid','gid','mode'} or any(type(wanted[k]) is not int for k in wanted):raise Rejected('checkpoint_metadata')
  if wanted['uid']!=uid or not 0<=wanted['gid']<2**31 or not 0<wanted['mode']<=0o777 or wanted['mode']&0o022 or not wanted['mode']&0o400:raise Rejected('checkpoint_permissions')
  if key in ('maintain','watchdog','core_health','backup_dbs','backup_agency') and not wanted['mode']&0o100:raise Rejected('checkpoint_executable')
  raw=owned_bytes(root/'fixed'/key,uid)
  if digest(raw)!=expected:raise Rejected('checkpoint_bytes')
  if target.suffix=='.py' or raw.startswith((b'#!/usr/bin/env python',b'#!/usr/bin/python')):
   try:compile(raw,str(target),'exec')
   except (SyntaxError,ValueError):raise Rejected('checkpoint_syntax') from None
  if target.suffix in ('.service','.timer'):
   try:
    unit=configparser.ConfigParser(interpolation=None,strict=False);unit.read_string(raw.decode('utf-8'))
    section='Service' if target.suffix=='.service' else 'Timer'
    if not unit.has_section('Unit') or not unit.has_section(section) or not dict(unit[section]):raise ValueError()
    if section=='Service' and (unit[section].get('type')!='oneshot' or not unit[section].get('execstart')):raise ValueError()
   except (ValueError,configparser.Error):raise Rejected('checkpoint_unit_syntax') from None
  no_parent_links(target)
  recipes.append({'key':key,'target':Path(target),'raw':raw,'metadata':wanted,'digest':expected})
  identity.append([key,expected,wanted])
 return recipes,digest(canonical(identity))

def matches(recipe):
 p=recipe['target'];m=recipe['metadata']
 try:
  s=p.lstat()
  return stat.S_ISREG(s.st_mode) and not p.is_symlink() and (s.st_uid,s.st_gid,stat.S_IMODE(s.st_mode))==(m['uid'],m['gid'],m['mode']) and digest(owned_bytes(p,m['uid']))==recipe['digest']
 except (OSError,ValueError):return False

class Context:
 def __init__(self,root=ROOT,data=DATA,files=None,uid=0,gid=0,runner=None,clock_fn=clock):
  self.root=Path(root);self.data=Path(data);self.files=FILES if files is None else files
  self.uid=uid;self.gid=gid;self.runner=runner or self._run;self.clock=clock_fn
 def _run(self,args,timeout=20):return subprocess.run(args,capture_output=True,text=True,timeout=timeout)
 def paused(self):return (self.data/'maintenance.disabled').exists() or (self.data/'maintenance.disabled').is_symlink()
 def units(self):
  args=['systemctl','show',SERVICE,*TIMERS,'--no-pager','--property=Id,ActiveState,Result,UnitFileState']
  r=self.runner(args,20)
  if r.returncode:raise Rejected('unit_query_failed')
  result={}
  for block in r.stdout.strip().split('\n\n'):
   fields=dict(line.split('=',1) for line in block.splitlines() if '=' in line)
   if fields.get('Id') in (SERVICE,*TIMERS):result[fields['Id']]=fields
  if set(result)!={SERVICE,*TIMERS}:raise Rejected('unit_query_failed')
  return result
 def report(self):
  try:
   raw=owned_bytes(self.data/'maintenance_health.json',self.uid,262144);v=json.loads(raw)
   return (v if isinstance(v,dict) else {}),digest(raw)
  except (OSError,ValueError):return {},digest(b'')
 def verified(self,recipes,before):
  if self.paused() or not all(matches(r) for r in recipes):return False
  units=self.units();data,fingerprint=self.report();now=self.clock()[0];at=data.get('at')
  return bool(all(units[t].get('ActiveState')=='active' and units[t].get('UnitFileState')=='enabled' for t in TIMERS) and
    units[SERVICE].get('Result')=='success' and units[SERVICE].get('ActiveState')=='inactive' and fingerprint!=before and valid_number(at) and 0<=now-at<=900 and
    data.get('disabled') is False and type(data.get('ttl_sweep')) is bool and
    isinstance(data.get('services'),dict) and isinstance(data.get('databases'),dict))
 def publish(self,status,**extra):
  if status not in STATUS_CODES:status='repair_failed'
  report={'schema':1,'at':self.clock()[0],'status':status,**extra}
  atomic_json(self.data/'repair_watchdog_health.json',report,self.uid,self.gid);return report
 def commands(self,changed,units):
  commands=[]
  if any(r['key'].startswith('unit_') for r in changed):commands.append((['systemctl','daemon-reload'],20))
  for t in TIMERS:
   if units[t].get('ActiveState')!='active' or units[t].get('UnitFileState')!='enabled':commands.append((['systemctl','enable','--now',t],20))
  commands.append((['systemctl','reset-failed',SERVICE],20))
  commands.append((['systemctl','start',SERVICE],540))
  return commands

def inspect(ctx):
 try:
  recipes,generation=inspect_checkpoint(ctx.root,ctx.files,ctx.uid);journal=Journal(ctx.data,ctx.uid,ctx.gid);p=journal.load();units=ctx.units();now=ctx.clock()
  active=[r for r in p['attempts'] if elapsed(r,now)<86400]
  changed=[r for r in recipes if not matches(r)]
  report,_=ctx.report();at=report.get('at');stale=not valid_number(at) or not 0<=now[0]-at<=1200
  return {'ok':True,'mode':'inspect','paused':ctx.paused(),'needs_repair':bool(changed or any(units[t].get('ActiveState')!='active' or units[t].get('UnitFileState')!='enabled' for t in TIMERS) or units[SERVICE].get('Result') not in (None,'success') or stale),
          'planned_files':[r['key'] for r in changed],'rolling_24h_attempts':len(active),'pending':any(r['outcome']=='pending' for r in active),'writes':False}
 except (OSError,ValueError,TypeError,OverflowError):return {'ok':False,'mode':'inspect','error':'checkpoint_or_journal_or_units_unavailable','writes':False}

def recover(ctx):
 ctx.data.mkdir(mode=0o700,parents=True,exist_ok=True);no_parent_links(ctx.data)
 s=ctx.data.lstat()
 if not stat.S_ISDIR(s.st_mode) or s.st_uid!=ctx.uid or s.st_mode&0o022:return {'schema':1,'at':ctx.clock()[0],'status':'state_unavailable'}
 run_lock=ctx.data/'.watchdog-run.lock'
 if run_lock.is_symlink():return ctx.publish('state_unavailable')
 with run_lock.open('a') as lock:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:return ctx.publish('busy')
  return _recover(ctx)

def _recover(ctx):
 ctx.data.mkdir(mode=0o700,parents=True,exist_ok=True);lockpath=ctx.data/'maintenance.lock'
 if lockpath.is_symlink():return ctx.publish('state_unavailable')
 with lockpath.open('a') as lock:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:return ctx.publish('busy')
  if ctx.paused():return ctx.publish('paused')
  try:recipes,generation=inspect_checkpoint(ctx.root,ctx.files,ctx.uid)
  except (OSError,ValueError,TypeError,OverflowError):return ctx.publish('checkpoint_rejected')
  journal=Journal(ctx.data,ctx.uid,ctx.gid)
  try:
   payload=journal.load();now=ctx.clock();active=[r for r in payload['attempts'] if elapsed(r,now)<86400]
  except (OSError,ValueError,TypeError,OverflowError) as exc:
   return ctx.publish('clock_guard' if str(exc)=='clock_guard' else 'journal_corrupt')
  payload['attempts']=active
  if journal.degraded:journal.save(payload)
  try:units=ctx.units()
  except (OSError,ValueError,subprocess.SubprocessError):return ctx.publish('unit_query_failed')
  changed=[r for r in recipes if not matches(r)];pending=next((r for r in reversed(active) if r['outcome']=='pending'),None)
  if pending:
   if pending['generation']!=generation:
    pending['outcome']='failed';journal.save(payload);return ctx.publish('generation_changed',pending=False)
   try:completed=ctx.verified(recipes,pending['report_before'])
   except (OSError,ValueError,subprocess.SubprocessError):completed=False
   if completed:
    pending['outcome']='complete';journal.save(payload);return ctx.publish('pending_recovery_verified',pending=False,engine_verified=True,rolling_24h_attempts=len(active))
   if pending['resume']:
    pending['outcome']='failed';journal.save(payload);return ctx.publish('pending_recovery_failed',pending=False,engine_verified=False,rolling_24h_attempts=len(active))
   pending['resume']=True;journal.save(payload);entry=pending
  else:
   report,_=ctx.report();at=report.get('at');stale=not valid_number(at) or not 0<=now[0]-at<=1200
   needs=changed or any(units[t].get('ActiveState')!='active' or units[t].get('UnitFileState')!='enabled' for t in TIMERS) or units[SERVICE].get('Result') not in (None,'success') or stale
   if not needs:return ctx.publish('healthy',pending=False,engine_verified=None,rolling_24h_attempts=len(active))
   if len(active)>=2:return ctx.publish('daily_budget_exhausted',pending=False,rolling_24h_attempts=len(active))
   if active and elapsed(active[-1],now)<1800:return ctx.publish('cooldown',pending=False,rolling_24h_attempts=len(active))
   entry={'wall':now[0],'uptime':now[1],'boot':now[2],'outcome':'pending','resume':False,'generation':generation,'report_before':ctx.report()[1]}
   active.append(entry);journal.save(payload)  # Durable reservation before the first mutation.
  try:
   for recipe in changed:
    if ctx.paused():return ctx.publish('paused',pending=True,rolling_24h_attempts=len(active))
    m=recipe['metadata'];atomic_bytes(recipe['target'],recipe['raw'],m['uid'],m['gid'],m['mode'])
   if not all(matches(r) for r in recipes):raise Rejected('postcheck_failed')
   commands=ctx.commands(changed,units)
   ctx.publish('deferred_verification',pending=True,restored_files=len(changed),rolling_24h_attempts=len(active))
  except (OSError,ValueError):return ctx.publish('repair_failed',pending=True,engine_verified=False,rolling_24h_attempts=len(active))
  # The engine takes maintenance.lock itself. Do not hold it while waiting for
  # systemd to execute the engine, or a successful no-op would masquerade as repair.
  fcntl.flock(lock,fcntl.LOCK_UN)
  try:
   for args,timeout in commands:
    if ctx.paused():return ctx.publish('paused',pending=True,rolling_24h_attempts=len(active))
    result=ctx.runner(args,timeout)
    if result.returncode:raise Rejected('systemd_action_failed')
  except (OSError,ValueError,subprocess.SubprocessError):return ctx.publish('repair_failed',pending=True,engine_verified=False,rolling_24h_attempts=len(active))
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:return ctx.publish('deferred_verification',pending=True)
  try:
   # An authorized upgrade may have changed the checkpoint while systemd ran.
   after,identity=inspect_checkpoint(ctx.root,ctx.files,ctx.uid)
   ok=identity==generation and ctx.verified(after,entry['report_before'])
   entry['outcome']='complete' if ok else 'failed';journal.save(payload)
   return ctx.publish('repair_succeeded' if ok else 'repair_failed',pending=False,engine_verified=ok,restored_files=len(changed),rolling_24h_attempts=len(active))
  except (OSError,ValueError,TypeError,subprocess.SubprocessError):return ctx.publish('repair_failed',pending=True,engine_verified=False,rolling_24h_attempts=len(active))

def main(argv=None):
 p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');args=p.parse_args(argv)
 ctx=Context(root=ROOT,data=DATA,files=FILES)
 if args.check:report=inspect(ctx)
 else:
  try:report=recover(ctx)
  except (OSError,ValueError,TypeError,OverflowError,subprocess.SubprocessError):report={'schema':1,'at':time.time(),'status':'state_unavailable'}
 print(json.dumps(report,ensure_ascii=False))
 return 0 if report.get('ok') is True or report.get('status') in ('healthy','paused','busy','repair_succeeded','pending_recovery_verified','cooldown','daily_budget_exhausted','deferred_verification') else 1
if __name__=='__main__':raise SystemExit(main())
