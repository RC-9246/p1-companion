"""Real AstrBot command filter/waking stage, temporary state and fake QQ only."""
import asyncio,json,os,sys,tempfile
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import AsyncMock,patch
R=Path(__file__).resolve().parents[1];sys.path[:0]=[str(R/'release'),str(R/'tests')]
from test_companion import init_db
from astrbot.core.star.filter.command import CommandFilter
from astrbot.core.pipeline.waking_check.stage import WakingCheckStage
from astrbot.core.message.components import Plain
from astrbot.core.message.message_event_result import MessageEventResult
from astrbot.core.platform.message_type import MessageType

async def main():
 with tempfile.TemporaryDirectory() as tmp:
  data=Path(tmp);os.environ['P1_COMPANION_DATA']=tmp;init_db(data/'affect.db')
  from astrbot_plugin_affect.main import AffectPlugin,authorized,atomic_json
  from astrbot_plugin_affect.identity import make_identity_key
  owner=make_identity_key('qq_snowluma','10001','20001')
  owners={'version':1,'allowed_identities':[owner]};groups={'version':1,'groups':[{'bot':'10001','group':g} for g in ('30001','30002')]}
  atomic_json(data/'allowed_identities.json',owners);atomic_json(data/'groups.json',groups)
  (data/'qq_policy.json').write_text((R/'policy/qq_policy.json').read_text())
  cfg={'platform_settings':{'enable_id_white_list':True,'id_whitelist':['qq_snowluma:FriendMessage:20001']}}
  p=AffectPlugin(N(get_config=lambda *a:cfg));p.reply_pause=AsyncMock();await p.initialize()
  assert p.agency.ready and p.qq.ready
  replies=[];sequence=0
  class Event:
   def __init__(self,text,group='',sender='20001'):
    nonlocal sequence
    sequence+=1;self.group=group;self.sender=sender;self.message_obj=N(message_str=text,message_id=str(sequence));self.extra={};self.stopped=False;self.message_str=text.lstrip('/');self.is_at_or_wake_command=True;self._has_send_oper=False
   def get_platform_id(self):return 'qq_snowluma'
   def get_self_id(self):return '10001'
   def get_sender_id(self):return self.sender
   def get_group_id(self):return self.group
   def is_private_chat(self):return not self.group
   def get_message_type(self):return MessageType.GROUP_MESSAGE if self.group else MessageType.FRIEND_MESSAGE
   def get_message_str(self):return self.message_str
   def get_extra(self,k,d=None):return self.extra.get(k,d)
   def set_extra(self,k,v):self.extra[k]=v
   def stop_event(self):self.stopped=True
   def plain_result(self,text):return MessageEventResult().message(text)
   def get_messages(self):return [Plain(self.message_obj.message_str)]
   async def send(self,result):replies.append(''.join(x.text for x in result.chain));self._has_send_oper=True
  command=CommandFilter('群内主动',handler_md=N(handler=AffectPlugin.interest_control))
  scope=p.qq.group_key('10001','30001');other=p.qq.group_key('10001','30002');p.agency.store.ensure(scope);p.agency.store.config(other,interest_join=0)
  async def private(text,sender='20001'):
   event=Event(text,sender=sender);assert command.filter(event,{})
   out=[x async for x in p.interest_control(event,**event.get_extra('parsed_params'))]
   return ''.join(x.text for r in out for x in r.chain)
  async def group(text,sender='20001',groupid='30001'):
   event=Event(text,groupid,sender);before=len(replies)
   await WakingCheckStage().process(event)
   assert event.stopped
   assert not event.get_extra('_p1_group_admitted') and not event.get_extra('activated_handlers')
   return event,replies[before:]
  try:
   # Native private command parsing and durable configuration, both argument orders.
   for text,want in (('/群内主动 关闭 30001',0),('/群内主动 开启 30001',1),('/群内主动 30001 关闭',0),('/群内主动 30001 开启',1)):
    assert '已' in await private(text);assert p.agency.store.ensure(scope)['interest_join']==want
   assert '已开启' in await private('/群内主动 状态 30001')
   assert '已开启' in await private('/群内主动 30001')
   assert '指定群号' in await private('/群内主动 开启')
   assert '用法' in await private('/群内主动 错误 30001')
   assert not await private('/群内主动 关闭 30001','20002');assert p.agency.store.ensure(scope)['interest_join']==1
   # Authenticated ChatUI is not a QQ owner identity. It must consume the command
   # with a clear hint rather than letting the model invoke arbitrary shell tools.
   web=Event('/群内主动 开启 30001');web.get_platform_id=lambda:'webchat'
   assert command.filter(web,{})
   hint=[x async for x in p.interest_control(web,**web.get_extra('parsed_params'))]
   assert web.stopped and len(hint)==1 and 'QQ主人控制命令' in ''.join(x.text for x in hint[0].chain)
   assert p.agency.store.ensure(scope)['interest_join']==1
   p.groups.route=AsyncMock(side_effect=AssertionError('control must not call conversational/model routing'))
   for text,want in (('/群内主动 关闭',0),('/群内主动 开启',1),('/群内主动 30001 关闭',0),('/群内主动 开启 30001',1)):
    event,out=await group(text);assert len(out)==1 and p.agency.store.ensure(scope)['interest_join']==want
    assert authorized(event) is None and authorized(event,private_only=False)==owner
   assert '已开启' in (await group('/群内主动 状态'))[1][0]
   assert '已开启' in (await group('/群内主动'))[1][0]
   assert '本群' in (await group('/群内主动 关闭 30002'))[1][0]
   assert p.agency.store.ensure(scope)['interest_join']==1 and p.agency.store.ensure(other)['interest_join']==0
   assert '用法' in (await group('/群内主动 错误'))[1][0]
   assert '用法' in (await group('/群内主动 开启 30001 多余'))[1][0]
   assert not (await group('/群内主动 关闭',sender='20002'))[1]
   assert not (await group('/群内主动 开启',groupid='39999'))[1]
   # A later human enrollment gets a new independent switch without a restart.
   added={'version':1,'groups':groups['groups']+[{'bot':'10001','group':'30003'}]}
   atomic_json(data/'groups.json',added)
   assert '已关闭' in (await group('/群内主动 关闭',groupid='30003'))[1][0]
   new_scope=p.qq.group_key('10001','30003')
   assert p.agency.store.ensure(new_scope)['interest_join']==0
   assert p.agency.store.ensure(scope)['interest_join']==1
   assert p.agency.store.ensure(other)['interest_join']==0
   # Unrelated management commands are never offered the narrow bypass.
   assert not await p.groups.control(Event('/浏览授权 example.org','30001'))
   assert not await p.groups.control(Event('转述：/群内主动 关闭','30001'))
   # Availability and authority revocation cannot turn into a traceback or leak reply.
   p.agency.ready=False;assert '准备中' in await private('/群内主动 关闭 30001');p.agency.ready=True
   assert p.agency.store.ensure(scope)['interest_join']==1
   async def revoke_owner(delay):atomic_json(data/'allowed_identities.json',{'version':1,'allowed_identities':['v1:'+'f'*64]})
   with patch.object(p,'reply_pause',revoke_owner):
    event,out=await group('/群内主动 状态');assert not out and event.get_extra('_p1_send_cancelled')
   atomic_json(data/'allowed_identities.json',owners)
   async def revoke_group(delay):atomic_json(data/'groups.json',{'version':1,'groups':[]})
   with patch.object(p,'reply_pause',revoke_group):
    event,out=await group('/群内主动 状态');assert not out and event.get_extra('_p1_send_cancelled')
   atomic_json(data/'groups.json',{'version':1,'groups':[groups['groups'][0]]})
   assert '已关闭' in await private('/群内主动 关闭');assert p.agency.store.ensure(scope)['interest_join']==0
   p.agency.store.config(scope,interest_join=1)
   assert all(2<=x.args[0]<=5 for x in p.reply_pause.await_args_list)
   assert not p.groups.route.await_args_list
   print(json.dumps({'native_command_filter':True,'native_group_waking_stage':True,'owner_private_and_current_group':True,'both_argument_orders':True,'status_on_off_durable':True,'new_group_isolation':True,'nonowner_and_unenrolled_silent':True,'webchat_consumed_without_model_or_shell':True,'other_admin_handlers_unreachable':True,'revocation_during_delay_cancels_reply':True,'unavailable_module_reported':True,'each_qq_reply_delayed_2_to_5':True,'model_requests':0,'real_qq_messages':0,'production_database_modified':False},ensure_ascii=False))
  finally:await p.terminate()
asyncio.run(main())
