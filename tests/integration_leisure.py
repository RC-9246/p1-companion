"""Synthetic tool permissions and actual AstrBot registration; no account writes or QQ sends."""
import asyncio,json,os,sys,tempfile
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'release'));sys.path.insert(0,str(ROOT/'tests'))
from test_companion import init_db
from astrbot_plugin_affect.identity import make_identity_key
from astrbot.core.provider.entities import ProviderRequest
from astrbot.core.agent.tool import FunctionTool,ToolSet
async def main():
 with tempfile.TemporaryDirectory() as t:
  data=Path(t);os.environ['P1_COMPANION_DATA']=t;init_db(data/'affect.db')
  subject=make_identity_key('qq_snowluma','10001','20002');(data/'allowed_identities.json').write_text(json.dumps({'version':1,'allowed_identities':[subject]}))
  from astrbot_plugin_affect.main import AffectPlugin
  p=AffectPlugin(SimpleNamespace());await p.initialize();calls=[]
  async def request(identity,action,**params):calls.append((identity,action,params));return {'ok':True,'remaining_seconds':5400}
  p.leisure.request=request
  class Event:
   unified_msg_origin='synthetic'
   def __init__(self,sender='20002',private=True):self.sender=sender;self.private=private;self.extra={}
   def get_platform_id(self):return 'qq_snowluma'
   def get_self_id(self):return '10001'
   def get_sender_id(self):return self.sender
   def is_private_chat(self):return self.private
   def get_extra(self,k,d=None):return self.extra.get(k,d)
   def set_extra(self,k,v):self.extra[k]=v
  for e in (Event('30003'),Event(private=False)):
   assert json.loads(await p.bilibili(e,'account'))['error']=='forbidden'
  for action in ('login','logout','poll','comment','danmaku','like','coin','follow','evaluate','open'):
   assert json.loads(await p.bilibili(Event(),action))['error']=='action_not_authorized'
  assert not calls
  e=Event()
  for n in range(6):assert json.loads(await p.bilibili(e,'quota'))['ok']
  assert e.get_extra('_p1_leisure_calls',0)==0 and len(calls)==6
  for n in range(4):assert json.loads(await p.bilibili(e,'search',query='public science'))['ok']
  assert json.loads(await p.bilibili(e,'search',query='public science'))['error']=='budget_exceeded' and len(calls)==10
  assert json.loads(await p.bilibili(e,'stop'))['ok'] and len(calls)==11
  (data/'companion.disabled').touch();assert json.loads(await p.bilibili(Event(),'quota'))['error']=='forbidden'
  req=ProviderRequest(func_tool=ToolSet([FunctionTool(name='p1_bilibili',description='test',parameters={},handler=None)]))
  await p.restrict_companion_tools(Event(),req);assert not req.func_tool.tools
  (data/'companion.disabled').unlink()
  assert (await p.leisure.watch(subject,'synthetic','BV1xx411c7mD',901))['ok'] is False
  from astrbot.core.star.star_handler import star_handlers_registry
  assert any('bilibili' in str(getattr(x,'handler_full_name','')) or 'bilibili' in str(getattr(x,'handler_name','')) for x in star_handlers_registry)
  # Response packets may split a large frame JSON at arbitrary byte boundaries.
  from astrbot_plugin_affect.leisure import Leisure
  (data/'leisure_token').write_text('synthetic-not-a-real-token')
  payload=json.dumps({'ok':True,'data':'x'*220000}).encode()
  class Content:
   async def iter_chunked(self,n):
    for i in range(0,len(payload),7919):yield payload[i:i+7919]
  class Reply:
   content=Content()
   async def __aenter__(self):return self
   async def __aexit__(self,*a):pass
  class Session:
   async def __aenter__(self):return self
   async def __aexit__(self,*a):pass
   def post(self,*a,**kw):return Reply()
  with patch('astrbot_plugin_affect.leisure.aiohttp.ClientSession',return_value=Session()):
   assert (await Leisure(p,data).request(subject,'quota'))['data']=='x'*220000
   payload=b'x'*1800001
   try:await Leisure(p,data).request(subject,'quota')
   except ValueError as exc:assert str(exc)=='broker_response_too_large'
   else:raise AssertionError('oversized image response not bounded')
  await p.terminate()
 print(json.dumps({'bilibili_runtime_gates':True,'real_framework_tool_registered':True,'cross_user_group_paused_denied':True,'llm_cannot_login_or_publicly_post':True,'turn_budget_enforced':True,'fragmented_large_response_and_size_cap':True,'real_account_writes':0,'qq_sends':0}))
asyncio.run(main())
