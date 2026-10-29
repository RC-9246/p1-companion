"""Opt-in synthetic evaluation through the installed AstrBot request/response hooks.

Each case runs in a separate process and scratch directory. Only the approved
DeepSeek endpoint receives synthetic conversations and the supplied character
card. QQ receipts are deliberately fake; no account, browser or real chat is
mounted. Only memory/knowledge tools run, in scratch storage; account/browser
tool loops, actual QQ delivery and human judgements are outside this experiment.
Raw character prompts, outputs and credentials stay private.
"""
import argparse,asyncio,hashlib,json,os,sys,tempfile,time
from pathlib import Path
from types import SimpleNamespace as N

def args():
 p=argparse.ArgumentParser(description=__doc__)
 for name in ('source','cases','credentials','persona','output'):p.add_argument('--'+name,type=Path,required=True)
 p.add_argument('--group-persona',type=Path);p.add_argument('--run',action='store_true')
 p.add_argument('--label',default='candidate')
 p.add_argument('--max-calls',type=int,default=400);p.add_argument('--workers',type=int,choices=(1,2),default=2)
 p.add_argument('--case-index',type=int,default=-1);return p.parse_args()

async def worker(a,case):
 # Set the scratch data path before importing any plugin: their DATA constant is
 # fixed at import time. Different cases never share a process or state ledger.
 with tempfile.TemporaryDirectory(prefix='synthetic-native-') as tmp:
  data=Path(tmp)/'data/plugin_data/affect';data.mkdir(parents=True);os.environ['P1_COMPANION_DATA']=str(data)
  # Test helpers may rewrite sys.path. Keep protocol fixtures local so the
  # baseline cannot silently import the candidate's plugin modules.
  sys.path.insert(0,str(a.source/'release'))
  from astrbot.core.provider.entities import ProviderRequest,LLMResponse
  from astrbot.core.agent.tool import ToolSet,FunctionTool
  from astrbot.core.message.components import Plain,At
  from astrbot.core.message.message_event_result import MessageChain,MessageEventResult
  from astrbot.core.platform.message_type import MessageType
  from astrbot_plugin_affect.main import AffectPlugin,atomic_json
  from astrbot_plugin_affect.identity import make_identity_key
  from astrbot_plugin_affect.thinking import MAX_PROVIDER,FAST_PROVIDER
  from astrbot_plugin_p1_group_memory.main import P1GroupMemory
  from astrbot_plugin_p1_group_affect.main import P1GroupAffect
  from astrbot_plugin_p1_stickers.main import P1Stickers
  from astrbot_plugin_p1_qq_style.main import P1QQStyle
  from astrbot_plugin_p1_learning.main import P1Learning
  from astrbot_plugin_p1_reflection.main import P1Reflection
  from astrbot_plugin_memoria.main import MemoriaPlugin
  from astrbot_plugin_memoria.memoria.db import MemoriaDB
  from openai import AsyncOpenAI
  loaded={name:Path(mod.__file__).resolve() for name,mod in sys.modules.items() if name.startswith('astrbot_plugin_') and getattr(mod,'__file__',None)}
  if any(not path.is_relative_to((a.source/'release').resolve()) for path in loaded.values()):raise ValueError('mixed_evaluation_sources')
  import sqlite3
  def init_db(path):
   with sqlite3.connect(path) as db:
    db.execute('CREATE TABLE affect_state(identity_key TEXT PRIMARY KEY,mood REAL NOT NULL DEFAULT 0,energy REAL NOT NULL DEFAULT .5,familiarity REAL NOT NULL DEFAULT 0,interaction_count INTEGER NOT NULL DEFAULT 0,last_interaction_at INTEGER NOT NULL DEFAULT 0,updated_at INTEGER NOT NULL DEFAULT 0)')
    db.execute('CREATE TABLE affect_processed_events(event_key TEXT PRIMARY KEY,identity_key TEXT NOT NULL,processed_at INTEGER NOT NULL)')
  class BaseEvent:
   def __init__(self,sender,group,text,mid):
    self.sender=sender;self.group=group;self.extra={};self.unified_msg_origin='qq_snowluma:'+('GroupMessage:'+group if group else 'FriendMessage:'+sender);self.message_obj=N(message_id=mid,message_str=text,timestamp=time.time())
   def get_platform_id(self):return 'qq_snowluma'
   def get_self_id(self):return '10001'
   def get_sender_id(self):return self.sender
   def get_group_id(self):return self.group
   def is_private_chat(self):return not self.group
   def get_sender_name(self):return '合成群友'
   def get_extra(self,k,d=None):return self.extra.get(k,d)
   def set_extra(self,k,v):self.extra[k]=v
  secret=json.loads(a.credentials.read_text());real=AsyncOpenAI(api_key=secret['key'],base_url=secret['base_url'],timeout=50,max_retries=0)
  if real.base_url.host!='api.deepseek.com' or real.base_url.scheme!='https':raise ValueError('unapproved_evaluation_destination')
  stats={'calls':0,'completed':0,'errors':0,'input_tokens':0,'output_tokens':0,'reasoning_tokens':0,'kinds':{}}
  init_db(data/'affect.db');owner=make_identity_key('qq_snowluma','10001','20002')
  cfg={'platform_settings':{'enable_id_white_list':True,'id_whitelist':['qq_snowluma:FriendMessage:20002','qq_snowluma:FriendMessage:20003']},
       'provider':[{'id':x,'enable':True,'model':secret['model'],'custom_extra_body':{'reasoning_effort':'max'}} for x in (MAX_PROVIDER,FAST_PROVIDER)]}
  atomic_json(data.parents[1]/'cmd_config.json',cfg);atomic_json(data/'allowed_identities.json',{'version':1,'allowed_identities':[owner]})
  atomic_json(data/'groups.json',{'version':1,'groups':[{'bot':'10001','group':'30003'}]})
  delays=[];sends=[];requests=[];started=time.monotonic()
  async def invoke(kw,options):
   if stats['calls']>=a.max_calls or stats['output_tokens']>=60000:raise RuntimeError('synthetic_case_budget')
   kw=dict(kw);kw['model']=secret['model'];system=kw['messages'][0]['content']
   kind='classifier' if '对话语境分类器' in system else ('review' if system.startswith('核对一条即将发送') else ('route' if '只判断当前QQ群消息' in system else 'generation'))
   stats['calls']+=1;stats['kinds'][kind]=stats['kinds'].get(kind,0)+1
   before=time.monotonic()
   try:
    result=await real.with_options(**options).chat.completions.create(**kw)
    usage=result.usage;detail=getattr(usage,'completion_tokens_details',None)
    stats['completed']+=1;stats['input_tokens']+=int(getattr(usage,'prompt_tokens',0) or 0);stats['output_tokens']+=int(getattr(usage,'completion_tokens',0) or 0);stats['reasoning_tokens']+=int(getattr(detail,'reasoning_tokens',0) or 0)
    requests.append({'kind':kind,'seconds':round(time.monotonic()-before,3),'input_characters':sum(len(str(x.get('content',''))) for x in kw['messages']),
                     'thinking':kw.get('extra_body',{}).get('thinking'),'effort':kw.get('reasoning_effort'),'max_tokens':kw.get('max_tokens'),'timeout':options.get('timeout')})
    return result
   except BaseException as exc:
    stats['errors']+=1;requests.append({'kind':kind,'error':type(exc).__name__,'seconds':round(time.monotonic()-before,3)});raise
  class Model:
   base_url=N(scheme='https',host='api.deepseek.com')
   def __init__(self,options=None):self.options=options or {'timeout':50,'max_retries':0};self.chat=N(completions=self)
   def with_options(self,**kw):return Model(dict(self.options,**kw))
   async def create(self,**kw):return await invoke(kw,self.options)
  model=Model()
  class Wire:
   async def call_action(self,action,**kw):
    if action=='get_login_info':return {'user_id':10001,'nickname':'伙伴'}
    if action=='get_friend_list':return [{'user_id':x,'nickname':'合成好友'} for x in (20002,20003)]
    if action=='get_group_list':return [{'group_id':30003,'group_name':'合成群'}]
    if action in ('get_friend_msg_history','get_group_msg_history'):return {'messages':[]}
    raise AssertionError('unrequested_fixture_action')
   async def send_group_msg(self,**kw):sends.append(kw);return {'message_id':80000+len(sends)}
   async def send_private_msg(self,**kw):sends.append(kw);return {'message_id':80000+len(sends)}
  wire=Wire()
  class Context:
   def __init__(self):self._event_queue=asyncio.Queue()
   def get_config(self,*x):return cfg
   def get_platform_inst(self,*x):return N(get_client=lambda:wire)
   @property
   def provider_manager(self):return self
   async def get_current_chat_provider_id(self,*x):return 'normal'
   async def get_provider_by_id(self,*x):return N(client=model,get_model=lambda:secret['model'])
  ctx=Context();p=AffectPlugin(ctx)
  async def pause(seconds):delays.append(seconds)
  p.reply_pause=pause
  class Event(BaseEvent):
   sequence=0
   def __init__(self,text,who='20002',group='',address='direct'):
    Event.sequence+=1;super().__init__(who,group,text,str(Event.sequence));self.session_id=group or who;self.session=N(message_type='group' if group else 'private');self.result=None;self.stopped=False;self._has_send_oper=False
    self.parts=[Plain(text)]
    if group and address in ('direct','other'):self.parts.insert(0,At(qq='10001' if address=='direct' else '29999'))
   def get_message_type(self):return MessageType.GROUP_MESSAGE if self.group else MessageType.FRIEND_MESSAGE
   def get_platform_name(self):return 'aiocqhttp'
   def get_messages(self):return self.parts
   def stop_event(self):self.stopped=True
   def continue_event(self):self.stopped=False
   def is_admin(self):return False
   def get_result(self):return self.result
   async def send(self,message):raise AssertionError('raw_transport_not_permitted')
  gm=P1GroupMemory(ctx);ga=P1GroupAffect(ctx);style=P1QQStyle(ctx);learning=P1Learning(ctx);stickers=P1Stickers(ctx);reflection=P1Reflection(ctx)
  memory=MemoriaPlugin(ctx,{'follow_up_tracking_enabled':False})
  turns=[];history=list(case.get('history',[]));error=None
  try:
   await p.initialize();await gm.initialize();await ga.initialize();await style.initialize();await learning.initialize();await stickers.initialize();await reflection.initialize();await p.qq.refresh(True)
   # Async summarisation/reflection has its own acceptance suites. This trial
   # measures foreground hooks, so no uncounted background model calls run.
   learning.schedule=lambda *x,**kw:None;gm.schedule=lambda *x,**kw:None
   p.persona=a.persona.read_text()
   if a.group_persona:
    import astrbot_plugin_affect.group_runtime as group_runtime
    group_runtime.PUBLIC_PERSONA=a.group_persona.read_text()
   memory.db=await MemoriaDB.create(str(Path(tmp)/'memoria'));memory._p1_session_file=Path(tmp)/'authorized_sessions.json';ctx._p1_memoria=memory
   group='30003' if case.get('scope')=='group' else '';who='20003' if case.get('scope')=='friend' else '20002'
   seed_event=Event('',who,group)
   scope=p.agency.scope(seed_event);p.agency.store.ensure(scope)
   for i,item in enumerate(case.get('activities',[])):
    p.agency.experience.activity(scope,'synthetic:activity:'+str(i),item['topic'],item['note'],item['coverage'],item['sources'],0,question=item.get('question',''),opinion=item.get('opinion',''))
   if group:
    # Bind synthetic public history to explicit speakers, never private history.
    await gm.hydrate(seed_event);meta=gm.store.meta(scope)
    from astrbot_plugin_p1_group_memory.store import event_key
    from astrbot_plugin_affect.group_chat import member
    for i,row in enumerate(history):
     role=row['role'];gm.store.add(scope,event_key(scope,'synthetic:history:'+str(i)),'saki' if role=='assistant' else member(seed_event),'伙伴' if role=='assistant' else '合成群友',row['content'],time.time()-30+i,role='saki' if role=='assistant' else 'member',source='synthetic-fixture',expected_epoch=meta['epoch'])
   # Real function-call protocol for the bounded conversation-only subset. Other
   # account/browser tools are excluded, rather than advertised without schemas.
   schemas={
    'search_memory':{'description':'搜索当前用户或会话的长期记忆；只查当前范围。','parameters':{'type':'object','properties':{'user_id':{'type':'string'},'session_id':{'type':'string'},'query':{'type':'string'},'limit':{'type':'integer','minimum':1,'maximum':8}},'required':['user_id','session_id','query']}},
    'add_memory_candidate':{'description':'把明确稳定偏好存成当前用户候选记忆；不等于确认。','parameters':{'type':'object','properties':{'user_id':{'type':'string'},'content':{'type':'string'},'session_id':{'type':'string'},'memory_type':{'type':'string'},'confidence':{'type':'number','minimum':0,'maximum':1}},'required':['user_id','content']}},
    'p1_knowledge':{'description':'查询已有角色或能力的来源摘要。','parameters':{'type':'object','properties':{'query':{'type':'string'}},'required':['query']}}}
   handlers={'search_memory':memory.tool_search_memory,'add_memory_candidate':memory.tool_add_memory_candidate,'p1_knowledge':p.knowledge}
   for index,item in enumerate(case['turns']):
    item={'text':item} if isinstance(item,str) else item;text=item['text'];event=Event(text,item.get('sender',who),group,item.get('address','direct'));begin=time.monotonic()
    await p.throttle_inbound_qq(event)
    if group and not await p.groups.route(event):
     turns.append({'input':text,'output':'','admitted':False,'appraisal':{},'seconds':round(time.monotonic()-begin,3)});continue
    req=ProviderRequest(prompt=text,system_prompt='SYNTHETIC_PRIVATE_SENTINEL' if group else '',contexts=history[-12:] if not group else [],func_tool=ToolSet([FunctionTool(name=n,**schema) for n,schema in schemas.items()]))
    await memory.on_llm_request(event,req);await p.inject_state_into_llm(event,req);await stickers.describe(event,req);await reflection.inject(event,req);await learning.private_prompt(event,req);await p.restrict_companion_tools(event,req);await p.group_llm_boundary(event,req);await style.instruct(event,req);await p.ground_media_request(event,req);await p.trace_model_start(event,req)
    pending=event.get_extra('_p1_companion_pending') or event.get_extra('_p1_group_affect_pending') or {};assessment=pending.get('appraisal',{})
    payload=req.prompt+'\n'+'\n'.join(getattr(part,'text','') for part in req.extra_user_content_parts)
    messages=[{'role':'system','content':req.system_prompt},*req.contexts,{'role':'user','content':payload}]
    for row in messages:
     if row.get('role')=='assistant':row.setdefault('reasoning_content','')
    exposed={tool.name for tool in req.func_tool.tools};api_tools=[{'type':'function','function':{'name':n,**schema}} for n,schema in schemas.items() if n in exposed]
    route=event.get_extra('selected_provider') or 'normal';kw={'model':secret['model'],'messages':messages,'temperature':.45,'max_tokens':4096,
            'extra_body':{'thinking':{'type':'disabled' if route==FAST_PROVIDER else 'enabled'}},**({'reasoning_effort':'max' if route==MAX_PROVIDER else 'high'} if route!=FAST_PROVIDER else {})}
    if api_tools:kw['tools']=api_tools
    tool_steps=[]
    while True:
     generated=await model.create(**kw);message=generated.choices[0].message
     if not message.tool_calls:break
     if len(tool_steps)+len(message.tool_calls)>2:raise ValueError('synthetic_tool_loop_limit')
     # DeepSeek requires this private protocol field throughout a thinking/tool
     # conversation. It is kept in memory only, never written into reports.
     messages.append({k:v for k,v in message.model_dump(exclude_none=True).items() if k in ('role','content','tool_calls','reasoning_content')})
     for call in message.tool_calls:
      name=call.function.name
      if name not in exposed or name not in handlers:raise ValueError('unexposed_tool')
      parameters=json.loads(call.function.arguments)
      if not isinstance(parameters,dict):raise ValueError('tool_arguments')
      import inspect
      inspect.signature(handlers[name]).bind(event,**parameters)
      result=await handlers[name](event,**parameters);result=result if isinstance(result,str) else json.dumps(result,ensure_ascii=False)
      messages.append({'role':'tool','tool_call_id':call.id,'content':result})
      parsed=json.loads(result);ok=parsed.get('ok') if isinstance(parsed,dict) else None
      tool_steps.append({'name':name,'state':'returned','ok':ok,'result_status':'candidate_only_not_confirmed' if name=='add_memory_candidate' and ok else 'read_result' if name!='add_memory_candidate' else 'denied','storage':'synthetic isolated ledger'})
    draft=message.content or ''
    if not draft.strip():raise ValueError('empty_generation')
    response=LLMResponse(role='assistant',completion_text=draft)
    await stickers.select(event,response);await ga.response(event,response);await p.mark_response(event,response);await p.ground_media_response(event,response)
    final=response.completion_text;event.result=MessageEventResult(chain=[Plain(final)])
    await event.send(MessageChain([Plain(final)]));await p.commit_after_delivery(event);await learning.delivered(event)
    if group:await p.groups.finish(event)
    else:history.extend([{'role':'user','content':text},{'role':'assistant','content':final,'reasoning_content':getattr(message,'reasoning_content','') or ''}])
    evidence=event.get_extra('_p1_continuity_evidence') or [];review=event.get_extra('_p1_review_evidence',{})
    turns.append({'input':text,'appraisal':assessment,'draft':draft,'output':final,'admitted':True,'receipt':'synthetic-only',
                  'prompt_characters':sum(len(str(x.get('content',''))) for x in messages),'system_characters':len(req.system_prompt),
                  'tools_exposed':[x.name for x in req.func_tool.tools],'continuity_evidence':evidence,'review_evidence':review,
                  'agency_epoch':event.get_extra('_p1_agency_epoch'),'model_route':route,'tool_steps':tool_steps,'reviewed':bool(event.get_extra('_p1_reply_review_done')),
                  'seconds':round(time.monotonic()-begin,3)})
  except BaseException as exc:
   error=type(exc).__name__
   import traceback
   error_frames=[{'file':Path(x.filename).name,'line':x.lineno,'function':x.name} for x in traceback.extract_tb(exc.__traceback__)]
  finally:
   await reflection.terminate();await learning.terminate();await gm.terminate();await ga.terminate();await style.terminate();await p.terminate();await memory.terminate();await real.close()
  loaded={name:Path(mod.__file__).resolve() for name,mod in sys.modules.items() if name.startswith('astrbot_plugin_') and getattr(mod,'__file__',None)}
  if any(not path.is_relative_to((a.source/'release').resolve()) for path in loaded.values()):raise ValueError('mixed_evaluation_sources')
  report={'case':case['id'],'family':case.get('family','social'),'scope':case.get('scope','private'),'rubric':case['rubric'],'history':case.get('history',[]),
          'loaded_modules_sha256':{name:hashlib.sha256(path.read_bytes()).hexdigest() for name,path in loaded.items()},
          'synthetic_activity_fixtures':case.get('activities',[]),'turns':turns,'completed':not error and len(turns)==len(case['turns']),'error':error,'error_frames':error_frames if error else [],'calls':stats,'requests':requests,'seconds':round(time.monotonic()-started,3),
          'fake_transport_sends':len(sends),'all_delays_2_to_5':all(2<=x<=5 for x in delays),'real_qq_messages':0,'production_database_modified':False}
  a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2));a.output.chmod(0o600)
  if error:raise SystemExit('synthetic_case_failed:'+error)

async def run(a,cases):
 if len(cases)*len(max((c['turns'] for c in cases),key=len))*6>a.max_calls:raise SystemExit('max_calls_must_cover_worst_case_budget')
 started=time.monotonic();a.output.parent.mkdir(parents=True,exist_ok=True);semaphore=asyncio.Semaphore(a.workers);results=[]
 with tempfile.TemporaryDirectory(prefix='native-evaluation-workers-') as tmp:
  async def one(index,case):
   async with semaphore:
    result=Path(tmp)/(str(index)+'.json');log=Path(tmp)/(str(index)+'.log')
    argv=[sys.executable,str(Path(__file__).resolve()),'--run','--source',str(a.source),'--cases',str(a.cases),'--credentials',str(a.credentials),'--persona',str(a.persona),'--output',str(result),'--case-index',str(index),'--max-calls',str(6*len(case['turns']))]
    if a.group_persona:argv+=['--group-persona',str(a.group_persona)]
    import multiprocessing
    if 'fork' in multiprocessing.get_all_start_methods():
     # SDK imports are warmed once in the parent. Only SDK modules are inherited;
     # all plugins/data are imported after the child sets its own scratch DATA.
     child=argparse.Namespace(**vars(a));child.output=result;child.max_calls=6*len(case['turns'])
     proc=multiprocessing.get_context('fork').Process(target=fork_worker,args=(child,case,log))
     proc.start();deadline=time.monotonic()+180*len(case['turns'])+60
     while proc.is_alive() and time.monotonic()<deadline:await asyncio.sleep(.5)
     if proc.is_alive():proc.kill()
     proc.join();returncode=proc.exitcode;proc.close()
    else:
     with log.open('w') as f:
      proc=await asyncio.create_subprocess_exec(*argv,stdout=f,stderr=f)
      try:await asyncio.wait_for(proc.wait(),180*len(case['turns'])+60)
      except TimeoutError:proc.kill();await proc.wait()
     returncode=proc.returncode
    row=json.loads(result.read_text()) if result.exists() else {'case':case['id'],'completed':False,'error':'worker_exit_without_result','turns':[],'calls':{}}
    row['worker_exit_code']=returncode;results.append(row);save()
  def save():
   aggregate={k:sum(r['calls'].get(k,0) for r in results) for k in ('calls','completed','errors','input_tokens','output_tokens','reasoning_tokens')}
   report={'schema':1,'variant':a.label,'evaluation':'native_astrbot_foreground_hooks','evaluator_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'model_destination':'api.deepseek.com','case_file_sha256':hashlib.sha256(a.cases.read_bytes()).hexdigest(),
           'persona_sha256':hashlib.sha256(a.persona.read_bytes()).hexdigest(),'source_files':{str(p.relative_to(a.source)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((a.source/'release').rglob('*.py'))},
           'expected_cases':len(cases),'processed_cases':len(results),'completed_cases':sum(bool(r.get('completed')) for r in results),'calls':aggregate,'cases':sorted(results,key=lambda x:x['case']),
           'wall_seconds':round(time.monotonic()-started,2),'real_qq_messages':0,'production_database_modified':False,'background_reflection':'excluded; separate SDK acceptance suites','tool_protocol':'native JSON function calls; only isolated memory search/candidate writes and knowledge lookup; max two calls per turn',
           'raw_outputs_private':True,'finished':len(results)==len(cases)}
   target=a.output.with_suffix('.next');target.write_text(json.dumps(report,ensure_ascii=False,indent=2));target.chmod(0o600);os.replace(target,a.output)
  await asyncio.gather(*(one(i,c) for i,c in enumerate(cases)));save()

def fork_worker(a,case,log):
 import contextlib
 with log.open('w') as f,contextlib.redirect_stdout(f),contextlib.redirect_stderr(f):asyncio.run(worker(a,case))

def warm_sdk():
 # No plugin imports, credentials, account access or network calls here.
 import importlib
 for name in ('astrbot.api.star','astrbot.api.event','astrbot.core.provider.entities','astrbot.core.agent.tool',
              'astrbot.core.message.components','astrbot.core.agent.message','astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event',
              'astrbot.core.pipeline.waking_check.stage','astrbot.core.pipeline.whitelist_check.stage'):
  importlib.import_module(name)
 if any(x.startswith('astrbot_plugin_') for x in sys.modules):raise RuntimeError('plugin_imported_before_worker_scope')

if __name__=='__main__':
 a=args()
 if not a.run:raise SystemExit('No calls made; --run requires prior human authorization for the model destination and data.')
 cases=json.loads(a.cases.read_text())
 if a.case_index>=0:asyncio.run(worker(a,cases[a.case_index]))
 else:warm_sdk();asyncio.run(run(a,cases))
