#!/usr/bin/env python3
"""Root guardian for bounded model-proposed pure-function repairs.

Known service/source/DB recovery remains with maintenance. This gate can add new
code only within explicitly sealed, pure formatting functions; all other modules
need a reviewed engineering release. A proposal can never edit its tests, policy,
network, permissions, credentials, ACL or repair journal.
"""
import argparse,ast,contextlib,hashlib,importlib.util,json,math,os,re,secrets,shutil,subprocess,sys,time
from pathlib import Path
S=Path(__file__).resolve().parents[1]/'updater/manager.py'
if not S.is_file():S=Path(__file__).with_name('updater.py')
spec=importlib.util.spec_from_file_location('candidate_updater',S);U=importlib.util.module_from_spec(spec);spec.loader.exec_module(U)
S=Path(__file__).resolve().parents[1]/'maintenance/resilience.py'
if not S.is_file():S=Path(__file__).with_name('resilience.py')
spec=importlib.util.spec_from_file_location('candidate_resilience',S);R=importlib.util.module_from_spec(spec);spec.loader.exec_module(R)
BASE=Path('/var/lib/p1-companion-candidates');TARGET='astrbot/data/plugins/astrbot_plugin_affect/reply_chunks.py'
FUNCTIONS={'casual_tail','qq_reply','split_reply'}
FAULTS={'punctuation_regression','segmentation_regression','formatting_regression'}
BUILTINS={'str','len','isinstance','enumerate','range','min','max','bool','int','float','list','tuple','set','any','all','sorted','sum'}
METHODS={'search','match','fullmatch','findall','split','sub','strip','lstrip','rstrip','startswith','endswith','join','append','extend','replace','count','lower','upper'}
TERMINAL={'accepted','rolled_back','blocked','rejected'}

def sha(raw):return hashlib.sha256(raw).hexdigest()
def canonical(v):return json.dumps(v,sort_keys=True,separators=(',',':')).encode()
def build_candidate(original,proposal):
 U.need(isinstance(proposal,dict) and set(proposal)=={'schema','target','function','base_sha256','replacement','fault'} and proposal['schema']==1,'proposal_shape')
 U.need(proposal['target']=='qq_format' and proposal['function'] in FUNCTIONS and proposal['fault'] in FAULTS,'repair_target_denied')
 U.need(proposal['base_sha256']==sha(original.encode()),'repair_base_changed')
 source=proposal['replacement'];U.need(isinstance(source,str) and len(source)<=10000 and source.count('\n')<100,'repair_size')
 tree=ast.parse(source);U.need(len(tree.body)==1 and isinstance(tree.body[0],ast.FunctionDef),'pure_function_required');fn=tree.body[0]
 U.need(fn.name==proposal['function'] and not fn.decorator_list and not getattr(fn,'type_params',[]),'repair_function_denied')
 old=ast.parse(original);before=next((x for x in old.body if isinstance(x,ast.FunctionDef) and x.name==fn.name),None)
 same_returns=(ast.dump(before.returns) if before is not None and before.returns is not None else None)==(ast.dump(fn.returns) if fn.returns is not None else None)
 U.need(before is not None and ast.dump(before.args)==ast.dump(fn.args) and same_returns,'repair_signature_changed')
 if fn.body and isinstance(fn.body[0],ast.Expr) and isinstance(fn.body[0].value,ast.Constant) and isinstance(fn.body[0].value.value,str):fn.body.pop(0)
 strings={x.value for x in ast.walk(before) if isinstance(x,ast.Constant) and isinstance(x.value,str)}
 locals_={x.id for x in ast.walk(fn) if isinstance(x,ast.Name) and isinstance(x.ctx,ast.Store)}|{x.arg for x in ast.walk(fn.args) if isinstance(x,ast.arg)}
 for node in ast.walk(fn):
  U.need(not isinstance(node,(ast.Import,ast.ImportFrom,ast.ClassDef,ast.Global,ast.Nonlocal,ast.With,ast.AsyncWith,ast.Lambda,ast.Yield,ast.YieldFrom,ast.Await,ast.Delete)),'repair_side_effect_denied')
  if isinstance(node,ast.FunctionDef):U.need(node is fn,'nested_function_denied')
  if isinstance(node,ast.Name):
   U.need(not node.id.startswith('__'),'repair_private_access')
   if isinstance(node.ctx,ast.Load):U.need(node.id in locals_|BUILTINS|FUNCTIONS|{'re','STRUCTURED','URL','FORMAL'},'repair_global_access_denied')
  if isinstance(node,ast.Constant) and isinstance(node.value,str) and node.value not in strings:
   U.need(len(node.value)<=128 and not re.search(r'[\u3400-\u9fff]|https?://|[A-Za-z0-9_]{6,}|[\x00-\x08]',node.value),'repair_new_content_denied')
  if isinstance(node,ast.Attribute):U.need(not node.attr.startswith('_') and not isinstance(node.ctx,(ast.Store,ast.Del)),'repair_private_access')
  if isinstance(node,ast.Call):
   ok=isinstance(node.func,ast.Name) and node.func.id in BUILTINS|FUNCTIONS
   ok=ok or isinstance(node.func,ast.Attribute) and node.func.attr in METHODS
   U.need(ok,'repair_call_denied')
  if isinstance(node,(ast.Subscript,ast.Attribute)):U.need(not isinstance(node.ctx,(ast.Store,ast.Del)),'repair_mutation_denied')
 # Keep the reviewed documentation and discard proposal comments/docstrings.
 # This also prevents a repair artifact from becoming an unrelated content store.
 if before.body and isinstance(before.body[0],ast.Expr) and isinstance(before.body[0].value,ast.Constant) and isinstance(before.body[0].value.value,str):fn.body.insert(0,before.body[0])
 U.need(bool(fn.body),'pure_function_required')
 lines=original.splitlines(keepends=True);replacement=ast.unparse(fn).rstrip()+'\n';candidate=''.join(lines[:before.lineno-1])+replacement+''.join(lines[before.end_lineno:]);ast.parse(candidate)
 return candidate

class Manager:
 def __init__(self,root,home=None,runner=None):
  self.root=U.root_path(str(root));self.home=Path(home) if home else BASE/sha(str(self.root).encode())[:16];self.runner=runner or subprocess.run
  self.target=self.root/TARGET;self.data=self.root/'astrbot/data/plugin_data/affect';self.inbox=self.data/'repair_candidates'
 def record(self,value):
  U.atom(self.home/'state.json',value)
  public={k:value[k] for k in ('schema','state','at','error','fault','production_modified','isolated_verified','watch_until','accepted_at') if k in value}
  try:R.atomic_bytes(self.data/'repair_candidate_status.json',canonical(public),0o600,1001,1001)
  except OSError:pass
  return value
 def status(self):return U.read(self.home/'state.json') if (self.home/'state.json').is_file() else {'state':'unconfigured'}
 def paused(self):
  if (self.data/'maintenance.disabled').exists() or (self.data/'companion.disabled').exists():return True
  p=self.data/'modules_enabled.json'
  if p.exists():
   try:v=U.read(p);return v.get('schema')!=1 or not isinstance(v.get('enabled'),list) or 'maintenance' not in v['enabled']
   except (OSError,ValueError,U.UpdateError):return True
  return False
 def seal(self,kit,auto_pure=False,image=None):
  self.home.mkdir(mode=0o700,parents=True,exist_ok=True);U.protected(self.home)
  with U.exclusive(self.home/'operation.lock'),U.exclusive(U.lifecycle_lock(self.root)):
   U.need(self.status().get('state') not in ('canary','observing','rolling_back'),'repair_observation_pending')
   U.need(self.target.is_file() and not self.target.is_symlink(),'repair_target_missing')
   if auto_pure:
    U.protected(U.CHECKPOINT)
    U.need(U.read(U.CHECKPOINT/'manifest.json').get('astrbot_plugin_affect/reply_chunks.py')==sha(self.target.read_bytes()),'maintenance_checkpoint_generation_required')
   kit=Path(kit);target=self.home/'kit';target.mkdir(mode=0o755,exist_ok=True)
   hashes={}
   for name in ('worker.py','probes.json'):
    p=kit/name;U.need(p.is_file() and not p.is_symlink(),'trusted_probe_missing');raw=p.read_bytes();(target/name).write_bytes(raw);(target/name).chmod(0o444);hashes[name]=sha(raw)
   if image is None:
    p=self.runner(['docker','inspect','astrbot','--format','{{.Image}}'],capture_output=True,text=True,timeout=12);U.need(p.returncode==0,'repair_image_unavailable');image=p.stdout.strip()
   U.need(re.fullmatch('sha256:[0-9a-f]{64}',image),'immutable_image_required')
   U.atom(self.home/'policy.json',{'schema':1,'root':str(self.root),'auto_pure':auto_pure is True,'image':image,'trusted_hashes':hashes,'sealed_at':time.time(),'targets':['qq_format'],'source_hash':sha(self.target.read_bytes())})
   return self.record({'schema':1,'state':'ready','at':time.time(),'auto_pure':auto_pure is True,'scope':'only_sealed_pure_formatting_functions'})
 def policy(self):
  U.protected(self.home);p=U.read(self.home/'policy.json');U.need(p.get('root')==str(self.root) and p.get('schema')==1,'repair_policy_invalid')
  for name,digest in p['trusted_hashes'].items():
   U.need(name in ('worker.py','probes.json') and not (self.home/'kit'/name).is_symlink() and sha((self.home/'kit'/name).read_bytes())==digest,'trusted_probe_changed')
  kit=self.home/'kit';U.need(not kit.is_symlink() and kit.stat().st_uid==os.geteuid(),'trusted_probe_directory_changed');kit.chmod(0o755)
  return p
 def probe(self,module,policy,ident):
  name='p1-candidate-'+ident[:20]
  args=['docker','run','--rm','--name',name,'--network','none','--read-only','--memory','128m','--cpus','0.5','--pids-limit','32','--cap-drop','ALL','--security-opt','no-new-privileges:true','--user','65534:65534','--tmpfs','/tmp:size=8m,mode=1777','--mount','type=bind,src='+str(self.home/'kit')+',dst=/trusted,readonly','--mount','type=bind,src='+str(module)+',dst=/candidate.py,readonly',policy['image'],'python','-I','/trusted/worker.py','/candidate.py','/trusted/probes.json']
  try:
   result=self.runner(args,capture_output=True,text=True,timeout=25);raw=result.stdout
   U.need(len(raw)<16000,'repair_probe_oversize');value=json.loads(raw);U.need(isinstance(value,dict) and value.get('trusted_probe') is True and type(value.get('checked')) is int and value['checked']>=500,'repair_probe_invalid');return {**value,'exit_code':result.returncode}
  except subprocess.TimeoutExpired:
   self.runner(['docker','rm','-f',name],capture_output=True,timeout=10);return {'ok':False,'code':'probe_timeout','checked':0}
 def resource_ok(self):
  if not sys.platform.startswith('linux'):return True
  try:
   values={line.split(':',1)[0]:int(line.split()[1]) for line in Path('/proc/meminfo').read_text().splitlines() if len(line.split())>=2}
   if values['MemAvailable']<450*1024 or shutil.disk_usage(self.home).free<512*1024**2:return False
   for p in list(Path('/sys/class/thermal').glob('thermal_zone*/temp'))[:8]:
    if int(p.read_text())>=78000:return False
   return True
  except (OSError,ValueError,KeyError):return False
 def process(self,proposal,publish=False):
  policy=self.policy();U.need(not self.paused(),'repair_paused');U.need(self.resource_ok(),'repair_resource_pressure')
  before=self.status();U.need(before.get('state')!='observing','repair_observation_pending')
  ledger=self.home/'attempts.json';marker=self.home/'attempts.initialized'
  U.need(not marker.exists() or ledger.exists(),'repair_journal_missing')
  attempts=U.read(ledger) if ledger.exists() else []
  U.need(isinstance(attempts,list) and len(attempts)<=32 and all(type(t) in (int,float) and math.isfinite(t) and t>=0 for t in attempts),'repair_journal_invalid')
  now=time.time();attempts=[t for t in attempts if now-t<86400];U.need(len(attempts)<2 and (not attempts or now-attempts[-1]>=1800),'repair_retry_limit')
  # Reserve durably before even the isolated executable runs.
  attempts.append(now);U.atom(ledger,attempts)
  if not marker.exists():R.atomic_bytes(marker,b'1',0o600)
  raw=self.target.read_text();U.need(sha(raw.encode())==policy['source_hash'],'repair_sealed_source_changed');candidate=build_candidate(raw,proposal);ident=secrets.token_hex(12);job=self.home/'jobs'/ident;job.mkdir(mode=0o755,parents=True)
  old=job/'before.py';new=job/'candidate.py';old.write_text(raw);new.write_text(candidate);old.chmod(0o444);new.chmod(0o444)
  state={'schema':1,'state':'candidate','id':ident,'at':now,'fault':proposal['fault'],'base_sha256':sha(raw.encode()),'candidate_sha256':sha(candidate.encode()),'job':ident,'production_modified':False};self.record(state)
  baseline=self.probe(old,policy,ident+'b');trial=self.probe(new,policy,ident+'c');U.atom(job/'verification.json',{'baseline':baseline,'candidate':trial})
  if not trial.get('ok') or trial.get('exit_code')!=0:return self.record({**state,'state':'rejected','error':'candidate_tests_failed'})
  if baseline.get('ok'):return self.record({**state,'state':'blocked','error':'no_reproduced_baseline_fault','isolated_verified':True})
  state.update(state='isolated_verified',isolated_verified=True);self.record(state)
  if not publish or not policy.get('auto_pure'):return state
  U.need(not self.paused() and sha(self.target.read_bytes())==state['base_sha256'],'repair_permission_or_source_changed')
  U.need(U.read(U.CHECKPOINT/'manifest.json').get('astrbot_plugin_affect/reply_chunks.py')==state['base_sha256'],'checkpoint_generation_changed')
  self.record({**state,'state':'canary','production_modified':True})
  try:
   U.atom(job/'publish-journal.json',{'state':'publishing','before':state['base_sha256'],'candidate':state['candidate_sha256']})
   self.atomic_source(candidate.encode());p=self.runner(['docker','restart','--time','10','astrbot'],capture_output=True,timeout=55);U.need(p.returncode==0,'repair_restart_failed')
   return self.record({**state,'state':'observing','production_modified':True,'published_at':time.time(),'watch_until':time.time()+900})
  except BaseException:
   self.rollback({**state,'production_modified':True});raise
 def atomic_source(self,raw):
  U.need(not self.target.is_symlink(),'symlink_denied');st=self.target.stat()
  R.atomic_bytes(self.target,raw,st.st_mode&0o777,st.st_uid,st.st_gid)
 def rollback(self,state):
  old=self.home/'jobs'/state['job']/'before.py';U.need(old.is_file() and sha(old.read_bytes())==state['base_sha256'],'repair_restore_source_invalid');self.record({**state,'state':'rolling_back'})
  # The automatic source watchdog still holds the old sealed program. Code-only
  # rollback never replaces a conversation database or runtime configuration.
  checkpoint=U.CHECKPOINT;manifest=checkpoint/'manifest.json';rel='astrbot_plugin_affect/reply_chunks.py'
  if manifest.exists():
   v=U.read(manifest)
   U.need(v.get(rel) in (state['base_sha256'],state['candidate_sha256']),'checkpoint_generation_changed')
   if v.get(rel)==state['candidate_sha256']:
    shutil.copyfile(old,checkpoint/'plugins'/rel);(checkpoint/'plugins'/rel).chmod(0o600);v[rel]=state['base_sha256'];U.atom(manifest,v)
  self.atomic_source(old.read_bytes());result=self.runner(['docker','restart','--time','10','astrbot'],capture_output=True,timeout=55)
  return self.record({**state,'state':'rolled_back' if result.returncode==0 else 'blocked','error':'' if result.returncode==0 else 'rollback_restart_failed'})
 def tick(self,publish=False):
  self.home.mkdir(mode=0o700,parents=True,exist_ok=True);U.protected(self.home)
  with U.exclusive(self.home/'operation.lock'),U.exclusive(U.lifecycle_lock(self.root)):
   state=self.status()
   if self.paused():
    if state.get('state') in ('canary','observing','rolling_back'):return self.rollback(state)
    return {'state':'paused','writes':False}
   if state.get('state') in ('canary','rolling_back'):return self.rollback(state)
   if state.get('state')=='observing':
    health=self.data/'companion_health.json'
    try:h=U.read(health)
    except (OSError,ValueError,U.UpdateError):h={}
    try:
     result=self.runner(['docker','inspect','astrbot','--format','{{json .State}}'],capture_output=True,text=True,timeout=12)
     service=json.loads(result.stdout) if result.returncode==0 else {}
    except (ValueError,OSError,subprocess.SubprocessError):service={}
    healthy=service.get('Running') is True and not service.get('OOMKilled') and h.get('phase') in ('ready','serving') and type(h.get('at')) in (int,float) and state['published_at']<=h['at']<=time.time() and time.time()-h['at']<300 and sha(self.target.read_bytes())==state['candidate_sha256']
    if not healthy and time.time()-state['published_at']>=120:return self.rollback(state)
    if healthy and time.time()>=state['watch_until']:
     # Preserve the accepted source in the existing sealed checkpoint as well.
     checkpoint=U.CHECKPOINT;manifest=checkpoint/'manifest.json';rel='astrbot_plugin_affect/reply_chunks.py'
     U.need(manifest.is_file(),'maintenance_checkpoint_required');v=U.read(manifest);U.need(v.get(rel) in (state['base_sha256'],state['candidate_sha256']),'checkpoint_generation_changed')
     target=checkpoint/'plugins'/rel;U.need(not target.is_symlink(),'symlink_denied');shutil.copyfile(self.target,target);target.chmod(0o600);v[rel]=state['candidate_sha256'];U.atom(manifest,v)
     policy=self.policy();policy['source_hash']=state['candidate_sha256'];U.atom(self.home/'policy.json',policy)
     return self.record({**state,'state':'accepted','accepted_at':time.time()})
    return state
   self.policy()
   if not self.inbox.exists():return state
   U.need(not self.inbox.is_symlink(),'proposal_path_untrusted')
   for p in sorted(self.inbox.glob('*.json'))[:8]:
    if p.is_symlink() or not p.is_file() or p.stat().st_size>16000:continue
    digest=sha(p.read_bytes());receipt=self.home/'received'/digest
    if receipt.exists():continue
    receipt.parent.mkdir(mode=0o700,exist_ok=True);receipt.write_text(str(time.time()));receipt.chmod(0o600)
    try:return self.process(U.read(p),publish)
    except (ValueError,SyntaxError,U.UpdateError) as exc:return self.record({'schema':1,'state':'rejected','at':time.time(),'error':str(exc) if isinstance(exc,U.UpdateError) else 'proposal_invalid'})
   return state

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',default='/srv/p1-agent');p.add_argument('action',choices=('seal','tick','status'));p.add_argument('--kit',type=Path,default=Path(__file__).parent);p.add_argument('--auto-pure',action='store_true');p.add_argument('--publish',action='store_true');a=p.parse_args()
 U.need(os.geteuid()==0 and sys.platform.startswith('linux'),'linux_root_required');m=Manager(a.root)
 try:out=m.seal(a.kit,a.auto_pure) if a.action=='seal' else m.tick(a.publish) if a.action=='tick' else m.status();print(json.dumps(out));return 0
 except Exception as exc:print(json.dumps({'ok':False,'error':str(exc) if isinstance(exc,U.UpdateError) else type(exc).__name__}));return 1
if __name__=='__main__':raise SystemExit(main())
