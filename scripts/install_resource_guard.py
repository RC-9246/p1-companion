"""Install bounded memory protection with a private rollback point and watchdog."""
import argparse,contextlib,fcntl,hashlib,importlib.util,json,os,re,select,shutil,signal,subprocess,sys,time
from pathlib import Path
SOURCE=Path(__file__).resolve().parents[1]
STATE=Path('/var/lib/p1-companion-resource');BIN=Path('/usr/local/sbin/p1-resource-guard.py')
UNITS=('p1-resource-guard.service','p1-resource-guard.timer')
OLD={'agency':'1da037a79ebf44ec235b8e778a57329f4bfbdae7af13ffabbfa9ac42416e23e3','leisure':'3aa902bf2c0c30c972733459db3e22592511c5e69e47239a3675f587292003b0'}
def digest(raw):return hashlib.sha256(raw).hexdigest()
def run(args,timeout=30):return subprocess.run(args,capture_output=True,text=True,timeout=timeout)
def need(value,code):
    if not value:raise RuntimeError(code)
def atomic(path,v):
    p=Path(path);tmp=p.with_name(p.name+'.guard-next')
    need(not p.is_symlink() and not tmp.is_symlink(),'unsafe_path')
    with tmp.open('w') as f:json.dump(v,f);f.flush();os.fsync(f.fileno())
    tmp.chmod(0o600);os.replace(tmp,p)
def load(path):return json.loads(Path(path).read_text())
def source_guard():
    p=Path(__file__).with_name('guard.py')
    if not p.exists():p=SOURCE/'services/resource_guard/guard.py'
    spec=importlib.util.spec_from_file_location('resource_guard',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def validate_root(root):
    need(root.is_absolute() and len(root.parts)>=3 and root==root.resolve() and re.fullmatch('/[A-Za-z0-9_./-]+',str(root)) and not any(p.is_symlink() for p in (root,*root.parents)),'invalid_root')
    need((root/'astrbot/data/plugin_data/affect/leisure_state').is_dir(),'companion_required')
def locations(root):
    data=root/'astrbot/data';stage=data/'companion_v020_lab';checkpoint=Path('/var/lib/p1-companion/recovery/current')
    return {'bin':BIN,'config':STATE/'config.json',**{'unit_'+n:Path('/etc/systemd/system')/n for n in UNITS},
      'agency':data/'plugins/astrbot_plugin_affect/agency_runtime.py','leisure':data/'companion_services/leisure/server.py',
      'stage_agency':stage/'release/astrbot_plugin_affect/agency_runtime.py','stage_leisure':stage/'services/leisure/server.py',
      'stage_manifest':stage/'evidence/release-manifest.json','checkpoint_agency':checkpoint/'plugins/astrbot_plugin_affect/agency_runtime.py',
      'checkpoint_leisure':checkpoint/'fixed/leisure_server','checkpoint_manifest':checkpoint/'manifest.json','checkpoint_fixed_manifest':checkpoint/'fixed-manifest.json'}
def unit_state(name):return {'active':run(['systemctl','is-active','--quiet',name]).returncode==0,'enabled':run(['systemctl','is-enabled','--quiet',name]).returncode==0}
def restore_limit(row):
    check=run(['docker','inspect',row['id']]);actual=json.loads(check.stdout)[0] if check.returncode==0 else {}
    if actual.get('Image')!=row['image']:return False
    h=row['limits'];args=['docker','update','--memory',str(h['Memory']),'--memory-reservation',str(h.get('MemoryReservation',0)),'--memory-swap',str(h.get('MemorySwap') or -1),'--pids-limit',str(h.get('PidsLimit') or -1),row['id']]
    return run(args,30).returncode==0
def owner_identity(pid):
    p=Path('/proc',str(pid));fields=(p/'stat').read_text().rsplit(')',1)[1].split()
    return {'pid':pid,'start':fields[19],'command_sha256':digest((p/'cmdline').read_bytes()),'boot':Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
def stop_owner(point):
    record=load(point/'owner.json');pid=record['pid'];need(type(pid) is int and pid>1 and pid!=os.getpid(),'invalid_owner')
    try:fd=os.pidfd_open(pid)
    except ProcessLookupError:return
    try:
        if owner_identity(pid)!=record:return
        signal.pidfd_send_signal(fd,signal.SIGTERM)
        if not select.select([fd],[],[],8)[0]:signal.pidfd_send_signal(fd,signal.SIGKILL)
        need(bool(select.select([fd],[],[],5)[0]),'installer_did_not_stop')
    finally:os.close(fd)
def rollback(point):
    point=Path(point);saved=load(point/'before.json');root=Path(saved['root']);validate_root(root)
    need(point.parent==root/'backups' and re.fullmatch('resource-guard-[0-9-]+',point.name) and point.stat().st_uid==0 and not point.is_symlink(),'invalid_recovery_point')
    if (point/'rolled_back').exists():return
    if (point/'committed').exists():
        after=load(point/'after-files.json')
        need(all(Path(p).is_file() and digest(Path(p).read_bytes())==d for p,d in after.items()),'post_install_changes_require_manual_restore')
    allowed=locations(root);need(all(allowed.get(k)==Path(v['path']) for k,v in saved['files'].items()),'invalid_restore_target')
    for name in saved['units']:run(['systemctl','stop',name])
    run(['systemctl','disable','--now','p1-resource-guard.timer']);run(['systemctl','stop','p1-resource-guard.service'])
    with contextlib.ExitStack() as stack:
        for p in (root/'astrbot/data/plugin_data/affect/.watchdog-run.lock',root/'astrbot/data/plugin_data/affect/maintenance.lock',STATE/'guard.lock'):
            f=stack.enter_context(p.open('a'));fcntl.flock(f,fcntl.LOCK_EX)
        for key,row in saved['files'].items():
            target=Path(row['path']);need(not target.is_symlink() and not any(p.is_symlink() for p in target.parents),'unsafe_restore_path')
            if row['exists']:
                source=point/'files'/key;need(digest(source.read_bytes())==row['sha256'],'restore_hash_mismatch');shutil.copy2(source,target);os.chown(target,row['uid'],row['gid']);target.chmod(row['mode'])
            else:target.unlink(missing_ok=True)
        for name,row in saved['containers'].items():
            if name in ('astrbot','snowluma'):need(restore_limit(row),'limit_restore_failed')
        for name in ('resource_guard_health.json','leisure_state/resource-lease.json'):
            p=root/'astrbot/data/plugin_data/affect'/name
            if p.is_file() and not p.is_symlink():p.unlink()
        run(['systemctl','daemon-reload'])
        for name,changed in saved['code_changes'].items():
            if changed:need(run(['docker','restart','--time','10',name],50).returncode==0,'rollback_restart_failed')
        for name,v in saved['units'].items():
            run(['systemctl','enable' if v['enabled'] else 'disable',name])
            if v['active']:run(['systemctl','start',name])
    (point/'rolled_back').write_text(str(time.time()))
def apply(root,core_limits=True):
    validate_root(root);G=source_guard();paths=locations(root);data=root/'astrbot/data';stage=data/'companion_v020_lab'
    if STATE.exists():
        need(not STATE.is_symlink() and STATE.stat().st_uid==0 and not STATE.stat().st_mode&0o077,'unmanaged_guard_state')
        if (STATE/'config.json').exists():need(G.config()['root']==str(root),'different_guard_root')
    sources={'agency':SOURCE/'release/astrbot_plugin_affect/agency_runtime.py','leisure':SOURCE/'services/leisure/server.py'}
    changed={}
    for key,p in sources.items():
        raw=p.read_bytes();compile(raw,str(p),'exec');old=paths[key].read_bytes();need(digest(old) in (OLD[key],digest(raw)),'modified_'+key+'_requires_manual_review');changed[key]=old!=raw
        for prefix in ('stage_','checkpoint_'):
            target=paths[prefix+key]
            if target.exists():need(digest(target.read_bytes()) in (OLD[key],digest(raw)),'snapshot_mismatch')
    rows=G.containers();need(set(rows)==set(G.NAMES),'required_containers_unavailable')
    bindings={}
    for name,row in rows.items():
        labels=row.get('Config',{}).get('Labels') or {};bindings[name]={'image':row['Image'],'project':labels.get('com.docker.compose.project',''),'service':labels.get('com.docker.compose.service','')};need(G.bound(row,bindings[name]),'unmanaged_container')
    need(G.host()['MemAvailable']>650*G.MIB,'installation_memory_low')
    if changed['leisure']:
        p=run(['docker','exec',rows['p1-leisure']['Id'],'python','-c',"import urllib.request,json; v=json.load(urllib.request.urlopen('http://127.0.0.1:8766/health',timeout=3)); print(json.dumps({'idle':not v.get('browser_running',True)}))"])
        need(p.returncode==0 and load_json(p.stdout).get('idle') is True,'leisure_busy_retry_later')
    STATE.mkdir(mode=0o700,exist_ok=True);point=root/'backups'/('resource-guard-'+str(time.time_ns()));point.mkdir(mode=0o700);(point/'files').mkdir(mode=0o700)
    timers=(*UNITS[1:],'p1-companion-maintain.timer','p1-companion-watchdog.timer')
    saved={'root':str(root),'files':{},'units':{name:unit_state(name) for name in timers},'containers':{},'code_changes':{'astrbot':changed['agency'],'p1-leisure':changed['leisure']}}
    for name,row in rows.items():saved['containers'][name]={'id':row['Id'],'image':row['Image'],'limits':{k:row['HostConfig'].get(k) for k in ('Memory','MemorySwap','MemoryReservation','PidsLimit')}}
    for key,target in paths.items():
        need(not target.is_symlink() and not any(p.is_symlink() for p in target.parents),'unsafe_install_path')
        info={'path':str(target),'exists':target.exists()}
        if target.exists():
            s=target.stat();info.update(uid=s.st_uid,gid=s.st_gid,mode=s.st_mode&0o777,sha256=digest(target.read_bytes()));shutil.copy2(target,point/'files'/key)
        saved['files'][key]=info
    atomic(point/'before.json',saved);atomic(point/'owner.json',owner_identity(os.getpid()));atomic(point/'deadline.json',{'at':time.time()+240});shutil.copy2(__file__,point/'installer.py');shutil.copy2(SOURCE/'services/resource_guard/guard.py',point/'guard.py')
    with (point/'watchdog.log').open('w') as out:subprocess.Popen([sys.executable,str(point/'installer.py'),'--watchdog',str(point)],stdin=subprocess.DEVNULL,stdout=out,stderr=out,start_new_session=True,close_fds=True)
    try:
        for name in timers:run(['systemctl','stop',name])
        # Lock both existing recovery paths; don't terminate an in-progress repair.
        with contextlib.ExitStack() as stack:
            for p in (data/'plugin_data/affect/.watchdog-run.lock',data/'plugin_data/affect/maintenance.lock',STATE/'guard.lock'):
                f=stack.enter_context(p.open('a'));fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
            for key,source in sources.items():
                for slot in (key,'stage_'+key,'checkpoint_'+key):
                    target=paths[slot]
                    if target.exists():
                        meta=target.stat();target.write_bytes(source.read_bytes());os.chown(target,meta.st_uid,meta.st_gid);target.chmod(meta.st_mode&0o777)
            for key in ('stage_manifest','checkpoint_manifest'):
                if paths[key].exists():
                    value=load(paths[key]);value['astrbot_plugin_affect/agency_runtime.py']=digest(sources['agency'].read_bytes());atomic(paths[key],value)
            if paths['checkpoint_fixed_manifest'].exists():
                value=load(paths['checkpoint_fixed_manifest']);value['leisure_server']=digest(sources['leisure'].read_bytes());atomic(paths['checkpoint_fixed_manifest'],value)
            BIN.write_bytes((SOURCE/'services/resource_guard/guard.py').read_bytes());BIN.chmod(0o700)
            atomic(STATE/'config.json',{'schema':1,'root':str(root),'bindings':bindings,'core_limits':core_limits})
            for n in UNITS:
                target=Path('/etc/systemd/system')/n;target.write_text((SOURCE/'services/resource_guard'/n).read_text().replace('/srv/p1-agent',str(root)));target.chmod(0o644)
            need(run(['systemctl','daemon-reload']).returncode==0,'systemd_reload_failed')
            for name,yes in saved['code_changes'].items():
                if yes:need(run(['docker','restart','--time','10',saved['containers'][name]['id']],50).returncode==0,'restart_failed')
        need(run(['systemctl','start','p1-resource-guard.service'],45).returncode==0,'guard_start_failed')
        report=G.private_json(STATE/'health.json');need(time.time()-report['at']<60 and not report['unbound_services'],'guard_health_failed')
        need(all(v['state']!='limit_failed' for v in report['core_limits'].values()),'limit_failed')
        for _ in range(25):
            current=G.containers()
            if all(x.get('State',{}).get('Running') and x.get('State',{}).get('Health',{}).get('Status','healthy')=='healthy' for x in current.values()) and len(current)==4:break
            time.sleep(2)
        else:raise RuntimeError('post_install_health_failed')
        if changed['agency']:
            for _ in range(20):
                ready=load(data/'plugin_data/affect/companion_health.json')
                if time.time()-ready.get('at',0)<60 and all(ready.get(k) for k in ('agency_ready','learning_ready','group_affect_ready','group_memory_ready','qq_plain_ready')):break
                time.sleep(2)
            else:raise RuntimeError('plugins_not_ready')
        need(run(['systemctl','enable','--now','p1-resource-guard.timer']).returncode==0,'timer_start_failed')
        for name,v in saved['units'].items():
            if name!='p1-resource-guard.timer' and v['active']:run(['systemctl','start',name])
        result={'installed':True,'source_and_limits_have_private_rollback':True,'core_limits_requested':core_limits,'databases_modified':False,'chatbot_restarted':changed['agency'],'leisure_restarted':changed['leisure'],'recovery_point':str(point)}
        atomic(point/'after-files.json',{str(p):digest(p.read_bytes()) for p in paths.values() if p.is_file()});atomic(point/'after.json',result);atomic(root/'backups/resource-guard-latest.json',{'point':str(point)});(point/'committed').write_text(str(time.time()));return result
    except BaseException:
        rollback(point);raise
def load_json(raw):return json.loads(raw)
def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=Path('/srv/p1-agent'));p.add_argument('--apply',action='store_true');p.add_argument('--no-core-limits',action='store_true');p.add_argument('--rollback',type=Path);p.add_argument('--watchdog',type=Path);a=p.parse_args()
    if a.watchdog:
        need(os.geteuid()==0,'sudo_required');point=a.watchdog;end=load(point/'deadline.json')['at']
        while time.time()<end:
            if (point/'committed').exists() or (point/'rolled_back').exists():return
            time.sleep(2)
        stop_owner(point);rollback(point);return
    if a.rollback:need(os.geteuid()==0,'sudo_required');rollback(a.rollback);return
    if not a.apply:print(json.dumps({'dry_run':True,'memory_pressure_guard':True,'known_orphan_browser_only':True,'cache_flush':False,'deletes_user_data':False}));return
    need(os.geteuid()==0,'sudo_required');os.umask(0o077);print(json.dumps(apply(a.root,not a.no_core_limits)))
if __name__=='__main__':main()
