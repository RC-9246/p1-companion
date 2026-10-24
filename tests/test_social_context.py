from pathlib import Path
import sqlite3,sys,tempfile,time,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'release'))
from astrbot_plugin_affect.social_context import delivered_dialogue,awaiting_reply
from astrbot_plugin_p1_learning.store import Store
A='v1:'+'a'*64;B='v1:'+'b'*64
class SocialContextTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.path=Path(self.tmp.name)/'affect.db';self.s=Store(self.path);self.s.migrate();self.now=time.time()
 def add(self,scope=A,event='e',user='答辩过了',reply='太好了',at=None):self.s.record(scope,event,'current_user',user,reply,now=at or self.now)
 def test_exact_scope_and_delivered_reply(self):
  self.add();self.add(B,user='OTHER_SCOPE_SENTINEL');self.add(event='pending',reply='')
  out=delivered_dialogue(self.path,A,self.now);self.assertEqual(len(out),1);self.assertEqual(out[0]['assistant_reply'],'太好了');self.assertNotIn('SENTINEL',str(out))
 def test_pause_disables_background_read(self):
  self.add();self.s.control(A,'off');self.assertEqual(delivered_dialogue(self.path,A,self.now),[])
 def test_retention_future_and_commands(self):
  self.add(event='old',at=self.now-8*86400);self.add(event='future',at=self.now+90);self.add(event='cmd',user='/学习 清空');self.add(event='current')
  self.assertEqual(len(delivered_dialogue(self.path,A,self.now)),1)
 def test_credentials_in_either_role_are_not_forwarded(self):
  self.add(user='我的password=hunter2',event='u');self.add(reply='token=abcde1234567890',event='a')
  self.assertEqual(delivered_dialogue(self.path,A,self.now),[])
 def test_time_order_and_capacity(self):
  for n in range(20):self.add(event=str(n),user='x'*600,reply='y'*700,at=self.now-20+n)
  out=delivered_dialogue(self.path,A,self.now)
  self.assertLessEqual(sum(len(r['text'])+len(r['assistant_reply']) for r in out),6000);self.assertLessEqual(len(out),8)
  self.assertEqual([r['recorded_at'] for r in out],sorted(r['recorded_at'] for r in out))
 def test_pending_question_needs_receipt_and_recent_time(self):
  self.add(reply='后来怎样？');facts=delivered_dialogue(self.path,A,self.now)
  self.assertTrue(awaiting_reply(facts,self.now));self.assertFalse(awaiting_reply(facts,self.now+25*3600))
  self.assertFalse(awaiting_reply(facts+[{'kind':'recent_user','text':'我还想要你下午问一下'}],self.now))
 def test_acknowledging_future_followup_is_not_already_asking(self):
  self.add(reply='好，下午我会留意一下');self.assertFalse(awaiting_reply(delivered_dialogue(self.path,A,self.now),self.now))
 def test_bad_identity_does_not_create_a_database(self):
  path=Path(self.tmp.name)/'absent.db';self.assertEqual(delivered_dialogue(path,'g1:'+'a'*64,self.now),[]);self.assertFalse(path.exists())
 def test_read_only_query_preserves_database_bytes(self):
  self.add();before=self.path.read_bytes();delivered_dialogue(self.path,A,self.now);self.assertEqual(before,self.path.read_bytes())
if __name__=='__main__':unittest.main()
