"""Actual AstrBot classes; synthetic identities, temporary DB, no network or QQ."""
import asyncio,json,os,sys,tempfile,sqlite3,time
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'release'));sys.path.insert(0,str(R/'tests'))
from test_companion import init_db
from astrbot_plugin_affect.identity import make_identity_key
from astrbot.core.provider.entities import ProviderRequest,LLMResponse

async def run():
 with tempfile.TemporaryDirectory() as t:
  data=Path(t);os.environ['P1_COMPANION_DATA']=t;init_db(data/'affect.db');identity=make_identity_key('qq_snowluma','10001','20002')
  (data/'allowed_identities.json').write_text(json.dumps({'version':1,'allowed_identities':[identity]}))
  from astrbot_plugin_affect.main import AffectPlugin
  from astrbot_plugin_p1_stickers.main import P1Stickers,extract
  from astrbot_plugin_p1_reflection.main import P1Reflection,safe_result
  from astrbot_plugin_p1_reflection.vendor.core.models import DeepEvidence
  from astrbot_plugin_affect.companion_store import CompanionStore
  from astrbot_plugin_affect.social_runtime import SocialController
  calls=[]
  class Client:
   base_url=SimpleNamespace(host='api.deepseek.com',scheme='https')
   def __init__(self):self.chat=SimpleNamespace(completions=self)
   def with_options(self,**kw):return self
   async def create(self,**kw):
    calls.append(kw)
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(dict(confidence='medium',relationship_summary='对方明确希望日常回复简短一些。',impression='把话说得具体一点就好。'),ensure_ascii=False)))])
  class Context:
   @property
   def provider_manager(self):return self
   async def get_current_chat_provider_id(self,*args):return 'synthetic'
   async def get_provider_by_id(self,*args):return SimpleNamespace(client=Client(),get_model=lambda:'synthetic')
  class Event:
   def __init__(self,text='好呀，谢谢',sender='20002'):
    self.message_obj=SimpleNamespace(message_str=text);self.extra={'_p1_companion_pending':{'appraisal':dict(intent='casual',emotion='happy',relation='none',confidence=.95)}};self.sender=sender
   def get_platform_id(self):return 'qq_snowluma'
   def get_self_id(self):return '10001'
   def get_sender_id(self):return self.sender
   def is_private_chat(self):return True
   def get_extra(self,k,default=None):return self.extra.get(k,default)
   def set_extra(self,k,v):self.extra[k]=v
  context=Context();store=CompanionStore(data/'affect.db');store.migrate()
  from astrbot_plugin_affect.reactions import ReactionStore
  ReactionStore(data/'affect.db').migrate()
  stickers=P1Stickers(context);await stickers.initialize();event=Event();req=ProviderRequest(prompt='谢谢')
  await stickers.describe(event,req);assert '[P1-STICKERS:v2]' in req.system_prompt
  resp=LLMResponse(role='assistant',completion_text='嗯，完成了。<sticker name="saki_smile"/>');await stickers.select(event,resp)
  assert event.extra['_p1_saki_reaction']=='saki_smile' and '<sticker' not in resp.completion_text
  tag_only=Event();resp=LLMResponse(role='assistant',completion_text='<sticker name="saki_smile"/>');await stickers.select(tag_only,resp)
  assert resp.completion_text.strip() and tag_only.get_extra('_p1_saki_reaction')=='saki_smile'
  await AffectPlugin(context).mark_response(tag_only,resp);assert tag_only.get_extra('_p1_companion_pending')['ready']
  serious=Event('不要表情，我现在很难过');resp=LLMResponse(role='assistant',completion_text='我在。<sticker name="saki_smile"/>');await stickers.select(serious,resp)
  assert not serious.get_extra('_p1_saki_reaction') and resp.completion_text=='我在。'
  assert extract('<sticker name="../../private"/>',stickers.catalog.assets)==('',None)
  assert extract('<sticker name="saki_smile"/><sticker name="saki_goodbye"/>',stickers.catalog.assets)[1]=='saki_smile'
  stranger=Event(sender='30003');req=ProviderRequest(prompt='hi');await stickers.describe(stranger,req);assert '[P1-STICKERS' not in req.system_prompt
  reflection=P1Reflection(context);await reflection.initialize()
  answer=await reflection.reflect('synthetic',identity,6,[{'role':'user','content':'日常回复简短些'},{'role':'assistant','content':'嗯，我会说短一点。'}])
  assert answer['relationship_summary'];req=ProviderRequest(prompt='hi');await reflection.inject(event,req);assert len(req.extra_user_content_parts)==1 and req.extra_user_content_parts[0]._no_save
  req=ProviderRequest(prompt='hi');await reflection.inject(stranger,req);assert not req.extra_user_content_parts
  for value in (DeepEvidence(pattern='one_sided'),DeepEvidence(trust_change='down'),DeepEvidence(impression='他欠我回应')):
   try:safe_result(value)
   except ValueError:pass
   else:raise AssertionError('unsafe reflection accepted')
  assert len(calls)==1 and '正常求助、交任务' in calls[0]['messages'][0]['content']
  old_create=Client.create
  async def revoke_after_response(client,**kw):
   out=await old_create(client,**kw)
   (data/'allowed_identities.json').write_text(json.dumps({'version':1,'allowed_identities':[]}))
   return out
  with patch.object(Client,'create',revoke_after_response),patch('time.time',return_value=time.time()+1801):
   stopped=await reflection.reflect('synthetic',identity,12,[{'role':'user','content':'平时回复具体些'},{'role':'assistant','content':'嗯'}],event=event)
  assert stopped is None and reflection.current(identity)[0]==6
  (data/'allowed_identities.json').write_text(json.dumps({'version':1,'allowed_identities':[identity]}))
  # Inbound activity uses the existing worker and cancels idle work promptly.
  plugin=SimpleNamespace(context=context,enabled=lambda:True,store=store)
  social=SocialController(plugin,data);social.store.migrate();social.idle.migrate()
  social.store.enroll(identity,'qq_snowluma:FriendMessage:20002','20002','10001',time.time()-4000)
  cancelled=[]
  async def long_work():
   try:await asyncio.sleep(600)
   finally:cancelled.append(True)
  social.idle.task=asyncio.create_task(long_work());await asyncio.sleep(0)
  event.unified_msg_origin='qq_snowluma:FriendMessage:20002';await social.observe(event,identity,'synthetic-inbound')
  assert cancelled and social.idle.task is None
  await reflection.terminate()
  print(json.dumps({'actual_astrbot_extensions':True,'sticker_catalog':len(stickers.catalog.assets),'closed_tag_selection':True,'serious_context_no_image':True,'identity_isolation':True,'relationship_reflection_applied':True,'revoked_reflection_does_not_persist':True,'refusal_and_score_changes_rejected':True,'inbound_cancels_idle':True,'real_qq_messages':0,'production_db_modified':False}))
asyncio.run(run())
