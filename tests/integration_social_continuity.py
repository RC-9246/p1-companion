"""Real AstrBot SDK, isolated ledgers, fake provider and OneBot; no QQ sends."""
import asyncio,json,os,runpy,sys,tempfile,time
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
R=Path(__file__).resolve().parents[1];sys.path[:0]=[str(R/'release'),str(R/'tests')]
from test_companion import init_db
from astrbot_plugin_affect.identity import make_identity_key
from astrbot_plugin_affect.social_context import awaiting_reply
from astrbot_plugin_affect.social_runtime import SocialController
from astrbot_plugin_affect.companion_store import CompanionStore
from astrbot_plugin_p1_learning.store import Store
from astrbot_plugin_p1_learning.policy import fast_preferences
from astrbot_plugin_p1_learning.main import P1Learning
async def run():
 with tempfile.TemporaryDirectory() as tmp:
  d=Path(tmp)/'affect';d.mkdir();init_db(d/'affect.db');identity=make_identity_key('qq_snowluma','10001','20002');other=make_identity_key('qq_snowluma','10001','20003');umo='qq_snowluma:FriendMessage:20002';(d/'allowed_identities.json').write_text(json.dumps({'version':1,'allowed_identities':[identity]}))
  ledger=Store(d/'affect.db');ledger.migrate();ledger.record(identity,'e','current_user','面试完了，等下午结果','结果出来了吗？');ledger.record(other,'other','current_user','OTHER_PRIVATE_SENTINEL','其他人的回复')
  class Learning:
   async def active(self,scope):return ledger.cards(scope)
   expression_hints=P1Learning.expression_hints
  learning=Learning();captured=[];history=[{'role':'user','content':'更早的问题'},{'role':'assistant','content':'更早回答'},{'role':'user','content':'面试完了，等下午结果'},{'role':'assistant','content':'结果出来了吗？'}]
  class Client:
   base_url=NS(scheme='https',host='api.deepseek.com')
   def __init__(self):self.chat=NS(completions=self)
   def with_options(self,**kw):return self
   async def create(self,**kw):captured.append(kw);return NS(choices=[NS(message=NS(tool_calls=None,content='{"contact":false,"reason":"none","evidence":[],"message":""}'))])
  client=Client()
  class Context:
   _p1_learning=learning
   @property
   def provider_manager(self):return self
   @property
   def conversation_manager(self):return self
   async def get_current_chat_provider_id(self,*a):return 'fake'
   async def get_provider_by_id(self,*a):return NS(client=client,get_model=lambda:'fake')
   async def get_curr_conversation_id(self,*a):return 'scope'
   async def get_conversation(self,*a):return NS(user_id=umo,updated_at=time.time(),history=json.dumps(history))
  ctx=Context();store=CompanionStore(d/'affect.db');store.migrate();p=NS(context=ctx,store=store,enabled=lambda:True,persona='synthetic');c=SocialController(p,d);c.store.migrate();c.idle.migrate();c.store.enroll(identity,umo,'20002','10001',time.time()-5*3600);row=c.store.get(identity)
  async def findings(row):return []
  c.discoveries=findings
  facts=await c.evidence(row);assert len(facts)==1 and facts[0]['kind']=='delivered_exchange' and 'SENTINEL' not in str(facts)
  assert awaiting_reply(facts,time.time());decision=await c.evaluate(row);assert decision['reason']=='awaiting_reply' and not captured
  # A newer human request must not disappear because the prior exchange has a receipt.
  history.append({'role':'user','content':'我想明天下午你再问一次结果'})
  facts=await c.evidence(row);assert facts[-1]['kind']=='recent_user' and not awaiting_reply(facts,time.time())
  ledger.record(identity,'pref','current_user','以后不要每次都追问我','嗯');pref=next(x for x in ledger.turns(identity) if x['id']=='pref');ledger.save(identity,1,fast_preferences(pref))
  # Pending/correction cards must never be promoted to policy by the bridge.
  ledger.save(identity,1,[dict(kind='correction',key='context_fake',value='UNCONFIRMED_SENTINEL',source='fake',quote='UNCONFIRMED_SENTINEL',speaker='current_user',seq=99,confidence=.95)])
  out=await learning.expression_hints(identity);assert any(x['key']=='followup' for x in out) and 'SENTINEL' not in str(out)
  await c.evaluate(row);payload=json.loads(captured[-1]['messages'][-1]['content']);assert payload['response_preferences']==out
  bad=dict(row,user_id='20003');count=len(captured);assert not await c.evidence(bad) and (await c.evaluate(bad))['reason']=='not_allowed';assert len(captured)==count
  ledger.control(identity,'off');assert await learning.expression_hints(identity)==[];facts=await c.evidence(row);assert all(x['kind']!='delivered_exchange' for x in facts)
  print(json.dumps({'exact_owner_scope':True,'only_receipt_backed_assistant_context':True,'older_framework_text_does_not_cancel_pending_guard':True,'newer_unanswered_human_preserved':True,'no_repeat_question_within_24h':True,'learned_preferences_bridge':True,'pending_corrections_excluded':True,'learning_pause_blocks_background_use':True,'recipient_forgery_denied_before_model':True,'actual_qq_messages':0,'production_db_modified':False}))
asyncio.run(run())
# Exercise the existing shared queue/arrival/disable/unknown-result guards in a simulated
# permitted send window. Real quiet-hour rules remain covered separately in unit tests.
with patch('astrbot_plugin_affect.social.in_quiet',return_value=False),patch('astrbot_plugin_affect.social_runtime.in_quiet',return_value=False):
 runpy.run_path(str(R/'tests/integration_social.py'),run_name='__main__')
print('quiet_window_simulated_for_transport_only=true')
