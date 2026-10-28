"""No model, account, apt or Docker calls; actual HTTP and temporary files."""
import hashlib,http.client,importlib.util,json,os,socket,subprocess,sys,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'deploy'))
import firstboot as F
import wizard as W
def values(root='/srv/p1-agent'):
    return {'root':str(root),'mode':'new','bot':'10001','owner':'20002','api_key':'synthetic-test-secret','model':'deepseek-chat','password':'SyntheticPassword123','social':False,'accepted':True,'real_chat_confirmed':False}

class ConfigurationTests(unittest.TestCase):
    def record(self):return {'schema':1,'id':'a'*32,'onebot_token':'b'*64,'vnc_password':'c'*8}
    def test_only_supported_distributions_are_accepted(self):
        for distro,code in [('debian','bookworm'),('debian','trixie'),('ubuntu','noble'),('armbian','bookworm')]:self.assertIn(F.distribution({'ID':distro,'VERSION_CODENAME':code})[0],('debian','ubuntu'))
        for v in ({'ID':'ubuntu','VERSION_CODENAME':'jammy'},{'ID':'arch'},{'ID':'debian','VERSION_CODENAME':'evil\nrepo'}):
            with self.assertRaises(F.SetupError):F.distribution(v)
    def test_shell_roots_and_extra_fields_are_rejected(self):
        for root in ('/','/srv','relative','/srv/a;id','/srv/x/../y'):
            with self.assertRaises((F.SetupError,F.integration.DeployError)):F.validate_input(values(root))
        with self.assertRaises(F.SetupError):F.validate_input({**values(),'command':'id'})
    def test_identities_and_exact_boolean_types(self):
        for v in ({'bot':'x'},{'owner':'10001'},{'social':'true'},{'accepted':1},{'model':'x;id'},{'api_key':'key\nvalue'}):
            with self.assertRaises((F.SetupError,F.integration.DeployError)):F.validate_input({**values(),**v})
    def test_dashboard_hash_is_salted_and_upstream_compatible(self):
        a=F.dashboard_hash('SyntheticPassword123');b=F.dashboard_hash('SyntheticPassword123');self.assertNotEqual(a,b)
        kind,count,salt,digest=a.split('$');self.assertEqual(kind,'pbkdf2_sha256');self.assertEqual(int(count),600000)
        self.assertEqual(digest,hashlib.pbkdf2_hmac('sha256',b'SyntheticPassword123',bytes.fromhex(salt),int(count)).hex())
        for weak in ('short','a'*16,'UPPERCASE12345'):
            with self.assertRaises(F.SetupError):F.dashboard_hash(weak)
    def test_all_host_ports_are_loopback_and_reverse_ws_is_internal(self):
        out=F.configs(values(),self.record())
        for name in ('astrbot/compose.yaml','snowluma/compose.yaml'):
            for service in out[name]['services'].values():
                self.assertTrue(all(x.startswith('127.0.0.1:') for x in service['ports']));self.assertNotIn('/var/run/docker.sock',json.dumps(service))
        cfg=out['astrbot/data/cmd_config.json'];one=out['snowluma/data/config/onebot.json']['networks']
        self.assertEqual(one['wsClients'][0]['url'],'ws://astrbot:6199/ws');self.assertEqual(one['wsClients'][0]['accessToken'],cfg['platform'][0]['ws_reverse_token']);self.assertFalse(one['wsServers'])
    def test_api_key_only_enters_provider_and_plain_admin_password_is_absent(self):
        out=F.configs(values(),self.record());cfg=out['astrbot/data/cmd_config.json']
        self.assertEqual(cfg['provider_sources'][0]['api_base'],'https://api.deepseek.com/v1');self.assertEqual(cfg['provider_sources'][0]['key'],['synthetic-test-secret']);self.assertEqual(cfg['provider'][0]['provider_source_id'],'deepseek')
        self.assertNotIn('SyntheticPassword123',json.dumps(out));self.assertEqual(cfg['admins_id'],['20002']);self.assertEqual(len(cfg['platform_settings']['id_whitelist']),1)
        self.assertFalse(any('latest' in out[n]['services'][k]['image'] for n,k in [('astrbot/compose.yaml','astrbot'),('snowluma/compose.yaml','snowluma')]))
    def test_invalid_credentials_fail_before_package_install(self):
        with tempfile.TemporaryDirectory() as t,patch.object(F.os,'geteuid',return_value=0),patch.object(F,'install_docker') as install:
            with self.assertRaises(F.SetupError):F.prepare_core({**values(Path(t)/'agent'),'password':'weak'},lambda *a:None)
            install.assert_not_called()
    def test_actual_new_files_permissions_and_no_overwrite_of_unknown_core(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t).resolve()/'agent';v=values(root);calls=[]
            with patch.object(F.os,'geteuid',return_value=0),patch.object(F.os,'chown') as chown,patch.object(F,'audit',return_value={'ok':True}),patch.object(F,'test_credentials',return_value={'connected':True}),patch.object(F,'install_docker'),patch.object(F,'inspect',return_value=None),patch.object(F,'command',side_effect=lambda a,*x:calls.append(a) or ''),patch.object(F.subprocess,'run',return_value=subprocess.CompletedProcess([],1,'')):
                result=F.prepare_core(v,lambda *x:None)
            self.assertTrue(result['awaiting_login']);self.assertFalse(result['accounts_logged_in']);self.assertEqual((root/'astrbot/data/cmd_config.json').stat().st_mode&0o777,0o600)
            self.assertTrue(any(c.args[1:]==(1000,1000) for c in chown.call_args_list));self.assertTrue(any('pull' in c for c in calls));self.assertTrue(any('up' in c for c in calls))
            self.assertNotIn('synthetic-test-secret',F.marker(root).read_text());self.assertEqual(F.owned(root)['root'],str(root))
    def test_foreign_container_never_removed(self):
        with patch.object(F,'inspect',return_value={'Config':{'Labels':{F.LABEL:'foreign'}}}),patch.object(F,'command') as cmd:
            with self.assertRaisesRegex(F.SetupError,'not_owned'):F.verify_container('snowluma',self.record())
            cmd.assert_not_called()
    def test_stop_core_refuses_companion_before_any_container_action(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);(root/'astrbot/data/plugin_data/affect').mkdir(parents=True)
            with patch.object(F,'owned',return_value=self.record()),patch.object(F,'command') as cmd:
                with self.assertRaisesRegex(F.SetupError,'rollback_companion'):F.rollback_core(root,lambda *a:None)
                cmd.assert_not_called()
    def test_api_errors_return_status_without_vendor_content(self):
        response=unittest.mock.Mock(status=401);response.read.return_value=b'{"error":"synthetic-private-vendor-text"}'
        connection=unittest.mock.Mock();connection.getresponse.return_value=response
        cfg=F.configs(values(),self.record())['astrbot/data/cmd_config.json']
        with patch.object(F,'owned',return_value=self.record()),patch.object(F,'read',return_value=cfg),patch.object(F.http.client,'HTTPSConnection',return_value=connection):r=F.test_model(Path('/srv/test'))
        self.assertFalse(r['connected']);self.assertEqual(r['http_status'],401);self.assertNotIn('private',json.dumps(r));self.assertEqual(connection.request.call_args.args[1],'/v1/chat/completions')
    def test_model_test_never_changes_destination_based_on_config(self):
        cfg=F.configs(values(),self.record())['astrbot/data/cmd_config.json'];cfg['provider_sources'][0]['api_base']='https://untrusted.invalid'
        with patch.object(F,'owned',return_value=self.record()),patch.object(F,'read',return_value=cfg),patch.object(F.http.client,'HTTPSConnection') as connect:
            with self.assertRaisesRegex(F.SetupError,'destination_changed'):F.test_model(Path('/srv/test'))
            connect.assert_not_called()
    def test_flash_routes_vision_and_thinking_are_configured_together(self):
        out=F.configs({**values(),'model':'deepseek-flash'},self.record())['astrbot/data/cmd_config.json'];rows={p['id']:p for p in out['provider']}
        self.assertEqual(len(rows),3);self.assertEqual(out['agent_runner']['config']['model']['provider_id'],'deepseek/deepseek-flash');self.assertIn('image',rows['deepseek/deepseek-flash']['modalities'])
        self.assertEqual(rows['deepseek-max/deepseek-flash']['custom_extra_body']['reasoning_effort'],'max');self.assertEqual(rows['deepseek-quick/deepseek-flash']['custom_extra_body']['thinking']['type'],'disabled')
        self.assertLess(rows['deepseek-quick/deepseek-flash']['custom_extra_body']['max_tokens'],4096)
    def test_custom_model_does_not_invent_flash_capabilities(self):
        self.assertEqual(len(F.models_for('custom-text-model')),1);self.assertNotIn('image',F.models_for('custom-text-model')[0]['modalities']);self.assertNotIn('custom_extra_body',F.models_for('custom-text-model')[0])
    def test_bilibili_allows_only_two_login_actions(self):
        with patch.object(F,'owned') as owned:
            for action in ('comment','like','watch','snapshot','http://example.com'):
                with self.assertRaises(F.SetupError):F.bilibili_login(Path('/srv/test'),action)
            owned.assert_not_called()
    def test_bad_api_key_blocks_host_changes(self):
        with tempfile.TemporaryDirectory() as t,patch.object(F.os,'geteuid',return_value=0),patch.object(F,'audit',return_value={'ok':True}),patch.object(F,'test_credentials',return_value={'connected':False}),patch.object(F,'install_docker') as install:
            root=Path(t)/'agent'
            with self.assertRaisesRegex(F.SetupError,'model_connection_failed'):F.prepare_core(values(root),lambda *a:None)
            install.assert_not_called();self.assertFalse(root.exists())
    def test_failed_model_restart_restores_old_configuration_and_preserves_history(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t).resolve()/'agent';cfg=F.configs(values(root),self.record())['astrbot/data/cmd_config.json'];target=root/'astrbot/data/cmd_config.json';F.write(target,cfg);db=target.parent/'data_v4.db';db.write_bytes(b'new-history-preserved');starts=[]
            def command(args,*rest):
                if args[1]=='start':
                    starts.append(1)
                    if len(starts)==1:raise F.SetupError('start_failed')
                return ''
            with patch.object(F,'owned',return_value=self.record()),patch.object(F,'verify_container'),patch.object(F,'command',side_effect=command):
                with self.assertRaises(F.SetupError):F.configure_model({**values(root),'api_key':'synthetic-new-secret','model':'deepseek-flash'})
            self.assertEqual(F.read(target),cfg);self.assertEqual(db.read_bytes(),b'new-history-preserved');self.assertEqual(len(starts),2)

class JobTests(unittest.TestCase):
    def test_preflight_does_not_invent_qq_accounts(self):
        with tempfile.TemporaryDirectory() as t:
            app=W.Wizard(Path(t).resolve())
            try:
                with patch.object(W.I,'verify_source'),patch.object(W.F,'audit',return_value={'ok':True,'errors':[]}):
                    app.start('check',{'root':'/srv/empty-agent','mode':'new'})
                    for _ in range(100):
                        if not app.lock.locked():break
                        time.sleep(.01)
                self.assertEqual(app.jobs[-1]['status'],'succeeded');self.assertNotIn('bot',app.snapshot()['defaults']);self.assertNotIn('owner',app.snapshot()['defaults'])
            finally:app.lease.close()
    def test_preview_blocks_every_action(self):
        with tempfile.TemporaryDirectory() as t:
            app=W.Wizard(Path(t).resolve(),True)
            try:
                for action in W.ACTIONS:
                    with self.assertRaisesRegex(F.SetupError,'preview_read_only'):app.start(action,values())
            finally:app.lease.close()
    def test_journal_and_api_snapshot_never_store_credentials(self):
        with tempfile.TemporaryDirectory() as t:
            app=W.Wizard(Path(t).resolve());v=values()
            try:
                with patch.object(W.I,'verify_source'),patch.object(W.F,'audit',return_value={'ok':True,'errors':[]}):
                    app.start('check',v)
                    for _ in range(100):
                        if not app.lock.locked():break
                        time.sleep(.01)
                self.assertEqual(app.jobs[-1]['status'],'succeeded');data=json.dumps(app.snapshot())+''.join(p.read_text() for p in Path(t).glob('*.json'))
                self.assertNotIn('synthetic-test-secret',data);self.assertNotIn('SyntheticPassword123',data)
            finally:app.lease.close()
    def test_active_job_and_no_consent_block_second_mutation(self):
        with tempfile.TemporaryDirectory() as t:
            app=W.Wizard(Path(t).resolve())
            try:
                with self.assertRaisesRegex(F.SetupError,'review_installation'):app.start('core',{**values(),'accepted':False})
                app.lock.acquire()
                try:
                    with self.assertRaisesRegex(F.SetupError,'another_operation'):app.start('check',values())
                finally:app.lock.release()
            finally:app.lease.close()
    def test_restart_marks_incomplete_job_without_claiming_rollback(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t).resolve();F.write(p/'job-1.json',{'id':'1','status':'running'})
            app=W.Wizard(p)
            try:self.assertEqual(app.jobs[0]['status'],'interrupted');self.assertNotIn('rolled_back',json.dumps(app.snapshot()))
            finally:app.lease.close()
    def test_failure_does_not_emit_exception_credentials(self):
        with tempfile.TemporaryDirectory() as t:
            app=W.Wizard(Path(t).resolve())
            try:
                with patch.object(W.I,'verify_source',side_effect=ValueError('synthetic-secret')):
                    app.start('check',values())
                    for _ in range(100):
                        if not app.lock.locked():break
                        time.sleep(.01)
                self.assertNotIn('synthetic-secret',json.dumps(app.snapshot()));self.assertEqual(app.jobs[-1]['status'],'failed')
            finally:app.lease.close()

class CoreUpgradeControls(unittest.TestCase):
    def test_module_catalog_is_available_in_preview_without_live_access(self):
        with tempfile.TemporaryDirectory() as t:
            app=W.Wizard(Path(t).resolve(),True)
            try:self.assertEqual(len(app.snapshot()['module_catalog']['modules']),15)
            finally:app.lease.close()
    def test_module_changes_reject_commands_and_require_consent(self):
        with tempfile.TemporaryDirectory() as t:
            app=W.Wizard(Path(t).resolve())
            try:
                with self.assertRaisesRegex(F.SetupError,'review_installation'):
                    app.start('modules_apply',{'root':'/srv/synthetic-agent','selected':['core']})
                with self.assertRaises(F.SetupError):
                    app.start('modules_apply',{'root':'/srv/synthetic-agent','selected':['core'],'accepted':True,'command':'id'})
                with self.assertRaises(W.U.UpdateError):
                    app.start('modules_plan',{'root':'/srv/synthetic-agent','selected':['shell']})
            finally:app.lease.close()
    def test_check_needs_no_qq_or_api_credentials(self):
        with tempfile.TemporaryDirectory() as t:
            app=W.Wizard(Path(t).resolve())
            try:
                with patch.object(W.I,'verify_source',return_value='verified'),patch.object(W.U,'catalog',return_value={'component':'astrbot','versions':[{'version':'v4.29.3'}]}):
                    app.start('upgrade_check',{'root':'/srv/synthetic-agent','component':'astrbot'})
                    end=time.monotonic()+2
                    while app.lock.locked() and time.monotonic()<end:time.sleep(.01)
                self.assertEqual(app.jobs[-1]['status'],'succeeded');self.assertEqual(app.jobs[-1]['result']['component'],'astrbot')
                self.assertNotIn('api_key',json.dumps(app.jobs))
            finally:app.lease.close()
    def test_upgrade_requires_explicit_action_and_closed_fields(self):
        with tempfile.TemporaryDirectory() as t:
            app=W.Wizard(Path(t).resolve())
            try:
                with self.assertRaisesRegex(F.SetupError,'review_installation'):
                    app.start('upgrade_apply',{'root':'/srv/synthetic-agent','component':'astrbot','version':'v4.29.3'})
                with self.assertRaises(F.SetupError):
                    app.start('upgrade_apply',{'root':'/srv/synthetic-agent','component':'astrbot','version':'v4.29.3','accepted':True,'command':'id'})
                with self.assertRaises(W.U.UpdateError):
                    app.start('upgrade_check',{'root':'/srv/synthetic-agent','component':'shell'})
            finally:app.lease.close()
    def test_management_mode_uses_operator_root(self):
        with tempfile.TemporaryDirectory() as t:
            app=W.Wizard(Path(t).resolve(),True,manage_root='/srv/synthetic-agent')
            try:
                v=app.snapshot();self.assertTrue(v['management']);self.assertEqual(v['defaults']['root'],'/srv/synthetic-agent');self.assertEqual(v['core_update']['state'],'preview')
            finally:app.lease.close()
    def test_upgrade_uses_server_source_and_no_browser_command(self):
        with tempfile.TemporaryDirectory() as t:
            app=W.Wizard(Path(t).resolve())
            try:
                with patch.object(W.I,'verify_source',return_value='verified'),patch.object(W.os,'geteuid',return_value=0),patch.object(W.sys,'platform','linux'),patch.object(W.U,'Engine') as engine:
                    engine.return_value.apply.return_value={'state':'observing'}
                    app.start('upgrade_apply',{'root':'/srv/synthetic-agent','component':'astrbot','version':'4.29.3','accepted':True})
                    end=time.monotonic()+2
                    while app.lock.locked() and time.monotonic()<end:time.sleep(.01)
                    engine.return_value.apply.assert_called_once_with('astrbot','v4.29.3',W.I.SOURCE)
                self.assertEqual(app.jobs[-1]['status'],'succeeded')
            finally:app.lease.close()

class HttpTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=W.Wizard(Path(self.temp.name).resolve(),True);self.server=W.make_server(self.app,0);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.port=self.server.server_port
    def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join();self.app.lease.close();self.temp.cleanup()
    def request(self,path='/',method='GET',body=None,headers=None):
        c=http.client.HTTPConnection('127.0.0.1',self.port,timeout=5)
        h=headers or {};raw=json.dumps(body) if isinstance(body,dict) else body;c.request(method,path,raw,h);r=c.getresponse();out=(r.status,dict(r.getheaders()),r.read());c.close();return out
    def auth(self):return {'X-P1-Setup-Token':self.app.token,'Origin':'http://127.0.0.1:'+str(self.port),'Content-Type':'application/json'}
    def test_static_assets_have_csp_and_no_external_runtime_dependencies(self):
        status,headers,body=self.request();self.assertEqual(status,200);self.assertIn("frame-ancestors 'none'",headers['Content-Security-Policy']);self.assertEqual(headers['Referrer-Policy'],'no-referrer');self.assertNotIn(self.app.token.encode(),body)
        self.assertNotIn(b'cdn.',body);self.assertEqual(self.request('/app.js')[0],200)
    def test_state_needs_session_and_sets_httponly_cookie(self):
        self.assertEqual(self.request('/api/state')[0],401);status,h,b=self.request('/api/state',headers=self.auth());self.assertEqual(status,200);self.assertIn('HttpOnly',h['Set-Cookie']);self.assertIn('SameSite=Strict',h['Set-Cookie']);self.assertNotIn(self.app.token.encode(),b)
    def test_rebinding_host_and_cross_origin_post_are_denied(self):
        self.assertEqual(self.request('/api/state',headers={**self.auth(),'Host':'evil.invalid'})[0],403)
        self.assertEqual(self.request('/api/action','POST',{'action':'check','values':values()}, {**self.auth(),'Origin':'https://evil.invalid'})[0],403)
    def test_query_token_not_accepted_and_arbitrary_proxy_not_available(self):
        self.assertEqual(self.request('/api/state?token='+self.app.token)[0],401);self.assertEqual(self.request('/proxy?url=http://example.com',headers=self.auth())[0],404)
    def test_paths_and_unsupported_post_types_are_rejected(self):
        self.assertEqual(self.request('/../../etc/passwd',headers=self.auth())[0],404);self.assertEqual(self.request('/api/action','POST','x', {**self.auth(),'Content-Type':'text/plain'})[0],415)
        self.assertEqual(self.request('/api/action','POST','x'*8193,self.auth())[0],400)
    def test_preview_forbids_login_desktop_and_installation(self):
        status,_,body=self.request('/api/action','POST',{'action':'core','values':values()},self.auth());self.assertEqual(status,400);self.assertNotIn(b'synthetic-test-secret',body)
        self.assertEqual(self.request('/api/desktop','POST',{'root':'/srv/p1-agent'},self.auth())[0],400)
    def test_api_accepts_no_extra_command_or_rollback_path(self):
        self.assertEqual(self.request('/api/action','POST',{'action':'core','values':values(),'command':'id'},self.auth())[0],400)
        self.assertEqual(self.request('/api/action','POST',{'action':'rollback','values':{**values(),'point':'/etc'}},self.auth())[0],400)
    def test_desktop_upgrade_relays_bytes_only_to_fixed_upstream(self):
        self.app.preview=False;self.app.desktop_root=Path(self.temp.name)
        upstream=socket.socket();upstream.bind(('127.0.0.1',0));upstream.listen(1);upstream.settimeout(5);received=[]
        def desktop():
            connection,_=upstream.accept();connection.settimeout(5)
            with connection:
                request=b''
                while b'\r\n\r\n' not in request:request+=connection.recv(4096)
                received.append(request);connection.sendall(b'HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\nRFB!');received.append(connection.recv(4))
        worker=threading.Thread(target=desktop,daemon=True);worker.start();original=socket.create_connection;seen=[]
        def connect(address,*a,**kw):
            if address==('127.0.0.1',6081):seen.append(address);return original(upstream.getsockname(),*a,**kw)
            return original(address,*a,**kw)
        try:
            with patch.object(W.socket,'create_connection',side_effect=connect):
                with original(('127.0.0.1',self.port),timeout=5) as client:
                    headers=self.auth();headers.update({'Host':'127.0.0.1:'+str(self.port),'Upgrade':'websocket','Connection':'Upgrade','Sec-WebSocket-Key':'synthetic-key','Sec-WebSocket-Version':'13'})
                    raw='GET /desktop/websockify HTTP/1.1\r\n'+''.join(k+': '+v+'\r\n' for k,v in headers.items())+'\r\n';client.sendall(raw.encode());data=b''
                    while b'RFB!' not in data:data+=client.recv(4096)
                    client.sendall(b'PING');worker.join(5)
            self.assertTrue(seen);self.assertEqual(received[-1],b'PING');self.assertIn(b'GET /websockify ',received[0]);self.assertNotIn(self.app.token.encode(),received[0])
        finally:upstream.close()
if __name__=='__main__':unittest.main()
