"""Temporary filesystem, real loopback HTTP and Linux process boundary checks."""
import hashlib,http.client,json,os,subprocess,sys,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'deploy'))
import gui_cleanup as G
import wizard as W

class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name).resolve();self.root=self.base/'agent';self.point=self.root/'backups/oneclick-20261027-123456-100'
        self.point.mkdir(parents=True);self.session=self.base/'session';self.session.mkdir(mode=0o700)
        self.source=self.base/'managed';self.source.mkdir();self.make_source()
        self.state={'status':'committed','root':str(self.root)}
        W.I.atomic(self.point/'state.json',self.state);W.I.atomic(self.root/'backups/oneclick-latest.json',{'point':str(self.point)})
        health=self.root/'astrbot/data/plugin_data/affect/companion_health.json';health.parent.mkdir(parents=True);W.I.atomic(health,{k:True for k in W.I.READY})
        self.db=health.parent/'affect.db';self.db.write_bytes(b'synthetic-newer-memory')
        (self.point/'source').mkdir();(self.point/'source/wizard.py').write_text('rollback evidence')
        (self.session/'browser.url').write_text('synthetic-session-secret')
    def tearDown(self):self.temp.cleanup()
    def make_source(self):
        (self.source/'deploy').mkdir(exist_ok=True);(self.source/'deploy/wizard.py').write_text('reviewed GUI source')
        W.I.atomic(self.source/'source-manifest.json',{'deploy/wizard.py':hashlib.sha256((self.source/'deploy/wizard.py').read_bytes()).hexdigest()})
        (self.source/'.p1-wizard-source').write_text('1\n')
    def finish(self,**kwargs):
        with patch.object(W.I,'inspect',return_value={'Running':True}),patch.object(G,'windows_runtime_ready'),patch.object(G,'MANAGED_SOURCE',self.source):
            return G.finish(self.root,self.point,self.state,self.session,source=self.source,**{'confirmed':True,**kwargs})
    def test_removes_verified_staging_only_and_preserves_runtime_and_rollback(self):
        r=self.finish();self.assertTrue(r['cleanup_complete']);self.assertEqual(r['services_checked'],8);self.assertFalse(self.source.exists());self.assertFalse((self.session/'browser.url').exists())
        self.assertEqual(self.db.read_bytes(),b'synthetic-newer-memory');self.assertEqual((self.point/'source/wizard.py').read_text(),'rollback evidence')
        self.assertTrue(W.I.read(self.session/'completed.json')['cleanup_complete'])
    def test_original_download_is_not_managed_staging(self):
        r=G.remove_managed_source(self.source);self.assertEqual(r['managed_files_removed'],0);self.assertTrue((self.source/'deploy/wizard.py').exists())
    def test_changed_and_untracked_files_are_retained(self):
        (self.source/'deploy/wizard.py').write_text('local edits');(self.source/'user-note.txt').write_text('preserve')
        r=self.finish();self.assertEqual(r['managed_files_retained'],1);self.assertTrue((self.source/'user-note.txt').exists());self.assertTrue((self.source/'source-manifest.json').exists())
    def test_untracked_file_is_not_removed_with_directory(self):
        (self.source/'local.txt').write_text('keep');self.finish();self.assertEqual((self.source/'local.txt').read_text(),'keep')
    def test_symlink_directory_never_traversed(self):
        outside=self.base/'outside';outside.mkdir();(outside/'important').write_text('keep')
        (self.source/'deploy/wizard.py').unlink();(self.source/'deploy').rmdir();(self.source/'deploy').symlink_to(outside,target_is_directory=True)
        r=self.finish();self.assertEqual(r['managed_files_retained'],1);self.assertEqual((outside/'important').read_text(),'keep')
    def test_manifest_traversal_rejected_before_deletion(self):
        W.I.atomic(self.source/'source-manifest.json',{'../important':'a'*64})
        with self.assertRaisesRegex(G.F.SetupError,'unmanaged'):self.finish()
        self.assertTrue((self.source/'deploy/wizard.py').exists());self.assertTrue((self.session/'browser.url').exists())
    def test_marker_must_match(self):
        (self.source/'.p1-wizard-source').write_text('foreign')
        with self.assertRaisesRegex(G.F.SetupError,'unmanaged'):self.finish()
        self.assertTrue((self.source/'deploy/wizard.py').exists())
    def test_no_cleanup_without_real_chat(self):
        with self.assertRaisesRegex(G.F.SetupError,'real_chat'):self.finish(confirmed=False)
        self.assertTrue((self.session/'browser.url').exists());self.assertTrue(self.source.exists())
    def test_failed_or_rolled_back_install_cannot_be_cleaned(self):
        for status in ('installing','rolled_back','rollback_failed'):
            self.state['status']=status
            with self.assertRaisesRegex(G.F.SetupError,'not_committed'):self.finish()
        self.assertTrue(self.source.exists())
    def test_unhealthy_service_or_stale_flags_preserves_gui(self):
        with patch.object(W.I,'inspect',return_value={'Running':False}):
            with self.assertRaisesRegex(G.F.SetupError,'final_health'):G.acceptance(self.root,self.point,self.state,True)
        W.I.atomic(self.root/'astrbot/data/plugin_data/affect/companion_health.json',{})
        with self.assertRaisesRegex(G.F.SetupError,'final_health'):self.finish()
        self.assertTrue(self.source.exists())
    def test_keep_gui_option_does_not_delete_anything_or_require_wsl_client(self):
        with patch.object(G,'windows_runtime_ready',side_effect=AssertionError('must not run')):
            with patch.object(W.I,'inspect',return_value={'Running':True}):r=G.finish(self.root,self.point,self.state,self.session,True,False,self.source)
        self.assertTrue(r['gui_kept']);self.assertTrue((self.session/'browser.url').exists());self.assertTrue(self.source.exists())
    def test_private_logs_archived_with_private_modes_and_unknown_files_preserved(self):
        (self.session/'job-123-abc.private.log').write_text('synthetic private failure evidence');(self.session/'unrelated.txt').write_text('keep')
        self.finish();archives=list(self.point.glob('wizard-final-*'));self.assertEqual(len(archives),1)
        log=archives[0]/'job-123-abc.private.log';self.assertEqual(log.read_text(),'synthetic private failure evidence');self.assertEqual(log.stat().st_mode&0o777,0o600)
        self.assertFalse((self.session/log.name).exists());self.assertTrue((self.session/'unrelated.txt').exists())
    def test_foreign_symlink_log_rejected(self):
        (self.session/'job-123-abc.json').symlink_to(self.db)
        with self.assertRaisesRegex(G.F.SetupError,'unsafe'):self.finish()
        self.assertTrue(self.source.exists());self.assertEqual(self.db.read_bytes(),b'synthetic-newer-memory')
    def test_bad_windows_keepalive_preserves_everything(self):
        with patch.object(W.I,'inspect',return_value={'Running':True}),patch.object(G,'windows_runtime_ready',side_effect=G.F.SetupError('windows_runtime_not_ready')):
            with self.assertRaisesRegex(G.F.SetupError,'windows_runtime'):G.finish(self.root,self.point,self.state,self.session,True,source=self.source)
        self.assertTrue(self.source.exists());self.assertTrue((self.session/'browser.url').exists())
    def test_authenticated_http_completion_closes_only_wizard_and_blocks_followup(self):
        app=W.Wizard(self.session);server=W.make_server(app,0);serving=threading.Thread(target=server.serve_forever,daemon=True);serving.start()
        app.on_shutdown=server.shutdown
        try:
            with patch.object(W.I,'verify_source'),patch.object(W.I,'inspect',return_value={'Running':True}),patch.object(G,'windows_runtime_ready'),patch.object(G,'MANAGED_SOURCE',self.source),patch.object(W.I,'SOURCE',self.source):
                c=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5);headers={'Content-Type':'application/json','Origin':'http://127.0.0.1:'+str(server.server_port),'X-P1-Setup-Token':app.token}
                v={'root':str(self.root),'mode':'existing','bot':'10001','owner':'20002','real_chat_confirmed':True}
                c.request('POST','/api/action',json.dumps({'action':'finish','values':v}),headers);response=c.getresponse();self.assertEqual(response.status,202);response.read();c.close()
                end=time.monotonic()+5
                while app.lock.locked() and time.monotonic()<end:time.sleep(.02)
                self.assertEqual(app.jobs[-1]['status'],'succeeded');self.assertTrue(app.retired);self.assertFalse(self.source.exists())
                c=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5);c.request('GET','/app.js');r=c.getresponse();self.assertEqual(r.status,200);self.assertIn(b'completed(result)',r.read());c.close()
                with self.assertRaisesRegex(W.F.SetupError,'completed'):app.start('check',{'root':str(self.root)})
                self.assertEqual(self.db.read_bytes(),b'synthetic-newer-memory')
                serving.join(10);self.assertFalse(serving.is_alive())
        finally:
            if serving.is_alive():server.shutdown()
            server.server_close();app.lease.close()
    def test_preview_cannot_finish(self):
        app=W.Wizard(self.session,True)
        try:
            with self.assertRaisesRegex(W.F.SetupError,'preview'):app.start('finish',{})
        finally:app.lease.close()
    def test_cleanup_parameter_requires_boolean(self):
        v={'root':str(self.root),'bot':'10001','owner':'20002','auto_cleanup':'true'}
        with self.assertRaises(W.F.SetupError):W.F.validate_input(v)
    def test_reopened_gui_does_not_reuse_an_old_completion_receipt(self):
        W.I.atomic(self.session/'completed.json',{'cleanup_complete':True})
        app=W.Wizard(self.session)
        try:
            self.assertFalse(app.retired);self.assertFalse((self.session/'completed.json').exists());self.assertEqual(len(list(self.session.glob('completed-previous-*.json'))),1)
        finally:app.lease.close()

@unittest.skipUnless(sys.platform=='linux' and os.geteuid()==0,'native Linux root process test')
class RuntimeHolderTests(unittest.TestCase):
    def test_native_holder_lives_after_gui_exit_and_only_stops_its_own_exact_pid(self):
        with tempfile.TemporaryDirectory() as t:
            base=Path(t);helper=base/'holder.sh';state=base/'holder-state'
            helper.write_text((ROOT/'deploy/wsl-runtime.sh').read_text().replace('STATE=/run/p1-companion-runtime','STATE='+str(state)))
            p=subprocess.Popen(['bash',str(helper)],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            try:
                for attempt in range(50):
                    check=subprocess.run(['bash',str(helper),'--check'],capture_output=True)
                    if check.returncode==0:break
                    time.sleep(.05)
                self.assertEqual(check.returncode,0);self.assertIsNone(p.poll())
                gui=subprocess.Popen([sys.executable,'-c','pass']);gui.wait(timeout=5);self.assertIsNone(p.poll())
                duplicate=subprocess.run(['bash',str(helper)],timeout=5,capture_output=True);self.assertNotEqual(duplicate.returncode,0);self.assertIsNone(p.poll())
                subprocess.run(['bash',str(helper),'--stop'],check=True,capture_output=True);p.wait(timeout=5);self.assertNotEqual(subprocess.run(['bash',str(helper),'--check'],capture_output=True).returncode,0)
                # Forged PID without the matching lock/start/command cannot kill
                # an unrelated process, even if that process is also sleep.
                foreign=subprocess.Popen(['/usr/bin/sleep','60'])
                try:
                    record=json.loads((state/'process.json').read_text());record['pid']=foreign.pid;(state/'process.json').write_text(json.dumps(record))
                    subprocess.run(['bash',str(helper),'--stop'],check=True,capture_output=True);self.assertIsNone(foreign.poll())
                finally:foreign.terminate();foreign.wait(timeout=5)
            finally:
                if p.poll() is None:p.terminate();p.wait(timeout=5)
                p.communicate()

if __name__=='__main__':unittest.main()
