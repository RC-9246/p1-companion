import json,tempfile,time,unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'release'))
from astrbot_plugin_p1_group_memory.store import Store,scope_key
from astrbot_plugin_affect.emotion_model import seed,react
class GroupMemoryTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'groups.db';self.store=Store(self.path);self.store.migrate();self.a=scope_key('1','2');self.b=scope_key('1','3');self.now=time.time()
 def tearDown(self):self.tmp.cleanup()
 def test_existing_metadata_does_not_need_write_lock(self):
  import sqlite3
  self.store.meta(self.a)
  with sqlite3.connect(self.path) as blocker:
   blocker.execute('BEGIN IMMEDIATE')
   self.assertEqual(self.store.meta(self.a)['epoch'],1)
 def test_restart_cross_group_bot_and_member_isolation(self):
  self.store.add(self.a,'a','m','甲','A独有',self.now)
  self.store.add(self.b,'b','m','乙','B独有',self.now)
  store=Store(self.path);store.migrate()
  self.assertEqual(store.history(self.a)['messages'][0]['text'],'A独有')
  self.assertNotIn('B独有',str(store.history(self.a)));self.assertNotEqual(self.a,scope_key('4','2'))
  state=seed();self.store.seed_affect(self.a,{'core':'saki'},state,self.now)
  nextstate,_=react(state,self.now,{'confidence':.9,'intent':'feedback','emotion':'happy','relation':'thanks','target':'self'})
  self.assertTrue(self.store.commit_affect(self.a,'e','memberA',nextstate,nextstate,{},self.now,1))
  self.assertIsNone(self.store.affect(self.a,'memberB')[1]);self.assertEqual(self.store.affect(self.a,'memberA')[1]['interactions'],1)
  self.assertIsNone(self.store.affect(self.b,'memberA')[0])
 def test_dedup_retention_unknown_time_and_reply_provenance(self):
  self.assertTrue(self.store.add(self.a,'a','m','甲','a',None,reply='prior',mentions=[{'member':'other'}]))
  self.assertFalse(self.store.add(self.a,'a','m','甲','changed',self.now))
  h=self.store.history(self.a)['messages'][0];self.assertIsNone(h['sent_at']);self.assertIsNone(h['seconds_ago']);self.assertEqual(h['reply_to'],'prior')
  for n in range(510):self.store.add(self.a,str(n),'m','甲','xy',self.now)
  self.assertEqual(self.store.counts(self.a)['messages'],500)
  self.assertLessEqual(len(self.store.history(self.a)['messages']),28)
 def test_epoch_revocation_rejects_stale_summary_and_affect(self):
  self.store.meta(self.a);self.store.bump(self.a)
  self.assertFalse(self.store.save_notes(self.a,1,1,[],self.now))
  s=seed();self.assertFalse(self.store.commit_affect(self.a,'e','m',s,s,{},self.now,1))
  self.assertTrue(self.store.commit_affect(self.a,'e','m',s,s,{},self.now,2));self.assertFalse(self.store.commit_affect(self.a,'e','m',s,s,{},self.now,2))
 def test_scope_delete_does_not_affect_neighbor(self):
  for key in (self.a,self.b):self.store.add(key,'x','m','人','text',self.now)
  self.store.bump(self.a,True);self.assertEqual(self.store.counts(self.a)['messages'],0);self.assertEqual(self.store.counts(self.b)['messages'],1);self.assertEqual(self.store.meta(self.a)['hydrated'],1)
 def test_note_cadence_and_failed_attempt_preserve_previous(self):
  for n in range(24):self.store.add(self.a,str(n),'m','人','topic',self.now)
  epoch,seq=self.store.claim_summary(self.a,self.now)
  old=[{'text':'旧笔记','evidence':[{'id':'0','text':'topic'}]}]
  self.assertTrue(self.store.save_notes(self.a,epoch,seq,old,self.now))
  self.assertIsNone(self.store.claim_summary(self.a,self.now+100))
  self.assertEqual(self.store.history(self.a)['notes'],old)
 def test_group_keys_cannot_be_private_identity(self):
  with self.assertRaises(ValueError):self.store.history('v1:'+'a'*64)
 def test_reaction_unknown_delivery_keeps_cooldown(self):
  self.store.meta(self.a);self.store.seed_affect(self.a,{},seed(),self.now)
  self.assertTrue(self.store.reserve_reaction(self.a,'r','saki_smile',self.now));self.store.reaction_done(self.a,'r',False)
  self.assertFalse(self.store.can_react(self.a,self.now+1));self.assertTrue(self.store.can_react(self.b,self.now+1))
