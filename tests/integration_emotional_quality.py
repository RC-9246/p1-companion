"""Reflection failure recovery and persistence with actual AstrBot classes, isolated storage."""
import asyncio,json,os,sqlite3,sys,tempfile,time
from pathlib import Path
from types import SimpleNamespace
R=Path(__file__).resolve().parents[1];sys.path[:0]=[str(R/'release'),str(R/'tests')]
from test_companion import init_db,I

async def main():
 with tempfile.TemporaryDirectory() as t:
  d=Path(t);os.environ['P1_COMPANION_DATA']=t;init_db(d/'affect.db')
  from astrbot_plugin_affect.companion_store import CompanionStore
  CompanionStore(d/'affect.db').migrate()
  from astrbot_plugin_p1_reflection.main import P1Reflection
  prior=json.dumps({'relationship_summary':'日常简短，不要每次叮嘱休息。','impression':'先把对方的话听完。','confidence':'high'},ensure_ascii=False)
  class Client:
   base_url=SimpleNamespace(host='api.deepseek.com',scheme='https')
   def __init__(self):self.chat=SimpleNamespace(completions=self);self.mode='fail';self.calls=[]
   def with_options(self,**kw):return self
   async def create(self,**kw):
    self.calls.append(kw)
    if kw['messages'][0]['content'].startswith('核对一条即将发送'):
     if self.mode=='fail':raise TimeoutError('synthetic_review_timeout')
     return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({'issues':['time_guess'],'edits':[{'before':'四点开会，那还有时间','after':'嗯，是四点，刚才记错了'}]},ensure_ascii=False)))])
    if self.mode=='fail':raise TimeoutError('synthetic')
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({'relationship_summary':'平时简短、少叮嘱休息；需要解释时可详细。','impression':'先听清这次想要什么。','confidence':self.mode},ensure_ascii=False)))])
  ai=Client()
  class Context:
   def get_config(self,*a):return {'provider':[]}
   @property
   def provider_manager(self):return self
   async def get_current_chat_provider_id(self,*a):return 'synthetic'
   async def get_provider_by_id(self,*a):return SimpleNamespace(client=ai,get_model=lambda:'synthetic')
  p=P1Reflection(Context());await p.initialize()
  with sqlite3.connect(d/'affect.db') as c:c.execute('INSERT INTO p1_reflection VALUES(?,?,?,?,?)',(I,6,time.time()-4000,'complete',prior))
  messages=[{'role':'user','content':'这次帮我详细讲清楚。'},{'role':'assistant','content':'嗯，这次我展开解释。'}]
  try:await p.reflect('synthetic',I,12,messages)
  except TimeoutError:pass
  else:raise AssertionError('failure expected')
  assert p.current(I)[3]==prior and p.current(I)[2]=='complete'
  assert await p.reflect('synthetic',I,13,messages) is None and len(ai.calls)==1
  def reopen():
   with sqlite3.connect(d/'affect.db') as c:c.execute('UPDATE p1_reflection_attempts SET at=?',(time.time()-4000,))
  reopen();ai.mode='low';assert await p.reflect('synthetic',I,14,messages) is None
  assert p.current(I)[3]==prior
  reopen();ai.mode='high';out=await p.reflect('synthetic',I,15,messages)
  assert out and '日常简短' in ai.calls[-1]['messages'][1]['content']
  assert p.current(I)[0]==15 and p.current(I)[2]=='complete'
  await p.terminate()
  from astrbot_plugin_affect.main import AffectPlugin
  from astrbot_plugin_affect.social_runtime import SocialController
  from astrbot_plugin_affect.identity import make_identity_key
  from astrbot.core.provider.entities import ProviderRequest
  subject=make_identity_key('qq_snowluma','10001','20002')
  (d/'allowed_identities.json').write_text(json.dumps({'version':1,'allowed_identities':[subject]}))
  plugin=AffectPlugin(Context());plugin.store=CompanionStore(d/'affect.db');plugin.social=SocialController(plugin,d);plugin.social.store.migrate();plugin.social.idle.migrate()
  plugin.thinking.migrate()
  class Event:
   def __init__(self):self.extra={};self.message_obj=SimpleNamespace(message_id='boundary',message_str='我去和朋友玩，这两天不用惦记着找我。');self.unified_msg_origin='qq_snowluma:FriendMessage:20002'
   def get_platform_id(self):return 'qq_snowluma'
   def get_self_id(self):return '10001'
   def get_sender_id(self):return '20002'
   def is_private_chat(self):return True
   def get_extra(self,k,default=None):return self.extra.get(k,default)
   def set_extra(self,k,v):self.extra[k]=v
   async def send(self,*a):raise AssertionError('no actual transport expected')
  event=Event();await plugin.throttle_inbound_qq(event)
  with sqlite3.connect(d/'affect.db') as c:
   for status,details in [('failed',{'thought':'must_not_surface'}),('complete',{})]:
    c.execute('INSERT INTO companion_idle_runs VALUES(?,?,?,?,?,?,?,?,?)',(status,subject,1,time.time(),status,'rest','reading',1,json.dumps(details)))
  req=ProviderRequest(prompt=event.message_obj.message_str);await plugin.inject_state_into_llm(event,req)
  until=plugin.social.store.paused_until(subject);assert until>time.time()+47*3600
  all_parts='\n'.join(x.text for x in req.extra_user_content_parts)
  assert '已实际暂停主动联系至' in all_parts and '调度器选择安静留白' in all_parts and 'must_not_surface' not in all_parts
  await plugin.inject_state_into_llm(event,req);assert plugin.social.store.paused_until(subject)==until
  assert plugin.store.read(subject)['interaction_count']==0
  from astrbot.core.provider.entities import LLMResponse
  event.message_obj.message_str='你记错了，是四点开会'
  a={'intent':'feedback','relation':'criticism','confidence':.95}
  event.extra['_p1_companion_pending']={'appraisal':a,'ready':False}
  ai.mode='high';response=LLMResponse(role='assistant',completion_text='四点开会，那还有时间')
  await plugin.mark_response(event,response);assert response.completion_text=='嗯，是四点，刚才记错了'
  count=len(ai.calls);await plugin.mark_response(event,response);assert len(ai.calls)==count
  event.extra.pop('_p1_reply_review_done');ai.mode='fail';response=LLMResponse(role='assistant',completion_text='嗯，是四点')
  await plugin.mark_response(event,response);assert response.completion_text=='嗯，是四点'
  print(json.dumps({'reflection_timeout_preserves_prior':True,'rate_limited_after_failure':True,'low_confidence_preserves_prior':True,'previous_preference_in_context':True,'successful_incremental_update_persisted':True,'natural_boundary_reaches_actual_scheduler':True,'boundary_applies_even_without_successful_reply':True,'actual_idle_records_reach_chat':True,'failed_activities_excluded':True,'production_db_modified':False,'qq_messages':0}))
asyncio.run(main())
