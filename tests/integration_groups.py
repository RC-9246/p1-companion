"""Actual AstrBot wake/whitelist/serialization; isolated state and fake OneBot."""
import asyncio,json,os,sys,tempfile,time
from pathlib import Path
from types import SimpleNamespace
R=Path(__file__).resolve().parents[1];sys.path[:0]=[str(R/'release'),str(R/'tests')]
from test_companion import init_db
from astrbot.core.message.components import At,Reply,Plain
from astrbot.core.message.message_event_result import MessageChain
from astrbot.core.provider.entities import ProviderRequest
from astrbot.core.pipeline.waking_check.stage import WakingCheckStage
from astrbot.core.pipeline.whitelist_check.stage import WhitelistCheckStage
from astrbot.core.platform.message_type import MessageType

async def main():
 with tempfile.TemporaryDirectory() as tmp:
  d=Path(tmp);os.environ['P1_COMPANION_DATA']=tmp;init_db(d/'affect.db')
  from astrbot_plugin_affect.main import AffectPlugin,authorized,atomic_json
  from astrbot_plugin_affect.companion_store import CompanionStore
  from astrbot_plugin_affect.identity import make_identity_key
  subject=make_identity_key('qq_snowluma','10001','20002');atomic_json(d/'allowed_identities.json',{'version':1,'allowed_identities':[subject]})
  calls=[];delays=[]
  class Client:
   async def get_group_list(self):return [{'group_id':30003}]
   async def send_group_msg(self,**kw):calls.append(kw);return {'message_id':90000+len(calls)}
  client=Client();ctx=SimpleNamespace(get_platform_inst=lambda _:SimpleNamespace(get_client=lambda:client))
  async def pid(*a):return 'synthetic'
  async def provider(*a):return SimpleNamespace(client=SimpleNamespace(base_url=SimpleNamespace(host='api.deepseek.com',scheme='https')))
  ctx.get_current_chat_provider_id=pid;ctx.provider_manager=SimpleNamespace(get_provider_by_id=provider)
  p=AffectPlugin(ctx);p.store=CompanionStore(d/'affect.db');p.store.migrate()
  p.thinking.migrate();ctx.get_config=lambda *a:{'provider':[]}
  async def pause(n):delays.append(n)
  p.reply_pause=pause
  class Event:
   seq=0
   def __init__(self,text='',components=None,group='30003',sender='20002',private=False):
    Event.seq+=1;self.message_obj=SimpleNamespace(message_str=text,message_id=str(Event.seq));self.parts=components or [Plain(text)];self.extra={};self.stopped=False;self.private=private;self.group=group;self.sender=sender;self._has_send_oper=False;self.is_at_or_wake_command=False;self.role='member';self.unified_msg_origin='qq_snowluma:'+('FriendMessage:20002' if private else 'GroupMessage:'+group)
   def get_platform_id(self):return 'qq_snowluma'
   def get_platform_name(self):return 'aiocqhttp'
   def get_message_type(self):return MessageType.FRIEND_MESSAGE if self.private else MessageType.GROUP_MESSAGE
   def get_self_id(self):return '10001'
   def get_group_id(self):return '' if self.private else self.group
   def get_sender_id(self):return self.sender
   def get_messages(self):return self.parts
   def is_private_chat(self):return self.private
   def get_extra(self,k,d=None):return self.extra.get(k,d)
   def set_extra(self,k,v):self.extra[k]=v
   def stop_event(self):self.stopped=True
   async def send(self,*a):raise AssertionError('raw transport bypassed receipt enforcement')
  # Real whitelist stage; private access must retain its native decision.
  cfg={'platform_settings':{'enable_id_white_list':True,'id_whitelist':['qq_snowluma:FriendMessage:20002'],'wl_ignore_admin_on_group':False,'wl_ignore_admin_on_friend':False,'id_whitelist_log':False}}
  w=WhitelistCheckStage();await w.initialize(SimpleNamespace(astrbot_config=cfg))
  native_wake=WakingCheckStage.process;native_white=WhitelistCheckStage.process
  p.groups.install();wake=WakingCheckStage()
  try:
   e=Event('你好',[At(qq='10001')]);await wake.process(e);assert e.stopped and not calls
   owner=Event(private=True);assert authorized(owner)==subject
   assert '已开启' in await p.groups.enroll(owner,'开启','30003')
   assert '还没有加入' in await p.groups.enroll(owner,'开启','30004')
   assert len(p.groups.policy())==1
   for private,who,want in ((True,'20002',False),(True,'99999',True)):
    e=Event(private=private,sender=who);e.unified_msg_origin='qq_snowluma:FriendMessage:'+who
    await w.process(e);assert e.stopped==want
   e=Event('你好',[At(qq='10001'),Plain('你好')]);assert authorized(e) is None
   await wake.process(e);await w.process(e)
   assert not e.stopped and e.is_at_or_wake_command and e.get_extra('activated_handlers')==[] and e.get_extra('enable_streaming') is False
   concurrent=Event('再次@你',[At(qq='10001')]);await wake.process(concurrent);assert concurrent.stopped
   from astrbot_plugin_affect.relationship_style import PRIVATE_GUIDANCE,PROFILE_ID
   req=ProviderRequest(prompt='wrong',system_prompt='PRIVATE_SENTINEL'+PRIVATE_GUIDANCE,contexts=[{'role':'user','content':'PRIVATE_SENTINEL'}],extra_user_content_parts=['PRIVATE_SENTINEL'],tool_calls_result=['PRIVATE_SENTINEL'],image_urls=['PRIVATE_SENTINEL'])
   await p.groups.prepare(e,req)
   assert 'PRIVATE_SENTINEL' not in str(req) and not req.contexts and not req.func_tool.tools and not req.image_urls and req.tool_calls_result is None
   assert all('PRIVATE_SENTINEL' not in str(x) for x in req.extra_user_content_parts)
   assert PROFILE_ID not in req.system_prompt
   await e.send(MessageChain([Plain('嗯，我在')]))
   assert len(calls)==1 and calls[0]['group_id']==30003 and 2<=delays[-1]<=5
   await p.groups.finish(e)
   assert p.groups.state.same_thread(p.groups.state.groups[('10001','30003')],__import__('astrbot_plugin_affect.group_chat',fromlist=['member']).member(e),time.time())
   async def yes(*a):return True
   p.groups.classify=yes
   f=Event('那再举个例子');await wake.process(f);assert not f.stopped;await p.groups.finish(f)
   for text,parts in [('今天吃什么',None),('伙伴在动画里说过什么', [At(qq='77777'),Plain('伙伴')]),('[CQ:at,qq=10001] 你好',None)]:
    f=Event(text,parts,sender='77777');await wake.process(f);assert f.stopped,(text,f.extra)
   async def no(*a):return False
   p.groups.classify=no
   f=Event('有人喜欢伙伴这个角色吗');await wake.process(f);assert f.stopped
   async def timeout(*a):raise TimeoutError('synthetic')
   p.groups.classify=timeout
   f=Event('伙伴你觉得呢');await wake.process(f);assert f.stopped
   f=Event('引用你',[Reply(id='90001',sender_id='10001')]);await wake.process(f);assert not f.stopped
   before=len(calls)
   async def revoke(n):
    delays.append(n);await p.groups.enroll(owner,'关闭','30003')
   p.reply_pause=revoke
   await f.send(MessageChain([Plain('不应发送')]))
   assert len(calls)==before and f.get_extra('_p1_send_cancelled')
   assert ('10001','30003') not in p.groups.state.groups
   f=Event('你好',[At(qq='10001')]);await wake.process(f);assert f.stopped
   assert p.store.read(subject)['interaction_count']==0
  finally:p.groups.close()
  assert WakingCheckStage.process is native_wake and WhitelistCheckStage.process is native_white
  print(json.dumps({'native_wake_and_whitelist':True,'dynamic_owner_enrollment':True,'membership_validation':True,'private_whitelist_preserved':True,'no_group_commands_or_tools':True,'private_context_cleared':True,'group_member_scope':True,'native_reply_and_at':True,'implicit_followup':True,'other_mentions_and_plain_cq_ignored':True,'timeout_silent':True,'revoke_during_delay_cancels_send':True,'native_serializer_and_receipt':True,'each_send_delayed_2_to_5':True,'adapter_unload_restores_core':True,'fake_onebot_sends':len(calls),'actual_qq_messages':0,'production_db_modified':False},indent=2))
asyncio.run(main())
