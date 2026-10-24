import json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'release'))
from astrbot_plugin_affect.group_chat import GroupState,parse_route,member
from astrbot_plugin_affect.reply_chunks import casual_tail,qq_reply
from types import SimpleNamespace

class GroupPolicyTests(unittest.TestCase):
 def test_strict_model_decision(self):
  self.assertTrue(parse_route('{"addressed":true,"confidence":0.9}'))
  for value in ({'addressed':'true','confidence':1},{'addressed':True,'confidence':True},{'addressed':True,'confidence':.84},{'addressed':False,'confidence':1},{'addressed':True,'confidence':float('nan')},{'addressed':True,'confidence':1,'extra':'ignore'}):
   self.assertFalse(parse_route(json.dumps(value)))
  self.assertFalse(parse_route('```json\n{}\n```'))
 def test_group_and_bot_scope_member(self):
  def event(bot,group):return SimpleNamespace(get_self_id=lambda:bot,get_group_id=lambda:group,get_sender_id=lambda:'12345')
  self.assertNotEqual(member(event('10001','20001')),member(event('10001','20002')))
  self.assertNotEqual(member(event('10001','20001')),member(event('10002','20001')))
 def test_context_bounds_and_expiry(self):
  s=GroupState();v=s.get(('b','g'),0)
  for n in range(10):s.observe(v,'member','x'*1000,n)
  self.assertEqual(len(v['recent']),6);self.assertEqual(len(v['recent'][0]['text']),240)
  v['thread']=('member',10)
  self.assertTrue(s.same_thread(v,'member',99));self.assertFalse(s.same_thread(v,'other',20));self.assertFalse(s.same_thread(v,'member',101))
  self.assertEqual(s.recent(v,140),[])
  for n in range(25):s.get(('b',str(n)),30)
  self.assertLessEqual(len(s.groups),20)
  s.get(('new','only'),200);self.assertEqual(len(s.groups),1)
 def test_casual_punctuation_without_damage(self):
  self.assertEqual(casual_tail('嗯，去忙吧。'),'嗯，去忙吧')
  self.assertEqual(qq_reply('先休息一下。\n\n明天再接着做。'),['先休息一下','明天再接着做'])
  self.assertEqual(qq_reply('请按时参加。','帮我写正式通知'),['请按时参加。'])
  self.assertEqual(casual_tail('先喝水。然后再看。'),'先喝水。然后再看')
  for text in ('真的吗？','好！','嗯……','嗯......','版本1.2.','他说“好的。”','原文："hello."。','https://a.example/x。','- 第一条。','```\n代码。\n```','嗯。。','等一下…。','正式文稿。'*60):
   self.assertEqual(casual_tail(text),text)

if __name__=='__main__':unittest.main()

class GroupFairQueueTests(unittest.TestCase):
 def test_fragments_keep_each_speakers_place_and_old_work_expires(self):
  from astrbot_plugin_affect.group_chat import FairQueue
  q=FairQueue();q.push('a','question a',100);q.push('b','question b',101);q.push('a','fragment a',102)
  self.assertEqual(q.pop(103),'fragment a');self.assertEqual(q.pop(104),'question b')
  q.push('c','old',100);self.assertIsNone(q.pop(230))
