"""Fresh neutral bootstrap + real nonroot leisure/egress; no network/accounts/prod mounts."""
import json,os,subprocess,sys,tempfile,time
from pathlib import Path
R=Path(__file__).resolve().parents[1];NAMES=('p1-neutral-leisure-install-lab','p1-neutral-leisure-egress-install-lab')
PROD=('astrbot','snowluma','p1-browser','p1-browser-egress','p1-workbench','p1-leisure','p1-leisure-egress','p1-n8n')
def run(args,timeout=30):return subprocess.run(args,capture_output=True,text=True,timeout=timeout)
def production():return run(['docker','inspect',*PROD,'--format','{{.Id}} {{.State.StartedAt}} {{.RestartCount}}']).stdout
def main():
 assert os.geteuid()==0;before=production()
 with tempfile.TemporaryDirectory(prefix='neutral-leisure-install-') as t:
  root=Path(t)/'agent';data=root/'astrbot/data';data.mkdir(parents=True);(data/'cmd_config.json').write_text('{"platform_settings":{"id_whitelist":[]}}')
  p=run([sys.executable,str(R/'scripts/bootstrap.py'),'--root',str(root),'--bot-id','10001','--owner-id','20002','--apply']);assert p.returncode==0,p.stderr[-500:]
  src=data/'companion_services/leisure';affect=data/'plugin_data/affect'
  # Exercise recovery too: protected bytes alone do not preserve nonroot access.
  import importlib.util,shutil
  spec=importlib.util.spec_from_file_location('neutral_recovery',R/'services/maintenance/resilience.py');recovery=importlib.util.module_from_spec(spec);spec.loader.exec_module(recovery)
  cp=Path(t)/'checkpoint';cp.mkdir();files={};hashes={};metadata={}
  for name in ('server.py','policy.py','quota.py','private_api.py','egress.py'):
   key='leisure_'+name[:-3];target=src/name;st=target.stat();shutil.copyfile(target,cp/key);hashes[key]=recovery.digest(target);metadata[key]={'uid':st.st_uid,'gid':st.st_gid,'mode':st.st_mode&0o777};files[key]=target;target.unlink()
  key='internal_leisure_token';target=affect/'leisure_token';st=target.stat();shutil.copyfile(target,cp/key);hashes[key]=recovery.digest(target);metadata[key]={'uid':st.st_uid,'gid':st.st_gid,'mode':st.st_mode&0o777};files[key]=target;target.unlink()
  assert len(recovery.restore_fixed(files,cp,hashes,metadata))==6
  base=['docker','run','-d','--rm','--init','--network','none','--read-only','--user','1001:1001','--cap-drop','ALL','--security-opt','no-new-privileges:true','--pids-limit','80','--memory','256m','--tmpfs','/tmp:size=32m,mode=1777','--workdir','/opt/leisure','-e','PYTHONDONTWRITEBYTECODE=1']
  for name in NAMES:run(['docker','rm','-f',name])
  common=[]
  for name in ('server.py','policy.py','quota.py','private_api.py','egress.py'):common+=['-v',str(src/name)+':/opt/leisure/'+name+':ro']
  p=run(base+['--name',NAMES[0],*common,'-v',str(affect/'leisure_state')+':/state','-v',str(affect/'leisure_policy')+':/policy:ro','-v',str(affect/'leisure_token')+':/run/secrets/leisure_token:ro','p1-companion-neutral-browser:0.20.0','python','server.py']);assert p.returncode==0,p.stderr[-500:]
  p=run(base+['--name',NAMES[1],*common,'p1-companion-neutral-browser:0.20.0','python','egress.py']);assert p.returncode==0,p.stderr[-500:]
  for _ in range(15):
   a=run(['docker','exec',NAMES[0],'python','-c',"import urllib.request,json;x=json.load(urllib.request.urlopen('http://127.0.0.1:8766/health',timeout=2));assert x['ok'] and not x['logged_in'];print('ok')"])
   b=run(['docker','exec',NAMES[1],'python','-c',"import socket;socket.create_connection(('127.0.0.1',8889),2).close();print('ok')"])
   if a.returncode==b.returncode==0:break
   time.sleep(1)
  else:
   for name in NAMES:print(run(['docker','logs',name]).stdout[-600:])
   raise RuntimeError('fresh_nonroot_service_failed')
  report={'fresh_neutral_bootstrap':True,'nonroot_leisure_health':True,'nonroot_egress_listens':True,'installed_code_group_readable':True,'recovered_nonroot_code_and_token_actual_services':True,'real_docker_services':2,'accounts_used':False,'network':'none','production_data_mounted':False,'production_lifecycle_unchanged':before==production()};assert report['production_lifecycle_unchanged'];(R/'evidence/portable-leisure-install.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
if __name__=='__main__':
 try:main()
 finally:
  for name in NAMES:run(['docker','rm','-f',name])
