"""Real AstrBot classes with fake OneBot/model, no actual QQ or production DB writes."""
import asyncio,json,os,sys,tempfile,time
from pathlib import Path
from types import SimpleNamespace as NS
R=Path(__file__).resolve().parents[1];sys.path[:0]=[str(R/'release'),str(R/'tests')]
from test_companion import init_db
from astrbot.core.message.components import Plain,At,Reply
from astrbot.core.message.message_event_result import MessageChain,MessageEventResult
from astrbot.core.platform.message_type import MessageType
from astrbot.core.provider.entities import ProviderRequest,LLMResponse
from astrbot.core.agent.tool import ToolSet,FunctionTool

async def run():
 with tempfile.TemporaryDirectory() as tmp:
  d=Path(tmp)/'affect';d.mkdir();os.environ['P1_COMPANION_DATA']=str(d);init_db(d/'affect.db')
  from astrbot_plugin_affect.identity import make_identity_key
  from astrbot_plugin_affect.main import AffectPlugin,authorized,atomic_json
  from astrbot_plugin_affect.private_access import companion_identity
  from astrbot_plugin_p1_group_memory.main import P1GroupMemory
  from astrbot_plugin_p1_group_affect.main import P1GroupAffect
  from astrbot_plugin_p1_qq_style.main import P1QQStyle
  from astrbot_plugin_memoria.main import MemoriaPlugin
  from astrbot_plugin_memoria.memoria.db import MemoriaDB
  owner=make_identity_key('qq_snowluma','10001','20002');atomic_json(d/'allowed_identities.json',{'version':1,'allowed_identities':[owner]})
  atomic_json(d/'groups.json',{'version':1,'groups':[{'bot':'10001','group':g} for g in ('30003','30004')]})
  config={'platform_settings':{'enable_id_white_list':True,'id_whitelist':['qq_snowluma:FriendMessage:'+str(n) for n in range(20002,20006)]}}
  requests=[];sends=[];delays=[]
  class Client:
   base_url=NS(host='api.deepseek.com',scheme='https')
   def __init__(self):self.chat=NS(completions=self)
   def with_options(self,**kw):return self
   async def create(self,**kw):
    requests.append(kw);text=kw['messages'][-1]['content'];system=kw['messages'][0]['content']
    if '只判断当前QQ群消息' in system:raw={'addressed':True,'confidence':.95}
    elif '整理可核对的简短话题笔记' in system:raw={'notes':[]}
    else:raw=dict(intent='casual',emotion='sad' if '难过' in text else 'happy',relation='none',target='user',confidence=.95)
    return NS(choices=[NS(message=NS(content=json.dumps(raw)))])
   async def send_group_msg(self,**kw):sends.append(kw);return {'message_id':90000+len(sends)}
  client=Client()
  class Context:
   def __init__(self):self._event_queue=asyncio.Queue()
   def get_config(self,*a):return config
   def get_platform_inst(self,*a):return NS(get_client=lambda:client)
   @property
   def provider_manager(self):return self
   async def get_current_chat_provider_id(self,*a):return 'fake'
   async def get_provider_by_id(self,*a):return NS(client=client,get_model=lambda:'fake')
  ctx=Context();p=AffectPlugin(ctx)
  async def pause(n):delays.append(n)
  p.reply_pause=pause
  class Event:
   seq=0
   def __init__(self,text='你好',sender='20002',group='',parts=None):
    Event.seq+=1;self.sender=sender;self.group=group;self.parts=parts or [Plain(text)];self.message_obj=NS(message_str=text,message_id=str(Event.seq),timestamp=time.time());self.extra={};self.stopped=False;self.session_id=group or sender;self.unified_msg_origin='qq_snowluma:'+('GroupMessage:'+group if group else 'FriendMessage:'+sender);self._has_send_oper=False;self.result=None
   def get_platform_id(self):return 'qq_snowluma'
   def get_platform_name(self):return 'aiocqhttp'
   def get_self_id(self):return '10001'
   def get_sender_id(self):return self.sender
   def get_sender_name(self):return '群友'+self.sender[-1]
   def get_group_id(self):return self.group
   def get_messages(self):return self.parts
   def get_message_type(self):return MessageType.GROUP_MESSAGE if self.group else MessageType.FRIEND_MESSAGE
   def is_private_chat(self):return not self.group
   def get_extra(self,k,default=None):return self.extra.get(k,default)
   def set_extra(self,k,v):self.extra[k]=v
   def stop_event(self):self.stopped=True
   def continue_event(self):self.stopped=False
   def get_result(self):return self.result
   def is_admin(self):return False
   async def send(self,msg):sends.append({'private_synthetic':self.sender,'message':str(msg)})
  gm=P1GroupMemory(ctx);ga=P1GroupAffect(ctx);style=P1QQStyle(ctx)
  await p.initialize();await gm.initialize();await ga.initialize();await style.initialize()
  m=MemoriaPlugin(ctx,{});m.db=await MemoriaDB.create(str(Path(tmp)/'memory'))
  try:
   # All four existing contacts and a fifth added at runtime; distinct stored identities.
   for sender in ('20002','20003','20004','20005','20006'):
    if sender=='20006':config['platform_settings']['id_whitelist'].append('qq_snowluma:FriendMessage:'+sender)
    e=Event(sender=sender);identity=companion_identity(e,ctx);assert identity
    tools=ToolSet([FunctionTool(name=n,description='fixture',parameters={},handler=None) for n in ('p1_bilibili','p1_browser','p1_saki_reaction','search_memory','execute_shell')])
    req=ProviderRequest(prompt='你好',system_prompt='PRIVATE_DEFAULT_PERSONA_SENTINEL',func_tool=tools);await p.inject_state_into_llm(e,req);await p.restrict_companion_tools(e,req)
    assert '[P1-EMOTION:v1]' in str(req.extra_user_content_parts)
    if sender!='20002':
     assert 'PRIVATE_DEFAULT_PERSONA_SENTINEL' not in req.system_prompt
     assert not authorized(e);assert {t.name for t in req.func_tool.tools}=={'p1_saki_reaction','search_memory'}
     assert 'generic_familiar_v1' not in str(req)
     assert json.loads(await p.bilibili(e,'recommend'))['error']=='forbidden'
    await p.mark_response(e,LLMResponse(role='assistant',completion_text='嗯，你好'))
    await e.send(MessageChain([Plain('嗯，你好')]))
    await p.commit_after_delivery(e);assert p.store.read(identity)['interaction_count']==1
    good=json.loads(await m.tool_add_memory_candidate(e,sender,'独有偏好'+sender));assert good['ok']
   identities=[companion_identity(Event(sender=str(n)),ctx) for n in range(20002,20007)]
   assert len(set(identities))==5
   assert len({m._memory_uid(Event(sender=str(n))) for n in range(20002,20007)})==5
   e=Event(sender='20003');assert json.loads(await m.tool_search_memory(e,'20004','','独有'))['error']=='forbidden'
   rows=await m.db.list_memories(m._memory_uid(e),None,'candidate',50);assert len(rows)==1 and '20003' in rows[0].content
   friend=Event('我平时喜欢简短一点',sender='20003');other=Event('另一个人的偏好',sender='20004')
   for ev in (friend,other):
    ident=companion_identity(ev,ctx)
    from astrbot_plugin_affect.main import event_key
    await m.db.record_private_turn(ident,event_key(ev),ev.message_obj.message_str)
   first=await m.db.private_transcript(companion_identity(friend,ctx));assert '简短' in str(first) and '另一个人' not in str(first)
   friend.extra['_p1_delivered_commit']=True;friend.result=MessageEventResult(chain=[Plain('嗯，我会说短一点')]);await m.remember_private_delivery(friend)
   assert 'assistant delivered' in str(await m.db.private_transcript(companion_identity(friend,ctx)))
   config['platform_settings']['id_whitelist'].remove('qq_snowluma:FriendMessage:20006');assert companion_identity(Event(sender='20006'),ctx) is None
   # Revoking a contact while the required outbound delay runs cancels delivery and growth.
   ev=Event(sender='20005');req=ProviderRequest(prompt='你好');await p.inject_state_into_llm(ev,req);await p.mark_response(ev,LLMResponse(role='assistant',completion_text='嗯'))
   original_count=p.store.read(companion_identity(ev,ctx))['interaction_count'];before_sends=len(sends)
   async def revoke(n):
    delays.append(n);config['platform_settings']['id_whitelist'].remove('qq_snowluma:FriendMessage:20005')
   p.reply_pause=revoke;await ev.send(MessageChain([Plain('不应送达')]))
   await p.commit_after_delivery(ev);assert len(sends)==before_sends and ev.get_extra('_p1_send_cancelled')
   assert p.store.read(make_identity_key('qq_snowluma','10001','20005'))['interaction_count']==original_count
   config['platform_settings']['id_whitelist'].append('qq_snowluma:FriendMessage:20005');p.reply_pause=pause
   # Same member, different group history and affect. Keep unrelated private sentinels out.
   for group,text,reply in [('30003','伙伴，今天有点难过','嗯，你慢慢说'),('30004','伙伴，这件事真开心','嗯，我也替你高兴')]:
    e=Event(text,group=group,parts=[At(qq='10001'),Plain(text)])
    assert await p.groups.route(e)
    req=ProviderRequest(prompt='PRIVATE_SENTINEL',system_prompt='PRIVATE_SENTINEL',contexts=[{'role':'user','content':'PRIVATE_SENTINEL'}],extra_user_content_parts=['PRIVATE_SENTINEL'],func_tool=ToolSet([FunctionTool(name='p1_bilibili',description='x',parameters={},handler=None)]))
    await p.groups.prepare(e,req);await style.instruct(e,req)
    assert 'PRIVATE_SENTINEL' not in str(req) and not req.contexts and not req.func_tool.tools
    assert '[P1-GROUP-CONTEXT:v1]' in str(req.extra_user_content_parts) and '[P1-GROUP-AFFECT:v1]' in str(req.extra_user_content_parts)
    await ga.response(e,LLMResponse(role='assistant',completion_text=reply))
    await ga.delivered(e,p.groups)
    assert gm.store.affect(gm.key(e),e.get_extra('_p1_group_scene')['current']['speaker'])[0]['interactions']==0
    await e.send(MessageChain([Plain(reply)]));await p.groups.finish(e)
    scene=await gm.snapshot(e);assert any(x['role']=='saki' for x in scene['messages'])
   from astrbot_plugin_p1_group_memory.store import scope_key
   a=gm.store.affect(scope_key('10001','30003'),'x')[0];b=gm.store.affect(scope_key('10001','30004'),'x')[0]
   assert a['concern']>b['concern'];assert a['interactions']==b['interactions']==1
   assert '难过' not in str(gm.store.history(scope_key('10001','30004')))
   # Unaddressed fragments still enter group history; a busy direct follow-up is requeued once.
   e=Event('伙伴，帮我看看',group='30003',parts=[At(qq='10001'),Plain('帮我看看')]);assert await p.groups.route(e)
   f=Event('是这一句哪里不通顺',group='30003',parts=[At(qq='10001'),Plain('是这一句哪里不通顺')]);assert not await p.groups.route(f)
   await p.groups.prepare(e,ProviderRequest(prompt='x'))
   assert '这一句' in str(await gm.snapshot(e))
   await p.groups.finish(e);assert (await ctx._event_queue.get()) is f and not f.stopped
   assert await p.groups.route(f);await p.groups.finish(f)
   # Reviewed group sticker goes through the real native serializer, never a model URL.
   ev=Event('伙伴，今天真开心',group='30004',parts=[At(qq='10001'),Plain('今天真开心')]);assert await p.groups.route(ev)
   await p.groups.prepare(ev,ProviderRequest(prompt='x'));await ga.response(ev,LLMResponse(role='assistant',completion_text='嗯，我也替你高兴<sticker name="saki_smile"/>'))
   await ev.send(MessageChain([Plain('嗯，我也替你高兴')]))
   assert any(x['type']=='image' for x in sends[-1]['message'])
   await p.groups.finish(ev)
   # Transport preserves literal code after decoration and native prefix.
   e=Event();e.result=MessageEventResult(chain=[Plain('```python\na*b*c\n# keep\n```')]);await style.decorate(e)
   text=e.result.chain[0].text;assert text=='a*b*c\n# keep'
   out=style.final(e,MessageChain([Plain('前缀 '+text)]));assert out.chain[0].text=='前缀 '+text
   assert all(2<=x<=5 for x in delays)
   print(json.dumps({'native_framework':True,'current_private_contacts':4,'future_contact_without_reload':True,'removal_revokes_access':True,'independent_private_memory_and_affect':True,'owner_tools_hidden_and_direct_calls_denied':True,'group_persona_isolation':True,'group_21d_state_and_per_member_relations':True,'failed_or_unsent_no_growth':True,'real_rhythm_and_fragment_context':True,'busy_followup_requeued_once':True,'private_context_not_in_groups':True,'qq_plain_transport_code_preserved':True,'all_sends_delayed_2_to_5':True,'actual_qq_messages':0,'production_db_modified':False},ensure_ascii=False,indent=2))
  finally:
   await gm.terminate();await ga.terminate();await style.terminate();await p.terminate()
asyncio.run(run())
