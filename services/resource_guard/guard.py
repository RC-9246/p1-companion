#!/usr/bin/env python3
"""Bounded host memory guardian. No models, accounts, arbitrary kill or cache flush."""
import argparse,fcntl,json,math,os,re,secrets,signal,stat,subprocess,time
from pathlib import Path
MIB=1048576
STATE=Path('/var/lib/p1-companion-resource')
NAMES=('astrbot','snowluma','p1-browser','p1-leisure')
LIMITS={'astrbot':(1536*MIB,768*MIB,2048*MIB,256),'snowluma':(1792*MIB,1024*MIB,2304*MIB,1536)}
EXE='/usr/lib/chromium/chromium'

def atomic(path,value,mode=0o600):
    path=Path(path)
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):raise ValueError('unsafe_state_path')
    tmp=path.with_name('.guard-'+secrets.token_hex(6))
    try:
        with tmp.open('x') as f:json.dump(value,f,separators=(',',':'),allow_nan=False);f.flush();os.fsync(f.fileno());os.fchmod(f.fileno(),mode)
        os.replace(tmp,path)
    finally:tmp.unlink(missing_ok=True)

def private_json(path,limit=65536):
    path=Path(path);s=path.lstat()
    if not stat.S_ISREG(s.st_mode) or s.st_uid!=0 or s.st_mode&0o022 or path.is_symlink() or any(p.is_symlink() for p in path.parents):raise ValueError('untrusted_guard_state')
    with path.open('rb') as f:raw=f.read(limit+1)
    if len(raw)>limit:raise ValueError('guard_state_limit')
    return json.loads(raw)

def config(path=STATE/'config.json'):
    v=private_json(path)
    if set(v)!={'schema','root','bindings','core_limits'} or v['schema']!=1 or type(v['core_limits']) is not bool:raise ValueError('invalid_guard_config')
    root=Path(v['root'])
    if not re.fullmatch('/[A-Za-z0-9_./-]+',str(root)) or len(root.parts)<3 or root!=root.resolve() or any(p.is_symlink() for p in (root,*root.parents)):raise ValueError('invalid_guard_root')
    if set(v['bindings'])!=set(NAMES):raise ValueError('invalid_guard_bindings')
    for row in v['bindings'].values():
        if set(row)!={'image','project','service'} or not re.fullmatch('sha256:[a-f0-9]{64}',row['image']) or any(not re.fullmatch('[A-Za-z0-9_.-]{1,80}',row[k]) for k in ('project','service')):raise ValueError('invalid_guard_bindings')
    return v

def run(argv,timeout=8):return subprocess.run(argv,capture_output=True,text=True,timeout=timeout)
def containers():
    p=run(['docker','inspect',*NAMES]);rows=json.loads(p.stdout)
    return {x['Name'].lstrip('/'):x for x in rows if x.get('Name','').lstrip('/') in NAMES}
def bound(row,binding):
    labels=row.get('Config',{}).get('Labels') or {}
    return bool(re.fullmatch('[a-f0-9]{64}',row.get('Id','')) and row.get('Image')==binding['image'] and labels.get('com.docker.compose.project')==binding['project'] and labels.get('com.docker.compose.service')==binding['service'] and row.get('State',{}).get('Running'))
def host(proc=Path('/proc')):
    info={k:int(v.split()[0])*1024 for k,v in (line.split(':',1) for line in (proc/'meminfo').read_text().splitlines()) if k in ('MemTotal','MemAvailable','SwapTotal','SwapFree')}
    if not 0<=info['MemAvailable']<=info['MemTotal']:raise ValueError('invalid_memory_sample')
    info.update(some=0.0,full=0.0)
    try:
        for line in (proc/'pressure/memory').read_text().splitlines():
            parts=line.split();value=float(next(x.split('=')[1] for x in parts if x.startswith('avg10=')))
            if parts[0] in ('some','full') and 0<=value<=100:info[parts[0]]=value
    except (OSError,ValueError,StopIteration):pass
    return info
def classify(sample,previous,boot,uptime):
    total=sample['MemTotal'];free=sample['MemAvailable'];same=previous.get('boot')==boot and 0<=uptime-previous.get('uptime',-999)<=120
    old=previous.get('mode','normal') if same else 'normal'
    pressure=free<max(768*MIB,total*.18) or (sample['some']>=10 and free<max(1024*MIB,total*.25))
    critical=free<max(384*MIB,total*.09) or (sample['full']>=20 and free<max(768*MIB,total*.18))
    recovered=free>=max(1024*MIB,total*.25) and sample['some']<2 and sample['full']<1
    bad=min(2,previous.get('bad',0)+1 if same else 1) if critical else 0
    good=min(3,previous.get('good',0)+1 if same else 1) if recovered else 0
    mode='critical' if critical and (bad>=2 or free<128*MIB) else 'pressure' if pressure or old!='normal' and good<3 else 'normal'
    return {'mode':mode,'bad':bad,'good':good,'boot':boot,'uptime':uptime}
def cgroup(row,proc=Path('/proc'),sysroot=Path('/sys/fs/cgroup')):
    pid=row['State']['Pid'];lines=(proc/str(pid)/'cgroup').read_text().splitlines()
    value=next((x[3:] for x in lines if x.startswith('0::')),None)
    if value is None:return None # cgroup v1: keep host protection, don't guess paths
    if not value.startswith('/') or '..' in Path(value).parts:raise ValueError('invalid_cgroup')
    p=sysroot/value.lstrip('/')
    if not p.resolve().is_relative_to(sysroot.resolve()) or not p.is_dir():raise ValueError('invalid_cgroup')
    return p
def usage(row):
    cg=cgroup(row)
    return int((cg/'memory.current').read_text()) if cg is not None else None
def limit_core(row,name):
    wanted=LIMITS[name];h=row['HostConfig'];current=h.get('Memory',0)
    if current:return {'state':'existing_limit_preserved','limit_bytes':current}
    used=usage(row)
    if used is None or used>wanted[0]*.7:return {'state':'insufficient_headroom_no_change'}
    # Docker treats reservation=0 as "no update". Preserve existing reservation
    # so rollback can restore the exact former policy instead of inventing one.
    p=run(['docker','update','--memory',str(wanted[0]),'--memory-swap',str(wanted[2]),'--pids-limit',str(wanted[3]),row['Id']],15)
    if p.returncode==0:
        check=run(['docker','inspect',row['Id']]);actual=json.loads(check.stdout)[0]['HostConfig']
        ok=check.returncode==0 and all(actual.get(k)==v for k,v in zip(('Memory','MemorySwap','PidsLimit'),(wanted[0],wanted[2],wanted[3]))) and actual.get('MemoryReservation',0)==h.get('MemoryReservation',0)
    else:ok=False
    return {'state':'limit_applied' if ok else 'limit_failed','limit_bytes':wanted[0] if ok else None}

def process(pid,proc=Path('/proc')):
    p=proc/str(pid);s=(p/'stat').read_text().rsplit(')',1)[1].split()
    return {'pid':int(pid),'ppid':int(s[1]),'start':s[19],'uid':p.stat().st_uid,'exe':str((p/'exe').resolve()),'cmd':(p/'cmdline').read_bytes(),'cgroup':(p/'cgroup').read_text(),'namespace':str((p/'ns/pid').readlink())}
def orphan_candidate(v,init):
    # A browser root adopted by the container's tini has lost its Playwright
    # parent. Renderers, zombies, QQ, host Chromium and active owned roots fail.
    return bool(v['ppid']==init['pid'] and v['pid']!=init['pid'] and v['uid']==1001 and v['exe']==EXE and b'--type=' not in v['cmd'] and b'--headless' in v['cmd'] and v['cgroup']==init['cgroup'] and v['namespace']==init['namespace'])
def terminate_orphan(v,init,proc=Path('/proc')):
    if not hasattr(os,'pidfd_open') or not hasattr(signal,'pidfd_send_signal'):return False
    fd=os.pidfd_open(v['pid'])
    try:
        again=process(v['pid'],proc)
        if again!=v or not orphan_candidate(again,process(init['pid'],proc)):return False
        signal.pidfd_send_signal(fd,signal.SIGTERM);return True
    finally:os.close(fd)
def sweep(rows,bindings,journal,uptime,boot):
    old=journal.get('orphans',{}) if journal.get('boot')==boot else {};seen={};actions=[]
    attempts=[v for v in journal.get('attempts',[]) if type(v) in (int,float) and journal.get('boot')==boot and 0<=uptime-v<3600]
    # At most two SIGTERMs per pass and four/hour. Never SIGKILL or pid-name kill.
    for name in ('p1-browser','p1-leisure'):
        row=rows.get(name)
        if not row or not bound(row,bindings[name]):continue
        try:init=process(row['State']['Pid'])
        except (OSError,ValueError,KeyError,IndexError):continue
        for p in Path('/proc').iterdir():
            if not p.name.isdigit():continue
            try:
                fields=(p/'stat').read_text().rsplit(')',1)[1].split()
                if fields[0]=='Z' or int(fields[1])!=init['pid']:continue
                v=process(int(p.name))
                if not orphan_candidate(v,init):continue
                key=name+':'+str(v['pid'])+':'+v['start'];first=old.get(key,uptime)
                if not 0<=uptime-first<=86400:first=uptime
                seen[key]=first
                if uptime-first>=90 and len(actions)<2 and len(attempts)<4:
                    # Reserve the attempt durably before signalling; a crash
                    # must not reset the bounded hourly action count.
                    attempts.append(uptime);journal.update(boot=boot,attempts=attempts,orphans=seen);atomic(STATE/'journal.json',journal)
                    if terminate_orphan(v,init):actions.append({'action':'orphan_browser_sigterm','service':name});seen.pop(key,None)
            except (OSError,ValueError,KeyError,IndexError):continue
    return seen,attempts,actions

def lease(root,mode,uptime,boot):
    p=root/'astrbot/data/plugin_data/affect/leisure_state'
    if not p.is_dir() or p.is_symlink() or any(q.is_symlink() for q in p.parents):raise ValueError('leisure_state_unavailable')
    target=p/'resource-lease.json';atomic(target,{'version':1,'boot':boot,'until':uptime+90 if mode!='normal' else 0,'mode':mode},0o644)

def validate_journal(j,boot,uptime):
    if not isinstance(j,dict) or set(j)-{'boot','uptime','mode','bad','good','orphans','attempts'}:raise ValueError('invalid_guard_journal')
    seen=j.get('orphans',{});attempts=j.get('attempts',[])
    if not isinstance(seen,dict) or len(seen)>128 or not isinstance(attempts,list) or len(attempts)>16:raise ValueError('invalid_guard_journal')
    if any(type(v) not in (int,float) or not math.isfinite(v) or v<0 for v in (*seen.values(),*attempts,j.get('uptime',0))):raise ValueError('invalid_guard_journal')
    if any(type(j.get(k,0)) is not int or not 0<=j.get(k,0)<1000000 for k in ('bad','good')):raise ValueError('invalid_guard_journal')
    if j.get('mode','normal') not in ('normal','pressure','critical'):raise ValueError('invalid_guard_journal')
    if j.get('boot')==boot and (uptime<j.get('uptime',0) or any(v>uptime for v in attempts)):raise ValueError('guard_clock_guard')
    return j

def once(cfg):
    root=Path(cfg['root']);data=root/'astrbot/data/plugin_data/affect';now=time.time();uptime=time.monotonic();boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    try:journal=private_json(STATE/'journal.json')
    except FileNotFoundError:journal={}
    # Invalid state stops actions; it is not reset to bypass cooldowns.
    validate_journal(journal,boot,uptime)
    sample=host();decision=classify(sample,journal,boot,uptime);paused=(STATE/'paused').exists();mode='paused' if paused else decision['mode'];actions=[];limits={};unbound=[]
    lease(root,'normal' if paused else mode,uptime,boot)
    try:rows=containers()
    except (OSError,ValueError,subprocess.SubprocessError):rows={}
    for name in NAMES:
        if name not in rows or not bound(rows[name],cfg['bindings'][name]):unbound.append(name)
    if not paused:
        for name in LIMITS:
            if name not in unbound and cfg['core_limits']:limits[name]=limit_core(rows[name],name)
        seen,attempts,actions=sweep(rows,cfg['bindings'],journal,uptime,boot)
        journal.update(orphans=seen,attempts=attempts,**decision)
    atomic(STATE/'journal.json',journal)
    report={'schema':1,'at':now,'uptime':uptime,'mode':mode,'pause_optional':not paused and mode!='normal','lease_seconds':90,'memory_available_bytes':sample['MemAvailable'],'memory_total_bytes':sample['MemTotal'],'pressure_some':sample['some'],'pressure_full':sample['full'],'actions':actions,'core_limits':limits,'unbound_services':unbound,'orphan_candidates':len(journal.get('orphans',{})),'hourly_signal_attempts':len(journal.get('attempts',[])),'kills_unknown_processes':False,'drops_kernel_cache':False}
    try:
        v=json.loads((data/'leisure_state/resource-status.json').read_text())
        if 0<=now-v.get('at',0)<120 and v.get('state') in ('login_in_progress','active_video_preserved','busy','already_idle','idle_browser_closed'):
            report['leisure_cleanup']={'state':v['state'],'closed':v.get('closed') is True}
    except (OSError,ValueError,TypeError):pass
    atomic(STATE/'health.json',report);atomic(data/'resource_guard_health.json',report,0o644);return report

def main():
    p=argparse.ArgumentParser();p.add_argument('--status',action='store_true');p.add_argument('--check',action='store_true');p.add_argument('--pause',action='store_true');p.add_argument('--resume',action='store_true');a=p.parse_args()
    if os.geteuid()!=0:raise SystemExit('Run on the target Linux host with sudo')
    os.umask(0o077);cfg=config()
    if a.status:print(json.dumps(private_json(STATE/'health.json')));return
    if a.check:print(json.dumps({'config_valid':True,'writes':False,'known_containers':list(cfg['bindings'])}));return
    with (STATE/'guard.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        if a.pause:(STATE/'paused').touch(mode=0o600)
        if a.resume:(STATE/'paused').unlink(missing_ok=True)
        print(json.dumps(once(cfg)))
if __name__=='__main__':main()
