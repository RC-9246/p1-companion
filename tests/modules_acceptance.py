#!/usr/bin/env python3
"""Opt-in Docker module lifecycle lab; no production mounts or QQ/model calls."""
import argparse, contextlib, importlib.util, json, os, shutil, signal, sqlite3
import subprocess, sys, tempfile, time
from pathlib import Path
from unittest.mock import patch
from core_upgrade_acceptance import LabDocker, PROGRAM, command

R=Path(__file__).resolve().parents[1]
s=importlib.util.spec_from_file_location('modules_lab',R/'services/modules/manager.py')
M=importlib.util.module_from_spec(s);s.loader.exec_module(M)


class LabHost:
    def unit(self,name):return {'installed':False,'enabled':False,'active':False}
    def arm(self):pass
    def set_unit(self,name,enabled,before=None):assert not enabled
    def restore_unit(self,name,before):assert not before['active']


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--run',action='store_true');ap.add_argument('--output',type=Path);a=ap.parse_args()
    if not a.run:print(json.dumps({'dry_run':True,'production_changes':False,'requires':'Linux root, Docker, systemd, local workbench image'}));return
    assert os.geteuid()==0 and Path('/run/systemd/system').is_dir()
    os.umask(0o077);stamp=str(time.time_ns());base=Path(tempfile.mkdtemp(prefix='p1-modules-lab-')).resolve()
    prefix='p1-module-lab-'+stamp+'-';net=prefix+'net';tag='p1-module-fixture:'+stamp;rows=[]
    before=json.loads(command(['docker','inspect','astrbot','snowluma','p1-browser','p1-browser-egress','p1-leisure','p1-leisure-egress','p1-workbench','p1-n8n']))
    snapshot=[(v['Id'],v['State']['StartedAt'],v['RestartCount']) for v in before]
    d=LabDocker(prefix);old_home=M.HOME;sys_original_path=list(sys.path)
    try:
        image=json.loads(command(['docker','inspect','p1-workbench']))[0]['Image']
        source=json.loads(command(['docker','image','inspect',image]))[0]['RepoTags'][0]
        build=base/'build';build.mkdir();(build/'program.py').write_text(PROGRAM)
        (build/'Dockerfile').write_text('FROM '+source+'\nUSER root\nCOPY program.py /fixture.py\nENV ROLE=old\nENTRYPOINT []\nCMD ["python","/fixture.py"]\n')
        command(['docker','build','--network=none','-q','-t',tag,str(build)])
        image=json.loads(command(['docker','image','inspect',tag]))[0]['Id']
        command(['docker','network','create','--internal',net])
        root=base/'agent';M.HOME=base/'control'
        for name in ('astrbot','snowluma',*sorted(M.ALL_SERVICES)):
            data=root/'fixtures'/name;data.mkdir(parents=True);(data/'session.txt').write_text('synthetic-login')
            with sqlite3.connect(data/'facts.db') as c:c.execute('CREATE TABLE facts(value)');c.execute("INSERT INTO facts VALUES ('keep')")
            labels={'com.docker.compose.project':'fixture','com.docker.compose.service':name,
                    'com.docker.compose.project.config_files':str(root/(name if name in ('astrbot','snowluma') else 'optional')/'compose.yaml')}
            spec={'Image':image,'Labels':labels,'HostConfig':{'NetworkMode':net,'Memory':96*1024**2,
                   'RestartPolicy':{'Name':'unless-stopped'},'Binds':[str(data)+':/AstrBot/data']}}
            d.create(name,spec);d.start(name)
        core=root/'astrbot/data/plugin_data/affect';core.mkdir(parents=True);(core/'companion_health.json').write_text('{"module_policy_schema":1}')
        c=M.Controller(root,d,LabHost());c.poll=.2;c.wait_seconds=15
        assert c.apply(['core','learning'])['state']=='ready'
        assert all(not d.inspect(n)['State']['Running'] for n in M.ALL_SERVICES)
        assert all(d.inspect(n)['HostConfig']['RestartPolicy']['Name']=='no' for n in M.ALL_SERVICES)
        rows.append({'case':'six_optional_containers_stopped_without_core_stop','ok':True})
        assert c.apply(['core','learning'],remove=True)['state']=='ready'
        assert all(d.inspect(n) is None for n in M.ALL_SERVICES)
        assert all((root/'fixtures'/n/'session.txt').read_text()=='synthetic-login' for n in M.ALL_SERVICES)
        rows.append({'case':'remove_stopped_services_preserves_all_bind_data','ok':True})
        assert c.apply(['core','public_web','bilibili','workbench','workflows','mcp'])['state']=='ready'
        assert all(d.inspect(n)['State']['Running'] and d.inspect(n)['Image']==image for n in M.ALL_SERVICES)
        rows.append({'case':'recreate_from_saved_image_settings_and_existing_data','ok':True})
        sys.path.insert(0,str(R/'services/maintenance'))
        spec=importlib.util.spec_from_file_location('maintenance_modules_lab',R/'services/maintenance/p1-companion-maintain.py')
        maint=importlib.util.module_from_spec(spec);spec.loader.exec_module(maint)
        assert c.apply(['core'])['state']=='ready'
        off,valid=maint.module_disabled_services(root,M.HOME)
        assert valid and off==M.ALL_SERVICES
        rows.append({'case':'maintenance_recognizes_intentionally_disabled_services','ok':True})
        # Re-enable before testing a partial failure while disabling.
        full=M.registry()[0]['profiles']['full'];assert c.apply(full)['state']=='ready'
        original=d.stop
        def fail_once(name):
            original(name)
            if name=='p1-workbench':d.stop=original;raise M.ModuleError('lab_injected_failure')
        d.stop=fail_once
        assert c.apply(['core'])['state']=='rolled_back';d.stop=original
        assert all(d.inspect(n)['State']['Running'] for n in M.ALL_SERVICES)
        rows.append({'case':'partial_failure_restores_original_selection_and_services','ok':True})
        def kill_once(name):
            original(name);os.kill(os.getpid(),signal.SIGKILL)
        d.stop=kill_once
        pid=os.fork()
        if pid==0:c.apply(['core']);os._exit(22)
        _,status=os.waitpid(pid,0);assert os.WIFSIGNALED(status) and os.WTERMSIG(status)==signal.SIGKILL
        d.stop=original
        assert c.recover()['state']=='rolled_back'
        assert all(d.inspect(n)['State']['Running'] for n in M.ALL_SERVICES)
        rows.append({'case':'sigkill_during_module_change_recovers_previous_composition','ok':True})
        for name in M.ALL_SERVICES:
            with sqlite3.connect(root/'fixtures'/name/'facts.db') as db:assert db.execute('SELECT value FROM facts').fetchone()[0]=='keep'
        rows.append({'case':'all_synthetic_database_and_login_fixtures_retained','ok':True})
        native_root=base/'native-idle';native_root.mkdir();native_home=old_home/M.hashlib.sha256(str(native_root).encode()).hexdigest()[:16];native_home.mkdir(mode=0o700,parents=True)
        h=M.Host(native_root,native_home);unit='p1-modules-'+native_home.name
        try:
            h.arm();command(['systemctl','start',unit+'.service'])
            assert command(['systemctl','show','-p','Result','--value',unit+'.service']).strip()=='success'
            rows.append({'case':'native_module_recovery_timer_idle_entrypoint','ok':True})
        finally:
            subprocess.run(['systemctl','disable','--now',unit+'.timer'],capture_output=True)
            subprocess.run(['systemctl','stop',unit+'.service'],capture_output=True)
            for suffix in ('.service','.timer'):(Path('/etc/systemd/system')/(unit+suffix)).unlink(missing_ok=True)
            subprocess.run(['systemctl','daemon-reload'],capture_output=True);shutil.rmtree(native_home)
    finally:
        M.HOME=old_home;sys.path[:]=sys_original_path
        for name in command(['docker','ps','-aq','--filter','name='+prefix]).split():subprocess.run(['docker','rm','-f',name],capture_output=True)
        subprocess.run(['docker','network','rm',net],capture_output=True);subprocess.run(['docker','image','rm',tag],capture_output=True)
        after=json.loads(command(['docker','inspect',*[v['Name'].lstrip('/') for v in before]]))
        unchanged=snapshot==[(v['Id'],v['State']['StartedAt'],v['RestartCount']) for v in after]
        result={'date':'2026-10-28','passed':len(rows),'tests':rows,'production_eight_containers_unchanged':unchanged,
                'real_docker':bool(rows),'real_sigkill':any('sigkill' in x['case'] for x in rows),
                'real_account_or_model_calls':False,'whole_host_reboot_tested':False}
        if a.output:a.output.write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result));shutil.rmtree(base);assert unchanged


if __name__=='__main__':main()
