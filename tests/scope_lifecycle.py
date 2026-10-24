"""Native component lifecycle, fresh-process persistence and dynamic admission.
All identities, data, models and QQ transports here are synthetic.
"""
import argparse,asyncio,hashlib,json,os,sqlite3,subprocess,sys,tempfile,time
from pathlib import Path
from types import SimpleNamespace as N
R=Path(__file__).resolve().parents[1];sys.path[:0]=[str(R/'release'),str(R/'tests')]

async def child_verify(path):
 s=json.loads(Path(path).read_text());root=Path(s['data']);os.environ['P1_COMPANION_DATA']=str(root)
 from astrbot_plugin_affect.companion_store import CompanionStore
 from astrbot_plugin_memoria.memoria.db import MemoriaDB
 from astrbot_plugin_p1_group_memory.store import Store
 from astrbot_plugin_p1_learning.store import Store as LearningStore
 from astrbot_plugin_affect.agency_store import AgencyStore
 agency=AgencyStore(root)
 for scope in s['private_scopes']+s['group_scopes']:assert len(agency.goals(scope))==1
 a=CompanionStore(root/'affect.db');m=await MemoriaDB.create(str(root.parent/'memoria'));g=Store(root.parent/'p1_groups/groups.db');learning=LearningStore(root/'affect.db')
 for scope,sentinel in zip(s['private_scopes'],s['private_sentinels']):
  assert a.read(scope)['interaction_count']==1
  records=await m.list_memories(scope,None,'active',10)
  assert [x.content for x in records]==[sentinel]
  assert learning.cards(scope)
 for scope,sentinel in zip(s['group_scopes'],s['group_sentinels']):
  assert sentinel in str(g.history(scope))
  assert g.affect(scope,'')[0]['interactions']==1
 print(json.dumps({'fresh_process':True,'private_states_recovered':2,'private_memories_recovered':2,'group_histories_recovered':2,'group_personas_recovered':2,'learning_recovered':True}))

async def run(round_no,out):
 from test_companion import init_db
 from test_qq_actions import API
 from astrbot.core.provider.entities import ProviderRequest,LLMResponse
 from astrbot.core.message.components import At,Plain
 from astrbot.core.message.message_event_result import MessageChain,MessageEventResult
 from astrbot.core.platform.message_type import MessageType
 from astrbot.core.pipeline.whitelist_check.stage import WhitelistCheckStage
 from astrbot.core.pipeline.waking_check.stage import WakingCheckStage
 from astrbot.core.agent.tool import ToolSet,FunctionTool
 with tempfile.TemporaryDirectory(prefix='p1-scope-lifecycle-') as tmp:
  data=Path(tmp)/'data/plugin_data/affect';data.mkdir(parents=True);os.environ['P1_COMPANION_DATA']=str(data);init_db(data/'affect.db')
  from astrbot_plugin_affect.main import AffectPlugin,atomic_json,authorized
  from astrbot_plugin_affect.identity import make_identity_key
  from astrbot_plugin_affect.private_access import companion_identity
  from astrbot_plugin_affect.qq_policy import DEFAULT
  from astrbot_plugin_memoria.main import MemoriaPlugin
  from astrbot_plugin_memoria.memoria.db import MemoriaDB
  from astrbot_plugin_p1_group_memory.main import P1GroupMemory
  from astrbot_plugin_p1_group_affect.main import P1GroupAffect
  from astrbot_plugin_p1_group_memory.store import scope_key
  from astrbot_plugin_p1_group_memory.scene import member_key
  from astrbot_plugin_p1_learning.main import P1Learning
  from astrbot_plugin_p1_learning.policy import member_scope
  owner='20002';bot='10001';peers=[str(21000+round_no*10+i) for i in (1,2)];groups=[str(31000+round_no*10+i) for i in (1,2)]
  cfg={'platform_settings':{'enable_id_white_list':True,'id_whitelist':['qq_snowluma:FriendMessage:'+owner],'wl_ignore_admin_on_group':False,'wl_ignore_admin_on_friend':False,'id_whitelist_log':False},'provider':[]}
  def save():atomic_json(data.parents[1]/'cmd_config.json',cfg)
  save();atomic_json(data/'allowed_identities.json',{'version':1,'allowed_identities':[make_identity_key('qq_snowluma',bot,owner)]});atomic_json(data/'groups.json',{'version':1,'groups':[]})
  atomic_json(data/'qq_policy.json',dict(DEFAULT,enabled=True,cross_forward='allow'))
  delays=[];sent=[]
  class Client(API):
   base_url=N(scheme='https',host='api.deepseek.com')
   def __init__(self):super().__init__();self.chat=N(completions=self)
   def with_options(self,**kw):return self
   async def create(self,**kw):
    system=kw['messages'][0]['content']
    value={'items':[]} if system.startswith('从当前唯一会话') else {'notes':[]} if '整理可核对的简短话题笔记' in system else {'addressed':True,'confidence':.99} if '只判断当前QQ群消息' in system else {'intent':'casual','emotion':'happy','target':'user','relation':'none','confidence':.95}
    return N(choices=[N(message=N(content=json.dumps(value)))])
   async def call_action(self,action,**kw):
    if action=='get_friend_list':return [{'user_id':int(n),'nickname':'合成好友'} for n in [owner,*peers]]
    if action=='get_group_list':return [{'group_id':int(n),'group_name':'合成群'} for n in groups]
    return await super().call_action(action,**kw)
   async def get_group_list(self):return await self.call_action('get_group_list')
   async def send_group_msg(self,**kw):sent.append(kw);return {'message_id':80000+len(sent)}
  client=Client()
  class Context:
   def __init__(self):self._event_queue=asyncio.Queue()
   def get_config(self,*a):return cfg
   def get_platform_inst(self,*a):return N(get_client=lambda:client)
   @property
   def provider_manager(self):return self
   async def get_current_chat_provider_id(self,*a):return 'synthetic'
   async def get_provider_by_id(self,*a):return N(client=client,get_model=lambda:'synthetic')
  ctx=Context();p=AffectPlugin(ctx)
  async def pause(seconds):delays.append(seconds)
  p.reply_pause=pause
  class Event:
   seq=0
   def __init__(self,sender=owner,text='以后回复简短一些',group='',self_id=bot):
    Event.seq+=1;self.sender=sender;self.group=group;self.bot=self_id;self.message_str=text;self.extra={};self.stopped=False;self.result=None;self.role='member';self.session_id=group or sender;self.unified_msg_origin='qq_snowluma:'+('GroupMessage:'+group if group else 'FriendMessage:'+sender);self.session=N(message_type='group' if group else 'private');self.message_obj=N(message_id=str(Event.seq),message_str=text,timestamp=time.time());self._has_send_oper=False
   def get_platform_id(self):return 'qq_snowluma'
   def get_platform_name(self):return 'aiocqhttp'
   def get_self_id(self):return self.bot
   def get_sender_id(self):return self.sender
   def get_sender_name(self):return '合成用户'
   def get_group_id(self):return self.group
   def get_message_type(self):return MessageType.GROUP_MESSAGE if self.group else MessageType.FRIEND_MESSAGE
   def get_messages(self):return [At(qq=self.bot),Plain(self.message_str)] if self.group else [Plain(self.message_str)]
   def is_private_chat(self):return not self.group
   def get_extra(self,k,d=None):return self.extra.get(k,d)
   def set_extra(self,k,v):self.extra[k]=v
   def stop_event(self):self.stopped=True
   def continue_event(self):self.stopped=False
   def get_result(self):return self.result
   def is_admin(self):return False
   def plain_result(self,text):return MessageEventResult(chain=[Plain(text)])
   async def send(self,message):sent.append({'private':self.sender});self._has_send_oper=True
  gm=P1GroupMemory(ctx);ga=P1GroupAffect(ctx);learning=P1Learning(ctx)
  await p.initialize();await gm.initialize();await ga.initialize();await learning.initialize()
  memory=MemoriaPlugin(ctx,{'follow_up_tracking_enabled':False});memory.db=await MemoriaDB.create(str(data.parent/'memoria'));memory._p1_session_file=data.parent/'memoria/authorized_sessions.json'
  async def group_command(mode,number):
   results=[r async for r in p.group_control(Event(),mode,number)]
   return results[0].chain[0].text if results else ''
  native=WhitelistCheckStage();await native.initialize(N(astrbot_config=cfg));wake=WakingCheckStage()
  private_scopes=[];private_sentinels=[];group_scopes=[];group_sentinels=[]
  try:
   denied=Event(peers[0]);await native.process(denied);assert denied.stopped and not companion_identity(denied,ctx)
   for i,peer in enumerate(peers):
    scope=make_identity_key('qq_snowluma',bot,peer)
    with sqlite3.connect(data/'affect.db') as c:assert c.execute('SELECT 1 FROM companion_state WHERE identity_key=?',(scope,)).fetchone() is None
    cfg['platform_settings']['id_whitelist'].append('qq_snowluma:FriendMessage:'+peer);save()
    # This reinitialization is what the native WebUI's pipeline reload applies.
    await native.initialize(N(astrbot_config=cfg));e=Event(peer,'以后回复简短一些' if i==0 else '以后回复详细一些')
    await native.process(e);assert not e.stopped and companion_identity(e,ctx)==scope and not authorized(e)
    request=ProviderRequest(prompt=e.message_str)
    await p.throttle_inbound_qq(e);await memory.on_llm_request(e,request);await p.inject_state_into_llm(e,request)
    assert p.store.read(scope)['interaction_count']==0 and p.store.read_emotion(scope)['familiarity']==0
    sentinel='私有独立资料'+('甲' if i==0 else '乙')+str(round_no)
    candidate=json.loads(await memory.tool_add_memory_candidate(e,peer,sentinel));assert candidate['ok']
    cmd=Event(peer,'确认记忆 '+str(candidate['id']));acks=[r async for r in memory.cmd_confirm_memory(cmd)];assert acks and '已确认' in acks[0].chain[0].text
    e.result=MessageEventResult(chain=[Plain('嗯，记下了')]);await p.mark_response(e,LLMResponse(role='assistant',completion_text='嗯，记下了'));await e.send(MessageChain([Plain('嗯，记下了')]));await p.commit_after_delivery(e);await memory.remember_private_delivery(e);await learning.delivered(e)
    await p.commit_after_delivery(e);assert p.store.read(scope)['interaction_count']==1
    p.agency.store.goal(scope,'私聊独立的持久小目标'+str(i));private_scopes.append(scope);private_sentinels.append(sentinel)
   for i,peer in enumerate(peers):
    e=Event(peer);rows=json.loads(await memory.tool_search_memory(e,peer,peer,'独立资料'))
    assert [x['content'] for x in rows]==[private_sentinels[i]]
    assert json.loads(await memory.tool_search_memory(e,peers[1-i],'','资料'))['error']=='forbidden'
    row=p.qq.store.target(p.qq.event_ref(e));assert row
    assert [x['text'] for x in p.qq.confirmed_memories(row)]==[private_sentinels[i]]
    assert learning.store.cards(private_scopes[i])[0]['value']==('short' if i==0 else 'detailed')
   other_bot=Event(peers[0],self_id='10002');other_scope=companion_identity(other_bot,ctx);assert other_scope and other_scope not in private_scopes
   assert memory._memory_uid(other_bot)==other_scope and not await memory.db.list_memories(other_scope,None,'active',10)
   assert not [r async for r in p.group_control(Event(peers[0]),'开启',groups[0])]
   assert '还没有加入' in await group_command('开启','399999')
   for i,number in enumerate(groups):
    e=Event(peers[0],'以后回复简短一些',group=number);assert not p.groups.allowed(e)
    denied_group=Event(peers[0],group=number);await wake.process(denied_group);assert denied_group.stopped
    assert '已开启' in await group_command('开启',number)
    g=scope_key(bot,number);private_before=[p.store.read(s)['interaction_count'] for s in private_scopes]
    assert gm.store.affect(g,'')[0]['interactions']==0
    await wake.process(e);await native.process(e);assert not e.stopped and e.get_extra('_p1_group_admitted',False)
    await p.groups.prepare(e,ProviderRequest(prompt=e.message_str))
    current_member=member_key(bot,number,peers[0]);assert member_scope(g,current_member) not in private_scopes
    sentinel='群独立资料'+('甲' if i==0 else '乙')+str(round_no)
    await asyncio.to_thread(gm.store.add,g,'sentinel-'+str(i),current_member,'合成用户',sentinel,time.time())
    e.result=MessageEventResult(chain=[Plain('嗯，我明白了')]);await ga.response(e,LLMResponse(role='assistant',completion_text='嗯，我明白了'));await e.send(MessageChain([Plain('嗯，我明白了')]));await learning.delivered(e);await p.groups.finish(e)
    assert gm.store.affect(g,current_member)[1]['interactions']==1
    assert [p.store.read(s)['interaction_count'] for s in private_scopes]==private_before
    p.agency.store.goal(g,'群聊独立的持久小目标'+str(i));group_scopes.append(g);group_sentinels.append(sentinel)
   assert len(set(private_scopes+group_scopes))==4
   for i,g in enumerate(group_scopes):
    h=str(gm.store.history(g));assert group_sentinels[i] in h and group_sentinels[1-i] not in h
    assert all(x not in h for x in private_sentinels)
   assert member_key(bot,groups[0],peers[0])!=member_key(bot,groups[1],peers[0])
   state={'data':str(data),'private_scopes':private_scopes,'private_sentinels':private_sentinels,'group_scopes':group_scopes,'group_sentinels':group_sentinels}
   statefile=Path(tmp)/'verify-state.json';statefile.write_text(json.dumps(state))
   recovered=await asyncio.to_thread(subprocess.run,[sys.executable,str(__file__),'--verify-child',str(statefile)],capture_output=True,text=True,timeout=30)
   assert recovered.returncode==0,recovered.stderr[-1000:];recovery=json.loads(recovered.stdout.splitlines()[-1])
   cfg['platform_settings']['id_whitelist'].remove('qq_snowluma:FriendMessage:'+peers[0]);save();await native.initialize(N(astrbot_config=cfg))
   e=Event(peers[0]);await native.process(e);assert e.stopped and not companion_identity(e,ctx) and await memory.tool_search_memory(e,peers[0],'','资料') is None
   cfg['platform_settings']['id_whitelist'].append('qq_snowluma:FriendMessage:'+peers[0]);save();await native.initialize(N(astrbot_config=cfg))
   assert companion_identity(Event(peers[0]),ctx)==private_scopes[0]
   assert [x.content for x in await memory.db.list_memories(private_scopes[0],None,'active',10)]==[private_sentinels[0]]
   epoch=gm.store.meta(group_scopes[0])['epoch'];await group_command('关闭',groups[0]);assert not p.groups.allowed(Event(peers[0],group=groups[0]))
   assert not gm.store.save_notes(group_scopes[0],epoch,99,[],time.time())
   assert '已开启' in await group_command('开启',groups[0]);assert group_sentinels[0] in str(gm.store.history(group_scopes[0]))
   old_epoch=gm.store.meta(group_scopes[1])['epoch'];await group_command('清空',groups[1])
   assert not p.agency.store.goals(group_scopes[1])
   assert not gm.store.history(group_scopes[1])['messages'] and gm.store.affect(group_scopes[1],'')[0]['interactions']==0
   assert not gm.store.save_notes(group_scopes[1],old_epoch,99,[],time.time())
   assert group_sentinels[0] in str(gm.store.history(group_scopes[0]))
   assert not learning.store.cards(member_scope(group_scopes[1],member_key(bot,groups[1],peers[0])))
   assert all(2<=x<=5 for x in delays)
   report={'round':round_no,'passed':True,'synthetic_only':True,'native_whitelist_apply_exercised':True,'owner_group_command_and_membership_validation':True,'new_private_scopes':2,'new_group_scopes':2,'lazy_creation_no_invented_interactions':True,'actual_memory_candidate_and_confirmation_command':True,'same_scopes_used_for_foreground_and_background_memory':True,'distinct_learning_preferences':True,'cross_user_cross_group_read_denied':True,'same_sender_different_bot_isolated':True,'same_member_different_groups_isolated':True,'agency_queue_persisted_in_fresh_process':True,'group_agency_clear_isolated':True,'process_recovery':recovery,'private_revoke_regrant_preserves_same_space':True,'group_close_reopen_preserves_same_space':True,'group_clear_is_local_and_rejects_stale_writes':True,'delay_range_preserved':True,'actual_qq_messages':0,'production_database_modified':False}
   Path(out).write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False,indent=2))
  finally:
   await learning.terminate();await gm.terminate();await ga.terminate();await p.terminate()

if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('--round',type=int,default=1);ap.add_argument('--out');ap.add_argument('--verify-child');a=ap.parse_args()
 asyncio.run(child_verify(a.verify_child) if a.verify_child else run(a.round,a.out))
