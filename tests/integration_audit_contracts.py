"""Real AstrBot imports and message components; synthetic scopes and fake I/O.

Run only in the credential-free acceptance container. No model or QQ endpoint is
called. Ordinary unittest discovery intentionally does not import the SDK.
"""
import asyncio,json,os,sys,tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import AsyncMock,patch
R=Path(__file__).resolve().parents[1];sys.path[:0]=[str(R/'release'),str(R/'tests')]
from test_companion import init_db
from astrbot.core.message.components import Plain
from astrbot.core.message.message_event_result import MessageChain
from astrbot.core.provider.entities import ProviderRequest

class Event:
 seq=0
 def __init__(self,text='合成当前消息'):
  Event.seq+=1;self.extra={};self.unified_msg_origin='qq_snowluma:FriendMessage:20002';self.session_id='20002';self.message_obj=N(message_str=text,message_id=str(Event.seq));self.message_str=text;self._has_send_oper=False
 def get_platform_id(self):return 'qq_snowluma'
 def get_self_id(self):return '10001'
 def get_sender_id(self):return '20002'
 def get_group_id(self):return ''
 def is_private_chat(self):return True
 def get_extra(self,k,d=None):return self.extra.get(k,d)
 def set_extra(self,k,v):self.extra[k]=v
 def plain_result(self,text):return text
 def stop_event(self):pass

class SDKContracts(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.d=Path(self.tmp.name);init_db(self.d/'affect.db')
  os.environ['P1_COMPANION_DATA']=str(self.d)
  from astrbot_plugin_affect import main as M
  self.M=M;self.patch=patch.object(M,'DATA',self.d);self.patch.start();self.addCleanup(self.patch.stop)
  from astrbot_plugin_affect.identity import make_identity_key
  self.identity=make_identity_key('qq_snowluma','10001','20002')
  (self.d/'allowed_identities.json').write_text(json.dumps({'version':1,'allowed_identities':[self.identity]}))
  self.client=N(send_private_msg=AsyncMock(return_value={'message_id':123}))
  async def pid(*a):return 'synthetic'
  self.provider=N(client=N(base_url=N(host='api.deepseek.com',scheme='https')))
  self.ctx=N(get_config=lambda *a,**k:{'admins_id':['20002'],'provider':[]},get_platform_inst=lambda _:N(get_client=lambda:self.client),get_current_chat_provider_id=pid,provider_manager=N(get_provider_by_id=AsyncMock(return_value=self.provider)))
  self.p=M.AffectPlugin(self.ctx)
  from astrbot_plugin_affect.companion_store import CompanionStore
  self.p.store=CompanionStore(self.d/'affect.db');self.p.store.migrate();self.p.thinking.migrate();await self.p.agency.start()
 async def test_private_send_uses_real_parser_and_requires_nonzero_receipt(self):
  e=Event();chain=MessageChain([Plain('合成普通回复')]);original=AsyncMock()
  await self.p.send_with_reaction(e,chain,original)
  original.assert_not_awaited();self.client.send_private_msg.assert_awaited_once();self.assertEqual(e.get_extra('_p1_verified_receipts'),['123'])
  self.client.send_private_msg.return_value={'message_id':0}
  with self.assertRaisesRegex(ValueError,'receipt_missing'):await self.p.send_with_reaction(Event(),chain,original)
 async def test_scope_revoked_during_real_parser_prevents_transport(self):
  from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
  async def parse(_):
   (self.d/'allowed_identities.json').write_text('{"version":1,"allowed_identities":[]}');return []
  with patch.object(AiocqhttpMessageEvent,'_parse_onebot_json',parse):
   with self.assertRaisesRegex(ValueError,'revoked'):await self.p.send_with_reaction(Event(),MessageChain([Plain('合成')]),AsyncMock())
  self.client.send_private_msg.assert_not_awaited()
 async def test_slow_receipt_does_not_hold_other_scopes_delay_gate(self):
  first=Event();second=Event();started=asyncio.Event();release=asyncio.Event();seen=[]
  async def send(e,*_):
   seen.append(e)
   if e is first:started.set();await release.wait()
  self.p.reply_pause=AsyncMock();self.p.send_with_reaction=send
  for e in (first,second):e.send=AsyncMock();self.p.install_reply_delay(e)
  task=asyncio.create_task(first.send(MessageChain([Plain('first')])));await started.wait()
  await asyncio.wait_for(second.send(MessageChain([Plain('second')])),1)
  self.assertEqual(seen,[first,second]);self.assertTrue(all(2<=x.args[0]<=5 for x in self.p.reply_pause.await_args_list));release.set();await task
 async def test_assessor_receives_scoped_concerns_and_exact_current_evidence(self):
  e=Event('报告已经交了');self.p.agency.store.ensure(self.identity);self.p.agency.scope=lambda _:self.identity;self.p.agency.experience.observe(self.identity,'prior','报告还在准备',{'confidence':.9,'continuity':{'subject':'报告','quote':'报告还在准备','status':'open'}},0)
  calls=[]
  async def create(**kw):
   calls.append(kw);return N(choices=[N(message=N(content=json.dumps({'intent':'casual','emotion':'happy','relation':'none','target':'user','confidence':.9})))])
  client=N(base_url=N(host='api.deepseek.com',scheme='https'));client.with_options=lambda **_:client;client.chat=N(completions=N(create=create));self.provider.client=client;self.provider.get_model=lambda:'synthetic'
  value=await self.p.assess(e,ProviderRequest(contexts=[]),e.message_str)
  self.assertEqual(value['source'],'semantic');payload=json.loads(calls[0]['messages'][1]['content']);self.assertEqual(payload['concerns'][0]['subject'],'报告')
 async def test_cancel_known_untransmitted_reminder_requeues(self):
  a=self.p.agency;s=self.identity;a.store.ensure(s);id=a.store.goal(s,'合成提醒','reminder',due=time.time()+60)
  with a.store.db() as c:c.execute('UPDATE task SET due=? WHERE id=?',(time.time()-1,id))
  row={'identity':s,'kind':'private','ref':'synthetic','peer':'20002'}
  a.plugin.qq=N(plain=lambda x:x,active=lambda:True,allowed=lambda _:True,store=N(db=lambda:__import__('sqlite3').connect(':memory:')))
  # An absent transport reservation proves no send began; use an actual ledger.
  qdb=self.d/'fake-qq.db'
  with __import__('sqlite3').connect(qdb) as c:c.execute('CREATE TABLE p1_qq_actions(target TEXT,event TEXT,state TEXT)')
  a.plugin.qq.store.db=lambda:__import__('sqlite3').connect(qdb)
  a.plugin.qq.perform=AsyncMock(side_effect=asyncio.CancelledError())
  reservation=a.store.reserve(s,'test',10)
  with self.assertRaises(asyncio.CancelledError):await a.run(row,reservation)
  self.assertEqual(a.store.goals(s)[0]['status'],'queued')
 async def test_private_clear_rotates_native_conversation_and_all_memory_layers(self):
  from astrbot_plugin_memoria import main as MM
  from astrbot_plugin_memoria.memoria.db import MemoriaDB
  m=MM.MemoriaPlugin(self.ctx,{});m.db=await MemoriaDB.create(str(self.d/'memory'));m._memory_uid=lambda _:self.identity;m._memory_sid=lambda _:self.identity
  self.ctx.conversation_manager=N(get_curr_conversation_id=AsyncMock(return_value='old'),get_conversation=AsyncMock(return_value=N(persona_id='preserved-persona')),new_conversation=AsyncMock(return_value='new'))
  await m.db.add_memory('session:'+self.identity,'session',self.identity,'note','合成会话资料',1,'manual','active')
  with patch.object(MM,'permitted_event',return_value=True):result=[x async for x in m.cmd_clear_memories(Event())]
  self.assertFalse(await m.db.scope_memories(self.identity,self.identity));self.ctx.conversation_manager.new_conversation.assert_awaited_once_with(Event().unified_msg_origin,persona_id='preserved-persona');self.assertIn('重新开始',result[0])

 async def test_proposed_stance_requires_actual_matching_reply_and_receipt(self):
  a=self.p.agency;e=Event('你觉得这个方案怎么样');a.store.ensure(self.identity)
  payload=json.dumps({'subject':'合成方案','quote':'这个方案','summary':'我更偏向先做小范围验证','status':'uncertain'},ensure_ascii=False)
  result=await a.tool(e,'stance',payload);self.assertEqual(result['state'],'pending_actual_reply');self.assertFalse(a.experience.view(self.identity))
  e.set_extra('_p1_agency_epoch',0);e.set_extra('_p1_verified_sent_text',['完全不同的实际回复']);e.set_extra('_p1_verified_receipts',['123'])
  await a.delivered(e,'not-matching');self.assertFalse(any(x['kind']=='stance' for x in a.experience.view(self.identity)))
  e.set_extra('_p1_verified_sent_text',['我更偏向先做小范围验证']);await a.delivered(e,'matching')
  positions=[x for x in a.experience.view(self.identity) if x['kind']=='stance'];self.assertEqual(positions[0]['summary'],'我更偏向先做小范围验证');self.assertEqual(positions[0]['sources'][-1]['ref'],'123')
 async def test_diagnostic_reports_all_four_route_combinations_and_separate_quotas(self):
  from astrbot_plugin_affect.qq_policy import reference
  from astrbot_plugin_affect.qq_runtime import QQController
  self.p.qq=QQController(self.p,self.d)
  q=self.p.qq;q.store.migrate();q.ready=True;scope=q.group_key('10001','30003')
  (self.d/'groups.json').write_text(json.dumps({'version':1,'groups':[{'bot':'10001','group':'30003'}]}))
  row={'ref':reference('t','group','10001','30003'),'kind':'group','bot':'10001','peer':'30003','identity':scope,'label':'合成群'};q.store.sync([row],time.time(),lambda _:time.time()+500)
  for native,p1 in ((0,0),(0,1),(1,0),(1,1)):
   self.p.agency.store.route_config(scope,native=native,p1=p1)
   result=[s async for s in self.p.proactive_diagnostic(Event(),'30003')]
   self.assertIn('原生'+('开' if native else '关')+'；P1'+('开' if p1 else '关'),result[0]);self.assertIn('/999',result[0]);self.assertIn('后台另起话题',result[0]);self.assertIn('普通前台回复另计',result[0])

if __name__=='__main__':unittest.main()
