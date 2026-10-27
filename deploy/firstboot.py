"""Fresh-host setup used by the local wizard; never adopts existing containers.

System packages remain installed on rollback. Account data is always retained.
Official upstream configuration references are in docs/installation-wizard.md.
"""
import base64,contextlib,hashlib,http.client,json,os,platform,re,secrets,shutil,socket,subprocess,time
from pathlib import Path
import install as integration

ASTRBOT_IMAGE='soulter/astrbot:v4.29.1@sha256:a140a326163ac5f82f62153f033cddeac74e38e4ee1809c6e333e950ff19edc4'
SNOWLUMA_IMAGE='motricseven7/snowluma:v1.10.0@sha256:f7dbe3a8c87974c4af47118d10953c4b117d1d5d7b2f17c088709cde05d986b9'
NETWORK='p1-companion-core'
LABEL='org.p1-companion.setup'
PORTS=(6185,6081,6300)
PRIVATE_LOG=None
class SetupError(RuntimeError):pass
def need(ok,code):
    if not ok:raise SetupError(code)
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def write(p,v):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    integration.atomic(p,v)
def command(args,timeout=120):
    try:r=subprocess.run(args,capture_output=True,text=True,timeout=timeout,stdin=subprocess.DEVNULL,env={**os.environ,'DEBIAN_FRONTEND':'noninteractive'})
    except (OSError,subprocess.SubprocessError):raise SetupError('command_unavailable_or_timed_out') from None
    if PRIVATE_LOG is not None:
        with Path(PRIVATE_LOG).open('a') as f:
            Path(PRIVATE_LOG).chmod(0o600);f.write('\n['+args[0]+']\n'+(r.stdout+r.stderr)[-65536:])
    need(r.returncode==0,'system_command_failed');return r.stdout
def os_release(path=Path('/etc/os-release')):
    values={}
    for line in path.read_text().splitlines():
        k,sep,v=line.partition('=')
        if sep:values[k]=v.strip('"\'')
    return values
def distribution(values=None):
    v=os_release() if values is None else values
    distro=v.get('ID');codename=v.get('UBUNTU_CODENAME') or v.get('VERSION_CODENAME')
    if distro=='armbian':distro='ubuntu' if codename in ('noble',) else 'debian'
    need((distro,codename) in (('ubuntu','noble'),('debian','bookworm'),('debian','trixie')),'unsupported_linux_release')
    return distro,codename
def marker(root):return Path(root)/'.p1-companion-setup.json'
def owned(root):
    path=marker(root);need(path.is_file() and not path.is_symlink(),'not_created_by_this_wizard')
    s=path.stat();need(s.st_uid==os.geteuid() and not s.st_mode&0o077,'untrusted_setup_record')
    v=read(path);need(v.get('schema')==1 and re.fullmatch('[a-f0-9]{32}',v.get('id','')) and v.get('root')==str(root),'invalid_setup_record');return v
def port_free(port):
    with socket.socket() as s:
        try:s.bind(('127.0.0.1',port));return True
        except OSError:return False
def inspect(name):
    r=subprocess.run(['docker','inspect',name],capture_output=True,text=True,timeout=20)
    return json.loads(r.stdout)[0] if r.returncode==0 else None
def verify_container(name,record):
    v=inspect(name)
    if v is not None:need(v.get('Config',{}).get('Labels',{}).get(LABEL)==record['id'],'existing_container_not_owned')
    return v
def audit(root):
    errors=[]
    def test(ok,code):
        if not ok:errors.append(code)
    test(platform.system()=='Linux','linux_host_required')
    test(platform.machine() in ('x86_64','amd64','aarch64','arm64'),'unsupported_cpu_architecture')
    try:distribution()
    except (OSError,SetupError):errors.append('unsupported_linux_release')
    test(Path('/run/systemd/system').is_dir(),'systemd_required')
    mem=integration.host_memory();test(mem.get('MemTotal',0)>=3*1024**3,'at_least_4gb_class_host_required')
    test(mem.get('MemAvailable',0)>=1024**3,'at_least_1_gib_available_memory_required')
    ancestor=root
    while not ancestor.exists():ancestor=ancestor.parent
    test(shutil.disk_usage(ancestor).free>=10*1024**3,'at_least_10_gib_free_disk_required')
    try:integration.verify_source(integration.SOURCE)
    except (OSError,ValueError,integration.DeployError):errors.append('source_verification_failed')
    if marker(root).exists():
        try:owned(root)
        except (SetupError,OSError,ValueError):errors.append('untrusted_setup_record')
    else:
        test(not root.exists() or not any(root.iterdir()),'existing_directory_requires_existing_mode')
        for port in PORTS:test(port_free(port),'port_'+str(port)+'_in_use')
    if shutil.which('docker'):
        try:
            test(subprocess.run(['docker','info'],capture_output=True,timeout=15).returncode==0,'docker_daemon_unavailable')
            record=owned(root) if marker(root).exists() else None
            for name in ('astrbot','snowluma'):
                obj=inspect(name)
                test(obj is None or bool(record and obj.get('Config',{}).get('Labels',{}).get(LABEL)==record['id']),'existing_container_not_owned')
            for name in integration.TOOLS:test(inspect(name) is None,'existing_companion_objects')
            for unit in ('p1-companion-maintain.timer','p1-companion-watchdog.timer'):
                test(subprocess.run(['systemctl','is-enabled','--quiet',unit],capture_output=True,timeout=10).returncode!=0,'existing_companion_objects')
        except (OSError,ValueError,SetupError,subprocess.SubprocessError):errors.append('docker_layout_check_failed')
    return {'ok':not errors,'errors':sorted(set(errors)),'docker_installed':bool(shutil.which('docker')),'fresh_host':True,'read_only':True}
def install_docker(emit):
    if shutil.which('docker'):
        command(['docker','info']);command(['docker','compose','version']);return
    distro,code=distribution();emit('docker','安装 Docker 与容器工具')
    for pkg in ('docker.io','podman-docker','containerd','runc'):
        p=subprocess.run(['dpkg-query','-W','-f=${Status}',pkg],capture_output=True,text=True)
        need('install ok installed' not in p.stdout,'conflicting_container_packages')
    command(['apt-get','update'],300)
    command(['apt-get','install','-y','ca-certificates','curl'],600)
    key=Path('/etc/apt/keyrings/p1-companion-docker.asc');repo=Path('/etc/apt/sources.list.d/p1-companion-docker.sources')
    arch=command(['dpkg','--print-architecture']).strip();need(arch in ('amd64','arm64'),'unsupported_cpu_architecture')
    content=f'Types: deb\nURIs: https://download.docker.com/linux/{distro}\nSuites: {code}\nComponents: stable\nArchitectures: {arch}\nSigned-By: {key}\n'
    # Reuse only our exact source; do not replace the administrator's repository.
    if repo.exists():need(repo.read_text()==content,'docker_repository_conflict')
    else:
        need(not key.exists(),'docker_repository_conflict');key.parent.mkdir(mode=0o755,exist_ok=True)
        command(['curl','--fail','--silent','--show-error','--proto','=https','--tlsv1.2','--max-time','90','https://download.docker.com/linux/'+distro+'/gpg','-o',str(key)],100);key.chmod(0o644)
        repo.write_text(content);repo.chmod(0o644)
    command(['apt-get','update'],300)
    command(['apt-get','install','-y','docker-ce','docker-ce-cli','containerd.io','docker-buildx-plugin','docker-compose-plugin'],1200)
    command(['systemctl','enable','--now','docker']);command(['docker','info']);command(['docker','compose','version'])
def dashboard_hash(password):
    need(isinstance(password,str) and 12<=len(password)<=128 and re.search('[A-Z]',password) and re.search('[a-z]',password) and re.search('[0-9]',password),'dashboard_password_too_weak')
    salt=secrets.token_hex(16);digest=hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),600000).hex()
    return 'pbkdf2_sha256$600000$'+salt+'$'+digest
def validate_input(v):
    need(isinstance(v,dict) and set(v)<= {'root','mode','bot','owner','api_key','model','password','social','accepted','real_chat_confirmed','auto_cleanup'},'invalid_input')
    root=integration.safe_root(v.get('root','/srv/p1-agent'));mode=v.get('mode','new');need(mode in ('new','existing'),'invalid_mode')
    bot=integration.identity(v.get('bot',''));owner=integration.identity(v.get('owner',''));need(bot!=owner,'bot_and_owner_must_differ')
    for key in ('social','accepted','real_chat_confirmed','auto_cleanup'):
        if key in v:need(type(v[key]) is bool,'invalid_input')
    model=v.get('model','deepseek-flash');need(isinstance(model,str) and re.fullmatch('[A-Za-z0-9_.:/-]{1,100}',model),'model_name_invalid')
    api=v.get('api_key','');need(isinstance(api,str) and len(api)<=1024 and not any(c.isspace() for c in api),'api_key_invalid')
    return {**v,'root':str(root),'mode':mode,'bot':bot,'owner':owner,'model':model,'api_key':api}
def models_for(model):
    base={'provider_source_id':'deepseek','type':'openai_chat_completion','provider_type':'chat_completion','model':model,'enable':True,'modalities':['text','image','tool_use'] if model=='deepseek-flash' else ['text','tool_use']}
    rows=[{**base,'id':'deepseek/'+model}]
    if model=='deepseek-flash':
        rows[0]['custom_extra_body']={'thinking':{'type':'enabled'},'reasoning_effort':'high','max_tokens':8192}
        rows.extend([{**base,'id':'deepseek-max/deepseek-flash','custom_extra_body':{'thinking':{'type':'enabled'},'reasoning_effort':'max','max_tokens':32768}},
                     {**base,'id':'deepseek-quick/deepseek-flash','custom_extra_body':{'thinking':{'type':'disabled'},'max_tokens':2048}}])
    return rows
def configs(v,record):
    root=Path(v['root']);ident=record['id'];token=record['onebot_token'];password=dashboard_hash(v.get('password',''))
    need(len(v['api_key'])>=8,'api_key_required')
    provider={'id':'deepseek','provider':'deepseek','type':'openai_chat_completion','provider_type':'chat_completion','enable':True,'key':[v['api_key']],'api_base':'https://api.deepseek.com/v1','timeout':120,'proxy':'','custom_headers':{}}
    cfg={'config_version':5,'provider_sources':[provider],'provider':models_for(v['model']),
         'agent_runner':{'runner_type':'local','config':{'model':{'provider_id':'deepseek/'+v['model']}}},
         'provider_settings':{'enable':True,'provider_pool':['*'],'default_image_caption_provider_id':'deepseek/'+v['model'] if v['model']=='deepseek-flash' else ''},'platform':[{'id':'qq_snowluma','type':'aiocqhttp','enable':True,'ws_reverse_host':'0.0.0.0','ws_reverse_port':6199,'ws_reverse_token':token}],
         'admins_id':[v['owner']],'platform_settings':{'enable_id_white_list':True,'id_whitelist':['qq_snowluma:FriendMessage:'+v['owner']]},
         'dashboard':{'enable':True,'host':'0.0.0.0','port':6185,'username':'astrbot','password':'','pbkdf2_password':password,'password_storage_upgraded':True,'password_change_required':False,'jwt_secret':secrets.token_hex(32)}}
    onebot={'networks':{'httpServers':[{'name':'p1-local','enabled':True,'host':'0.0.0.0','port':3000,'accessToken':token,'messageFormat':'array'}],'httpClients':[],'wsServers':[],
                       'wsClients':[{'name':'p1-astrbot','enabled':True,'url':'ws://astrbot:6199/ws','role':'Universal','accessToken':token,'messageFormat':'array','reconnectIntervalMs':5000}]}}
    ast={'services':{'astrbot':{'image':ASTRBOT_IMAGE,'container_name':'astrbot','restart':'unless-stopped','environment':{'TZ':'Asia/Shanghai'},'ports':['127.0.0.1:6185:6185'],'volumes':[str(root/'astrbot/data')+':/AstrBot/data'],'labels':{LABEL:ident}}},'networks':{'default':{'external':True,'name':NETWORK}}}
    snow={'services':{'snowluma':{'image':SNOWLUMA_IMAGE,'container_name':'snowluma','restart':'unless-stopped','shm_size':'1gb','cap_add':['SYS_PTRACE'],'security_opt':['seccomp=unconfined'],'ulimits':{'nofile':{'soft':65536,'hard':1048576}},
          'environment':{'TZ':'Asia/Shanghai','VNC_PASSWD':record['vnc_password'],'SNOWLUMA_WEBUI_HOST':'0.0.0.0','SNOWLUMA_QQ_FLAGS':'--disable-gpu --disable-software-rasterizer --disable-gpu-compositing'},'ports':['127.0.0.1:6081:6081','127.0.0.1:6300:3000'],
          'volumes':[str(root/'snowluma/data')+':/app/data',str(root/'snowluma/qq-config')+':/app/.config',str(root/'snowluma/qq-local')+':/app/.local/share'],'labels':{LABEL:ident}}},'networks':{'default':{'external':True,'name':NETWORK}}}
    return {'astrbot/data/cmd_config.json':cfg,'snowluma/data/config/onebot.json':onebot,'astrbot/compose.yaml':ast,'snowluma/compose.yaml':snow}
def compose(root,name,*args):return ['docker','compose','-p',name,'-f',str(root/name/'compose.yaml'),*args]
def prepare_core(v,emit):
    need(os.geteuid()==0,'apply_requires_sudo');root=Path(v['root'])
    if not marker(root).exists():
        need(len(v['api_key'])>=8,'api_key_required');dashboard_hash(v.get('password',''))
    report=audit(root);need(report['ok'],'preflight_failed')
    if not marker(root).exists():
        emit('test_api','用合成短句核验模型连接（不发送聊天记录）')
        need(test_credentials(v['api_key'],v['model'])['connected'],'model_connection_failed')
    install_docker(emit)
    with integration.deploy_lock(root):
        if marker(root).exists():
            record=owned(root);need(record['bot']==v['bot'] and record['owner']==v['owner'],'setup_identity_changed')
            need(record.get('files_ready'),'incomplete_setup_requires_review')
        else:
            # The lock creates backups/. Reject all pre-existing managed paths.
            need(not (root/'astrbot').exists() and not (root/'snowluma').exists(),'existing_directory_requires_existing_mode')
            record={'schema':1,'id':secrets.token_hex(16),'root':str(root),'bot':v['bot'],'owner':v['owner'],'onebot_token':secrets.token_hex(32),'vnc_password':secrets.token_hex(4),'status':'preparing','created_at':int(time.time())}
            generated=configs(v,record);write(marker(root),record)
            for name,value in generated.items():write(root/name,value)
            # SnowLuma's documented non-root UID must be able to read its own
            # OneBot configuration and persist QQ login state in these bind mounts.
            for rel in ('snowluma/data','snowluma/data/config','snowluma/qq-config','snowluma/qq-local'):
                p=root/rel;p.mkdir(mode=0o700,parents=True,exist_ok=True);os.chown(p,1000,1000);p.chmod(0o700)
            os.chown(root/'snowluma/data/config/onebot.json',1000,1000)
            record['compose_hashes']={n:hashlib.sha256((root/n).read_bytes()).hexdigest() for n in ('astrbot/compose.yaml','snowluma/compose.yaml')};record['files_ready']=True;write(marker(root),record)
        for name,digest in record['compose_hashes'].items():need(hashlib.sha256((root/name).read_bytes()).hexdigest()==digest,'setup_compose_changed')
        for name in ('astrbot','snowluma'):verify_container(name,record)
        network=subprocess.run(['docker','network','inspect',NETWORK],capture_output=True,text=True)
        if network.returncode==0:need(json.loads(network.stdout)[0].get('Labels',{}).get(LABEL)==record['id'],'existing_network_not_owned')
        else:command(['docker','network','create','--label',LABEL+'='+record['id'],NETWORK])
        for name in ('astrbot','snowluma'):
            emit('pull_'+name,'下载 '+('AstrBot' if name=='astrbot' else 'QQ 接入')+'（首次下载需要几分钟）')
            command(compose(root,name,'pull'),1800)
            emit('start_'+name,'启动 '+('AstrBot' if name=='astrbot' else 'QQ 登录桌面'))
            command(compose(root,name,'up','-d','--no-build','--pull','never'),180)
        record['status']='awaiting_login';write(marker(root),record)
    return {'core_ready':True,'awaiting_login':True,'accounts_logged_in':False}
def pause_maintenance(root):
    # Rollback must not race sealed-source recovery. Keep the timers disabled
    # afterwards; the old checkpoint is no longer an accepted code baseline.
    for timer in ('p1-companion-maintain.timer','p1-companion-watchdog.timer'):
        subprocess.run(['systemctl','disable','--now',timer],capture_output=True,text=True,timeout=30)
    for service in ('p1-companion-maintain.service','p1-companion-watchdog.service'):
        end=time.monotonic()+650
        while subprocess.run(['systemctl','is-active',service],capture_output=True,text=True).stdout.strip() in ('active','activating','deactivating'):
            need(time.monotonic()<end,'maintenance_did_not_quiesce');time.sleep(1)
def login_status(root):
    record=owned(root);c=http.client.HTTPConnection('127.0.0.1',6300,timeout=5)
    try:
        c.request('POST','/get_login_info',body='{}',headers={'Content-Type':'application/json','Authorization':'Bearer '+record['onebot_token']});r=c.getresponse();v=json.loads(r.read(65536))
        logged=r.status==200 and v.get('retcode')==0 and str(v.get('data',{}).get('user_id',''))==record['bot']
        return {'logged_in':logged,'account_matches':logged}
    except (OSError,ValueError,http.client.HTTPException):return {'logged_in':False,'account_matches':False}
    finally:c.close()
def rollback_core(root,emit):
    record=owned(root)
    need(not (root/'astrbot/data/plugin_data/affect').exists(),'rollback_companion_first')
    with integration.deploy_lock(root):
        for name in ('astrbot','snowluma'):verify_container(name,record)
        for name in ('astrbot','snowluma'):
            emit('stop_'+name,'停止本向导创建的 '+name+'，保留账号数据')
            obj=verify_container(name,record)
            if obj is not None:command(['docker','rm','-f',name],60)
        record['status']='stopped_data_preserved';write(marker(root),record)
    return {'stopped':True,'data_preserved':True,'docker_uninstalled':False}
def configure_model(v):
    root=Path(v['root']);owned(root);need(len(v['api_key'])>=8,'api_key_required')
    with integration.deploy_lock(root):
        cfgpath=root/'astrbot/data/cmd_config.json';cfg=read(cfgpath)
        sources=[p for p in cfg.get('provider_sources',[]) if p.get('id')=='deepseek'];need(len(sources)==1,'model_config_changed')
        backup=root/'backups'/('model-settings-'+str(time.time_ns())+'.json');write(backup,cfg)
        sources[0]['key']=[v['api_key']]
        model=next((p for p in cfg.get('provider',[]) if p.get('provider_source_id')=='deepseek' and str(p.get('id','')).startswith('deepseek/')),None);need(model is not None,'model_config_changed')
        known={model['id'],'deepseek-max/deepseek-flash','deepseek-quick/deepseek-flash'}
        cfg['provider']=[p for p in cfg['provider'] if p.get('id') not in known]+models_for(v['model'])
        cfg.setdefault('agent_runner',{}).setdefault('config',{}).setdefault('model',{})['provider_id']='deepseek/'+v['model']
        cfg.setdefault('provider_settings',{})['default_image_caption_provider_id']='deepseek/'+v['model'] if v['model']=='deepseek-flash' else ''
        record=owned(root);verify_container('astrbot',record)
        command(['docker','stop','--time','10','astrbot'],40)
        try:write(cfgpath,cfg);command(['docker','start','astrbot'],60)
        except BaseException:write(cfgpath,read(backup));command(['docker','start','astrbot'],60);raise
    return {'saved':True,'credentials_returned':False,'model_called':False}
def test_model(root):
    owned(root);cfg=read(root/'astrbot/data/cmd_config.json');source=next(p for p in cfg['provider_sources'] if p['id']=='deepseek');model=next(p for p in cfg['provider'] if p.get('provider_source_id')=='deepseek')
    need(source.get('api_base')=='https://api.deepseek.com/v1','model_destination_changed')
    return test_credentials(source['key'][0],model['model'])
def test_credentials(key,model):
    c=http.client.HTTPSConnection('api.deepseek.com',timeout=45)
    try:
        c.request('POST','/v1/chat/completions',body=json.dumps({'model':model,'messages':[{'role':'user','content':'Reply only OK. This is a connection test.'}],'thinking':{'type':'disabled'},'max_tokens':16}),headers={'Content-Type':'application/json','Authorization':'Bearer '+key})
        r=c.getresponse();raw=r.read(65536)
        try:payload=json.loads(raw)
        except ValueError:payload={}
        return {'connected':r.status==200 and isinstance(payload,dict) and isinstance(payload.get('choices'),list) and bool(payload['choices']),'http_status':r.status,'synthetic_test_only':True}
    finally:c.close()
def bilibili_login(root,action):
    need(action in ('login','login_state'),'unsupported_login_action');record=owned(root)
    need(integration.field('p1-leisure','{{index .Config.Labels "com.docker.compose.project.config_files"}}')==str(root/'astrbot/data/companion_services/leisure/compose.yaml'),'leisure_container_layout_changed')
    subject='v1:'+hashlib.sha256(json.dumps(['qq_snowluma',record['bot'],record['owner']],ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    # Fixed local service only; the container reads its token without returning it.
    code="import json,sys,urllib.request;from pathlib import Path;v=json.load(sys.stdin);t=Path('/run/secrets/leisure_token').read_text().strip();q=urllib.request.Request('http://127.0.0.1:8766/action',data=json.dumps(v).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+t});r=urllib.request.urlopen(q,timeout=55);sys.stdout.buffer.write(r.read(1048576))"
    p=subprocess.run(['docker','exec','-i','p1-leisure','python','-c',code],input=json.dumps({'subject':subject,'action':action}),capture_output=True,text=True,timeout=65)
    need(p.returncode==0 and len(p.stdout)<=1048576,'bilibili_login_unavailable');v=json.loads(p.stdout);need(v.get('ok') is True,'bilibili_login_unavailable')
    result={'ok':True,'logged_in':v.get('logged_in') is True,'expires_seconds':150,'challenge':bool(v.get('challenge'))}
    qr=v.get('qr_png')
    if isinstance(qr,str) and len(qr)<800000:
        data=base64.b64decode(qr,validate=True);need(data.startswith(b'\x89PNG\r\n\x1a\n'),'invalid_qrcode');result['qr_png']=qr
    return result
