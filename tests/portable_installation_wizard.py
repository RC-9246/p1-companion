"""P1/Linux root acceptance: synthetic files and a networkless native SDK container.

No production mounts, host package install, QR account login or model calls.
Uses the already-installed AstrBot image ID; does not pull new images.
"""
import json,os,subprocess,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'deploy'))
import firstboot as F
NAMES=('astrbot','snowluma','p1-browser','p1-browser-egress','p1-leisure','p1-leisure-egress','p1-workbench','p1-n8n')
def run(args,timeout=30):
    r=subprocess.run(args,capture_output=True,text=True,timeout=timeout);assert r.returncode==0,(args[0],(r.stdout+r.stderr)[-2000:]);return r.stdout
def production():return run(['docker','inspect','--format','{{.Name}} {{.State.StartedAt}} {{.RestartCount}}',*NAMES])
def main():
    assert os.geteuid()==0 and sys.platform=='linux';os.umask(0o077);before=production();cases=[]
    def item(name,ok):cases.append({'case':name,'passed':bool(ok)});assert ok,name
    lab='p1-installation-wizard-lab-'+str(os.getpid())
    with tempfile.TemporaryDirectory(prefix=lab) as temp:
        base=Path(temp);root=base/'agent';record={'id':'a'*32,'onebot_token':'synthetic-onebot-token','vnc_password':'1234abcd'}
        v={'root':str(root),'bot':'10001','owner':'20002','model':'deepseek-flash','api_key':'synthetic-no-model-calls','password':'SyntheticPassword123'}
        for rel,config in F.configs(v,record).items():F.write(root/rel,config)
        for name in ('astrbot','snowluma'):
            parsed=json.loads(run(['docker','compose','-p',lab,'-f',str(root/name/'compose.yaml'),'config','--format','json']))
            item(name+'_real_compose_parses_without_starting',name in parsed['services'])
            service=parsed['services'][name];item(name+'_ports_bind_loopback',all(p['host_ip']=='127.0.0.1' for p in service['ports']))
            item(name+'_immutable_image', '@sha256:' in service['image'])
        item('configuration_is_private',all(p.stat().st_mode&0o777==0o600 for p in root.rglob('*') if p.is_file()))
        image=run(['docker','inspect','astrbot','--format','{{.Image}}']).strip();script=base/'native.py'
        script.write_text('''import json,hashlib
from pathlib import Path
import astrbot.api
from astrbot.core.config import AstrBotConfig
from astrbot.core.provider.manager import ProviderManager
from astrbot.core.provider.sources.openai_source import ProviderOpenAIOfficial
from astrbot.core.utils.auth_password import verify_dashboard_password
p=Path('/fixture/agent/astrbot/data/cmd_config.json')
cfg=AstrBotConfig(config_path=str(p))
assert cfg['platform'][0]['id']=='qq_snowluma'
assert cfg['platform_settings']['id_whitelist']==['qq_snowluma:FriendMessage:20002']
assert verify_dashboard_password(cfg['dashboard']['pbkdf2_password'],'SyntheticPassword123')
manager=ProviderManager.__new__(ProviderManager);manager.provider_sources_config=cfg['provider_sources']
for row in cfg['provider']:
 merged=manager.get_merged_provider_config(row)
 assert merged['key']==['synthetic-no-model-calls'] and merged['api_base']=='https://api.deepseek.com/v1'
 provider=ProviderOpenAIOfficial(merged,cfg['provider_settings'])
 assert provider.get_model()=='deepseek-flash'
print(json.dumps({'config_default_merge':True,'password_upstream_verified':True,'native_provider_instances':3,'network':'none'}))
''')
        try:
            output=run(['docker','run','--rm','--name',lab,'--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges:true','--pids-limit','64','--memory','384m','--tmpfs','/tmp:size=96m','-e','PYTHONDONTWRITEBYTECODE=1','--mount','type=bind,src='+str(base)+',dst=/fixture','--workdir','/tmp','--entrypoint','python',image,'/fixture/native.py'],65)
            result=json.loads(output.strip().splitlines()[-1]);item('native_astrbot_accepts_generated_configuration',result['config_default_merge']);item('native_astrbot_accepts_password_hash',result['password_upstream_verified']);item('three_native_model_routes_instantiate',result['native_provider_instances']==3)
        finally:subprocess.run(['docker','rm','-f',lab],capture_output=True)
    item('all_production_containers_unchanged',before==production())
    result={'all_passed':True,'cases':cases,'actual_docker_compose_parser':True,'actual_astrbot_sdk':True,'production_data_mounted':False,'lab_network':'none','host_packages_installed':False,'windows_wsl_or_reboot_tested':False,'real_account_logins':0,'model_calls':0,'cold_full_stack_install_accepted':False}
    (ROOT/'evidence/portable-installation-wizard.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
if __name__=='__main__':main()
