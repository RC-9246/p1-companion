"""Run newly built neutral images with disposable tokens and no production data mounts."""
import json,os,subprocess,tempfile,time
from pathlib import Path
R=Path(__file__).resolve().parents[1]
NAMES=('p1-neutral-browser-lab','p1-neutral-worker-lab')
def run(args,timeout=30):return subprocess.run(args,capture_output=True,text=True,timeout=timeout)
def request(name,path,payload=None):
 code="import urllib.request,json;v="+repr(payload)+";u='http://127.0.0.1:"+('8765' if name==NAMES[0] else '8767')+"/"+path+"';r=urllib.request.Request(u,data=json.dumps(v).encode() if v is not None else None,headers={'Content-Type':'application/json','Authorization':'Bearer synthetic-neutral-lab-token'});x=json.load(urllib.request.urlopen(r,timeout=45));print(json.dumps(x))"
 result=run(['docker','exec',name,'python','-c',code],55)
 if result.returncode:raise RuntimeError('isolated_http_failed:'+result.stderr[-600:])
 return json.loads(result.stdout)
def main():
 assert os.geteuid()==0;before=run(['docker','inspect','astrbot','snowluma','p1-browser','p1-workbench','p1-leisure','--format','{{.Id}} {{.State.StartedAt}} {{.RestartCount}}']).stdout
 with tempfile.TemporaryDirectory(prefix='neutral-image-acceptance-') as tmp:
  folder=Path(tmp);token=folder/'token';token.write_text('synthetic-neutral-lab-token');token.chmod(0o600);os.chown(token,1001,1001);policy=folder/'policy';policy.mkdir(mode=0o755);(policy/'domains.json').write_text('["docs.python.org"]');(policy/'domains.json').chmod(0o644)
  for name in NAMES:run(['docker','rm','-f',name])
  base=['docker','run','-d','--rm','--init','--read-only','--user','1001:1001','--cap-drop','ALL','--security-opt','no-new-privileges:true','--tmpfs','/tmp:size=192m,mode=1777']
  args=base+['--name',NAMES[0],'--network','p1-companion-control','--pids-limit','160','--memory','700m','--shm-size','128m','--tmpfs','/home/companion:size=16m,uid=1001,gid=1001','--security-opt','seccomp='+str(R/'browser/seccomp_profile.json'),'-v',str(token)+':/run/secrets/browser_token:ro','-v',str(policy)+':/policy:ro','p1-companion-neutral-browser:0.20.0']
  r=run(args);assert r.returncode==0,r.stderr[-600:]
  r=run(base+['--name',NAMES[1],'--network','none','--pids-limit','40','--memory','512m','-v',str(token)+':/run/secrets/workbench_token:ro','p1-companion-neutral-workbench:0.20.0']);assert r.returncode==0,r.stderr[-600:]
  for name in NAMES:
   for _ in range(15):
    try:assert request(name,'health')['ok'];break
    except Exception:time.sleep(1)
   else:raise RuntimeError('isolated_service_not_ready')
  page=request(NAMES[0],'browse',{'subject':'v1:'+'f'*64,'action':'open','url':'https://docs.python.org/3/'});assert page.get('ok') and 'Python' in page.get('text','')
  import base64
  decoded=request(NAMES[1],'decode',{'name':'synthetic.txt','data':base64.b64encode('中性复现解析'.encode('gb18030')).decode()});assert decoded.get('ok') and '中性复现' in decoded['text']
  experiment=request(NAMES[1],'experiment',{'code':'import math\nprint(math.sqrt(81))'});assert experiment.get('ok') and '9.0' in experiment['output']
  report={'neutral_public_images_started':2,'fresh_browser_real_public_page':True,'fresh_worker_gb18030_decode':True,'fresh_worker_math_experiment':True,'production_data_mounted':False,'private_accounts_used':False,'production_container_lifecycle_unchanged':before==run(['docker','inspect','astrbot','snowluma','p1-browser','p1-workbench','p1-leisure','--format','{{.Id}} {{.State.StartedAt}} {{.RestartCount}}']).stdout,'qq_messages':0,'real_model_calls':0};assert report['production_container_lifecycle_unchanged'];(R/'evidence/portable-image-runtime.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
if __name__=='__main__':
 try:main()
 finally:
  for name in NAMES:run(['docker','rm','-f',name])
