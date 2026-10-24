"""Actual SDK dependencies, isolated failure ledger, no model or QQ transport."""
import json,sys,tempfile,unittest
from pathlib import Path
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'release'))
G='g1:'+'c'*64

class BackgroundFailureDiagnostics(unittest.IsolatedAsyncioTestCase):
 def fixture(self,tmp,remaining):
  from types import SimpleNamespace as N
  from unittest.mock import AsyncMock
  from astrbot_plugin_affect.agency_runtime import Agency
  qq=N(active=lambda:True,allowed=lambda row:True,owner=lambda scope:False,perform=AsyncMock())
  p=N(enabled=lambda:True,qq=qq,groups=N(memory=None),store=N(budget_status=lambda *a,**k:{'remaining':remaining,'limit':240}))
  return Agency(p,tmp)
 async def test_exhausted_research_is_not_offered_or_executed(self):
  from unittest.mock import AsyncMock
  with tempfile.TemporaryDirectory() as tmp:
   a=self.fixture(tmp,0);await a.start();reservation=a.store.reserve(G,'test',10)
   a.complete=AsyncMock(return_value={'activity':'research','topic':'reading','goal_id':''});a.research=AsyncMock()
   await a.run({'identity':G,'kind':'group'},reservation)
   with a.store.db() as c:r=c.execute('SELECT state,details FROM action WHERE id=?',(reservation,)).fetchone()
   self.assertEqual(r['state'],'quiet');self.assertEqual(json.loads(r['details'])['reason'],'research_budget')
   self.assertNotIn('research',a.complete.await_args.args[2]['available_activities']);a.research.assert_not_awaited();a.plugin.qq.perform.assert_not_awaited()
 async def test_concurrent_quota_exhaustion_is_quiet_and_keeps_scope_enabled(self):
  from unittest.mock import AsyncMock
  with tempfile.TemporaryDirectory() as tmp:
   a=self.fixture(tmp,1);await a.start();reservation=a.store.reserve(G,'test',10)
   a.complete=AsyncMock(return_value={'activity':'research','topic':'reading','goal_id':''});a.research=AsyncMock(side_effect=ValueError('research_budget'))
   await a.run({'identity':G,'kind':'group'},reservation)
   with a.store.db() as c:r=c.execute('SELECT state,details FROM action WHERE id=?',(reservation,)).fetchone()
   self.assertEqual(r['state'],'quiet');self.assertEqual(json.loads(r['details'])['phase'],'research');self.assertEqual(a.store.ensure(G)['paused'],0)
 async def test_zero_public_quota_still_allows_organizing(self):
  from unittest.mock import AsyncMock
  with tempfile.TemporaryDirectory() as tmp:
   a=self.fixture(tmp,0);await a.start();reservation=a.store.reserve(G,'test',10)
   a.complete=AsyncMock(side_effect=[{'activity':'organize','topic':'reading','goal_id':''},{'note':'仅整理已有笔记','expression':'brief','pace_minutes':20}])
   await a.run({'identity':G,'kind':'group'},reservation)
   with a.store.db() as c:r=c.execute('SELECT state FROM action WHERE id=?',(reservation,)).fetchone();count=c.execute('SELECT COUNT(*) FROM artifact').fetchone()[0]
   self.assertEqual(r['state'],'complete');self.assertEqual(count,1);a.plugin.qq.perform.assert_not_awaited()
 async def test_model_budget_exhaustion_waits_for_reset_instead_of_failing(self):
  from unittest.mock import AsyncMock
  with tempfile.TemporaryDirectory() as tmp:
   a=self.fixture(tmp,0);await a.start();reservation=a.store.reserve(G,'test',10);a.complete=AsyncMock(side_effect=ValueError('model_budget'))
   await a.run({'identity':G,'kind':'group'},reservation)
   with a.store.db() as c:r=c.execute('SELECT state,details FROM action WHERE id=?',(reservation,)).fetchone()
   self.assertEqual(r['state'],'quiet');self.assertEqual(json.loads(r['details'])['reason'],'model_budget');self.assertGreater(a.store.ensure(G)['next_at'],__import__('time').time())
 async def test_runtime_records_closed_failure_code_without_private_exception_text(self):
  from types import SimpleNamespace as N
  from unittest.mock import AsyncMock
  from astrbot_plugin_affect.agency_runtime import Agency
  for exc,expected in [(ValueError('invalid_goal'),'invalid_goal'),(ValueError('private account or model output'),'unclassified_failure'),(RuntimeError('token=private-secret'),'unclassified_failure')]:
   with self.subTest(error=type(exc).__name__),tempfile.TemporaryDirectory() as tmp:
    qq=N(active=lambda:True,allowed=lambda row:True,owner=lambda scope:False,perform=AsyncMock())
    agency=Agency(N(enabled=lambda:True,qq=qq),tmp);await agency.start()
    row={'identity':G,'kind':'group'};reservation=agency.store.reserve(G,'test',10)
    agency.complete=AsyncMock(side_effect=exc);await agency.run(row,reservation)
    with agency.store.db() as c:
     r=c.execute('SELECT state,details FROM action WHERE id=?',(reservation,)).fetchone()
    data=json.loads(r['details']);self.assertEqual(r['state'],'failed');self.assertEqual(data['code'],expected);self.assertEqual(data['phase'],'plan')
    self.assertNotIn('private',r['details']);qq.perform.assert_not_awaited();await agency.stop()

if __name__=='__main__':unittest.main()
