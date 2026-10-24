import hashlib,sys,unittest
from pathlib import Path
from types import SimpleNamespace as NS
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'release'))
from astrbot_plugin_affect.reply_chunks import media_evidence,retract_context_claims,ground_media_reply

class MediaGrounding(unittest.TestCase):
 def evidence(self,visible=0,direct=0):return {'current_visible_images':visible,'direct_images':direct}
 def test_incident_missing_image(self):
  self.assertEqual(ground_media_reply('一张梗图：紫发角色，图角上印着小红书号','这是什么',self.evidence()),'你指的是哪一项？这条消息里我没收到图片')
 def test_denial_cannot_be_overruled_by_old_assistant_claim(self):
  for q in ['我怎么不知道我发了这个','我没有发过图片','图片不是我发的']:
   out=ground_media_reply('图确实是从你这个窗口过来的，可能是另一个端登录',q,self.evidence())
   self.assertIn('我收回',out);self.assertNotIn('另一个端',out)
 def test_denial_blocks_unsupported_account_speculation(self):
  for draft in ['你之前发过图片','可能是另一个端登录了你的账号','也许是手滑']:
   self.assertIn('我收回',ground_media_reply(draft,'我没有发过图片',self.evidence()))
 def test_textual_answer_and_genuine_current_images_preserved(self):
  for draft,prompt,evidence in [('这是6174的固定点','这是什么',self.evidence()),('一张梗图','这是什么',self.evidence(1,1)),('图里是车','这个',self.evidence(1,0)),('那张图里有一只猫','昨天那张图片是什么',self.evidence())]:
   self.assertEqual(ground_media_reply(draft,prompt,evidence),draft)
 def test_recent_verified_same_sender_followup_preserved(self):
  e={**self.evidence(),'verified_recent_user_image':True,'historical_image_parts':1}
  self.assertEqual(ground_media_reply('图里是一只猫','这是什么',e),'图里是一只猫')
  e['historical_image_parts']=0
  self.assertIn('没收到图片',ground_media_reply('一张梗图','这是什么',e))
 def test_historical_or_bot_images_do_not_count_as_current(self):
  Image=type('Image',(),{});Reply=type('Reply',(),{})
  event=NS(get_messages=lambda:[Reply()])
  req=NS(image_urls=[],contexts=[{'role':'assistant','content':[{'type':'image_url','image_url':{'url':'fixture'}}]},{'role':'user','content':[{'type':'image_url'}]}])
  evidence=media_evidence(event,req)
  self.assertEqual(evidence,{'direct_images':0,'current_visible_images':0,'has_quote_or_forward':True,'historical_image_parts':2})
  event.get_messages=lambda:[Image()];req.image_urls=['fixture']
  self.assertEqual(media_evidence(event,req)['direct_images'],1)
 def test_exact_retraction_only_assistant_and_no_mutation(self):
  text='图确实是从你这个窗口过来的';h=hashlib.sha256(text.encode()).hexdigest()
  source=[{'role':'user','content':text},{'role':'assistant','content':[{'type':'think','think':'hidden fixture'},{'type':'text','text':' '+text}],'reasoning_content':'hidden fixture'},{'role':'assistant','content':'别的正常回复'}]
  updated,n=retract_context_claims(source,{h});self.assertEqual(n,1)
  self.assertEqual(source[1]['content'][1]['text'],' '+text)
  self.assertEqual(updated[0],source[0]);self.assertEqual(updated[2],source[2]);self.assertNotIn('reasoning_content',updated[1])
  self.assertIsInstance(updated[1]['content'],str)
  self.assertEqual(retract_context_claims(source,set())[1],0)
if __name__=='__main__':unittest.main()
