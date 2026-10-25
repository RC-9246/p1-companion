"""P1-only synthetic paired model timing with the already approved DeepSeek account."""
import asyncio,json,statistics,time
from pathlib import Path
from openai import AsyncOpenAI
R=Path(__file__).resolve().parents[1]
async def run():
 cfg=json.loads(Path('/AstrBot/data/cmd_config.json').read_text(encoding='utf-8-sig'))
 pid=cfg['agent_runner']['config']['model']['provider_id'];p=next(x for x in cfg['provider'] if x['id']==pid)
 source=next(x for x in cfg['provider_sources'] if x['id']==p['provider_source_id']);keys=source['key'];key=keys[0] if isinstance(keys,list) else keys
 assert source['api_base'].rstrip('/') in ('https://api.deepseek.com','https://api.deepseek.com/v1')
 client=AsyncOpenAI(api_key=key,base_url=source['api_base'],timeout=42,max_retries=0)
 system='你是一个克制、独立、有温度的群聊伙伴。刚好看到当前公开话题，可表达自己的感受，不迎合，不提问，不做客服式邀约。只接一两句自然中文，不使用Markdown，不编造经历。'
 cases=['这段配乐的节奏真不错，听着有点想再看一集','忙了一天总算把小组报告交了，刚坐下来']
 records=[]
 for i,text in enumerate(cases):
  for mode in (('max','quick') if i==0 else ('quick','max')):
   start=time.monotonic()
   try:
    out=await client.chat.completions.create(model=p['model'],messages=[{'role':'system','content':system},{'role':'user','content':text}],max_tokens=32768 if mode=='max' else 2048,extra_body={'thinking':{'type':'enabled' if mode=='max' else 'disabled'}},**({'reasoning_effort':'max'} if mode=='max' else {}))
    body=out.choices[0].message.content or '';u=out.usage;d=getattr(u,'completion_tokens_details',None)
    r={'case':i+1,'mode':mode,'seconds':round(time.monotonic()-start,3),'ok':bool(body.strip()),'reply_characters':len(body),'reasoning_tokens':getattr(d,'reasoning_tokens',0) or 0,'completion_tokens':u.completion_tokens,
      'service_offer_phrase':any(x in body for x in ('如果你','我可以帮','随时找我')),'markdown_heading':body.startswith('#')}
   except Exception as exc:r={'case':i+1,'mode':mode,'seconds':round(time.monotonic()-start,3),'ok':False,'error':type(exc).__name__}
   records.append(r);print(json.dumps(r),flush=True)
 await client.close()
 report={'synthetic_only':True,'model':p['model'],'same_existing_account_and_endpoint':True,'real_private_context_sent':False,'real_qq_messages':0,'model_requests':len(records),'records':records,
  'median_model_seconds':{mode:round(statistics.median(r['seconds'] for r in records if r['mode']==mode and r['ok']),3) for mode in ('max','quick') if any(r['mode']==mode and r['ok'] for r in records)},
  'limits':'Two short synthetic scenes only; excludes production prompt, tools, appraisal, queue, required 2–5s delay and QQ transport; not a guarantee of chat latency or emotional quality.'}
 (R/'evidence/group-latency-model.json').write_text(json.dumps(report,indent=2))
if __name__=='__main__':asyncio.run(run())
