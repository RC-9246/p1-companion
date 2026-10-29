"""Local, authenticated installation wizard. Standard library; loopback only."""
import argparse,contextlib,fcntl,hashlib,hmac,http.client,importlib.util,json,os,re,secrets,select,socket,subprocess,sys,threading,time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
import firstboot as F
import install as I
import gui_cleanup as G
_update_spec=importlib.util.spec_from_file_location('p1_core_updater',Path(__file__).resolve().parents[1]/'services/updater/manager.py')
U=importlib.util.module_from_spec(_update_spec);sys.modules[_update_spec.name]=U;_update_spec.loader.exec_module(U)
_module_spec=importlib.util.spec_from_file_location('p1_module_manager',Path(__file__).resolve().parents[1]/'services/modules/manager.py')
M=importlib.util.module_from_spec(_module_spec);_module_spec.loader.exec_module(M)
ASSETS=Path(__file__).resolve().parent/'wizard'
STEPS={'tag_installed_base':'保存原始镜像','build_core_dependencies':'安装 AstrBot 扩展依赖','build_browser':'准备浏览器','build_workbench':'准备文件与实验工具','offline_neutral_checks':'运行离线检查','stop_core':'保存恢复点并切换服务','install_plugins_and_config':'安装记忆、情绪与学习模块','start_p1-companion':'启动公开浏览器','start_p1-workbench':'启动文件工具','start_p1-leisure':'启动私人浏览空间','initialize_workflows':'准备工作流','secure_workflow_setup':'保护工作流账号','start_integrated_core':'启动完整伙伴','verify_core_dependencies':'核对依赖与服务'}
ACTIONS={'check','core','integrate','login','model_save','model_test','maintenance','monitor','rollback','stop_core','finish','guard','upgrade_check','upgrade_apply','upgrade_status','upgrade_rollback','modules_status','modules_plan','modules_apply','modules_remove','modules_recover'}
class Wizard:
    def __init__(self,state,preview=False,manage_root=None):
        self.state=Path(state);self.preview=preview;self.token=secrets.token_urlsafe(32);self.lock=threading.Lock();self.jobs=[];self.config={};self.ticket=None;self.desktop_root=None;self.retired=False;self.on_shutdown=lambda:None;self.manage_root=str(I.safe_root(manage_root)) if manage_root else None
        self.state.mkdir(mode=0o700,parents=True,exist_ok=True)
        F.need(not self.state.is_symlink() and self.state.stat().st_uid==os.geteuid() and not self.state.stat().st_mode&0o077,'untrusted_wizard_state')
        self.lease=(self.state/'server.lock').open('a');fcntl.flock(self.lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if not self.preview and (self.state/'completed.json').exists():
            F.need(not (self.state/'completed.json').is_symlink(),'untrusted_wizard_state')
            # A deliberately reopened installer is a new session. A previous
            # success must never make a failed new run look completed.
            previous=self.state/('completed-previous-'+str(time.time_ns())+'.json')
            os.replace(self.state/'completed.json',previous)
        for p in sorted(self.state.glob('job-*.json'))[-30:]:
            with contextlib.suppress(OSError,ValueError):
                row=F.read(p)
                if row.get('status')=='running':row['status']='interrupted'
                self.jobs.append(row)
    def save(self,row):I.atomic(self.state/('job-'+row['id']+'.json'),row)
    def snapshot(self):
        defaults={'root':self.manage_root or '/srv/p1-agent','model':'deepseek-flash'}
        if self.jobs:
            latest=self.jobs[-1].get('settings',{})
            earlier=next((j.get('settings',{}) for j in reversed(self.jobs) if j.get('root')==latest.get('root') and j.get('settings',{}).get('bot')), {})
            defaults.update(earlier);defaults.update(latest)
        if self.manage_root:defaults.update(root=self.manage_root,mode='existing')
        update={'state':'preview' if self.preview else 'idle'}
        if not self.preview:
            try:update=U.public_status(defaults['root'])
            except (OSError,ValueError,U.UpdateError):update={'state':'unavailable'}
        return {'project':'p1-companion-installer','preview':self.preview,'retired':self.retired,'management':bool(self.manage_root),'jobs':self.jobs[-12:],'running':self.lock.locked(),'defaults':defaults,'core_update':update,'module_catalog':M.registry()[0],'supported':['Windows 10/11 x64 + WSL2 Ubuntu 24.04','Ubuntu 24.04 / Debian 12,13 / compatible Armbian']}
    def emit(self,row,step,label):
        row['step']=step;row['message']=label;row['events']=(row['events']+[{'step':step,'message':label,'at':int(time.time())}])[-60:];self.save(row)
    def start(self,action,values):
        F.need(action in ACTIONS,'unknown_action');F.need(not self.preview,'preview_read_only');F.need(not self.retired,'wizard_completed')
        if action.startswith('modules_'):
            F.need(isinstance(values,dict) and set(values)<={'root','selected','accepted'},'invalid_input')
            v={'root':str(I.safe_root(values.get('root','/srv/p1-agent'))),'accepted':values.get('accepted') is True}
            if action not in ('modules_status','modules_recover'):
                selected=values.get('selected');F.need(isinstance(selected,list) and len(selected)<=32 and all(isinstance(k,str) for k in selected),'invalid_input')
                M.closure(selected,M.registry()[1]);v['selected']=selected
        elif action.startswith('upgrade_'):
            F.need(isinstance(values,dict) and set(values)<={'root','component','version','accepted'},'invalid_input')
            v={'root':str(I.safe_root(values.get('root','/srv/p1-agent'))),'component':U.component(values.get('component','astrbot')),'accepted':values.get('accepted') is True}
            if action=='upgrade_apply':v['version']=U.version(values.get('version'))
        elif action=='check':
            F.need(isinstance(values,dict) and values.get('mode','new') in ('new','existing'),'invalid_input')
            v={'root':str(I.safe_root(values.get('root','/srv/p1-agent'))),'mode':values.get('mode','new')}
        else:v=F.validate_input(values)
        if v.get('mode')=='existing' and action in ('core','login','model_save','model_test','stop_core'):
            F.need(False,'existing_core_use_dashboard')
        F.need(v.get('accepted') is True or action in ('check','login','finish','upgrade_check','upgrade_status','modules_status','modules_plan'),'review_installation_first')
        F.need(self.lock.acquire(blocking=False),'another_operation_in_progress')
        row={'id':str(time.time_ns())+'-'+secrets.token_hex(3),'action':action,'root':v['root'],'settings':{k:v[k] for k in ('root','mode','bot','owner','model','social') if k in v},'status':'running','events':[],'message':'正在准备','at':int(time.time())}
        try:self.jobs.append(row);self.save(row);threading.Thread(target=self.run,args=(row,v),daemon=True).start()
        except BaseException:self.lock.release();raise
        return {'job':row['id']}
    def latest_point(self,root):
        p=Path(F.read(root/'backups/oneclick-latest.json')['point'])
        F.need(p.parent==root/'backups' and re.fullmatch('oneclick-[0-9-]+',p.name) and not p.is_symlink(),'invalid_recovery_point')
        state=F.read(p/'state.json');F.need(state.get('root')==str(root),'invalid_recovery_point');return p,state
    def run(self,row,v):
        action=row['action'];root=Path(v['root']);emit=lambda step,label:self.emit(row,step,label)
        try:
            F.PRIVATE_LOG=self.state/('job-'+row['id']+'.private.log')
            I.verify_source(I.SOURCE)
            if action.startswith('modules_'):
                emit(action,{'modules_status':'读取模块状态','modules_plan':'计算依赖与调整计划','modules_apply':'应用功能组合，保留数据','modules_remove':'移除未选服务容器，保留数据','modules_recover':'恢复上一次未完成的模块调整'}[action])
                controller=M.Controller(root)
                if action=='modules_status':result=controller.status()
                elif action=='modules_plan':result=M.plan(v['selected'],controller.current()['enabled'])
                elif action=='modules_recover':
                    F.need(os.geteuid()==0 and sys.platform.startswith('linux'),'apply_requires_sudo');result=controller.recover(True)
                else:
                    F.need(os.geteuid()==0 and sys.platform.startswith('linux'),'apply_requires_sudo')
                    result=controller.apply(v['selected'],action=='modules_remove')
            elif action.startswith('upgrade_'):
                emit(action,{'upgrade_check':'查询官方稳定版','upgrade_apply':'保存恢复点、隔离预检与切换版本','upgrade_status':'读取升级状态','upgrade_rollback':'验证当前数据并回退最近一次升级'}[action])
                if action=='upgrade_check':result=U.catalog(v['component'])
                elif action=='upgrade_status':result=U.public_status(root)
                else:
                    F.need(os.geteuid()==0 and sys.platform.startswith('linux'),'apply_requires_sudo')
                    engine=U.Engine(root)
                    result=engine.apply(v['component'],v['version'],I.SOURCE) if action=='upgrade_apply' else engine.tick(True)
            elif action=='check':
                result=F.audit(root) if v['mode']=='new' else I.doctor(root)
                self.ticket={'root':str(root),'mode':v['mode'],'at':time.monotonic(),'ok':result['ok']}
            elif action=='core':
                F.need(v['mode']=='new','fresh_setup_only');result=F.prepare_core(v,emit)
            elif action=='login':result=F.login_status(root)
            elif action=='model_save':result=F.configure_model(v)
            elif action=='model_test':result=F.test_model(root)
            elif action=='integrate':
                if v['mode']=='new':F.need(F.login_status(root)['logged_in'],'qq_login_required')
                report=I.doctor(root);F.need(report['ok'],'integration_preflight_failed')
                class Progress:
                    def write(self,text):
                        label=text.strip()
                        if label in STEPS:emit(label,STEPS[label])
                        return len(text)
                    def flush(self):pass
                with contextlib.redirect_stdout(Progress()):result=I.apply(root,v['bot'],v['owner'],social=v.get('social',False))
            elif action in ('maintenance','monitor','guard'):
                F.need(v.get('real_chat_confirmed') is True,'real_chat_confirmation_required');point,state=self.latest_point(root);F.need(state.get('status')=='committed','integration_not_committed')
                script={'maintenance':'install_maintenance.py','monitor':'install_monitor.py','guard':'install_resource_guard.py'}[action]
                args=[sys.executable,str(point/'source/scripts'/script)]
                if action in ('maintenance','guard'):args+=['--root',str(root),'--apply']
                emit(action,{'maintenance':'安装自动维护','monitor':'安装资源面板','guard':'开启内存保护'}[action])
                F.command(args,240);result={'installed':True,'kind':action}
                if action!='guard':result['chatbot_restart_requested']=False
            elif action=='finish':
                point,state=self.latest_point(root)
                G.acceptance(root,point,state,v.get('real_chat_confirmed'))
                if v.get('resource_protection',True):
                    emit('resource_guard','开启内存保护并保存恢复点')
                    F.command([sys.executable,str(point/'source/scripts/install_resource_guard.py'),'--root',str(root),'--apply'],240)
                emit('final_check','核对服务与模块，保存安装记录')
                result=G.finish(root,point,state,self.state,v.get('real_chat_confirmed'),v.get('auto_cleanup',True))
                if result['cleanup_complete']:self.retired=True
            elif action=='rollback':
                point,state=self.latest_point(root);F.need(state.get('status') in ('committed','rolled_back'),'installation_not_ready_for_rollback')
                # Existing CLI enforces latest point, unchanged source/config/image,
                # and preserves databases. Never accept a point from a web request.
                F.pause_maintenance(root)
                with contextlib.ExitStack() as stack:
                    lockpath=root/'astrbot/data/plugin_data/affect/maintenance.lock'
                    if lockpath.parent.exists():
                        lock=stack.enter_context(lockpath.open('a'));fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    F.command([sys.executable,str(I.SOURCE/'deploy/install.py'),'--root',str(root),'--rollback',str(point)],600)
                result={'rolled_back':True,'databases_restored':False,'maintenance_timers_left_disabled':True}
            else:result=F.rollback_core(root,emit)
            row.update(status='succeeded',result=result,message='操作完成')
            if action.startswith('upgrade_') and result.get('state') in ('rolled_back','rollback_blocked'):
                row.update(message='升级未提交，旧版已恢复' if result['state']=='rolled_back' else '自动回滚未通过，当前数据已保留，请查看升级状态')
            self.save(row)
            if self.retired:
                timer=threading.Timer(8,self.on_shutdown);timer.daemon=True;timer.start()
        except BaseException as exc:
            # Do not return str(exc): vendor output or configuration can contain credentials.
            allowed={'preview_read_only','apply_requires_sudo','preflight_failed','qq_login_required','integration_preflight_failed','real_chat_confirmation_required','integration_not_committed','existing_container_not_owned','setup_identity_changed','setup_compose_changed','not_created_by_this_wizard','incomplete_setup_requires_review','api_key_required','dashboard_password_too_weak','model_destination_changed','model_connection_failed','rollback_companion_first','post_install_changes_require_manual_restore','final_health_check_failed','windows_runtime_not_ready','unsafe_cleanup_path','unmanaged_installer_source'}
            code=str(exc) if (isinstance(exc,(F.SetupError,I.DeployError)) and str(exc) in allowed) or (isinstance(exc,U.UpdateError) and re.fullmatch('[a-z_]{1,80}',str(exc))) else 'operation_failed'
            row.update(status='failed',error=code,message='未完成，数据已保留；可检查原因后重试');self.save(row)
        finally:v.pop('api_key',None);v.pop('password',None);F.PRIVATE_LOG=None;self.lock.release()

class Server(ThreadingHTTPServer):
    daemon_threads=True
class Handler(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'
    def setup(self):super().setup();self.connection.settimeout(20)
    def log_message(self,*args):pass
    def safe_host(self):return self.headers.get('Host') in self.server.allowed_hosts
    def authorized(self):
        supplied=self.headers.get('X-P1-Setup-Token','');cookies=SimpleCookie()
        with contextlib.suppress(Exception):cookies.load(self.headers.get('Cookie',''))
        cookie=cookies.get('p1_setup');return hmac.compare_digest(supplied,self.server.app.token) or bool(cookie and hmac.compare_digest(cookie.value,self.server.app.token))
    def send(self,status,value,ctype='application/json; charset=utf-8',cookie=False):
        data=json.dumps(value,ensure_ascii=False).encode() if isinstance(value,(dict,list)) else value
        self.send_response(status);self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.send_header('Referrer-Policy','no-referrer');self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self' ws://127.0.0.1:* ws://localhost:*; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if cookie:self.send_header('Set-Cookie','p1_setup='+('deleted; Max-Age=0' if self.server.app.retired else self.server.app.token)+'; HttpOnly; SameSite=Strict; Path=/')
        self.end_headers();self.wfile.write(data)
    def do_GET(self):
        if not self.safe_host():return self.send(403,{'error':'host_denied'})
        path=urlsplit(self.path).path
        if path in ('/','/style.css','/app.js'):
            file={'/':'index.html','/style.css':'style.css','/app.js':'app.js'}[path];mime={'/':'text/html; charset=utf-8','/style.css':'text/css; charset=utf-8','/app.js':'text/javascript; charset=utf-8'}[path]
            return self.send(200,self.server.assets[file],mime)
        if not self.authorized():return self.send(401,{'error':'session_required'})
        if path=='/api/state':return self.send(200,self.server.app.snapshot(),cookie=True)
        if path.startswith('/desktop/'):
            if self.server.app.preview or self.server.app.retired:return self.send(403,{'error':'preview_read_only_or_completed'})
            return self.proxy_desktop()
        return self.send(404,{'error':'not_found'})
    def do_POST(self):
        if not self.safe_host() or self.headers.get('Origin') not in self.server.origins or not self.authorized():return self.send(403,{'error':'session_or_origin_denied'})
        if self.headers.get('Transfer-Encoding') or self.headers.get('Content-Type','').split(';')[0]!='application/json':return self.send(415,{'error':'json_required'})
        try:
            size=int(self.headers.get('Content-Length','0'));F.need(0<size<=8192,'invalid_request_size');body=json.loads(self.rfile.read(size));F.need(isinstance(body,dict),'invalid_input')
            path=urlsplit(self.path).path
            F.need(not self.server.app.retired,'wizard_completed')
            if path=='/api/desktop':
                F.need(not self.server.app.preview,'preview_read_only');root=I.safe_root(body.get('root',''));record=F.owned(root)
                obj=F.verify_container('snowluma',record);F.need(obj is not None and obj.get('State',{}).get('Running'),'desktop_not_ready');self.server.app.desktop_root=root
                return self.send(200,{'password':record['vnc_password'],'transport':'authenticated_local_proxy'})
            if path=='/api/bilibili':
                F.need(not self.server.app.preview,'preview_read_only');F.need(set(body)=={'root','action'},'invalid_input')
                root=I.safe_root(body['root']);F.need(self.server.app.lock.acquire(blocking=False),'another_operation_in_progress')
                try:result=F.bilibili_login(root,body['action'])
                finally:self.server.app.lock.release()
                return self.send(200,result)
            F.need(path=='/api/action' and set(body)=={'action','values'},'invalid_endpoint')
            result=self.server.app.start(body['action'],body['values']);return self.send(202,result)
        except (ValueError,TypeError,KeyError,OSError,subprocess.SubprocessError,F.SetupError,I.DeployError,U.UpdateError):return self.send(400,{'error':'invalid_or_unavailable_request'})
    def proxy_desktop(self):
        # A single fixed loopback upstream. No configurable URL/host or generic proxy.
        root=self.server.app.desktop_root
        if root is None:return self.send(403,{'error':'open_desktop_first'})
        path=self.path.removeprefix('/desktop');F.need(path.startswith('/') and '..' not in path,'invalid_desktop_path')
        if self.headers.get('Upgrade','').lower()=='websocket':
            if urlsplit(path).path!='/websockify' or self.headers.get('Origin') not in self.server.origins:return self.send(403,{'error':'desktop_origin_denied'})
            upstream=socket.create_connection(('127.0.0.1',6081),timeout=5)
            try:
                request='GET '+path+' HTTP/1.1\r\nHost: 127.0.0.1:6081\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
                for key in ('Sec-WebSocket-Key','Sec-WebSocket-Version','Sec-WebSocket-Protocol'):
                    value=self.headers.get(key)
                    if value:request+=key+': '+value+'\r\n'
                upstream.sendall((request+'\r\n').encode());self.connection.settimeout(60);upstream.settimeout(60)
                end=time.monotonic()+3600
                while time.monotonic()<end:
                    ready,_,_=select.select([upstream,self.connection],[],[],30)
                    if not ready:continue
                    for src in ready:
                        data=src.recv(65536)
                        if not data:return
                        (self.connection if src is upstream else upstream).sendall(data)
            except (OSError,ValueError):pass
            finally:upstream.close();self.close_connection=True
        else:
            c=http.client.HTTPConnection('127.0.0.1',6081,timeout=10)
            try:
                c.request('GET',path);r=c.getresponse();data=r.read(4*1024**2+1)
                if len(data)>4*1024**2:return self.send(502,{'error':'desktop_asset_too_large'})
                return self.send(r.status,data,r.getheader('Content-Type','application/octet-stream'))
            except (OSError,http.client.HTTPException):return self.send(503,{'error':'desktop_not_ready'})
            finally:c.close()
def make_server(app,port):
    server=Server(('127.0.0.1',port),Handler);server.app=app;server.assets={name:(ASSETS/name).read_bytes() for name in ('index.html','style.css','app.js')};server.allowed_hosts={f'127.0.0.1:{server.server_port}',f'localhost:{server.server_port}'};server.origins={'http://'+x for x in server.allowed_hosts};app.on_shutdown=server.shutdown;return server
def main():
    p=argparse.ArgumentParser();p.add_argument('--preview',action='store_true');p.add_argument('--port',type=int,default=6191);p.add_argument('--state-dir',type=Path,default=Path('/var/lib/p1-companion-installer'));p.add_argument('--url-file',type=Path);p.add_argument('--manage-root');a=p.parse_args()
    if not a.preview:F.need(sys.platform=='linux' and os.geteuid()==0,'start_on_linux_with_sudo')
    F.need(all((ASSETS/name).is_file() and not (ASSETS/name).is_symlink() for name in ('index.html','style.css','app.js')),'download_complete_source_first')
    os.umask(0o077);app=Wizard(a.state_dir,a.preview,a.manage_root);server=make_server(app,a.port);url='http://127.0.0.1:'+str(server.server_port)+'/#'+app.token
    pidfile=app.state/'server.pid';pidfile.write_text(str(os.getpid()));pidfile.chmod(0o600)
    if a.url_file:
        F.need(a.url_file.is_absolute() and not a.url_file.is_symlink(),'unsafe_url_file');a.url_file.write_text(url);a.url_file.chmod(0o600)
    print('请在浏览器打开：'+url,flush=True)
    try:server.serve_forever(poll_interval=.3)
    except KeyboardInterrupt:pass
    finally:server.server_close();app.lease.close();pidfile.unlink(missing_ok=True)
if __name__=='__main__':main()
