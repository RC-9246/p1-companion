"""SDK-present isolated foreground latency acceptance; no QQ or model network calls."""
import asyncio,json,os,sys,tempfile,time
from pathlib import Path
from types import SimpleNamespace as N
from astrbot.api import logger
R=Path(__file__).resolve().parents[1];sys.path[:0]=[str(R/'release'),str(R/'tests')]
from astrbot_plugin_affect.agency_runtime import Agency
async def run():
 with tempfile.TemporaryDirectory() as tmp:
  calls=[];options=[];mode='normal';valid=True;approved=True;budget=True;charges=[]
  class Client:
   @property
   def base_url(self):return N(host='api.deepseek.com' if approved else 'example.com',scheme='https')
   def __init__(self):self.chat=N(completions=self)
   def with_options(self,**kw):options.append(kw);return self
   async def create(self,**kw):
    nonlocal valid
    calls.append(kw)
    if mode=='slow':await asyncio.sleep(8)
    if mode=='revoke':valid=False
    return N(choices=[N(message=N(content=json.dumps({'join':True,'confidence':.96,'topic':'music'})))])
  async def pid(*a):return 'normal'
  async def provider(*a):return N(client=Client(),get_model=lambda:'deepseek-flash')
  a=Agency(N(context=N(get_current_chat_provider_id=pid,provider_manager=N(get_provider_by_id=provider))),tmp)
  a.row_valid=lambda _:valid
  def take(*args):charges.append(args);return budget
  a.store.take_model_budget=take
  row={'peer':'30003','identity':'g1:'+'a'*64,'kind':'group'}
  await a.gate.acquire();start=time.monotonic()
  answer=await a.interest_vote(row,'这个配乐的节奏挺特别',[],['music']);free_seconds=time.monotonic()-start
  assert answer['join'] is True and free_seconds<1,'background gate must not queue foreground ingress'
  a.gate.release()
  assert options[-1]=={'timeout':2.5,'max_retries':0}
  assert calls[-1]['max_tokens']==160 and calls[-1]['extra_body']=={'thinking':{'type':'disabled'}}
  before=len(calls);charged=len(charges);await a.interest_gate.acquire();start=time.monotonic()
  assert await a.interest_vote(row,'音乐',[],['music'])=={} and time.monotonic()-start<.1
  assert len(calls)==before and len(charges)==charged;a.interest_gate.release()
  mode='slow';start=time.monotonic();assert await a.interest_vote(row,'音乐',[],['music'])=={}
  timeout_seconds=time.monotonic()-start;assert 2.8<=timeout_seconds<4.5 and not a.interest_gate.locked(),{'timeout_seconds':timeout_seconds}
  mode='revoke';assert await a.interest_vote(row,'音乐',[],['music'])=={} and not a.interest_gate.locked()
  valid=True;mode='normal';approved=False;before=len(calls);charged=len(charges)
  assert await a.interest_vote(row,'音乐',[],['music'])=={} and len(calls)==before and len(charges)==charged
  approved=True;budget=False;assert await a.interest_vote(row,'音乐',[],['music'])=={} and len(calls)==before
  budget=True;task=asyncio.create_task(a.interest_vote(row,'音乐',[],['music']));mode='slow';await asyncio.sleep(.05);task.cancel()
  result=await asyncio.gather(task,return_exceptions=True);assert isinstance(result[0],asyncio.CancelledError) and not a.interest_gate.locked()
  os.environ['P1_COMPANION_DATA']=str(Path(tmp)/'data/plugin_data/affect')
  from astrbot_plugin_p1_group_affect.main import P1GroupAffect
  from test_qq_actions import Event
  affect=P1GroupAffect(N());affect.store=N(seed_affect=lambda *a:None,affect=lambda *a:(None,None,None))
  async def slow_provider(*a):await asyncio.sleep(8)
  groups=N(memory=N(key=lambda e:'g1:'+'a'*64),provider=slow_provider,plugin=N(store=N(take_budget=lambda *a,**kw:True),reaction_catalog=None))
  scene={'current':{'speaker':'20003','text':'今天的配乐不错','id':'synthetic'},'messages':[],'epoch':1}
  async def appraisal():
   e=Event(group='30003');request=N(extra_user_content_parts=[],system_prompt='');await affect.prepare(e,request,scene,groups)
   assert e.get_extra('_p1_group_affect_pending') and any('[P1-GROUP-AFFECT:v1]' in part.text for part in request.extra_user_content_parts)
  await affect.gate.acquire();start=time.monotonic();await appraisal();busy_affect=time.monotonic()-start;affect.gate.release()
  assert busy_affect<1,'busy appraisal must retain local affect without queuing'
  start=time.monotonic();await appraisal();slow_affect=time.monotonic()-start
  assert 4.8<=slow_affect<6.5 and not affect.gate.locked(),'provider lookup is within whole appraisal deadline'
  report={'background_gate_held_foreground_still_completed':True,'foreground_vote_seconds':round(free_seconds,3),'busy_foreground_skips_without_api_or_budget':True,
   'whole_vote_deadline_seconds':3,'observed_timeout_seconds':round(timeout_seconds,3),'timeout_revocation_cancellation_release_gate':True,'destination_and_budget_checked':True,
   'busy_affect_fallback_seconds':round(busy_affect,3),'appraisal_provider_timeout_seconds':round(slow_affect,3),'appraisal_fallback_keeps_scoped_emotion_hint':True,
   'decision_tokens_cap':160,'decision_thinking_disabled':True,'decision_sdk_retries':0,'real_model_calls':0,'real_qq_messages':0,'production_database_modified':False}
  (R/'evidence/group-latency-isolated.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
if __name__=='__main__':asyncio.run(run())
