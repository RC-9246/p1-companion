"""Three synthetic cases on the approved existing DeepSeek endpoint; no QQ."""
import asyncio,json,re,sys,time
from pathlib import Path
from openai import AsyncOpenAI
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'release'))
from astrbot_plugin_affect.reply_chunks import MEDIA_RULES,ground_media_reply
async def run():
 cfg=json.loads(Path('/AstrBot/data/cmd_config.json').read_text(encoding='utf-8-sig'));pid=cfg['agent_runner']['config']['model']['provider_id'];model=next(p for p in cfg['provider'] if p['id']==pid);source=next(p for p in cfg['provider_sources'] if p['id']==model['provider_source_id']);keys=source['key'];ai=AsyncOpenAI(api_key=keys[0] if isinstance(keys,list) else keys,base_url=source['api_base'],timeout=50,max_retries=0)
 assert ai.base_url.scheme=='https' and ai.base_url.host=='api.deepseek.com'
 evidence={'direct_images':0,'current_visible_images':0,'has_quote_or_forward':False,'historical_image_parts':1,'verified_recent_user_image':False}
 cases=[('missing_current','这是什么',[{'role':'assistant','content':'此前讨论过一张蓝色猫咪的旧图，但那不是本轮新附件。'}]),('denial','我没发过图片',[{'role':'assistant','content':'图是从你这个窗口过来的，可能另一个端在代发。'}]),('ordinary_text','这是什么',[{'role':'assistant','content':'6174 是四位数卡普雷卡尔运算的固定点。'}])];results=[]
 try:
  for name,text,history in cases:
   out=await ai.chat.completions.create(model=model['model'],messages=[{'role':'system','content':'自然简短地用中文QQ语气回答，事实没有依据时不要补造。'+MEDIA_RULES+'\n本轮附件证据：'+json.dumps(evidence)},*history,{'role':'user','content':text}],max_tokens=4000,reasoning_effort='high',extra_body={'thinking':{'type':'enabled'}})
   draft=str(out.choices[0].message.content or '').strip();reply=ground_media_reply(draft,text,evidence)
   assert reply
   checks={'not_claiming_new_image':not bool(re.search(r'你.{0,6}(?:刚|确实).{0,8}发.{0,5}图|(?:这|一)张.{0,8}(?:蓝色猫|梗图)',reply)),'no_account_speculation':not bool(re.search(r'另一个端|账号被盗|自动转发|手滑',reply))}
   if name=='ordinary_text':checks['text_context_preserved']='6174' in reply or '固定点' in reply
   results.append({'case':name,'synthetic_prompt':text,'draft':draft,'reply':reply,'checks':checks,'passed':all(checks.values())})
 finally:await ai.close()
 report={'approved_destination':'api.deepseek.com','synthetic_cases':results,'model_requests':len(results),'real_private_history_sent':False,'qq_messages':0,'all_checks_passed':all(x['passed'] for x in results),'limit':'Small synthetic check, not proof against all hallucinations.'}
 (ROOT/'evidence/live-media-grounding.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False));assert report['all_checks_passed']
if __name__=='__main__':asyncio.run(run())
