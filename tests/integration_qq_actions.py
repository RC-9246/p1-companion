"""Real AstrBot lifecycle, group tool isolation, proactive opening and follow-up ingress."""
import asyncio,json,os,sys,tempfile,time
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import patch
from datetime import datetime
from zoneinfo import ZoneInfo
R=Path(__file__).resolve().parents[1];sys.path[:0]=[str(R/'release'),str(R/'tests')]
from test_companion import init_db
from test_qq_actions import API,Event
from astrbot.core.provider.entities import ProviderRequest
from astrbot.core.agent.tool import ToolSet,FunctionTool
from astrbot.core.message.components import Plain,At
from astrbot.core.platform.message_type import MessageType

async def main():
 with tempfile.TemporaryDirectory() as tmp:
  d=Path(tmp)/'data/plugin_data/affect';d.mkdir(parents=True);os.environ['P1_COMPANION_DATA']=str(d);init_db(d/'affect.db')
  from astrbot_plugin_affect.identity import make_identity_key
  from astrbot_plugin_affect.main import AffectPlugin
  from astrbot_plugin_affect.qq_policy import DEFAULT
  from astrbot_plugin_p1_group_memory.main import P1GroupMemory
  from astrbot_plugin_p1_group_affect.main import P1GroupAffect
  from astrbot_plugin_p1_qq_style.main import P1QQStyle
  owner=make_identity_key('qq_snowluma','10001','20002');(d/'allowed_identities.json').write_text(json.dumps({'version':1,'allowed_identities':[owner]}))
  (d/'groups.json').write_text(json.dumps({'version':1,'groups':[{'bot':'10001','group':'30003'}]}));(d/'qq_policy.json').write_text(json.dumps(dict(DEFAULT,enabled=True)))
  cfg={'platform_settings':{'enable_id_white_list':True,'id_whitelist':['qq_snowluma:FriendMessage:20002','qq_snowluma:FriendMessage:20003']}};(d.parents[1]/'cmd_config.json').write_text(json.dumps(cfg))
  api=API();delays=[]
  async def pid(*a):return 'synthetic'
  class Provider:
   def __init__(self):self.client=N(base_url=N(host='api.deepseek.com',scheme='https'))
   def get_model(self):return 'synthetic'
  provider=Provider()
  async def get(*a):return provider
  ctx=N(get_platform_inst=lambda _:N(get_client=lambda:api),get_config=lambda _:cfg,get_current_chat_provider_id=pid,provider_manager=N(get_provider_by_id=get))
  p=AffectPlugin(ctx)
  async def pause(x):delays.append(x)
  p.reply_pause=pause;await p.initialize();memory=P1GroupMemory(ctx);affect=P1GroupAffect(ctx);style=P1QQStyle(ctx)
  await memory.initialize();await affect.initialize();await style.initialize();await p.qq.refresh(True)
  class E(Event):
   def get_message_type(self):return MessageType.GROUP_MESSAGE if self.group else MessageType.FRIEND_MESSAGE
   def get_messages(self):return self.parts
   async def send(self,*args):raise AssertionError('raw synthetic event transport must not be used')
   def stop_event(self):self.stopped=True
   def __init__(self,*a,parts=None,**kw):super().__init__(*a,**kw);self.parts=parts or [Plain(self.message_obj.message_str)];self.stopped=False
  e=E('20003','30003',text='伙伴，你觉得这个话题怎么样',parts=[At(qq='10001'),Plain('这个话题怎么样')])
  await p.groups.route(e);assert e.get_extra('_p1_group_admitted')
  req=ProviderRequest(prompt=e.message_obj.message_str,system_prompt='PRIVATE_SENTINEL',contexts=[{'role':'user','content':'PRIVATE_SENTINEL'}],func_tool=ToolSet([FunctionTool(name=n,description='synthetic',parameters={'type':'object','properties':{}}) for n in ('p1_qq_social','p1_qq_stickers','p1_qq_records','p1_browser')]))
  await p.groups.prepare(e,req)
  assert {x.name for x in req.func_tool.tools}=={'p1_qq_social','p1_qq_stickers','p1_qq_records'}
  assert 'PRIVATE_SENTINEL' not in str(req) and '[P1-QQ-ACTIONS:v1]' in req.system_prompt
  r=json.loads(await p.qq_social_tool(e,'list'));assert len(r['targets'])==1 and r['targets'][0]['type']=='group'
  r=json.loads(await p.qq_social_tool(e,'send',p.qq.event_ref(Event('20002')),'不能越权'));assert not r['ok']
  await p.groups.finish(e)
  # Start an unsolicited group topic via the SAME SocialController.tick, never a second worker.
  day=datetime(2026,10,24,10,tzinfo=ZoneInfo('Asia/Shanghai')).timestamp()
  async def evaluate(row):return {'contact':True,'reason':'open_topic','message':'这个话题让我想到另一点，你们怎么看','sticker':''}
  p.qq.evaluate=evaluate
  with patch('time.time',return_value=day):
   p.qq.synced=day
   # The fixed test clock can precede real wall time; explicitly age test ingress.
   with p.qq.store.db() as c:c.execute('UPDATE p1_qq_targets SET last_inbound=?',(day-3600,))
   for row in p.qq.store.targets():p.qq.store.defer(row['ref'],day-1 if row['kind']=='group' else day+3600)
   await p.social.tick()
   assert api.sent[-1][0]=='send_group_msg' and api.sent[-1][1]['group_id']==30003
   assert p.qq.group_open('10001','30003',day)
   async def addressed(event,text,recent,same):return same and '接着' in text
   p.groups.classify=addressed
   follow=E('20003','30003',text='我接着刚才的话说',mid='102');await p.groups.route(follow)
   assert follow.get_extra('_p1_group_admitted'), 'a reply to her own new topic must not require another @'
   await p.groups.finish(follow)
  assert all(2<=x<=5 for x in delays)
  await style.terminate();await memory.terminate();await p.terminate()
  print(json.dumps({'native_qq_runtime':True,'new_tools':3,'group_tool_scope_isolated':True,'single_scheduler_group_opening':True,'unmentioned_reply_to_own_topic_admitted':True,'actual_onebot_payload':True,'send_delay_2_to_5':True,'real_qq_messages':0,'production_database_modified':False},ensure_ascii=False))
asyncio.run(main())
