"""Five sequential native/real-service stability rounds; no real QQ/model sends."""
import importlib.util,json,os,re,subprocess,time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
S=Path(__file__).resolve().parents[1];V='/AstrBot/data/'+S.name;E=S/'evidence/stability-five'
INTEGRATIONS=['agency','qq_actions','learning','extensions','runtime','memoria','groups','emotional_quality','social_continuity','reactions','leisure','novel_group','scope_matrix']
def execute(args,out,timeout=210):
 start=time.monotonic();r=subprocess.run(args,capture_output=True,text=True,timeout=timeout);out.write_text(r.stdout+r.stderr)
 assert r.returncode==0,str(out)+' failed'
 return {'case':out.stem,'passed':True,'seconds':round(time.monotonic()-start,2)}
def docker(args,folder,name):
 return execute(['docker','exec','-e','P1_VALIDATION_ROUND='+V+'/evidence/stability-five/'+folder.name,'-w',V,'astrbot',*args],folder/name)
def states():
 r=subprocess.run(['docker','inspect','astrbot','snowluma','p1-browser','p1-browser-egress','p1-leisure','p1-leisure-egress','p1-n8n','p1-workbench'],capture_output=True,text=True,check=True,timeout=20)
 return {x['Name'].strip('/'):{'started_at':x['State']['StartedAt'],'running':x['State']['Running'],'oom_killed':x['State'].get('OOMKilled'),'restart_count':x['RestartCount']} for x in json.loads(r.stdout)}
def main():
 assert os.geteuid()==0;E.mkdir(parents=True,exist_ok=True);baseline=states();(E/'baseline.json').write_text(json.dumps(baseline,indent=2));results=[]
 spec=importlib.util.spec_from_file_location('runtime',S/'tools/runtime_audit.py');audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)
 for n in range(1,6):
  folder=E/f'round-{n}';folder.mkdir();start=time.monotonic();checks=[]
  checks.append(docker(['python','-m','unittest','discover','-s','tests','-p','test_*.py'],folder,'unit.txt'));match=re.search(r'Ran (\d+) tests',(folder/'unit.txt').read_text());assert match and int(match[1])>=280
  def native_check(name):return docker(['python','tests/integration_'+name+'.py'],folder,'integration-'+name+'.txt')
  with ThreadPoolExecutor(2) as pool:checks.extend(pool.map(native_check,INTEGRATIONS))
  for name,args in [
   ('scope-lifecycle',['python','tests/scope_lifecycle.py','--round',str(n),'--out',V+'/evidence/stability-five/'+folder.name+'/lifecycle.json']),
   ('directory-boundary',['python','tests/directory_boundary.py','--out',V+'/evidence/stability-five/'+folder.name+'/directory.json']),
   ('performance',['python','tests/performance.py']),
   ('real-services',['python','tests/service_probe.py','--round',str(n),'--out',V+'/evidence/stability-five/'+folder.name+'/services.json']),
   ('current-entries',['python','tools/capability_coverage.py'])]:checks.append(docker(args,folder,name+'.txt'))
  runtime=audit.collect();runtime['container_lifecycle']=states();assert runtime['container_lifecycle']==baseline,'unexpected production restart'
  assert all(x['running'] and not x['oom_killed'] for x in baseline.values()) and not runtime['release_drift_files'] and runtime['core_healthcheck_passed']
  assert all(x['integrity']=='ok' for x in runtime['databases'].values());assert runtime['host']['memory_available_mb']>=512
  assert all(x['init_enabled'] and x['zombies']==0 for x in runtime['browser_process_cleanup'].values())
  (folder/'runtime.json').write_text(json.dumps(runtime,indent=2));row={'round':n,'passed':True,'unit_tests':int(match[1]),'checks':checks,'seconds':round(time.monotonic()-start,2),'real_qq_messages':0,'model_requests':0};results.append(row)
  (folder/'result.json').write_text(json.dumps(row,indent=2));(E/'results.json').write_text(json.dumps(results,indent=2));print(json.dumps({'round':n,'passed':True,'seconds':row['seconds'],'checks':len(checks)+1,'memory_available_mb':runtime['host']['memory_available_mb']}),flush=True)
 print('FIVE_ROUNDS_COMPLETE',flush=True)
if __name__=='__main__':main()
