"""Goal choice is autonomous; human holds, reminders, epochs and TTL remain binding."""
import json,sys,tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import patch
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'release'))
from astrbot_plugin_affect.agency_store import AgencyStore
from astrbot_plugin_affect.agency_runtime import Agency
S='v1:'+'a'*64
class GoalPlanner(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.s=AgencyStore(self.tmp.name);self.s.migrate();self.s.ensure(S)
 def change(self,id,state='queued',priority=4):return {'id':id,'state':state,'priority':priority,'note':'选择下一小步，不代表已经执行'}
 def test_own_pause_survives_restart_and_can_resume_reprioritize_or_abandon(self):
  id=self.s.goal(S,'阅读一个公开主题');self.s.planner_updates(S,[self.change(id,'paused')],0);self.s.migrate()
  self.assertFalse(self.s.goals(S)[0]['manual_hold']);self.s.planner_updates(S,[self.change(id,'queued',5)],0)
  self.assertEqual(self.s.goals(S)[0]['priority'],5);self.assertEqual(self.s.goals(S)[0]['status'],'queued')
  self.s.planner_updates(S,[self.change(id,'abandoned')],0);self.assertFalse(self.s.planner_updates(S,[self.change(id)],0)[0]['applied'])
 def test_human_or_legacy_pause_cannot_be_automatically_resumed(self):
  id=self.s.goal(S,'人为暂缓的目标');self.s.update_goal(S,id,'paused',manual_hold=True)
  self.assertEqual(self.s.planner_updates(S,[self.change(id)],0)[0]['reason'],'manual_hold')
  with self.s.db() as c:c.execute('DELETE FROM task_control WHERE id=?',(id,))
  self.s.migrate();self.assertTrue(self.s.goals(S)[0]['manual_hold'])
 def test_plan_cannot_edit_permissions_finish_work_or_cross_a_clear(self):
  id=self.s.goal(S,'公开研究')
  for entry in ({**self.change(id),'level':3},{**self.change(id),'state':'done'},{**self.change(id),'priority':999}):
   with self.assertRaises(ValueError):self.s.planner_updates(S,[entry],0)
  self.s.wipe(S)
  with self.assertRaisesRegex(ValueError,'scope_cleared'):self.s.planner_updates(S,[self.change(id)],0)
  self.assertFalse(self.s.goals(S))
 def test_reminders_are_not_ordinary_planner_goals(self):
  id=self.s.goal(S,'明确提醒','reminder',due=time.time()+600);self.assertFalse(self.s.planner_updates(S,[self.change(id,'abandoned')],0)[0]['applied']);self.assertEqual(self.s.goals(S)[0]['status'],'queued')
 def test_document_goal_body_is_not_reinjected_into_general_or_background_context(self):
  id='b'*24;now=time.time()
  with self.s.db() as c:c.execute('INSERT INTO document VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(id,S,'fixture','txt',now,now+600,1,'ready','','source',0,0))
  goal=self.s.goal(S,'仅在附件里的合成标题',sources=[id]);self.s.update_goal(S,goal,'queued','仅在附件里的合成正文')
  self.assertNotIn('仅在附件里',json.dumps(self.s.context(S),ensure_ascii=False));self.assertEqual(self.s.planner_updates(S,[self.change(goal)],0)[0]['reason'],'temporary_source')
class ArtifactLineage(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.a=Agency(N(),self.tmp.name);await self.a.start();self.a.scope=lambda _:S;self.a.store.ensure(S);now=time.time();self.doc='d'*24
  with self.a.store.db() as c:c.execute('INSERT INTO document VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(self.doc,S,'fixture','txt',now,now+600,1,'ready','','source',0,0))
  self.artifact=self.a.artifact(S,'临时派生资料','仅临时保存的合成正文',sources=[self.doc]);self.extra={};self.e=N(get_extra=lambda k,d=None:self.extra.get(k,d),set_extra=lambda k,v:self.extra.__setitem__(k,v))
 async def test_derived_artifact_propagates_ttl_into_reply_and_native_history(self):
  result=await self.a.tool(self.e,'read_artifact',json.dumps({'id':self.artifact['id']}));self.assertTrue(result['ok']);self.assertIn('[P1-DOC-TTL:'+self.doc,result['text']);self.assertTrue(self.extra['_p1_temporary_document_used']);self.assertEqual(self.extra['_p1_document_sources'][0]['id'],self.doc)
 async def test_deletion_during_file_read_returns_no_temporary_text(self):
  original=Path.read_text
  def read(path,*args,**kwargs):
   text=original(path,*args,**kwargs)
   if path.name==self.artifact['id']+'.md':self.a.store.revoke_document(S,self.doc)
   return text
  with patch.object(Path,'read_text',read):result=await self.a.tool(self.e,'read_artifact',json.dumps({'id':self.artifact['id']}))
  self.assertFalse(result['ok']);self.assertNotIn('合成正文',json.dumps(result,ensure_ascii=False));self.assertFalse(self.extra)
if __name__=='__main__':unittest.main()
