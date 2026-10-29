"""Real native probability predicate, isolated P1 routing and fake QQ receipts."""
import asyncio,json,os,sys,tempfile
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import AsyncMock,patch
from datetime import datetime
from zoneinfo import ZoneInfo
R=Path(__file__).resolve().parents[1];sys.path[:0]=[str(R/'release'),str(R/'tests')]
from test_companion import init_db
from test_qq_actions import API,Event
from astrbot.core.message.components import At,Plain
from astrbot.core.message.message_event_result import MessageChain
from astrbot.core.platform.message_type import MessageType

async def run():
 with tempfile.TemporaryDirectory() as tmp:
  d=Path(tmp)/'data/plugin_data/affect';d.mkdir(parents=True);os.environ['P1_COMPANION_DATA']=str(d);init_db(d/'affect.db')
  from astrbot_plugin_affect.main import AffectPlugin
  from astrbot_plugin_affect.identity import make_identity_key
  from astrbot_plugin_affect.qq_policy import DEFAULT
  owner=make_identity_key('qq_snowluma','10001','20002')
  (d/'allowed_identities.json').write_text(json.dumps({'version':1,'allowed_identities':[owner]}))
  (d/'groups.json').write_text(json.dumps({'version':1,'groups':[{'bot':'10001','group':'30003'}]}))
  (d/'qq_policy.json').write_text(json.dumps(dict(DEFAULT,enabled=True)))
  native={'enable':True,'method':'possibility_reply','possibility_reply':1.0,'whitelist':[]}
  cfg={'platform_settings':{'enable_id_white_list':True,'id_whitelist':['qq_snowluma:FriendMessage:20002']},'provider_ltm_settings':{'active_reply':native}}
  from astrbot_plugin_affect.thinking import FAST_PROVIDER,MAX_PROVIDER
  cfg['provider']=[{'id':FAST_PROVIDER,'enable':True,'model':'deepseek-flash','custom_extra_body':{'thinking':{'type':'disabled'},'max_tokens':2048}},
   {'id':MAX_PROVIDER,'enable':True,'model':'deepseek-flash','custom_extra_body':{'reasoning_effort':'max','thinking':{'type':'enabled'}}}]
  (d.parents[1]/'cmd_config.json').write_text(json.dumps(cfg))
  api=API();delays=[]
  async def send_group_msg(**kw):return await api.call_action('send_group_msg',**kw)
  api.send_group_msg=send_group_msg
  async def pid(*a):return 'synthetic'
  async def provider(*a):return N(client=N(base_url=N(host='api.deepseek.com',scheme='https')))
  ctx=N(get_config=lambda *a,**kw:cfg,get_platform_inst=lambda _:N(get_client=lambda:api),get_current_chat_provider_id=pid,provider_manager=N(get_provider_by_id=provider))
  p=AffectPlugin(ctx)
  async def pause(n):delays.append(n)
  p.reply_pause=pause;await p.initialize()
  assert not json.loads((d/'companion_health.json').read_text())['quick_group_provider_ready']
  ctx.provider_manager.inst_map={FAST_PROVIDER:N()};await p.provider_ready_health()
  assert json.loads((d/'companion_health.json').read_text())['quick_group_provider_ready']
  class E(Event):
   seq=0
   def __init__(self,parts=None,group='30003'):
    E.seq+=1;super().__init__('20003',group,text='动画配乐里这个节奏挺有意思',mid=str(E.seq));self.parts=parts or [Plain(self.message_obj.message_str)]
   def get_messages(self):return self.parts
   def get_message_type(self):return MessageType.GROUP_MESSAGE
   def stop_event(self):self.stopped=True
   async def send(self,*a):raise AssertionError('raw QQ transport bypass')
  scope=p.qq.group_key('10001','30003')
  async def interest(e,*a):
   accepted=p.agency.store.join(scope,__import__('time').time())
   if accepted:e.set_extra('_p1_interest_join',True)
   return accepted
  p.agency.interest=interest;p.groups.classify=AsyncMock(side_effect=AssertionError('no classifier for automatic or direct route'))
  now=datetime(2026,10,25,12,tzinfo=ZoneInfo('Asia/Shanghai')).timestamp()
  try:
   with patch('time.time',side_effect=lambda:now):
    await p.qq.refresh(True)
    for a,b in ((0,0),(1,0),(0,1),(1,1)):
     p.agency.store.route_config(scope,native=a,p1=b,interest=1,background=1)
     e=E();accepted=await p.groups.route(e);assert accepted==bool(a or b)
     if accepted:
      assert e.get_extra('_p1_group_auto_route')==('interest' if b else 'native')
      assert e.get_extra('selected_provider')==FAST_PROVIDER
      assert not await p.groups.route(e),'same actual message cannot be selected twice'
      await p.groups.finish(e)
    p.agency.store.route_config(scope,native=1,p1=0)
    for key,value in [('enable',False),('possibility_reply',0.0),('whitelist',['30004'])]:
     previous=native[key];native[key]=value;assert not await p.groups.route(E());native[key]=previous
    native['whitelist']=['30003'];e=E();assert await p.groups.route(e);await p.groups.finish(e);native['whitelist']=[]
    with patch('astrbot_plugin_affect.qq_policy.quiet',return_value=True):assert not await p.groups.route(E())
    p.agency.store.config(scope,paused=1);assert not await p.groups.route(E());p.agency.store.config(scope,paused=0)
    assert not await p.groups.route(E(group='30004'))
    # Only one scoped send, through delay and shared proactive reservation.
    e=E();assert await p.groups.route(e);await e.send(MessageChain([Plain('这段节奏确实挺特别')]))
    assert len(api.sent)==1 and api.sent[0][0]=='send_group_msg'
    timing=json.loads((d/'group_latency_last.json').read_text());assert timing['route']=='native' and timing['effort']=='fast' and timing['required_delay_ms'] is not None
    assert '20003' not in json.dumps(timing) and '30003' not in json.dumps(timing)
    with p.qq.store.db() as c:
     row=c.execute('SELECT event,proactive,state FROM p1_qq_actions').fetchone()
     assert row['event'].startswith('native:') and row['proactive']==1 and row['state']=='sent'
    await p.groups.finish(e)
    # Toggle either lane after selection but during delay: no late delivery.
    now+=3601
    assert not p.qq.allowed(p.qq.store.target(p.qq.event_ref(E()))),'stale directory must fail closed'
    await p.qq.refresh(True)
    e=E();selected=await p.groups.route(e)
    if not selected:
     row=p.qq.store.target(p.qq.event_ref(e))
     raise AssertionError({'phase':'late_disable_selection','native_candidate':await p.groups.native_candidate(e),'routes':p.agency.store.reply_routes(scope),'qq_allowed':p.qq.allowed(row),'native_allowed':p.qq.autonomy_allowed(row,'native'),'shared_limit':p.qq.store.can_action(row,now,p.qq.policy(),True),'p1_paused':p.agency.store.ensure(scope)['paused']})
    async def disable(n):delays.append(n);p.agency.store.route_config(scope,native=0)
    p.reply_pause=disable;await e.send(MessageChain([Plain('不应投递')]))
    assert len(api.sent)==1 and e.get_extra('_p1_send_cancelled');await p.groups.finish(e)
    p.reply_pause=pause;p.agency.store.route_config(scope,native=0,p1=1,interest=1,background=0)
    row=p.qq.store.target(p.qq.event_ref(E()))
    assert p.qq.autonomy_allowed(row,'interest') and not p.qq.autonomy_allowed(row,'background')
    p.agency.store.route_config(scope,interest=0,background=1)
    assert not p.qq.autonomy_allowed(row,'interest') and p.qq.autonomy_allowed(row,'background')
    # Explicit @ remains conversational when all unsolicited routes are off.
    p.agency.store.route_config(scope,native=0,p1=0);e=E([At(qq='10001'),Plain('你好')])
    assert await p.groups.route(e) and not e.get_extra('_p1_group_auto_route');await p.groups.finish(e)
    assert e.get_extra('_p1_thinking_selected')=='high' and e.get_extra('selected_provider')!=FAST_PROVIDER
    e=E([At(qq='10001'),Plain('你上次误解了两个人的意思，请认真比较前后的矛盾')]);e.message_obj.message_str='你上次误解了两个人的意思，请认真比较前后的矛盾'
    assert await p.groups.route(e);await p.groups.finish(e)
    assert e.get_extra('selected_provider')==MAX_PROVIDER and e.get_extra('_p1_thinking_selected')=='max'
    assert all(2<=x<=5 for x in delays)
  finally:await p.terminate()
  result={'native_probability_predicate_used':True,'four_native_p1_combinations':True,'p1_selected_before_probability_fallback':True,'native_ui_enable_probability_whitelist_honored':True,'independent_interest_and_background':True,'same_message_deduplicated':True,'single_scoped_transport_and_receipt':True,'shared_proactive_limit_ledger':True,'late_disable_cancels_send':True,'stale_directory_denied_then_verified_refresh':True,'quiet_pause_and_enrollment_preserved':True,'normal_mentions_with_both_routes_off':True,'casual_auto_selects_quick_after_real_admission':True,'complex_mention_selects_max':True,'ordinary_mention_uses_configured_provider':True,'content_free_phase_metrics_written_after_receipt':True,'delay_2_to_5_preserved':True,'fake_qq_sends':1,'real_qq_sends':0,'model_requests':0,'production_database_modified':False}
  (R/'evidence/reply-routes-native.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
if __name__=='__main__':asyncio.run(run())
