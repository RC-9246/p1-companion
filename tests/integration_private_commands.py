"""Actual AstrBot config saver, command parser and cached whitelist; isolated state only."""
import asyncio,json,os,sys,tempfile
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import AsyncMock
R=Path(__file__).resolve().parents[1];sys.path[:0]=[str(R/'release'),str(R/'tests')]
from astrbot.api.event import filter
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.star.filter.command import CommandFilter
from astrbot.core.pipeline.whitelist_check.stage import WhitelistCheckStage
from astrbot.core.pipeline.waking_check.stage import WakingCheckStage
from astrbot.core.message.components import Plain
from astrbot.core.message.message_event_result import MessageEventResult
from astrbot.core.platform.message_type import MessageType
from test_companion import init_db

async def run():
 with tempfile.TemporaryDirectory() as tmp:
  d=Path(tmp)/'data/plugin_data/affect';d.mkdir(parents=True);os.environ['P1_COMPANION_DATA']=str(d);init_db(d/'affect.db')
  from astrbot_plugin_affect.main import AffectPlugin,authorized
  from astrbot_plugin_affect.identity import make_identity_key
  from astrbot_plugin_affect.private_access import companion_identity
  from astrbot_plugin_memoria.main import MemoriaPlugin
  from astrbot_plugin_p1_learning.main import P1Learning
  owner=make_identity_key('qq_snowluma','10001','20001');owners={'version':1,'allowed_identities':[owner]}
  (d/'allowed_identities.json').write_text(json.dumps(owners));(d/'groups.json').write_text(json.dumps({'version':1,'groups':[{'bot':'10001','group':'40001'}]}))
  path=d.parents[1]/'cmd_config.json';cfgdata={'platform_settings':{'enable_id_white_list':True,'id_whitelist':['qq_snowluma:FriendMessage:20001'],'wl_ignore_admin_on_group':False,'wl_ignore_admin_on_friend':False,'id_whitelist_log':False},'admins_id':['astrbot']};path.write_text(json.dumps(cfgdata))
  cfg=AstrBotConfig(str(path),default_config=cfgdata);context=N(get_config=lambda *a,**kw:cfg)
  p=AffectPlugin(context);p.reply_pause=AsyncMock();await p.initialize();assert p.access.supported()
  sent=[]
  class Event:
   def __init__(self,text='',sender='20001',group='',platform='qq_snowluma'):
    self.sender=sender;self.group=group;self.platform=platform;self.message_obj=N(message_str=text,message_id='synthetic');self.message_str=text.lstrip('/');self.extra={};self.stopped=False;self.role='member';self._has_send_oper=False;self.is_at_or_wake_command=True
    self.unified_msg_origin=platform+(':GroupMessage:'+group if group else ':FriendMessage:'+sender)
   def get_sender_id(self):return self.sender
   def get_self_id(self):return '10001'
   def get_platform_id(self):return self.platform
   def get_platform_name(self):return self.platform
   def get_group_id(self):return self.group
   def is_private_chat(self):return not self.group
   def get_message_type(self):return MessageType.GROUP_MESSAGE if self.group else MessageType.FRIEND_MESSAGE
   def get_message_str(self):return self.message_str
   def get_messages(self):return [Plain(self.message_obj.message_str)]
   def get_extra(self,k,d=None):return self.extra.get(k,d)
   def set_extra(self,k,v):self.extra[k]=v
   def stop_event(self):self.stopped=True
   def plain_result(self,text):return MessageEventResult().message(text)
   async def send(self,result):sent.append(''.join(x.text for x in result.chain));self._has_send_oper=True
  commands={name:CommandFilter(name,handler_md=N(handler=handler)) for name,handler in [('加白',AffectPlugin.add_private_account),('加主人',AffectPlugin.add_owner_account)]}
  async def command(text,sender='20001',platform='qq_snowluma'):
   e=Event(text,sender,platform=platform);name=text.lstrip('/').split()[0];assert commands[name].filter(e,{})
   handler=p.add_private_account if name=='加白' else p.add_owner_account
   replies=[x async for x in handler(e,**e.get_extra('parsed_params'))];assert e.stopped
   for result in replies:await e.send(result)
   return e,''.join(x.text for r in replies for x in r.chain)
  native=WhitelistCheckStage();await native.initialize(N(astrbot_config=cfg));cached=list(native.whitelist)
  try:
   denied=Event(sender='30003');await native.process(denied);assert denied.stopped
   _,reply=await command('/加白 30003');assert '普通私聊白名单' in reply
   e=Event(sender='30003');await native.process(e);assert not e.stopped and native.whitelist==cached and authorized(e) is None
   memory=MemoriaPlugin(context,{});learner=P1Learning(context);key=companion_identity(e,context)
   assert key and memory._memory_uid(e)==key and learner.private(e)==key and key!=owner
   before=path.read_bytes();_,reply=await command('/加白 30003');assert '已有' in reply and path.read_bytes()==before
   _,reply=await command('/加主人 30003');assert '加入主人' in reply and authorized(Event(sender='30003'))==key
   assert memory._memory_uid(Event(sender='30003'))==key and learner.private(Event(sender='30003'))==key
   assert cfg['admins_id']==['astrbot'] and len(json.loads((d/'allowed_identities.json').read_text())['allowed_identities'])==2
   await command('/加白 30004',sender='30003');e=Event(sender='30004');await native.process(e);assert not e.stopped and not authorized(e)
   before_owner=(d/'allowed_identities.json').read_bytes();_,reply=await command('/加主人 30005',sender='30004');assert not reply and (d/'allowed_identities.json').read_bytes()==before_owner
   _,reply=await command('/加主人 30005',platform='webchat');assert '私聊' in reply and (d/'allowed_identities.json').read_bytes()==before_owner
   bad=Event('/加主人 30005 多余');assert [x async for x in p.add_owner_account(bad,'30005')] and not authorized(Event(sender='30005'))
   group=Event('/加主人 30005',group='40001');await WakingCheckStage().process(group);assert group.stopped and not authorized(Event(sender='30005')) and '私聊' in sent[-1]
   # Live revocation is also honored despite the original native stage cache.
   cfg['platform_settings']['id_whitelist'].remove('qq_snowluma:FriendMessage:30004');await cfg.save_config_async()
   e=Event(sender='30004');await native.process(e);assert e.stopped and native.whitelist==cached
   assert all(2<=call.args[0]<=5 for call in p.reply_pause.await_args_list)
  finally:await p.terminate()
  result={'native_command_parser':True,'native_async_config_writer':True,'cached_native_stage_uses_live_private_snapshot':True,'no_restart_needed':True,'ordinary_contact_not_owner':True,'owner_command_also_whitelists':True,'promoted_owner_can_manage_contacts':True,'separate_memoria_affect_and_learning_keys':True,'promotion_preserves_existing_scope':True,'duplicate_is_idempotent':True,'nonowner_and_webchat_cannot_grant':True,'group_command_only_suggests_private_use':True,'live_revocation_honored':True,'astrbot_admins_unchanged':True,'reply_delay_2_to_5_preserved':True,'model_requests':0,'real_qq_messages':0,'production_database_modified':False}
  (R/'evidence/private-access-commands-native.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
if __name__=='__main__':asyncio.run(run())
