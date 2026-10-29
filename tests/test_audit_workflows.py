"""Real SQLite/decoder regressions; transport and clocks stay synthetic."""
import asyncio,io,json,sys,tempfile,time,unittest,zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'release'));sys.path.insert(0,str(R))
from astrbot_plugin_affect.agency_store import AgencyStore
from astrbot_plugin_affect.file_runtime import Documents
from astrbot_plugin_p1_group_memory.store import Store,scope_key
from services.workbench.decoder import extract,MAX_TEXT
S='g1:'+'c'*64

class WorkflowTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name).resolve()
  self.s=AgencyStore(self.root);self.s.migrate();self.s.ensure(S)
 def doc(self,id='a'*24):
  now=time.time()
  with self.s.db() as c:c.execute('INSERT INTO document VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(id,S,'fixture','txt',now,now+600,7,'ready','','source',0,0))
  return id
 def test_unrelated_goal_and_update_do_not_inherit_active_documents(self):
  doc=self.doc();id=self.s.goal(S,'unrelated reminder','reminder',due=time.time()+600)
  self.s.update_goal(S,id,'paused');self.s.revoke_document(S,doc)
  goal=self.s.goals(S)[0];self.assertEqual(goal['status'],'paused');self.assertEqual(goal['expires'],0);self.assertEqual(json.loads(goal['sources']),[])
 def test_document_source_is_required_current_and_propagates_expiry(self):
  doc=self.doc();id=self.s.goal(S,'document summary',sources=[doc]);self.assertGreater(self.s.goals(S)[0]['expires'],time.time())
  self.s.revoke_document(S,doc)
  with self.assertRaisesRegex(ValueError,'document_source_revoked'):self.s.goal(S,'stale new goal',sources=[doc])
  self.assertFalse(self.s.task_current(S,id,0,'queued'))
 def test_reschedule_atomic_and_in_flight_denied(self):
  id=self.s.goal(S,'remind','reminder',due=time.time()+600);self.s.block_reminder(S,id,'level_3_required')
  self.s.reschedule(S,id,time.time()+1200);self.assertEqual(self.s.goals(S)[0]['status'],'queued')
  self.s.update_goal(S,id,'active')
  with self.assertRaisesRegex(ValueError,'in_flight'):self.s.reschedule(S,id,time.time()+1200)
 def test_level3_resume_unblocks_level2_reminders_without_recreating(self):
  id=self.s.goal(S,'remind','reminder',due=time.time()+600);self.s.block_reminder(S,id,'level_3_required');self.s.config(S,level=3)
  self.assertEqual(self.s.goals(S)[0]['id'],id);self.assertEqual(self.s.goals(S)[0]['status'],'queued')
 def test_failure_circuit_backoff_success_reset(self):
  for i in range(3):self.s.circuit_result('experiment',False,now=1000+i)
  self.assertFalse(self.s.circuit_available('experiment',now=1003));self.assertTrue(self.s.circuit_available('experiment',now=1303))
  self.s.circuit_result('experiment',True,now=1400);self.assertTrue(self.s.circuit_available('experiment',now=1401))
 def test_summary_cursor_covers_exact_contiguous_batches(self):
  g=Store(self.root/'group.db');g.migrate();s=scope_key('bot','group');now=time.time()
  for i in range(80):g.add(s,str(i),'speaker','name','message '+str(i),now)
  epoch,through=g.claim_summary(s,now);batch=g.summary_batch(s,epoch,through)
  self.assertEqual([r['id'] for r in batch['messages']],[str(i) for i in range(24)])
  g.save_notes(s,epoch,through,[],now)
  epoch,through=g.claim_summary(s,now+901);batch=g.summary_batch(s,epoch,through)
  self.assertEqual([r['id'] for r in batch['messages']],[str(i) for i in range(24,48)])
 def test_xlsx_reports_2000_of_2100_rows_instead_of_full_read(self):
  rows=''.join('<row><c r="A%d"><v>%d</v></c></row>'%(i,i) for i in range(2100));out=io.BytesIO()
  with zipfile.ZipFile(out,'w',compression=zipfile.ZIP_STORED) as z:z.writestr('xl/worksheets/sheet1.xml','<worksheet><sheetData>'+rows+'</sheetData></worksheet>')
  r=extract('synthetic.xlsx',out.getvalue());self.assertTrue(r['truncated']);self.assertFalse(r['coverage']['complete']);self.assertEqual(r['coverage']['sections'][0]['rows_total'],2100);self.assertNotIn('A2099=',r['text'])
 def test_plaintext_limit_declares_partial_coverage(self):
  r=extract('fixture.txt',b'x'*(MAX_TEXT+10));self.assertFalse(r['coverage']['complete']);self.assertIn('character_limit',r['coverage']['omitted'])
 def test_research_urls_remain_sources_without_becoming_document_dependencies(self):
  id=self.s.goal(S,'public research');self.s.update_goal(S,id,'done','actual public source',['https://example.org/public'])
  self.assertEqual(self.s.goals(S)[0]['status'],'done');self.assertEqual(self.s.goals(S)[0]['expires'],0)
 def test_retired_derived_reply_is_filtered_only_in_source_scope(self):
  from astrbot_plugin_affect.retention import retire
  import hashlib
  id=self.doc();body='合成文档的派生结论：这里包含足够长的受保留期限约束的具体资料'
  self.s.remember_document_reply(S,'qq_snowluma:GroupMessage:30003',[body],[{'id':id}],0);self.s.revoke_document(S,id)
  rows=self.s.document_lineage(S);hashes={x['digest'] for x in rows if x['document'] in self.s.revoked_sources(S)}
  self.assertNotEqual(retire(body,hashes=hashes),body);self.assertEqual(retire(body,hashes=set()),body)
 def test_interest_uses_independent_evidence_and_rejects_previous_epoch(self):
  self.assertTrue(self.s.learn_interest(S,'reading',.8,'source1',expected_epoch=0));self.assertFalse(self.s.learn_interest(S,'reading',.8,'source1',expected_epoch=0))
  self.s.wipe(S)
  with self.assertRaisesRegex(ValueError,'scope_cleared'):self.s.learn_interest(S,'reading',.8,'source2',expected_epoch=0)

class ReadRevocation(unittest.IsolatedAsyncioTestCase):
 async def test_delete_while_reading_does_not_return_retired_text(self):
  with tempfile.TemporaryDirectory() as tmp:
   s=AgencyStore(Path(tmp));s.migrate();s.ensure(S);id='d'*24;now=time.time()
   with s.db() as c:c.execute('INSERT INTO document VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(id,S,'fixture','txt',now,now+600,7,'ready','','source',0,0))
   p=s.directory(S)/(id+'.txt');p.write_text('private fixture')
   agency=SimpleNamespace(store=s,plugin=None,scope=lambda _:S);docs=Documents(agency);extra={}
   event=SimpleNamespace(get_extra=lambda k,d=None:extra.get(k,d),set_extra=lambda k,v:extra.__setitem__(k,v))
   original=Path.read_text
   def read(path,*a,**kw):
    result=original(path,*a,**kw)
    if path==p:s.revoke_document(S,id)
    return result
   with patch.object(Path,'read_text',read):r=await docs.run(event,'read',id)
   self.assertFalse(r['ok']);self.assertNotIn('private fixture',json.dumps(r));self.assertFalse(extra)

if __name__=='__main__':unittest.main()
