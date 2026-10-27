"""Opt-in disposable Docker acceptance; never mounts production account state."""
import argparse,hashlib,importlib.util,json,os,secrets,shutil,subprocess,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def run(args,**kw):return subprocess.run(args,capture_output=True,text=True,timeout=kw.pop('timeout',50),**kw)
def inspect(name):return json.loads(run(['docker','inspect',name]).stdout)[0]
def main():
 p=argparse.ArgumentParser();p.add_argument('--run',action='store_true');a=p.parse_args()
 if not a.run:print(json.dumps({'dry_run':True,'needs_disposable_docker':True,'production_mounts':False}));return
 assert os.geteuid()==0
 baseline={n:(inspect(n)['State']['StartedAt'],inspect(n)['RestartCount']) for n in ('astrbot','snowluma','p1-browser','p1-leisure')}
 image=inspect('p1-leisure')['Image'];name='p1-guard-accept-'+secrets.token_hex(5);label=secrets.token_hex(8)
 code='''import sys,asyncio,json,time
from pathlib import Path
sys.path.insert(0,'/opt/leisure')
import server as S
Path('/state/ready').touch()
end=time.monotonic()+45
while not Path('/state/go').exists():
 if time.monotonic()>end:raise RuntimeError('acceptance_gate_timeout')
 time.sleep(.1)
def children():
 n=0
 for p in Path('/proc').iterdir():
  try:
   if p.name.isdigit() and (p/'comm').read_text().strip()=='chromium':n+=1
  except OSError:pass
 return n
async def test():
 await S.B.ensure()
 await S.B.ctx.add_cookies([{'name':'synthetic','value':'acceptance-only','domain':'example.invalid','path':'/'}])
 before=children();assert before>0
 Path('/state/resource-lease.json').write_text(json.dumps({'version':1,'boot':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'until':time.monotonic()+90,'mode':'pressure'}))
 result=await S.resource_cleanup();assert result['closed'] and S.B.ctx is None
 saved=json.loads(Path('/state/browser.json').read_text());assert any(c['name']=='synthetic' and c['value']=='acceptance-only' for c in saved['cookies'])
 for _ in range(30):
  if children()==0:break
  await asyncio.sleep(.1)
 assert children()==0
 print(json.dumps({'real_idle_chromium_closed':True,'chromium_before':before,'chromium_after':0,'synthetic_cookie_preserved':True,'real_accounts_used':False}))
asyncio.run(test())
'''
 with tempfile.TemporaryDirectory(prefix='p1-guard-accept-') as t:
  base=Path(t);base.chmod(0o755);state=base/'state';state.mkdir(mode=0o700);os.chown(state,1001,1001);policy=base/'policy';policy.mkdir();(policy/'identities.json').write_text(json.dumps({'allowed_identities':['v1:'+'a'*64]}));secret=base/'token';secret.write_text('synthetic-test-token');script=base/'accept.py';script.write_text(code)
  args=['docker','run','-d','--name',name,'--label','io.p1.guard.acceptance='+label,'--init','--user','1001:1001','--network','none','--memory','384m','--memory-swap','512m','--pids-limit','160','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges:true','--security-opt','seccomp='+str(ROOT/'services/leisure/seccomp_profile.json'),'--tmpfs','/tmp:size=96m,mode=1777']
  for source,target,ro in ((ROOT/'services/leisure','/opt/leisure',True),(state,'/state',False),(policy,'/policy',True),(secret,'/run/secrets/leisure_token',True),(script,'/accept.py',True)):
   args+=['--mount','type=bind,src='+str(source)+',dst='+target+(',readonly' if ro else '')]
  args += ['--tmpfs','/home/companion:size=16m,uid=1001,gid=1001',image,'python','/accept.py'];cid=run(args).stdout.strip();assert len(cid)==64
  try:
   for _ in range(60):
    if (state/'ready').exists():break
    if not inspect(cid)['State']['Running']:raise RuntimeError('isolated_container_start_failed')
    time.sleep(.2)
   else:raise RuntimeError('isolated_ready_timeout')
   original=inspect(cid);h=original['HostConfig'];saved={'id':cid,'image':image,'limits':{k:h.get(k) for k in ('Memory','MemoryReservation','MemorySwap','PidsLimit')}}
   assert run(['docker','update','--memory','512m','--memory-swap','768m','--pids-limit','180',cid]).returncode==0
   spec=importlib.util.spec_from_file_location('guard_install',ROOT/'scripts/install_resource_guard.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);assert m.restore_limit(saved)
   after=inspect(cid)['HostConfig'];assert all(after.get(k)==v for k,v in saved['limits'].items())
   (state/'go').touch();result=run(['docker','wait',cid],timeout=60);output=run(['docker','logs',cid]);logs=output.stdout
   assert result.stdout.strip()=='0',(logs+output.stderr)[-3000:];report=json.loads(logs.strip().splitlines()[-1]);report.update(disposable_memory_and_pid_limits_restored=True,network='none',production_mounts=False,production_core_start_state_unchanged=all((inspect(n)['State']['StartedAt'],inspect(n)['RestartCount'])==v for n,v in baseline.items()))
   print(json.dumps(report))
  finally:
   obj=inspect(cid);assert obj['Id']==cid and obj['Config']['Labels'].get('io.p1.guard.acceptance')==label;run(['docker','rm','-f',cid])
if __name__=='__main__':main()
