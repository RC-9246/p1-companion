"""Install the additive local monitor. Does not restart or edit the chatbot stack."""
import argparse,hashlib,http.client,json,os,shutil,socket,subprocess,sys,time
from pathlib import Path
SOURCE=Path(__file__).resolve().parents[1]/'services/monitor'
DEST=Path('/opt/p1-monitor');BASE=Path('/home/p1admin/p1-agent');UNITS=('p1-resource-collector.service','p1-resource-panel.service')
FILES=('collector.py','server.py','dist/index.html','dist/style.css','dist/app.js')
def run(args,timeout=25):return subprocess.run(args,capture_output=True,text=True,timeout=timeout)
def health():
    c=http.client.HTTPConnection('127.0.0.1',6190,timeout=3)
    try:c.request('GET','/health');r=c.getresponse();return r.status==200 and json.loads(r.read(1024)).get('ready') is True
    except (OSError,ValueError):return False
    finally:c.close()
def rollback(point):
    point=Path(point).resolve();assert point.parent==BASE/'backups' and point.name.startswith('resource-panel-')
    if (point/'rolled_back').exists():return
    saved=json.loads((point/'before.json').read_text());run(['systemctl','stop',*UNITS]);run(['systemctl','disable',*UNITS])
    if DEST.exists():shutil.rmtree(DEST)
    if saved['installed']:shutil.copytree(point/'source-before',DEST)
    for name in UNITS:
        p=Path('/etc/systemd/system')/name;before=point/name
        if before.exists():shutil.copy2(before,p)
        else:p.unlink(missing_ok=True)
    run(['systemctl','daemon-reload'])
    for name,value in saved['units'].items():
        if value['enabled']:run(['systemctl','enable',name])
        else:run(['systemctl','disable',name])
        if value['active']:run(['systemctl','start',name],55)
    (point/'rolled_back').write_text(str(time.time()))
def main():
    p=argparse.ArgumentParser();p.add_argument('--watchdog');p.add_argument('--rollback');a=p.parse_args();assert os.geteuid()==0;os.umask(0o077)
    if a.rollback:rollback(a.rollback);return
    if a.watchdog:
        point=Path(a.watchdog);deadline=json.loads((point/'deadline.json').read_text())['at']
        while time.time()<deadline:
            if (point/'committed').exists() or (point/'rolled_back').exists():return
            time.sleep(2)
        if not (point/'committed').exists():rollback(point)
        return
    assert not DEST.is_symlink()
    if DEST.exists():assert (DEST/'installation.json').is_file(),'unmanaged_target_directory'
    with socket.socket() as s:
        if s.connect_ex(('127.0.0.1',6190))==0:assert run(['systemctl','is-active','--quiet','p1-resource-panel.service']).returncode==0,'port_6190_in_use'
    for name in (*FILES,*UNITS):assert (SOURCE/name).is_file() and not (SOURCE/name).is_symlink()
    point=BASE/'backups'/('resource-panel-'+time.strftime('%Y%m%d-%H%M%S'));point.mkdir(mode=0o700)
    installed=DEST.exists();state={}
    if installed:shutil.copytree(DEST,point/'source-before')
    for name in UNITS:
        state[name]={'active':run(['systemctl','is-active','--quiet',name]).returncode==0,'enabled':run(['systemctl','is-enabled','--quiet',name]).returncode==0}
        src=Path('/etc/systemd/system')/name
        if src.exists():shutil.copy2(src,point/name)
    (point/'before.json').write_text(json.dumps({'installed':installed,'units':state}));(point/'deadline.json').write_text(json.dumps({'at':time.time()+150}))
    with (point/'watchdog.log').open('w') as log:subprocess.Popen([sys.executable,str(__file__),'--watchdog',str(point)],stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,close_fds=True)
    try:
        run(['systemctl','stop',*UNITS]);DEST.mkdir(mode=0o755,exist_ok=True);DEST.chmod(0o755)
        manifest={}
        for name in FILES:
            p=DEST/name;p.parent.mkdir(mode=0o755,parents=True,exist_ok=True);p.parent.chmod(0o755);shutil.copy2(SOURCE/name,p);p.chmod(0o644);manifest[name]=hashlib.sha256(p.read_bytes()).hexdigest()
        (DEST/'installation.json').write_text(json.dumps({'version':1,'files':manifest}));(DEST/'installation.json').chmod(0o644)
        for name in UNITS:
            p=Path('/etc/systemd/system')/name;shutil.copy2(SOURCE/name,p);p.chmod(0o644)
        checked=run(['systemd-analyze','verify',*[str(Path('/etc/systemd/system')/u) for u in UNITS]])
        (point/'unit-verification.txt').write_text(checked.stdout+checked.stderr);assert checked.returncode==0,'unit_verification_failed'
        assert run(['systemctl','daemon-reload']).returncode==0
        assert run(['systemctl','enable',*UNITS]).returncode==0
        assert run(['systemctl','start','p1-resource-collector.service'],55).returncode==0,'collector_start_failed'
        assert run(['systemctl','start','p1-resource-panel.service']).returncode==0,'viewer_start_failed'
        for _ in range(20):
            if health():break
            time.sleep(1)
        else:raise RuntimeError('monitor_health_failed')
        helper=Path('/usr/local/sbin/p1-healthcheck.py')
        stack_checked=helper.is_file() and not helper.is_symlink()
        if stack_checked:assert run(['python3',str(helper)],30).returncode==0,'existing_stack_health_failed'
        (point/'committed').write_text(str(time.time()));report={'installed':True,'host':'127.0.0.1','port':6190,'sample_interval_seconds':5,'history_minutes':30,'chatbot_restarted':False,'existing_stack_healthy':True if stack_checked else None,'existing_stack_checked':stack_checked,'recovery_point':str(point),'production_memory_modified':False}
        (SOURCE.parents[1]/'evidence/resource-panel-install.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
    except BaseException:rollback(point);raise
if __name__=='__main__':main()
