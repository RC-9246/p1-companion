"""Actual SQLite regressions for scope invalidation and separate social lanes."""
import json,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'release'))
from astrbot_plugin_affect.agency_store import AgencyStore
from astrbot_plugin_affect.qq_store import QQStore
from astrbot_plugin_affect.qq_policy import DEFAULT,reference
from astrbot_plugin_affect.retention import retire
from astrbot_plugin_p1_group_memory.store import Store,scope_key
try:from astrbot_plugin_memoria.memoria.db import MemoriaDB
except ImportError:MemoriaDB=None
S='g1:'+'a'*64;U='v1:'+'b'*64

class ScopeAndLaneTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name).resolve()
  self.s=AgencyStore(self.root);self.s.migrate();self.s.ensure(S)
  self.q=QQStore(self.root/'qq.db');self.q.migrate();self.now=time.time();self.policy={**DEFAULT,'enabled':True}
  self.target={'ref':reference('t','group','10001','30001'),'kind':'group','bot':'10001','peer':'30001','identity':S,'label':'synthetic'}
  self.q.sync([self.target],self.now,lambda _:self.now);self.row=self.q.target(self.target['ref'])
 def add_action(self,i,lane='background',target=None,at=None):
  with self.q.db() as c:
   c.execute('INSERT INTO p1_qq_actions VALUES(?,?,?,?,?,?,?,?,?)',(str(i),target or self.row['ref'],'e'+str(i),'message',self.now-1000 if at is None else at,'sent',1,'receipt','synthetic'))
   c.execute('INSERT INTO p1_qq_action_lanes VALUES(?,?)',(str(i),lane))
 def test_background_global16_does_not_block_realtime_interest_or_native(self):
  for i in range(16):self.add_action(i,target='other'+str(i))
  self.assertFalse(self.q.can_action(self.row,self.now,self.policy,True))
  for lane in ('interest','native'):self.assertTrue(self.q.can_action(self.row,self.now,self.policy,True,lane=lane))
 def test_999th_allowed_1000th_rejected_and_native_shares_pool(self):
  for i in range(998):self.add_action(i,'interest' if i%2 else 'native')
  rid=self.q.reserve(self.row,'reply999','message',self.now,self.policy,True,lane='interest');self.assertIsNotNone(rid)
  self.q.finish(rid,'sent','999')
  self.assertEqual(self.q.block_reason(self.row,self.now+121,self.policy,True,lane='native'),'interest_daily_quota')
 def test_realtime_cooldown_is_based_on_actual_reservation_not_admission(self):
  for _ in range(15):self.assertTrue(self.s.join(S,self.now,True))
  rid=self.q.reserve(self.row,'r','message',self.now,self.policy,True,lane='interest');self.assertTrue(rid)
  self.assertEqual(self.q.block_reason(self.row,self.now+1,self.policy,True,lane='interest'),'interest_cooldown')
  self.q.finish(rid,'cancelled');self.assertTrue(self.q.can_action(self.row,self.now+1,self.policy,True,lane='interest'))
 def test_known_untransmitted_can_retry_but_unknown_cannot(self):
  rid=self.q.reserve(self.row,'retry','message',self.now,self.policy,True,lane='interest');self.q.finish(rid,'cancelled')
  again=self.q.reserve(self.row,'retry','message',self.now+1,self.policy,True,lane='interest');self.assertEqual(again,rid)
  self.q.finish(again,'unknown');self.assertIsNone(self.q.reserve(self.row,'retry','message',self.now+1000,self.policy,True,lane='interest'))
 def test_realtime_does_not_inflate_unanswered_background_counter(self):
  rid=self.q.reserve(self.row,'realtime','message',self.now,self.policy,True,lane='native');self.q.finish(rid,'sent','123')
  self.assertEqual(self.q.target(self.row['ref'])['unanswered'],0)
 def test_background40_preserves160_for_real_time_without_increasing_total(self):
  for _ in range(40):self.assertTrue(self.s.take_model_budget(now=self.now,lane='background'))
  self.assertFalse(self.s.take_model_budget(now=self.now,lane='background'))
  for _ in range(160):self.assertTrue(self.s.take_model_budget(now=self.now,lane='foreground'))
  self.assertFalse(self.s.take_model_budget(now=self.now,lane='foreground'))
 def test_clear_keeps_reservation_settlement_without_content(self):
  rid=self.s.reserve(S,'test',120);self.s.wipe(S);self.s.finish(rid,'interrupted',2)
  self.assertEqual(self.s.budget()['used'],2)
  with self.s.db() as c:self.assertEqual(c.execute('SELECT details FROM action WHERE id=?',(rid,)).fetchone()[0],'{}')
 def test_old_epoch_event_cannot_supersede_new_event(self):
  other=AgencyStore(self.root);original=self.s.ensure
  def ensure(scope):
   old=original(scope);other.wipe(scope);other.event(scope,'note','new fact','fixture:new',conflict='same',expected_epoch=1);return old
  with patch.object(self.s,'ensure',side_effect=ensure):
   with self.assertRaisesRegex(ValueError,'scope_cleared'):self.s.event(S,'note','old fact','fixture:old',conflict='same',expected_epoch=0)
  self.assertEqual(other.search(S)[0]['text'],'new fact')
 def test_group_hydrate_old_epoch_is_not_written(self):
  s=Store(self.root/'groups.db');s.migrate();key=scope_key('10001','30001');epoch=s.meta(key)['epoch'];s.bump(key,True)
  self.assertFalse(s.add(key,'old','m','member','old history',expected_epoch=epoch));s.hydrated(key,epoch)
  self.assertFalse(s.history(key)['messages'])
 def test_qq_clear_removes_cache_and_blocks_old_history(self):
  self.q.observe(self.row['ref'],'old','member','member','old',False,0,0,self.now-100)
  self.q.clear_target(self.row['ref'])
  self.assertFalse(self.q.messages(self.row['ref']))
  self.assertIsNone(self.q.observe(self.row['ref'],'old2','member','member','old',False,0,0,self.now-10))
  self.assertIsNone(self.q.observe(self.row['ref'],'late','member','member','late',False,0,0,self.now+1,expected_generation=self.row['generation']))
 def test_deleting_document_uses_source_edges_not_expiry(self):
  now=time.time();a='a'*24;b='b'*24
  with self.s.db() as c:
   for id in (a,b):c.execute('INSERT INTO document VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(id,S,'fixture','txt',now,now+1000,5,'ready','','source',0,0))
   for id,src in [('one',a),('two',b)]:c.execute('INSERT INTO artifact VALUES(?,?,?,?,?,?,?,?,?)',(id,S,id,'txt',now,now+900,json.dumps([src]),5,0))
  self.s.revoke_document(S,a)
  with self.s.db() as c:rows={r['id']:r['expires'] for r in c.execute('SELECT id,expires FROM artifact')}
  self.assertEqual(rows['one'],1);self.assertGreater(rows['two'],now)
  tag='[P1-DOC-TTL:'+a+':'+str(int(now+1000))+'] sensitive temporary fixture'
  self.assertNotIn('sensitive temporary fixture',retire(tag,revoked=self.s.revoked_sources(S)))

@unittest.skipIf(MemoriaDB is None,'requires declared aiosqlite dependency')
class MemoryEpochTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.db=await MemoriaDB.create(self.tmp.name)
 async def asyncTearDown(self):self.tmp.cleanup()
 async def test_clear_removes_three_layers_and_transcript(self):
  for owner,scope in [(U,'user'),('session:'+U,'session'),('relationship:'+U+':'+U,'relationship')]:await self.db.add_memory(owner,scope,U,'note','forget this fixture',1,'explicit','active')
  await self.db.record_private_turn(U,'event','old private text')
  self.assertEqual(await self.db.clear_scope(U,U),3);self.assertFalse(await self.db.private_transcript(U));self.assertFalse(await self.db.scope_memories(U,U))
 async def test_stale_model_write_rejected_in_transaction(self):
  epoch=await self.db.scope_epoch(U);await self.db.clear_scope(U,U)
  with self.assertRaisesRegex(ValueError,'memory_scope_changed'):await self.db.upsert_memory_candidate(U,'user',U,'note','stale fixture',.8,'dream',expected_epoch=epoch)
  with self.assertRaisesRegex(ValueError,'memory_scope_changed'):await self.db.record_private_turn(U,'old','stale transcript',expected_epoch=epoch)
 async def test_session_candidate_is_visible_confirmable_and_scoped(self):
  mid=await self.db.upsert_memory_candidate('session:'+U,'session',U,'note','one fixture',.7,'dream')
  self.assertEqual((await self.db.scope_memories(U,U,'candidate'))[0].id,mid)
  self.assertFalse(await self.db.scope_status(mid,'other','other','active',verified=True))
  self.assertTrue(await self.db.scope_status(mid,U,U,'active',verified=True))
 async def test_precise_retrieval_after_300_other_memories(self):
  for i in range(301):await self.db.add_memory(U,'user',U,'note','无关天气记录 '+str(i),1,'explicit','active')
  wanted=await self.db.add_memory(U,'user',U,'note','独特的天文观测目标是天狼星',.9,'explicit','active')
  self.assertEqual((await self.db.search_memories(U,'active','天狼星',8))[0].id,wanted)

if __name__=='__main__':unittest.main()

@unittest.skipIf(MemoriaDB is None,'requires declared aiosqlite dependency')
class MemoryRecoveryLedgerTests(unittest.IsolatedAsyncioTestCase):
 async def test_old_snapshot_cannot_reintroduce_explicitly_cleared_memory(self):
  import sqlite3
  with tempfile.TemporaryDirectory() as tmp:
   db=await MemoriaDB.create(tmp);snapshot=Path(tmp)/'old.db';await db.add_memory(U,'user',U,'note','must stay forgotten',1,'manual','active');await db.add_memory('other','user','other','note','unrelated preserved',1,'manual','active')
   with sqlite3.connect(db.db_path) as source,sqlite3.connect(snapshot) as target:source.backup(target)
   await db.clear_scope(U,U)
   with sqlite3.connect(snapshot) as source,sqlite3.connect(db.db_path) as target:source.backup(target)
   fresh=await MemoriaDB.create(tmp);self.assertFalse(await fresh.scope_memories(U,U));self.assertTrue(await fresh.list_memories('other',None,'active',20));self.assertGreater(await fresh.scope_epoch(U),0)
 async def test_corrupt_forget_ledger_blocks_reopen_instead_of_reactivating_old_memory(self):
  with tempfile.TemporaryDirectory() as tmp:
   db=await MemoriaDB.create(tmp);await db.clear_scope(U,U);Path(db.db_path).with_name('clear-epochs.json').write_text('{broken')
   with self.assertRaises(ValueError):await MemoriaDB.create(tmp)
