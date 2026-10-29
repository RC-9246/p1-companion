"""Exercise the evaluation CLI with an offline provider, including malformed replies."""
import json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
R=Path(__file__).resolve().parents[1]
STUB='''from types import SimpleNamespace as N
import json,os
class AsyncOpenAI:
 def __init__(self,**kw):self.base_url=N(host='api.deepseek.com',scheme='https');self.chat=N(completions=self)
 async def create(self,**kw):
  score=dict(grounding=4,continuity=4,independent_view=4,emotional_nuance=4,natural_expression=4,group_judgement=4)
  text='malformed final output' if os.environ['OFFLINE_JUDGE_MODE']=='invalid' else json.dumps(dict(winner='tie',scores=dict(X=score,Y=score),problems=dict(X=[],Y=[])))
  return N(choices=[N(message=N(content=text,reasoning_content='MUST_NOT_BE_SAVED'))],usage=N(prompt_tokens=10,completion_tokens=2))
 async def close(self):pass
'''
class JudgeAccounting(unittest.TestCase):
 def run_case(self,mode):
  with tempfile.TemporaryDirectory() as t:
   d=Path(t);(d/'openai.py').write_text(STUB);(d/'credentials.json').write_text(json.dumps(dict(key='synthetic-secret-not-for-output',model='synthetic',base_url='https://api.deepseek.com')))
   case=dict(case='synthetic',family='ordinary',completed=True,rubric='合成检查',turns=[dict(input='你好',output='嗯')])
   for label in ('left','right'):(d/(label+'.json')).write_text(json.dumps(dict(variant=label,case_file_sha256='synthetic',cases=[case])))
   p=subprocess.run([sys.executable,str(R/'evaluation/judge_dialogues.py'),'--run','--left',str(d/'left.json'),'--right',str(d/'right.json'),'--credentials',str(d/'credentials.json'),'--output',str(d/'result.json')],env={**os.environ,'PYTHONPATH':str(d),'OFFLINE_JUDGE_MODE':mode},capture_output=True,text=True,timeout=15)
   self.assertEqual(p.returncode,0,p.stderr);text=(d/'result.json').read_text();self.assertNotIn('MUST_NOT_BE_SAVED',text);self.assertNotIn('synthetic-secret-not-for-output',text)
   result=json.loads(text);self.assertEqual(result['schema'],2);self.assertEqual(result['usage']['completed'],2);self.assertEqual(result['usage']['input_tokens'],20);self.assertEqual(result['usage']['output_tokens'],4);return result
 def test_invalid_responses_still_count_cost_and_keep_private_final_answer(self):
  result=self.run_case('invalid');self.assertEqual(result['usage']['valid_judgements'],0);self.assertEqual(result['usage']['errors'],2)
  self.assertEqual(result['cases'][0]['state'],'judge_error');self.assertTrue(all(x['invalid_final_output_private']=='malformed final output' for x in result['cases'][0]['reviews']))
 def test_valid_counterbalanced_ties_remain_valid(self):
  result=self.run_case('valid');self.assertEqual(result['usage']['valid_judgements'],2);self.assertEqual(result['usage']['errors'],0);self.assertEqual(result['summary']['tie'],1)
if __name__=='__main__':unittest.main()
