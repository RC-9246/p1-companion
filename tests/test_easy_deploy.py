"""Installer safety regressions: temporary files and fake Docker, no real accounts."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

R = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('easy_installer', R/'deploy/install.py')
M = importlib.util.module_from_spec(spec); spec.loader.exec_module(M)

class InputTests(unittest.TestCase):
    def test_qq_ids_reject_shell_syntax_and_bot_names(self):
        for v in ('1', '00001', '12345;id', '12345\n', '-10001', 'a'*10):
            with self.assertRaises(M.DeployError): M.identity(v)
        self.assertEqual(M.identity('123456789'), '123456789')
    def test_root_rejects_broad_and_traversing_paths(self):
        for p in ('/', '/srv', '/var/lib', 'relative/root', '/srv/a/../b', '/tmp/a;id', '/tmp/root with spaces'):
            with self.assertRaises(M.DeployError): M.safe_root(p)
    def test_root_rejects_symlink_ancestor(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); (root/'real').mkdir(); (root/'alias').symlink_to(root/'real')
            with self.assertRaises(M.DeployError): M.safe_root(str(root/'alias/sub'))
    def test_health_never_treats_unhealthy_or_oom_as_ready(self):
        for state in (None, {}, {'Running': False}, {'Running': True, 'OOMKilled': True},
                      {'Running': True, 'Health': {'Status': 'starting'}},
                      {'Running': True, 'Health': {'Status': 'unhealthy'}}): self.assertFalse(M.healthy(state))
        self.assertTrue(M.healthy({'Running': True, 'Health': {'Status': 'healthy'}}))

class SourceTests(unittest.TestCase):
    def fixture(self, p):
        for n in ('scripts/bootstrap.py', 'deploy/install.py', 'deploy/AstrBot.Dockerfile'):
            t = p/n; t.parent.mkdir(parents=True, exist_ok=True); t.write_text('root="/srv/p1-agent"\n')
        M.atomic(p/'source-manifest.json', {n: hashlib.sha256((p/n).read_bytes()).hexdigest()
                 for n in ('scripts/bootstrap.py', 'deploy/install.py', 'deploy/AstrBot.Dockerfile')})
    def test_source_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d); self.fixture(p); M.verify_source(p)
            (p/'deploy/install.py').write_text('tampered')
            with self.assertRaisesRegex(M.DeployError, 'source_hash'): M.verify_source(p)
    def test_source_paths_cannot_escape(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d); self.fixture(p); m = M.read(p/'source-manifest.json'); m['../outside'] = 'x'; M.atomic(p/'source-manifest.json', m)
            with self.assertRaises(M.DeployError): M.verify_source(p)
    def test_staging_changes_only_private_copy_and_preserves_image_readability(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d); s=p/'source'; s.mkdir(); self.fixture(s)
            before=(s/'scripts/bootstrap.py').read_bytes(); target=p/'private/source'; target.mkdir(parents=True)
            M.materialize(s, target, Path('/srv/custom-agent'))
            self.assertEqual((s/'scripts/bootstrap.py').read_bytes(), before)
            self.assertIn('/srv/custom-agent', (target/'scripts/bootstrap.py').read_text())
            self.assertEqual((target/'scripts/bootstrap.py').stat().st_mode & 0o777, 0o644)
    def test_staging_rechecks_hashes_at_copy_time(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d); s=p/'source'; s.mkdir(); self.fixture(s); (s/'deploy/install.py').write_text('changed')
            with self.assertRaisesRegex(M.DeployError,'source_changed'): M.materialize(s, p/'staged', Path('/srv/custom'))

class JobTests(unittest.TestCase):
    def fixture(self, p):
        root=p/'agent'; (root/'backups').mkdir(parents=True)
        j=root/'backups/oneclick-test'; j.mkdir()
        M.atomic(j/'state.json', {'root': str(root), 'status': 'installing', 'steps': [], 'core_project': 'astrbot'})
        return root, M.Job(j)
    def test_snapshot_and_restore_preserve_prior_sources_and_existing_databases(self):
        with tempfile.TemporaryDirectory() as d:
            root,job=self.fixture(Path(d)); cfg=root/'astrbot/data/cmd_config.json'; cfg.parent.mkdir(parents=True); cfg.write_text('original config')
            db=cfg.parent/'data_v4.db'; db.write_bytes(b'original-history')
            M.snapshot(job); cfg.write_text('new config'); new=root/'public-browser'; new.mkdir(); (new/'code').write_text('new')
            db.write_bytes(b'new-real-history-must-survive')
            M.restore_paths(job)
            self.assertEqual(cfg.read_text(),'original config'); self.assertFalse(new.exists())
            self.assertEqual(db.read_bytes(),b'new-real-history-must-survive')
            self.assertTrue((job.path/'replaced/10/code').is_file())
    def test_snapshot_rejects_symlink_target(self):
        with tempfile.TemporaryDirectory() as d:
            root,job=self.fixture(Path(d)); (root/'public-browser').symlink_to('/tmp')
            with self.assertRaises(M.DeployError): M.snapshot(job)
    def test_restore_rejects_unlisted_paths(self):
        with tempfile.TemporaryDirectory() as d:
            root,job=self.fixture(Path(d)); job.state['before']=[{'path':'/etc/passwd','exists':True,'slot':'0'}]
            with self.assertRaisesRegex(M.DeployError,'rollback_path'): M.restore_paths(job)
    def test_private_state_is_atomic_and_mode_600(self):
        with tempfile.TemporaryDirectory() as d:
            root,job=self.fixture(Path(d)); job.save()
            self.assertEqual((job.path/'state.json').stat().st_mode&0o777,0o600)
            self.assertFalse((job.path/'state.json.new').exists())
    def test_mutating_child_is_released_only_after_pid_is_saved(self):
        with tempfile.TemporaryDirectory() as d:
            root,job=self.fixture(Path(d)); marker=job.path/'child-started'; saved=[]; original=job.save
            def save():
                if 'active' in job.state:
                    self.assertFalse(marker.exists()); saved.append(job.state['active']['pid'])
                original()
            with patch.object(job,'save',side_effect=save):
                job.command('write_marker',[sys.executable,'-c','from pathlib import Path; import sys; Path(sys.argv[1]).write_text("ok")',str(marker)],10)
            self.assertTrue(saved); self.assertTrue(marker.exists()); self.assertNotIn('active',job.state)
    def test_command_timeout_cleans_process_and_records_no_success(self):
        with tempfile.TemporaryDirectory() as d:
            root,job=self.fixture(Path(d))
            with self.assertRaises(subprocess.TimeoutExpired): job.command('timeout',[sys.executable,'-c','import time; time.sleep(30)'],0.1)
            self.assertNotIn('timeout',job.state['steps']); self.assertNotIn('active',job.state)
    def test_build_failure_does_not_stop_or_restore_original_core(self):
        with tempfile.TemporaryDirectory() as d:
            root,job=self.fixture(Path(d)); calls=[]
            with patch.object(job,'command',side_effect=lambda *a,**k:calls.append(a)), patch.object(M,'inspect',return_value=None): M.rollback(job)
            self.assertEqual(calls,[]); self.assertEqual(job.state['status'],'rolled_back')
    def test_runtime_failure_restores_original_image_and_source(self):
        with tempfile.TemporaryDirectory() as d:
            root,job=self.fixture(Path(d)); cfg=root/'astrbot/data/cmd_config.json'; cfg.parent.mkdir(parents=True); cfg.write_text('before')
            M.snapshot(job); cfg.write_text('after'); job.state['mutations_started']=True; job.save(); calls=[]
            with patch.object(job,'command',side_effect=lambda *a,**k:calls.append(a)), patch.object(job,'wait'), patch.object(M,'inspect',return_value=None), patch.object(M,'probe',return_value=subprocess.CompletedProcess([],1,'')):
                M.rollback(job)
            self.assertEqual(cfg.read_text(),'before'); self.assertEqual(job.state['status'],'rolled_back')
            self.assertTrue(any(a[0]=='rollback_original_core' and str(job.path/'original-image.json') in a[1] for a in calls))
    def test_rollback_refuses_foreign_container(self):
        with tempfile.TemporaryDirectory() as d:
            root,job=self.fixture(Path(d)); job.state['mutations_started']=True; job.save(); calls=[]
            with patch.object(job,'command',side_effect=lambda *a,**k:calls.append(a)), patch.object(M,'inspect',return_value={'Running':True}), patch.object(M,'field',side_effect=lambda n,t:'astrbot' if n=='astrbot' else 'other-project'):
                with self.assertRaisesRegex(M.DeployError,'foreign_container'): M.rollback(job)
            self.assertEqual(job.state['status'],'rollback_failed')
            self.assertFalse(any('rm' in a[1] for a in calls))
    def test_repeated_completed_rollback_is_noop(self):
        with tempfile.TemporaryDirectory() as d:
            root,job=self.fixture(Path(d)); job.state['status']='rolled_back'; job.save()
            with patch.object(job,'command') as command: M.rollback(job)
            command.assert_not_called()
    @unittest.skipUnless(os.name=='posix','flock requires Unix')
    def test_concurrent_installer_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root,job=self.fixture(Path(d))
            with M.deploy_lock(root):
                with self.assertRaisesRegex(M.DeployError,'another_deployment'):
                    with M.deploy_lock(root): pass

class PlanTests(unittest.TestCase):
    def test_doctor_is_read_only_and_does_not_echo_config_secrets(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'agent'; data=root/'astrbot/data'; data.mkdir(parents=True)
            secret='synthetic-key-do-not-print'; M.atomic(data/'cmd_config.json', {'provider':[{'enable':True,'key':secret}],'platform':[{'id':'qq_snowluma'}]})
            before={str(p):p.read_bytes() for p in root.rglob('*') if p.is_file()}
            with patch.object(M,'verify_source',return_value='x'),patch.object(M,'probe',return_value=subprocess.CompletedProcess([],1,'')),patch.object(M,'inspect',return_value=None),patch.object(M,'field',side_effect=M.DeployError('no_core')):
                report=M.doctor(root)
            self.assertFalse(report['ok']); self.assertNotIn(secret,json.dumps(report)); self.assertTrue(report['read_only'])
            self.assertEqual(before,{str(p):p.read_bytes() for p in root.rglob('*') if p.is_file()})
    def test_existing_installation_refused_instead_of_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'agent'; (root/'astrbot/data/plugin_data/affect').mkdir(parents=True)
            with patch.object(M,'verify_source',return_value='x'),patch.object(M,'probe',return_value=subprocess.CompletedProcess([],1,'')),patch.object(M,'inspect',return_value=None),patch.object(M,'field',side_effect=M.DeployError('no_core')): report=M.doctor(root)
            self.assertIn('existing_companion_data_use_manual_upgrade',report['errors'])
    def test_gate_does_not_execute_on_closed_input(self):
        r=subprocess.run([sys.executable,'-c',M.GATE,sys.executable,'-c','raise Exception("must not run")'],input=b'',capture_output=True)
        self.assertEqual(r.returncode,125); self.assertNotIn(b'must not run',r.stderr)

class FinalSafetyTests(unittest.TestCase):
    def test_positive_doctor_accepts_standard_fresh_layout(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'agent';data=root/'astrbot/data';data.mkdir(parents=True)
            for folder in ('astrbot','snowluma'):
                (root/folder).mkdir(exist_ok=True);(root/folder/'compose.yaml').write_text('services: {}')
            M.atomic(data/'cmd_config.json',{'provider':[{'enable':True}],'platform':[{'id':'qq_snowluma'}]})
            def probe(args,**kw):
                if args[:3]==['docker','network','inspect'] or args[0]=='systemctl':return subprocess.CompletedProcess(args,1,'')
                if 'config' in args:return subprocess.CompletedProcess(args,0,json.dumps({'services':{'astrbot':{}}}))
                return subprocess.CompletedProcess(args,0,'ok')
            def field(n,t):
                if 'Mounts' in t:return json.dumps([{'Destination':'/AstrBot/data','Type':'bind','Source':str(data)}])
                if 'Labels' in t:return json.dumps({'com.docker.compose.service':'astrbot','com.docker.compose.project.config_files':str(root/'astrbot/compose.yaml')})
                return 'root'
            with patch.object(M,'verify_source',return_value='digest'),patch.object(M.platform,'system',return_value='Linux'),patch.object(M.platform,'machine',return_value='aarch64'),patch.object(M,'host_memory',return_value={'MemTotal':4*1024**3,'MemAvailable':2*1024**3}),patch.object(M,'probe',side_effect=probe),patch.object(M,'field',side_effect=field),patch.object(M,'inspect',side_effect=lambda n:{'Running':True} if n in ('astrbot','snowluma') else None),patch.object(M.shutil,'disk_usage',return_value=type('Disk',(),{'free':20*1024**3})()):report=M.doctor(root)
            self.assertTrue(report['ok'],report['errors'])
    def test_dead_parent_watchdog_finishes_no_mutation_job(self):
        with tempfile.TemporaryDirectory() as d:
            root,job=JobTests().fixture(Path(d));job.state.update(parent_pid=999999,parent_start='old');job.save()
            with patch.object(M,'process_start',return_value=None),patch.object(M.Job,'command') as cmd:M.watchdog(job.path)
            self.assertEqual(M.Job(job.path).state['status'],'rolled_back');cmd.assert_not_called()
    def test_failure_does_not_stop_replaced_foreign_core(self):
        with tempfile.TemporaryDirectory() as d:
            root,job=JobTests().fixture(Path(d));job.state['mutations_started']=True;job.save()
            with patch.object(M,'inspect',return_value={'Running':True}),patch.object(M,'field',return_value='foreign-project'),patch.object(job,'command') as command:
                with self.assertRaisesRegex(M.DeployError,'foreign_core'):M.rollback(job)
            command.assert_not_called();self.assertEqual(job.state['status'],'rollback_failed')

class CoordinatorTests(unittest.TestCase):
    def run_case(self, fail=None):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d); root=base/'agent'; data=root/'astrbot/data'; data.mkdir(parents=True)
            for folder in ('astrbot','snowluma'):
                (root/folder).mkdir(exist_ok=True)
                (root/folder/'compose.yaml').write_text('services: {}\n')
            M.atomic(data/'cmd_config.json',{'marker':'original'})
            (data/'data_v4.db').write_bytes(b'keep-history')
            source=base/'source'; source.mkdir()
            for rel in ('scripts/bootstrap.py','scripts/setup_workflows.py','scripts/secure_workflows.py','scripts/selftest.py','deploy/install.py','deploy/AstrBot.Dockerfile'):
                p=source/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('# test stub\n')
            for rel in ('browser/compose.yaml','services/leisure/compose.yaml','services/workbench/compose.yaml'):
                p=source/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('image: p1-companion-browser:0.20.0\n')
            M.atomic(source/'source-manifest.json',{str(p.relative_to(source)):hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob('*') if p.is_file()})
            original_compose=(root/'astrbot/compose.yaml').read_bytes(); states={'astrbot':True,'snowluma':True}; calls=[]
            def state(n): return {'Running':True} if states.get(n) else None
            def field(n,t):
                if t=='{{.Image}}':return 'sha256:'+'a'*64
                return 'astrbot' if n=='astrbot' else M.TOOLS.get(n,'unknown')
            def command(job,label,args,timeout=180,cwd=None):
                calls.append((label,args))
                if label in ('stop_core','rollback_stop_core'):states['astrbot']=False
                if label=='install_plugins_and_config':
                    M.atomic(data/'cmd_config.json',{'marker':'installed'})
                    M.atomic(data/'mcp_server.json',{'mcpServers':{}})
                    p=data/'plugin_data/affect';p.mkdir(parents=True)
                    plugin=data/'plugins/astrbot_plugin_affect';plugin.mkdir(parents=True);(plugin/'main.py').write_text('new plugin')
                if label.startswith('start_p1-') or label=='initialize_workflows':
                    states.update({n:True for n in M.TOOLS})
                if label in ('start_integrated_core','rollback_original_core'):
                    states['astrbot']=True
                    if label=='start_integrated_core':M.atomic(data/'plugin_data/affect/companion_health.json',{k:True for k in M.READY})
                if label.startswith('rollback_p1-') and label!='rollback_original_core':states.pop(label[len('rollback_'):],None)
                if label==fail:raise M.DeployError('injected_'+label)
                job.state['steps'].append(label);job.save()
            def probe(args,**kw):
                if 'config' in args:return subprocess.CompletedProcess(args,0,json.dumps({'services':{'astrbot':{'networks':{'default':{}}}}}))
                return subprocess.CompletedProcess(args,1,'')
            with patch.object(M,'doctor',return_value={'ok':True,'errors':[],'manifest_sha256':'fixture'}),patch.object(M.os,'geteuid',return_value=0),patch.object(M,'process_start',return_value='start'),patch.object(M,'field',side_effect=field),patch.object(M,'inspect',side_effect=state),patch.object(M,'probe',side_effect=probe),patch.object(M.Job,'command',new=command),patch.object(M.subprocess,'Popen'),contextlib.redirect_stdout(io.StringIO()):
                if fail:
                    with self.assertRaises(M.DeployError):M.apply(root,'10001','20002',source)
                else:
                    report=M.apply(root,'10001','20002',source);self.assertTrue(report['installed'])
            job=M.Job(next(p for p in (root/'backups').glob('oneclick-*') if p.is_dir()))
            self.assertEqual((root/'astrbot/compose.yaml').read_bytes(),original_compose)
            self.assertEqual((data/'data_v4.db').read_bytes(),b'keep-history')
            self.assertTrue(states['snowluma'])
            if fail:
                self.assertEqual(job.state['status'],'rolled_back')
                self.assertEqual(M.read(data/'cmd_config.json'),{'marker':'original'})
                self.assertTrue(states['astrbot'])
            else:
                self.assertEqual(job.state['status'],'committed')
                order=[label for label,args in calls]
                self.assertLess(order.index('build_workbench'),order.index('stop_core'))
                self.assertLess(order.index('snapshot') if 'snapshot' in order else order.index('offline_neutral_checks'),order.index('stop_core'))
                self.assertTrue((job.path/'companion-override.json').is_file())
                self.assertEqual(M.read(job.path/'original-image.json')['services']['astrbot']['image'],'sha256:'+'a'*64)
    def test_complete_coordinator_preserves_original_compose(self):self.run_case()
    def test_failures_at_ten_stages_restore_prior_installation(self):
        for stage in ('build_core_dependencies','build_browser','build_workbench','offline_neutral_checks','stop_core','install_plugins_and_config','start_p1-companion','initialize_workflows','start_integrated_core','verify_core_dependencies'):
            with self.subTest(stage=stage):self.run_case(stage)

if __name__=='__main__': unittest.main()
