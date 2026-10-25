import json,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import patch
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'release'));sys.path.insert(0,str(R/'tests'))
from astrbot_plugin_affect.thinking import Thinking,effort_for,MAX_PROVIDER,FAST_PROVIDER,latency_report
from astrbot_plugin_affect.public_research import Research
from test_qq_actions import Event
class ThinkingTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.d=Path(self.tmp.name);self.calls=[];self.valid=True
  self.cfg={'provider':[{'id':MAX_PROVIDER,'enable':True,'model':'deepseek-flash','custom_extra_body':{'reasoning_effort':'max'}}]}
  class Client:
   base_url=N(host='api.deepseek.com',scheme='https')
   def __init__(me):me.chat=N(completions=me)
   def with_options(me,**kw):return me
   async def create(me,**kw):
    self.calls.append(kw)
    return N(choices=[N(message=N(content=json.dumps({'decision':'先听清楚对方的意思','uncertainties':[],'next_step':'简短回应'})))],usage=N(completion_tokens=210,completion_tokens_details=N(reasoning_tokens=180)))
  async def pid(*a):return 'normal'
  async def provider(*a):return N(client=Client(),get_model=lambda:'deepseek-flash')
  self.plugin=N(scope_for=lambda e:'v1:'+'a'*64 if self.valid else None,enabled=lambda:True,store=N(take_budget=lambda *a,**kw:True),context=N(get_config=lambda *a:self.cfg,get_current_chat_provider_id=pid,provider_manager=N(get_provider_by_id=provider)))
  self.t=Thinking(self.plugin,self.d);self.t.migrate();self.plugin.thinking=self.t
 async def asyncTearDown(self):self.tmp.cleanup()
 def test_small_ack_and_substantive_topics(self):
  for x in ['嗯','谢谢你','晚安','哈哈哈！','好的']:self.assertEqual(effort_for(x),'high')
  for x in ['我很难过，但又觉得自己没资格难过','你怎么看','帮我比较这几条记录再决定怎么回','最近呢','沙季，你觉得我们这样合适吗']:self.assertEqual(effort_for(x),'max')
 async def test_native_route_is_event_local_not_global(self):
  a=Event(text='我有点矛盾，不知道怎么面对这件事');b=Event(text='谢谢')
  await self.t.select(a);await self.t.select(b)
  self.assertEqual(a.get_extra('selected_provider'),MAX_PROVIDER);self.assertIsNone(b.get_extra('selected_provider'))
  self.assertEqual(self.cfg['provider'][0]['custom_extra_body'],{'reasoning_effort':'max'})
  await self.t.select(a)
  with self.t.db() as c:self.assertEqual(c.execute('select count(*) from p1_thinking_audit').fetchone()[0],2)
 async def test_missing_or_disabled_max_does_not_break_normal_chat(self):
  self.cfg['provider'][0]['enable']=False;e=Event(text='认真解释一下')
  await self.t.select(e);self.assertIsNone(e.get_extra('selected_provider'));self.assertEqual(e.get_extra('_p1_thinking_selected'),'high')
 async def test_casual_autonomous_group_reply_uses_scoped_quick_provider(self):
  self.cfg['provider'].append({'id':FAST_PROVIDER,'enable':True,'model':'deepseek-flash','custom_extra_body':{'thinking':{'type':'disabled'},'max_tokens':2048}})
  for lane in ('native','interest'):
   e=Event(group='30003',text='这个配乐的节奏真不错');e.set_extra('_p1_group_auto_route',lane)
   await self.t.select(e);self.assertEqual(e.get_extra('selected_provider'),FAST_PROVIDER);self.assertEqual(e.get_extra('_p1_thinking_selected'),'fast')
  private=Event(text='这个配乐的节奏真不错');await self.t.select(private);self.assertEqual(private.get_extra('selected_provider'),MAX_PROVIDER)
  serious=Event(group='30003',text='我很难过，不知道该怎么办');serious.set_extra('_p1_group_auto_route','native')
  await self.t.select(serious);self.assertEqual(serious.get_extra('selected_provider'),MAX_PROVIDER)
  self.assertEqual(self.cfg['provider'][0]['custom_extra_body'],{'reasoning_effort':'max'})
 async def test_missing_malformed_and_unapproved_quick_fall_back(self):
  for body in (None,{'thinking':{'type':'disabled'},'max_tokens':'2048'},{'thinking':{'type':'enabled'},'max_tokens':2048}):
   self.cfg['provider'][:]=self.cfg['provider'][:1];self.cfg['provider'].append({'id':FAST_PROVIDER,'enable':True,'model':'deepseek-flash','custom_extra_body':body})
   e=Event(group='30003',text='这段配乐挺好听');e.set_extra('_p1_group_auto_route','native');await self.t.select(e)
   self.assertEqual(e.get_extra('selected_provider'),MAX_PROVIDER)
  self.cfg['provider'][-1]['custom_extra_body']={'thinking':{'type':'disabled'},'max_tokens':2048}
  async def wrong(*a):return N(client=N(base_url=N(host='example.com',scheme='https')))
  self.plugin.context.provider_manager.get_provider_by_id=wrong
  e=Event(group='30003',text='这段配乐挺好听');e.set_extra('_p1_group_auto_route','native');await self.t.select(e)
  self.assertEqual(e.get_extra('selected_provider'),MAX_PROVIDER)
 def test_latency_metrics_split_delay_from_generation_without_content(self):
  e=Event(text='password=synthetic_secret');e.set_extra('_p1_reply_clock',{'start':0,'input':0,'admitted':2,'prompt_ready':3,'response_ready':7,'send_queued':8,'send_unlocked':10,'send_delayed':13})
  with patch('time.monotonic',return_value=14):r=latency_report(e)
  self.assertEqual(r['total_ms'],14000);self.assertEqual(r['send_queue_ms'],2000);self.assertEqual(r['required_delay_ms'],3000);self.assertEqual(r['generation_and_tools_ms'],4000)
  self.assertNotIn('synthetic_secret',json.dumps(r));self.assertNotIn('20002',json.dumps(r))
 async def test_revoked_scope_never_routes_or_deliberates(self):
  self.valid=False;e=Event(text='帮我思考');await self.t.select(e)
  self.assertIsNone(e.get_extra('selected_provider'));self.assertFalse((await self.t.deliberate(e,'合成问题'))['ok']);self.assertFalse(self.calls)
 async def test_voluntary_max_exact_api_parameters_and_usage(self):
  e=Event();out=await self.t.deliberate(e,'合成问题：如何自然接话又不冒然推断')
  self.assertTrue(out['ok']);self.assertFalse(out['actions_executed'])
  self.assertEqual(self.calls[0]['reasoning_effort'],'max');self.assertEqual(self.calls[0]['extra_body'],{'thinking':{'type':'enabled'}})
  self.assertFalse((await self.t.deliberate(e,'第二次'))['ok'])
  with self.t.db() as c:self.assertEqual(c.execute('select reasoning_tokens,completion_tokens from p1_thinking_audit').fetchone(),(180,210))
 async def test_credential_question_never_sent(self):
  self.assertFalse((await self.t.deliberate(Event(),'password=privatecredential'))['ok']);self.assertFalse(self.calls)
 async def test_public_research_denies_side_effects_credentials_and_private_hosts(self):
  research=Research(self.plugin);e=Event()
  for action,q,url in [('post','',''),('search','我的聊天记录',''),('search','password=abc',''),('read','','https://127.0.0.1/'),('read','','https://gimaiseikatsu-anime.com/login')]:self.assertFalse((await research.run(e,action,q,url))['ok'])
  self.valid=False;self.assertEqual((await research.run(e,'search','轻小说'))['error'],'forbidden')
if __name__=='__main__':unittest.main()
