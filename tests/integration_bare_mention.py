"""Real native empty-input guard and scoped hooks; isolated storage, no network."""
import asyncio,json,os,sys,tempfile
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import patch
R=Path(__file__).resolve().parents[1];sys.path[:0]=[str(R/'release'),str(R/'tests')]
from test_companion import init_db
from astrbot.core.message.components import At,Plain,Image
from astrbot.core.platform.message_type import MessageType
from astrbot.core.pipeline.process_stage.method.agent_sub_stages import internal

async def run():
 with tempfile.TemporaryDirectory() as temp:
  d=Path(temp);os.environ['P1_COMPANION_DATA']=temp;init_db(d/'affect.db')
  from astrbot_plugin_affect.main import AffectPlugin,atomic_json
  from astrbot_plugin_affect.companion_store import CompanionStore
  from astrbot_plugin_p1_group_memory.main import P1GroupMemory
  from astrbot_plugin_p1_group_memory.store import Store
  atomic_json(d/'groups.json',{'version':1,'groups':[{'bot':'10001','group':'30003'}]})
  async def pid(*a):return 'synthetic'
  async def provider(*a):return N(client=N(base_url=N(host='api.deepseek.com',scheme='https')))
  ctx=N(get_current_chat_provider_id=pid,provider_manager=N(get_provider_by_id=provider),get_config=lambda *a:{'provider':[]})
  p=AffectPlugin(ctx);p.store=CompanionStore(d/'affect.db');p.store.migrate();p.thinking.migrate()
  memory=P1GroupMemory(ctx);memory.store=Store(d/'groups.db');await memory.initialize()
  class Event:
   seq=0
   def __init__(self,parts,text='',group='30003'):
    Event.seq+=1;self.message_obj=N(message_str=text,message_id=str(Event.seq),message=parts);self.extra={};self.group=group;self.unified_msg_origin='qq_snowluma:GroupMessage:'+group;self.typing=0
   @property
   def message_str(self):return self.message_obj.message_str
   def get_platform_id(self):return 'qq_snowluma'
   def get_platform_name(self):return 'aiocqhttp'
   def get_message_type(self):return MessageType.GROUP_MESSAGE
   def get_self_id(self):return '10001'
   def get_group_id(self):return self.group
   def get_sender_id(self):return '20002'
   def get_sender_name(self):return '合成发言者'
   def is_private_chat(self):return False
   def get_messages(self):return self.message_obj.message
   def get_extra(self,k,d=None):return self.extra.get(k,d)
   def set_extra(self,k,v):self.extra[k]=v
   async def send_typing(self):self.typing+=1
   async def stop_typing(self):pass
   async def send(self,*a):raise AssertionError('no real or fake QQ send expected')
  reached=[]
  async def stop_at_waiting(*a,**k):reached.append(True);return True
  async def native_guard(e):
   with patch.object(internal,'try_capture_follow_up',lambda *_:None),patch.object(internal,'call_event_hook',stop_at_waiting):
    async for _ in internal.InternalAgentSubStage.process(N(streaming_response=False,show_reasoning=False),e,''):pass
  try:
   bare=Event([At(qq='10001')]);await native_guard(bare);assert not reached
   assert await p.groups.route(bare);req=bare.get_extra('provider_request');assert req is not None and req.prompt==''
   assert bare.message_str=='' and bare.message_obj.message_str==''
   assert all(part._no_save for part in req.extra_user_content_parts)
   await native_guard(bare);assert reached and bare.typing==1
   await p.groups.prepare(bare,req)
   assert req.prompt=='' and sum('[P1-GROUP-BARE-MENTION:v1]' in part.text for part in req.extra_user_content_parts)==1
   assert all(part._no_save for part in req.extra_user_content_parts)
   history=memory.store.history(memory.key(bare));assert history['messages'][-1]['text']=='' and history['messages'][-1]['mentions'][0]['member']=='saki'
   await p.groups.finish(bare)
   for e in [Event([Plain('')]),Event([At(qq='99999')]),Event([At(qq='10001')],group='30004')]:
    assert not await p.groups.route(e) and e.get_extra('provider_request') is None
   ordinary=Event([At(qq='10001'),Plain('你好')],'你好');assert await p.groups.route(ordinary);assert ordinary.get_extra('provider_request') is None;await p.groups.finish(ordinary)
   assert not p.groups.bare_mention(Event([At(qq='10001'),Image(file='synthetic')]))
   assert not p.groups.bare_mention(Event([At(qq='10001'),At(qq='99999')]))
   denied=Event([At(qq='10001')]);original=p.store.take_budget;p.store.take_budget=lambda *a,**k:False
   assert not await p.groups.route(denied) and denied.get_extra('provider_request') is None;p.store.take_budget=original
   revoked=Event([At(qq='10001')]);assert await p.groups.route(revoked);atomic_json(d/'groups.json',{'version':1,'groups':[]});assert not p.groups.valid(revoked)
  finally:
   for task in p.groups.expiry.values():task.cancel()
   if p.groups.expiry:await asyncio.gather(*p.groups.expiry.values(),return_exceptions=True)
   await memory.terminate()
 report={'native_empty_guard_reproduced':True,'explicit_request_reaches_native_waiting_hook':True,'raw_user_text_remains_empty':True,'metadata_is_temporary':True,'original_group_memory_preserved':True,'other_mentions_empty_text_and_unenrolled_group_do_not_trigger':True,'ordinary_text_path_unchanged':True,'budget_and_revocation_preserved':True,'qq_messages_sent':0,'model_requests':0,'production_database_modified':False}
 (R/'evidence/bare-mention-native.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
if __name__=='__main__':asyncio.run(run())
