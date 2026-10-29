"""Continuity must change behavior context, preserve provenance and honor clear."""
import json,sys,tempfile,time,unittest
from pathlib import Path
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'release'))
from astrbot_plugin_affect.agency_store import AgencyStore
from astrbot_plugin_affect.experience import Experience
from astrbot_plugin_affect.appraisal import parse_appraisal
from astrbot_plugin_affect.emotion_model import seed,react
S='v1:'+'a'*64;T='g1:'+'b'*64

class ContinuityTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.s=AgencyStore(self.tmp.name);self.s.migrate();self.s.ensure(S);self.s.ensure(T);self.x=Experience(self.s);self.x.migrate()
 def cue(self,status='open',quote='汇报还在准备'):
  return {'intent':'casual','emotion':'neutral','relation':'none','target':'user','confidence':.9,'continuity':{'subject':'汇报','quote':quote,'status':status}}
 def test_real_source_updates_concern_and_resolves_without_new_question(self):
  self.x.observe(S,'event1','汇报还在准备',self.cue(),0)
  self.assertIn('汇报',self.x.hint(S,'汇报'))
  self.x.observe(S,'event2','汇报讲完了',self.cue('resolved','汇报讲完了'),0)
  row=self.x.view(S,'汇报')[0];self.assertEqual(row['status'],'resolved');self.assertEqual(row['version'],2)
  self.assertIn('已解决',self.x.hint(S,'汇报'))
 def test_other_scope_and_duplicate_event_do_not_change_state(self):
  self.x.observe(S,'same','汇报还在准备',self.cue(),0);self.x.observe(S,'same','汇报还在准备',self.cue(),0)
  self.assertEqual(self.x.view(S)[0]['version'],1);self.assertFalse(self.x.view(T))
 def test_implicit_resolution_is_bound_to_existing_subject_and_speaker(self):
  id=self.x.observe(T,'a1','汇报还在准备',self.cue(),0,actor='alice')
  cue={'confidence':.9,'continuity':{'subject':'汇报','quote':'已经交了','status':'resolved','ref':id}}
  self.assertIsNone(self.x.observe(T,'b1','已经交了',cue,0,actor='bob'))
  self.assertEqual(self.x.view(T,actor='alice')[0]['status'],'open');self.assertFalse(self.x.view(T,actor='bob'))
  self.x.observe(T,'a2','已经交了',cue,0,actor='alice')
  self.assertEqual(self.x.view(T,'后来呢',actor='alice')[0]['status'],'resolved')
  self.assertNotIn('continuity',parse_appraisal(json.dumps({**self.cue(),'continuity':{**cue['continuity'],'ref':'other-scope'}}),'已经交了'))
 def test_old_epoch_cannot_recreate_concern_after_clear(self):
  self.x.observe(S,'e','汇报还在准备',self.cue(),0);self.s.wipe(S)
  with self.assertRaisesRegex(ValueError,'scope_cleared'):self.x.observe(S,'old','汇报还在准备',self.cue(),0)
  self.assertFalse(self.x.view(S));self.assertFalse(self.s.context(S)['continuity'])
 def test_recent_episode_volume_does_not_hide_older_relevant_concern(self):
  self.x.observe(S,'old','汇报还在准备',self.cue(),0)
  evidence=[{'kind':'delivered_reply','ref':'synthetic:reply','quote':'普通合成交流'}]
  for n in range(205):self.x.put(S,'episode','日常交流'+str(n),'另一件普通合成小事','resolved',evidence,0,receipt='synthetic:'+str(n))
  self.assertEqual(self.x.view(S,'汇报')[0]['kind'],'concern');self.assertIn('汇报',self.x.hint(S,'汇报'))
 def test_fake_evidence_cannot_become_concern(self):
  self.assertIsNone(self.x.observe(S,'x','普通问候',self.cue(),0));self.assertFalse(self.x.view(S))
  appraisal=parse_appraisal(json.dumps(self.cue()),'普通问候');self.assertNotIn('continuity',appraisal)
 def test_actual_activity_keeps_coverage_own_curiosity_and_revision_sources(self):
  ids=self.x.activity(S,'artifact:one','reading','摘要里描述了不同的叙述角度','search_snippet_not_full_page',['https://example.org/book'],0,question='想进一步看叙事结构',opinion='暂时更喜欢直接的叙事')
  self.assertEqual(len(ids),3);self.assertEqual({r['kind'] for r in self.x.view(S)},{'concern','stance','episode'})
  self.assertIn('search_snippet_not_full_page',self.x.hint(S));self.assertFalse(self.x.view(T))
  self.s.wipe(S)
  with self.assertRaisesRegex(ValueError,'scope_cleared'):self.x.activity(S,'artifact:late','reading','过期结果','visited_page',['https://example.org/book'],0)
  self.assertFalse(self.x.view(S))
 def test_episode_requires_actual_receipt(self):
  src=[{'kind':'user_quote','ref':'event','quote':'合成'}]
  with self.assertRaisesRegex(ValueError,'receipt'):self.x.put(S,'episode','合成项目','合成经历','resolved',src,0)
  self.x.put(S,'episode','合成项目','实际回执','resolved',src,0,receipt='onebot:123')
  self.assertEqual(self.x.view(S)[0]['kind'],'episode')
 def test_stance_revision_requires_independent_evidence_and_keeps_version(self):
  a=[{'kind':'user_quote','ref':'event1','quote':'你怎么看'}]
  self.x.put(S,'stance','合成设计','偏好简洁','open',a,0)
  self.x.put(S,'stance','合成设计','随意翻转','open',a,0)
  self.assertEqual(self.x.view(S)[0]['summary'],'偏好简洁')
  self.x.put(S,'stance','合成设计','新证据下修改','eased',[{'kind':'user_quote','ref':'event2','quote':'这里有新证据'}],0)
  self.assertEqual(self.x.view(S)[0]['version'],2)
 def test_silence_does_not_change_relationship_or_concern(self):
  self.x.observe(S,'e','汇报还在准备',self.cue(),0);before=self.x.view(S)[0]
  after=self.x.view(S,now=time.time()+86400)[0]
  self.assertEqual(after['status'],before['status']);self.assertEqual(after['version'],before['version'])
 def test_confidence_and_intensity_have_separate_effects(self):
  base={'confidence':.9,'intent':'feedback','emotion':'happy','relation':'none','target':'self','self_response':{'concern':'understanding','trigger':'recognition','feeling':'pleased','source_hash':'a'*64},'interaction':{'need':'none','nuance':'none','intensity':.1,'resolution':'unknown'}}
  # Use accepted enums from the model rather than granting state through arbitrary words.
  from astrbot_plugin_affect.emotion_model import CONCERN_LABELS,TRIGGER_LABELS
  base['self_response']['concern']=next(iter(CONCERN_LABELS));base['self_response']['trigger']=next(iter(TRIGGER_LABELS))
  low,_=react(seed(),time.time()+1,base);base['interaction']={**base['interaction'],'intensity':.9};high,_=react(seed(),time.time()+1,base)
  self.assertGreater(high['thread']['strength'],low['thread']['strength'])

if __name__=='__main__':unittest.main()
