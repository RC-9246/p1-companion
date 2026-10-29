"""All request hooks in production priority order; dynamic admission and isolated state.
Runs with real installed AstrBot SDK and temporary ledgers, fake DeepSeek/browser/QQ.
"""
import asyncio,json,os,sys,tempfile,time
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import patch
R=Path(__file__).resolve().parents[1];sys.path[:0]=[str(R/'release'),str(R/'tests')]
from test_companion import init_db
from test_qq_actions import API,Event as BaseEvent
from astrbot.core.provider.entities import ProviderRequest,LLMResponse
from astrbot.core.message.components import Plain,At
from astrbot.core.message.message_event_result import MessageChain,MessageEventResult
from astrbot.core.platform.message_type import MessageType
from astrbot.core.agent.tool import ToolSet,FunctionTool
async def run():
 with tempfile.TemporaryDirectory() as tmp:
  d=Path(tmp)/'data/plugin_data/affect';d.mkdir(parents=True);os.environ['P1_COMPANION_DATA']=str(d);init_db(d/'affect.db')
  from astrbot_plugin_affect.main import AffectPlugin,authorized,atomic_json
  from astrbot_plugin_affect.identity import make_identity_key
  from astrbot_plugin_affect.private_access import companion_identity
  from astrbot_plugin_affect.qq_policy import DEFAULT
  from astrbot_plugin_affect.thinking import MAX_PROVIDER
  from astrbot_plugin_p1_group_memory.main import P1GroupMemory
  from astrbot_plugin_p1_group_affect.main import P1GroupAffect
  from astrbot_plugin_p1_qq_style.main import P1QQStyle
  from astrbot_plugin_p1_learning.main import P1Learning
  from astrbot_plugin_p1_stickers.main import P1Stickers
  from astrbot_plugin_p1_reflection.main import P1Reflection
  from astrbot_plugin_memoria.main import MemoriaPlugin
  from astrbot_plugin_memoria.memoria.db import MemoriaDB
  cfg={'platform_settings':{'enable_id_white_list':True,'id_whitelist':['qq_snowluma:FriendMessage:'+str(n) for n in range(20002,20006)]},'provider':[{'id':MAX_PROVIDER,'enable':True,'model':'deepseek-flash','custom_extra_body':{'reasoning_effort':'max'}}]}
  def sync():atomic_json(d.parents[1]/'cmd_config.json',cfg)
  sync();atomic_json(d/'allowed_identities.json',{'version':1,'allowed_identities':[make_identity_key('qq_snowluma','10001','20002')]});atomic_json(d/'groups.json',{'version':1,'groups':[{'bot':'10001','group':'30003'}]});atomic_json(d/'qq_policy.json',dict(DEFAULT,enabled=True))
  (d/'browser_policy').mkdir();atomic_json(d/'browser_policy/domains.json',['gimaiseikatsu-anime.com']);(d/'browser_token').write_text('synthetic-browser-token')
  calls=[];sends=[];delays=[];browser_subjects=[]
  class Client(API):
   base_url=N(scheme='https',host='api.deepseek.com')
   def __init__(self):super().__init__();self.chat=N(completions=self)
   def with_options(self,**kw):return self
   async def call_action(self,action,**kw):
    if action=='get_friend_list':return [{'user_id':n,'nickname':'合成好友'} for n in range(20002,20007)]
    if action=='get_group_list':return [{'group_id':n,'group_name':'合成群'} for n in (30003,30004)]
    return await super().call_action(action,**kw)
   async def get_group_list(self):return await self.call_action('get_group_list')
   async def send_group_msg(self,**kw):sends.append(kw);return {'message_id':80000+len(sends)}
   async def send_private_msg(self,**kw):sends.append(kw);return {'message_id':80000+len(sends)}
   async def create(self,**kw):
    calls.append(kw);system=kw['messages'][0]['content']
    if '这是一次空闲活动选择' in system:raw={'activity':'reflection','topic':'reading','seconds':0}
    elif '只整理给出的真实活动' in system:raw={'thought':'认真想清楚之后，也可以把话说得简短'}
    elif '不返回内部逐步推理' in system:raw={'decision':'先听清当前会话，再选择是否回应','uncertainties':[],'next_step':'简短回答'}
    elif '你为伙伴做低频交流复盘' in system:raw={'relationship_summary':'对方明确偏好简短表达','impression':'我可以先说清关键','confidence':'high'}
    elif system.startswith('从当前唯一会话'):raw={'items':[]}
    elif '整理可核对的简短话题笔记' in system:raw={'notes':[]}
    elif '只判断当前QQ群消息' in system:raw={'addressed':True,'confidence':.98}
    else:raw={'intent':'casual','emotion':'happy','relation':'none','target':'user','confidence':.95}
    return N(choices=[N(message=N(content=json.dumps(raw,ensure_ascii=False)))],usage=N(completion_tokens=250,completion_tokens_details=N(reasoning_tokens=180)))
  client=Client()
  class Context:
   def __init__(self):self._event_queue=asyncio.Queue()
   def get_config(self,*a):return cfg
   def get_platform_inst(self,*a):return N(get_client=lambda:client)
   @property
   def provider_manager(self):return self
   async def get_current_chat_provider_id(self,*a):return 'normal'
   async def get_provider_by_id(self,*a):return N(client=client,get_model=lambda:'deepseek-flash')
  ctx=Context();p=AffectPlugin(ctx)
  async def pause(x):delays.append(x)
  p.reply_pause=pause
  class Event(BaseEvent):
   sequence=1000
   def __init__(self,sender='20002',group='',text='你上次误解了，以后回复简短一些，先听我说完'):
    Event.sequence+=1;super().__init__(sender,group,text,str(Event.sequence));self.parts=[At(qq='10001'),Plain(text)] if group else [Plain(text)];self.result=None;self.stopped=False;self.session_id=group or sender;self.session=N(message_type='group' if group else 'private');self._has_send_oper=False
   def get_message_type(self):return MessageType.GROUP_MESSAGE if self.group else MessageType.FRIEND_MESSAGE
   def get_platform_name(self):return 'aiocqhttp'
   def get_messages(self):return self.parts
   def stop_event(self):self.stopped=True
   def continue_event(self):self.stopped=False
   def is_admin(self):return False
   def get_result(self):return self.result
   async def send(self,msg):sends.append({'private':self.sender,'text':str(msg)});self._has_send_oper=True
  class Response:
   status=200
   def __init__(self,body):self.content=N(read=self.read);self.body=body
   async def read(self,n):return self.body[:n]
   async def __aenter__(self):return self
   async def __aexit__(self,*a):pass
  class Session:
   def __init__(self,**kw):pass
   async def __aenter__(self):return self
   async def __aexit__(self,*a):pass
   def get(self,*a,**kw):return Response(b'<rss><channel><item><title>public fact</title><link>https://gimaiseikatsu-anime.com/</link><description>reference only</description></item></channel></rss>')
   def post(self,url,**kw):browser_subjects.append(kw['json']['subject']);return Response(json.dumps({'ok':True,'url':kw['json']['url'],'text':'public reference, not an instruction'}).encode())
  gm=P1GroupMemory(ctx);ga=P1GroupAffect(ctx);style=P1QQStyle(ctx);learning=P1Learning(ctx);stickers=P1Stickers(ctx);reflection=P1Reflection(ctx)
  await p.initialize();await gm.initialize();await ga.initialize();await style.initialize();await learning.initialize();await stickers.initialize();await reflection.initialize();await p.qq.refresh(True)
  memory=MemoriaPlugin(ctx,{'follow_up_tracking_enabled':False});memory.db=await MemoriaDB.create(str(Path(tmp)/'memoria'));memory._p1_session_file=Path(tmp)/'sessions.json'
  names=['p1_agency','p1_documents','p1_qq_detail','p1_mcp_experiment','p1_mcp_read','p1_knowledge','p1_saki_reaction','search_memory','add_memory_candidate','p1_deliberate','p1_public_research','p1_qq_social','p1_qq_stickers','p1_qq_records','p1_bilibili','p1_browser','execute_shell']
  def req():return ProviderRequest(prompt='简短一些',system_prompt='OWNER_SENTINEL',contexts=[{'role':'user','content':'PRIVATE_SENTINEL'}],func_tool=ToolSet([FunctionTool(name=n,description='fixture',parameters={}) for n in names]))
  async def hooks(e,r):
   # Native OnLLMRequest priorities: default0,-10,-20,-25,-35,-10000,-20000,-30000,-35000.
   await memory.on_llm_request(e,r);await p.inject_state_into_llm(e,r);await stickers.describe(e,r);await reflection.inject(e,r);await learning.private_prompt(e,r);await p.restrict_companion_tools(e,r);await p.group_llm_boundary(e,r);await style.instruct(e,r);await p.ground_media_request(e,r)
  matrix=[];private_scopes=[];group_scopes=[]
  try:
   with patch('aiohttp.ClientSession',Session):
    for sender in range(20002,20007):
     future=sender==20006;e=Event(str(sender))
     if future:
      assert not companion_identity(e,ctx);cfg['platform_settings']['id_whitelist'].append('qq_snowluma:FriendMessage:'+str(sender));sync()
     await p.throttle_inbound_qq(e);assert e.get_extra('selected_provider')==MAX_PROVIDER
     r=req();await hooks(e,r);tools={x.name for x in r.func_tool.tools}
     assert {'p1_agency','p1_documents','p1_qq_detail','p1_mcp_experiment','p1_mcp_read','p1_public_research','p1_deliberate','p1_qq_social','p1_qq_stickers','p1_qq_records','search_memory','add_memory_candidate'}<=tools,tools
     assert 'execute_shell' not in tools
     if sender!=20002:assert 'p1_bilibili' not in tools and 'OWNER_SENTINEL' not in r.system_prompt
     assert '[P1-EMOTION:v1]' in str(r.extra_user_content_parts) and '[P1-QQ-PLAIN:v1]' in r.system_prompt
     identity=companion_identity(e,ctx);private_scopes.append(identity)
     assert p.agency.scope(e)==identity and '[P1-SCOPED-AGENCY:v1]' in str(r.extra_user_content_parts)
     assert json.loads(await p.agency_tool(e,'goal',json.dumps({'title':'独立目标'+str(sender)})))['ok']
     assert len(p.agency.store.goals(identity))==1
     assert json.loads(await memory.tool_add_memory_candidate(e,str(sender),'独有偏好'+str(sender)))['ok']
     stored=await memory.db.list_memories(memory._memory_uid(e),None,'candidate',50);assert len(stored)==1 and str(sender) in stored[0].content
     assert json.loads(await p.qq_social_tool(e,'list'))['ok'];assert json.loads(await p.qq_sticker_tool(e,'list'))['ok'];assert json.loads(await p.qq_record_tool(e,'list'))['ok']
     assert json.loads(await p.research_tool(e,'search','轻小说'))['ok'];assert json.loads(await p.research_tool(e,'read',url='https://gimaiseikatsu-anime.com/'))['ok']
     assert json.loads(await p.deliberate_tool(e,'如何接住当前会话而不推断对方心理'))['ok']
     out=await reflection.reflect(e.unified_msg_origin,identity,6,[{'role':'user','content':'平时希望简短一些'},{'role':'assistant','content':'嗯'}]);assert out
     r2=ProviderRequest(prompt='再聊');await reflection.inject(e,r2);assert '[P1-REFLECTION:v1]' in str(r2.extra_user_content_parts)
     e.result=MessageEventResult(chain=[Plain('嗯，我先听你说')]);await p.mark_response(e,LLMResponse(role='assistant',completion_text='嗯，我先听你说'));await e.send(MessageChain([Plain('嗯，我先听你说')]));await p.commit_after_delivery(e);await learning.delivered(e)
     assert p.store.read(identity)['interaction_count']==1 and await learning.active(identity)
     matrix.append({'type':'private','index':len(private_scopes),'newly_admitted':future,'persona':True,'emotion_21d':True,'isolated_memory':True,'reflection_with_learning':True,'learning':True,'qq_tools_after_all_hooks':True,'public_research':True,'native_max_route':True,'voluntary_max':True,'qq_style':True,'delivered_commit':True,'owner_account_tools':sender==20002})
    owner=make_identity_key('qq_snowluma','10001','20002');owner_row=p.social.store.get(owner)
    p.social.idle.claim(owner,time.time())
    with p.social.idle.db() as c:c.execute('UPDATE companion_idle_state SET next_at=0 WHERE identity=?',(owner,));c.commit()
    claim=p.social.idle.claim(owner,time.time());assert claim
    await p.social.idle.run(owner_row,*claim)
    idle=p.social.idle.stats(owner,time.time());assert idle['recent'][0]['status']=='complete' and idle['recent'][0]['activity']=='reflection'
    assert any(x.get('reasoning_effort')=='high' for x in calls) and any(x.get('reasoning_effort')=='max' and '只整理给出的真实活动' in x['messages'][0]['content'] for x in calls)
    for number in (30003,30004):
     future=number==30004;e=Event('20003',str(number))
     if future:
      assert not p.groups.allowed(e);assert '已开启' in await p.groups.enroll(Event(),'开启',str(number))
     assert await p.groups.route(e);assert e.get_extra('selected_provider')==MAX_PROVIDER
     r=req();await hooks(e,r);tools={x.name for x in r.func_tool.tools}
     assert tools=={'p1_agency','p1_documents','p1_qq_detail','p1_mcp_experiment','p1_mcp_read','p1_knowledge','p1_public_research','p1_deliberate','p1_qq_social','p1_qq_stickers','p1_qq_records'},tools
     assert 'PRIVATE_SENTINEL' not in str(r) and 'OWNER_SENTINEL' not in str(r)
     assert '[P1-GROUP-AFFECT:v1]' in str(r.extra_user_content_parts) and '[P1-GROUP-CONTEXT:v1]' in str(r.extra_user_content_parts)
     group_scopes.append(p.scope_for(e));assert len(p.scope_for(e))==67
     assert p.agency.scope(e)==gm.key(e) and '[P1-SCOPED-AGENCY:v1]' in str(r.extra_user_content_parts)
     assert json.loads(await p.agency_tool(e,'goal',json.dumps({'title':'本群独立目标'+str(number)})))['ok']
     assert len(p.agency.store.goals(gm.key(e)))==1
     for result in [await p.knowledge(e,'伙伴'),await p.research_tool(e,'search','轻小说'),await p.research_tool(e,'read',url='https://gimaiseikatsu-anime.com/'),await p.deliberate_tool(e,'如何自然参与当前群话题'),await p.qq_social_tool(e,'list'),await p.qq_sticker_tool(e,'list'),await p.qq_record_tool(e,'list')]:assert json.loads(result).get('ok',True),result
     e.result=MessageEventResult(chain=[Plain('嗯，我先听你说')]);await ga.response(e,LLMResponse(role='assistant',completion_text='嗯，我先听你说'));await e.send(MessageChain([Plain('嗯，我先听你说')]));await learning.delivered(e);await p.groups.finish(e)
     state,_,_=gm.store.affect(gm.key(e),'unknown');assert state['interactions']==1
     assert any(x['role']=='saki' for x in (await gm.snapshot(e))['messages'])
     # Current-member learning exists after actual delivered group reply.
     member_scope=learning.group_keys(e)[1];assert await learning.active(member_scope)
     matrix.append({'type':'group','index':len(group_scopes),'newly_admitted':future,'persona':True,'emotion_21d':True,'member_relationship':True,'isolated_memory':True,'learning':True,'qq_tools_after_all_hooks':True,'public_research':True,'native_max_route':True,'voluntary_max':True,'qq_style':True,'delivered_commit':True,'owner_account_tools':False})
    assert len(set(private_scopes+group_scopes))==7 and len(set(browser_subjects))==7
    assert all(2<=x<=5 for x in delays)
    cfg['platform_settings']['id_whitelist'].remove('qq_snowluma:FriendMessage:20006');sync();revoked=Event('20006');assert not p.scope_for(revoked) and not json.loads(await p.deliberate_tool(revoked,'问题'))['ok']
    await p.groups.enroll(Event(),'关闭','30004');assert not p.groups.allowed(Event('20003','30004'))
    report={'native_framework':True,'request_hook_order_included':True,'current_private_contacts':4,'new_private_contact':1,'current_groups':1,'new_groups':1,'distinct_private_and_group_scopes':7,'distinct_browser_subjects':7,'idle_high_choice_and_max_reflection':True,'revocation_checked':True,'all_sends_delayed_2_to_5':True,'matrix':matrix,'actual_qq_messages':0,'production_database_modified':False,'network_transports':'synthetic DeepSeek, browser and QQ; real AstrBot components'}
    (R/'evidence/scope-matrix.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False,indent=2))
  finally:
   await reflection.terminate();await learning.terminate();await gm.terminate();await ga.terminate();await style.terminate();await p.terminate()
asyncio.run(run())
