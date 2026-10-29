"""Explicit root-only Docker lab: model proposal, sealed tests, real canary and rollback.

No production container, config, database or account is mounted. Takes about 16
minutes. Credentials are an explicit private input; reports stay in the lab.
"""
import argparse,ast,concurrent.futures,importlib.util,json,os,secrets,subprocess,sys,time
from pathlib import Path
R=Path(__file__).resolve().parents[1]
def run(a):
 assert a.run and os.geteuid()==0 and sys.platform.startswith('linux'),'explicit_linux_root_lab_required'
 assert a.lab.is_absolute() and not a.lab.exists() and not any(p.is_symlink() for p in a.lab.parents),'new_private_lab_required'
 assert a.image.startswith('sha256:') and len(a.image)==71,'immutable_image_required'
 a.lab.mkdir(mode=0o700);spec=importlib.util.spec_from_file_location('candidate_acceptance',R/'services/repair_candidates/manager.py');M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)
 source=(R/'release/astrbot_plugin_affect/reply_chunks.py').read_text();faulty=source.replace('return text[:-1]','return text');assert faulty!=source
 old=next(n for n in ast.parse(faulty).body if isinstance(n,ast.FunctionDef) and n.name=='casual_tail')
 original=ast.get_source_segment(faulty,old);request={'source':original,'fault':'An ordinary short Chinese bubble still retains a single terminal Chinese full stop. Fix only this function. Keep its signature and structured content, quotes and URLs unchanged.'}
 private=a.lab/'private';private.mkdir(mode=0o700);os.chown(private,1001,1001)
 payload=private/'request.json';payload.write_text(json.dumps(request));payload.chmod(0o600);os.chown(payload,1001,1001)
 # The request contains synthetic code only, never conversation data or policy.
 program='''import asyncio,json,pathlib,sys
from openai import AsyncOpenAI
async def main():
 s=json.loads(pathlib.Path('/credentials.json').read_text());c=AsyncOpenAI(api_key=s['key'],base_url=s['base_url'],max_retries=0,timeout=80)
 assert c.base_url.host=='api.deepseek.com' and c.base_url.scheme=='https'
 try:
  r=await c.chat.completions.create(model=s['model'],messages=[{'role':'system','content':'Propose a bounded pure Python function repair. Return JSON with exactly replacement (the complete function definition). No imports, filesystem, network, policy, test edits or unrelated content.'},{'role':'user','content':pathlib.Path('/out/request.json').read_text()}],response_format={'type':'json_object'},extra_body={'thinking':{'type':'enabled'}},reasoning_effort='high',max_tokens=8000)
  pathlib.Path('/out/response-metadata.json').write_text(json.dumps({'finish_reason':r.choices[0].finish_reason,'content_chars':len(r.choices[0].message.content or ''),'input_tokens':r.usage.prompt_tokens,'output_tokens':r.usage.completion_tokens}));pathlib.Path('/out/replacement-response.txt').write_text(r.choices[0].message.content or '')
  v=json.loads(r.choices[0].message.content);assert set(v)=={'replacement'};pathlib.Path('/out/proposal.json').write_text(json.dumps(v));pathlib.Path('/out/usage.json').write_text(json.dumps({'model':s['model'],'destination':'api.deepseek.com','calls':1,'input_tokens':r.usage.prompt_tokens,'output_tokens':r.usage.completion_tokens}))
 finally:await c.close()
asyncio.run(main())'''
 p=private/'propose.py';p.write_text(program);p.chmod(0o644)
 def docker(argv,**kw):return subprocess.run(argv,**kw)
 args=['docker','run','--rm','--name','p1-candidate-model-'+secrets.token_hex(4),'--read-only','--memory','256m','--cpus','0.5','--pids-limit','64','--cap-drop','ALL','--security-opt','no-new-privileges:true','--user','1001:1001','--tmpfs','/tmp:size=32m,mode=1777','--mount','type=bind,src='+str(a.credentials)+',dst=/credentials.json,readonly','--mount','type=bind,src='+str(private)+',dst=/out',a.image,'python','/out/propose.py']
 completed=docker(args,capture_output=True,text=True,timeout=100)
 (private/'model-driver.log').write_text(completed.stdout+'\n'+completed.stderr)
 (private/'model-driver-result.json').write_text(json.dumps({'exit_code':completed.returncode,'attempted_calls_upper_bound':1}))
 assert completed.returncode==0,'model_proposal_failed_output_kept_private'
 replacement=json.loads((private/'proposal.json').read_text())['replacement'];proposal={'schema':1,'target':'qq_format','function':'casual_tail','base_sha256':M.sha(faulty.encode()),'replacement':replacement,'fault':'punctuation_regression'}
 checkpoint=a.lab/'checkpoint';(checkpoint/'plugins/astrbot_plugin_affect').mkdir(parents=True);checkpoint.chmod(0o700);(checkpoint/'manifest.json').write_text(json.dumps({'astrbot_plugin_affect/reply_chunks.py':M.sha(faulty.encode())}));(checkpoint/'plugins/astrbot_plugin_affect/reply_chunks.py').write_text(faulty);M.U.CHECKPOINT=checkpoint
 containers=[]
 def case(kind):
  root=a.lab/kind;target=root/M.TARGET;target.parent.mkdir(parents=True);target.write_text(faulty);target.chmod(0o644);data=root/'astrbot/data/plugin_data/affect';data.mkdir(parents=True);os.chown(data,1001,1001);data.chmod(0o700)
  name='p1-candidate-canary-'+kind+'-'+secrets.token_hex(4);containers.append(name)
  health='''import importlib.util,json,pathlib,time
while True:
 s=importlib.util.spec_from_file_location('candidate','/candidate.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
 pathlib.Path('/health/companion_health.json').write_text(json.dumps({'at':time.time(),'phase':'serving','source_imported':True}));time.sleep(3)
'''
  cmd=['docker','run','-d','--name',name,'--network','none','--read-only','--memory','96m','--cpus','0.15','--pids-limit','32','--cap-drop','ALL','--security-opt','no-new-privileges:true','--user','1001:1001','-e','PYTHONDONTWRITEBYTECODE=1','--tmpfs','/tmp:size=8m,mode=1777','--mount','type=bind,src='+str(target.parent)+',dst=/code,readonly','--mount','type=bind,src='+str(data)+',dst=/health',a.image,'python','-c',health.replace('/candidate.py','/code/reply_chunks.py')]
  assert docker(cmd,capture_output=True,timeout=30).returncode==0
  def transport(argv,**kw):
   # The only live container alias is rewritten to this disposable fixture.
   argv=[name if x=='astrbot' else x for x in argv];return docker(argv,**kw)
  m=M.Manager(root,a.lab/('guardian-'+kind),transport);m.seal(R/'services/repair_candidates',True,a.image);state=m.process(proposal,True);assert state['state']=='observing',state.get('error','not_observing')
  if kind=='rollback':assert docker(['docker','stop','--time','1',name],capture_output=True,timeout=15).returncode==0
  began=time.monotonic()
  while time.monotonic()-began<1020:
   state=m.tick(True)
   if state['state'] in ('accepted','rolled_back','blocked','rejected'):break
   time.sleep(15)
  proof=json.loads((m.home/'jobs'/state['job']/'verification.json').read_text());expected='rolled_back' if kind=='rollback' else 'accepted';assert state['state']==expected,state
  assert target.read_text()==(faulty if kind=='rollback' else M.build_candidate(faulty,proposal))
  return {'case':kind,'state':state['state'],'real_elapsed_seconds':round(time.monotonic()-began,1),'baseline_failed':not proof['baseline']['ok'],'candidate_checked':proof['candidate']['checked'],'candidate_passed':proof['candidate']['ok'],'fixture_container':True,'production_modified':False}
 try:
  with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(case,('rollback','accept')))
  report={'schema':1,'results':results,'usage':json.loads((private/'usage.json').read_text()),'actual_clock':True,'production_data_mounted':False,'real_qq_messages':0,'networkless_execution_tests':True}
  (a.lab/'result.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
 finally:
  for name in containers:docker(['docker','rm','-f',name],capture_output=True,timeout=20)
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',action='store_true');p.add_argument('--lab',type=Path,required=True);p.add_argument('--credentials',type=Path,required=True);p.add_argument('--image',required=True);a=p.parse_args();run(a)
if __name__=='__main__':main()
