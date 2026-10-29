"""Conversation focus must not create memories, permissions or contact duties."""
import copy,json,sys,tempfile,time,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'release'))
from astrbot_plugin_affect.dialogue import focus,normalize,compact_context
from astrbot_plugin_affect.appraisal import parse_appraisal
from astrbot_plugin_affect.emotion_model import interaction_context,seed,perspective
from astrbot_plugin_affect.agency_store import AgencyStore
from astrbot_plugin_affect.experience import Experience
from astrbot_plugin_affect.reply_chunks import parse_review,needs_review
from astrbot_plugin_affect.social import requested_pause

def a(**kw):
 return dict(intent='boundary',emotion='neutral',target='self',relation='boundary',confidence=.95,
             interaction=dict(need='space',nuance='none',intensity=.5,resolution='unknown'),**kw)

class Focus(unittest.TestCase):
 def test_preference_or_self_choice_is_not_independence_from_contact(self):
  for text,kind in [('不用再问我更想听哪一种','style_preference'),('现在换你自己选一件想弄清楚的小事','self_choice'),
                    ('你最近有什么在意的事','self_status'),('说话自然一点，别像客服','style_preference')]:
   raw=a();before=copy.deepcopy(raw);out=normalize(raw,text)
   self.assertEqual(focus(text,out),kind,text);self.assertEqual(out['interaction']['need'],'none',text)
   self.assertEqual(raw,before);self.assertIsNone(requested_pause(text,out))
 def test_explicit_contact_pause_keeps_actual_boundary_but_not_silent_expression(self):
  text='这两天不用主动联系我，不过这会儿想听听你的看法';out=normalize(a(),text)
  self.assertEqual(focus(text,out),'contact_pause');self.assertEqual(out['interaction']['need'],'space')
  self.assertEqual(requested_pause(text,out),48*3600)
  self.assertNotIn('不续问',interaction_context(out));self.assertNotIn('space',str(perspective(seed(),out)))
  self.assertEqual(focus('困了，今天先到这里',a()),'close')
 def test_third_party_or_quoted_boundary_is_not_this_conversation(self):
  for text in ('例如不要再找我','假如你自己选一个','他说不要联系我','翻译：别再说了','她的原话是“不要找我”'):
   self.assertEqual(focus(text,a()),'other',text);self.assertIsNone(requested_pause(text,a()),text)
  other=a();other['target']='third';self.assertEqual(focus('她说这两天不要找我',other),'other')
 def test_meaning_questions_and_factual_corrections_do_not_become_preferences(self):
  for text in ('别问我是什么意思','不用联系我，这句话是什么意思'):
   self.assertEqual(focus(text,a()),'question')
  raw=a();raw['interaction']['need']='repair'
  out=normalize(raw,'不是我拍的，你说错了，不用再问我')
  self.assertEqual(out['interaction']['need'],'repair');self.assertTrue(needs_review('这张是你拍的',out,'不是我拍的'))
 def test_optional_act_needs_exact_current_quote_and_no_authority(self):
  raw=a();raw['dialogue']={'act':'self_choice','quote':'不存在'}
  out=parse_appraisal(json.dumps(raw),'你好');self.assertNotIn('dialogue',out)
  raw['dialogue']={'act':'self_choice','quote':'换你选'};out=parse_appraisal(json.dumps(raw),'这次换你选')
  self.assertEqual(out['dialogue_focus'],'self_choice');self.assertNotIn('permissions',out)
 def test_framed_experiences_cannot_become_current_concerns(self):
  for prefix in ('例如','假设','假如','引用','台词','[转发]','他说','她说','翻译'):
   raw=a();raw['continuity']={'subject':'汇报','quote':'汇报已经完成','status':'resolved'}
   raw['dialogue']={'act':'share','quote':'汇报已经完成'}
   out=parse_appraisal(json.dumps(raw),prefix+'：汇报已经完成')
   self.assertNotIn('continuity',out,prefix);self.assertNotIn('dialogue',out,prefix)
 def test_compact_projection_keeps_scoped_facts_and_no_controls(self):
  ctx={'control':{'level':3,'epoch':0},'shared_device_budget':{'calls':199},
       'goals':[{'id':'one','title':'阅读','status':'active','notes':'已计划'}, {'id':'two','title':'旧任务','status':'done'}],
       'events':[{'kind':'receipt','text':'只读了摘要','source':'synthetic','at':123}],
       'explicit_feedback':[{'rule':'不要没完没了追问'}],'interests':[{'topic':'science','score':.6}]}
  before=copy.deepcopy(ctx);out=compact_context(ctx,'换你自己选一个话题',a())
  self.assertEqual(ctx,before);self.assertNotIn('control',out);self.assertNotIn('shared_device_budget',out)
  self.assertEqual(len(out['current_goals']),1);self.assertEqual(out['recent_records'][0]['source'],'synthetic')
  self.assertIsNone(compact_context(ctx,'列出详细用量',{'intent':'question'}))

class OwnExperience(unittest.TestCase):
 def test_own_focus_retrieves_actual_activity_not_another_persons_worry(self):
  with tempfile.TemporaryDirectory() as t:
   store=AgencyStore(t);store.migrate();scope='v1:'+'a'*64;other='v1:'+'b'*64
   store.ensure(scope);store.ensure(other);e=Experience(store);e.migrate()
   e.put(scope,'concern','课程汇报','明天要做课程汇报','open',[{'kind':'user_quote','ref':'synthetic:user','quote':'明天要做课程汇报'}],0)
   e.activity(scope,'synthetic:read','雨后气味','只读到公开摘要','search_snippet_not_full_page',['https://example.org/abstract'],0,
              question='土壤细菌的作用是什么',opinion='先查清机制再谈感觉')
   e.activity(other,'synthetic:other','量子理论','另一范围','visited_page',['https://example.org/other'],0)
   rows=e.view(scope,'你最近有什么在意的事',appraisal={'intent':'question'})
   self.assertTrue(rows);self.assertTrue(all(r['subject']=='雨后气味' for r in rows))
   self.assertIn('search_snippet_not_full_page',e.hint(scope,'你自己选一个话题'))
   self.assertNotIn('量子理论',str(rows));self.assertNotIn('课程汇报',str(rows))
   store.wipe(scope);self.assertEqual(e.view(scope,'你自己选一个话题'),[])
 def test_projection_bounds_evidence_and_preserves_provenance(self):
  record={'id':'one','kind':'concern','subject':'x'*500,'summary':'s'*3000,'status':'open','updated_at':123,
          'sources':[{'kind':'tool_receipt','ref':'r'*500,'quote':'q'*2000,'actor':'self','coverage':'visited_page'}]*6}
  before=copy.deepcopy(record);out=Experience.for_prompt([record]*9)
  self.assertEqual(record,before);self.assertEqual(len(out),3);self.assertLess(len(json.dumps(out)),4000)
  self.assertEqual(out[0]['sources'][0]['actor'],'self');self.assertEqual(out[0]['updated_at'],123)

class LocalizedReview(unittest.TestCase):
 def test_public_review_sees_same_group_speakers_without_private_context(self):
  from types import SimpleNamespace
  from astrbot_plugin_affect.prompt_context import review_evidence
  req=SimpleNamespace(contexts=[],extra_user_content_parts=[])
  scene={'current':{'id':'now','speaker':'memberB','text':'小赵转的，不知谁拍的'},
         'messages':[{'speaker':'memberA','text':'只知道是小赵转来','source':'live','sent_at':'2026-10-29'}],
         'private':'PRIVATE_SENTINEL','control':{'level':3}}
  out=review_evidence(req,scope_records=[],group_scene=scene)
  self.assertEqual(out['group']['current']['speaker'],'memberB');self.assertEqual(out['group']['messages'][0]['speaker'],'memberA')
  self.assertNotIn('PRIVATE_SENTINEL',str(out));self.assertEqual(out['recent'],[])
 def test_preserves_opinion_and_only_edits_bad_inference(self):
  text='嗯，是四点。那就来得及，我还挺期待你的汇报'
  raw=json.dumps({'issues':['time_guess'],'edits':[{'before':'那就来得及，','after':''}]},ensure_ascii=False)
  self.assertEqual(parse_review(raw,text,'四点开会',allow_legacy=False),'嗯，是四点。我还挺期待你的汇报')
 def test_refuses_full_rewrite_overlap_new_numbers_and_unknown_schema(self):
  text='我更喜欢这个结尾，因为它没有替人把话说尽，这一点挺难得。留下来的那一点空白，让人还能自己再想一会，而不是刚看完就被告知应该有什么感受'
  edits=[{'before':text,'after':'好的，我支持你'}, {'before':'结尾','after':'2030年'}]
  for edit in edits:
   with self.assertRaises(ValueError):parse_review(json.dumps({'issues':['unsupported_fact'],'edits':[edit]}),text,allow_legacy=False)
  with self.assertRaises(ValueError):parse_review('{"reply":"好的"}',text,allow_legacy=False)
  with self.assertRaises(ValueError):parse_review(json.dumps({'issues':['wrong_speaker'],'edits':[{'before':'结尾','after':''},{'before':'这个结尾','after':''}]}),text)
  self.assertEqual(parse_review('{"issues":[],"edits":[]}',text,allow_legacy=False),text)

if __name__=='__main__':unittest.main()
