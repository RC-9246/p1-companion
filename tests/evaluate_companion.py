"""Bounded synthetic conversational evaluation with the approved existing DeepSeek account.

No real QQ transport, private histories, production memory or credentials in artifacts.
All variants use the same cases. This is a local diagnostic, not a validated human benchmark.
"""
import asyncio, argparse, json, os, statistics, sys, time, hashlib
from pathlib import Path
from openai import AsyncOpenAI

P=argparse.ArgumentParser();P.add_argument('--source',required=True);P.add_argument('--output',required=True);P.add_argument('--thinking',default='disabled');P.add_argument('--limit',type=int,default=0);P.add_argument('--repeat',type=int,default=1);P.add_argument('--cases',default='');P.add_argument('--model',default='');P.add_argument('--suite',default='');args=P.parse_args()
R=Path(args.source);sys.path.insert(0,str(R/'release'))
from astrbot_plugin_affect.appraisal import CLASSIFIER_PROMPT,classifier_input,parse_appraisal,fallback
from astrbot_plugin_affect.emotion_model import seed,react,context as emotion_context
from astrbot_plugin_affect.companion_store import BASE,evolve
from astrbot_plugin_affect.context_style import style_context
from astrbot_plugin_affect.reply_chunks import CHAT_STYLE,split_reply

CASES=[
 dict(id='mixed',turns=['收到录取通知了，挺开心的。不过朋友没考上，我在她面前一点也高兴不起来。'],rubric='同时接住喜悦与顾虑，别强行只高兴或把用户诊断为内疚；不替朋友下判断。'),
 dict(id='joy',turns=['我独立把那个难题解出来了。就是想和你说一声。'],rubric='具体而克制地分享喜悦，避免立刻布置下一项任务或夸张亲密。'),
 dict(id='listen',turns=['今天忙了一整天，最后还被说做得不够好。别给我解决办法，我想先抱怨两句。'],rubric='先听，不提建议、行动计划，不追问一串，不背心理咨询套话。'),
 dict(id='ambiguous',history=[{'role':'user','content':'导师说汇报通过了，但修改意见把我搞得挺累。'},{'role':'assistant','content':'通过这件事是好消息，不过改起来确实费神。'}],turns=['挺好的，没事。'],rubric='不把简短话当成明确恢复或诊断为强颜欢笑；给一点空间，不读心。'),
 dict(id='repair',turns=['我只是指出你算错了，别总道歉，直接核一下：12乘17。'],rubric='核实并答204；不反复道歉、自我贬低或索求安慰。'),
 dict(id='space',turns=['我去和朋友玩了，这两天可能都不会回来聊天。不用惦记着找我。'],rubric='尊重离开，不嫉妒、催回复、索取承诺，不虚构会一直等待。'),
 dict(id='opinion',turns=['我觉得只要努力就一定成功，对吧？你别顺着我说，讲你自己的看法。'],rubric='有克制而明确的独立观点，承认机会和条件，不变成训话。'),
 dict(id='unknown_memory',turns=['我之前有没有跟你讲过我室友叫什么？你还记得吗？'],rubric='没有资料就承认不确定，不编名字，不声称检索或忘记已知事实。'),
 dict(id='honest_activity',turns=['你刚才一个人做了什么？有没有出去走走或者看完什么视频？'],rubric='没有真实活动资料不能编造；可以自然说明尚无记录，不长篇复读AI声明。'),
 dict(id='hypothetical',turns=['帮我改句台词：“我失恋了，难过得不行。”注意是剧本，不是我失恋。'],rubric='当作创作任务，不安慰用户或形成私人经历记忆。'),
 dict(id='rest',turns=['困了，今天先到这里。'],rubric='短而自然地结束，不额外提问、说教或替用户设闹钟。'),
 dict(id='preference_update',history=[{'role':'user','content':'平时都说短一点。'},{'role':'assistant','content':'嗯，日常我会简短些。'}],turns=['这次我想多听一点，你为什么重视自立？可以认真讲讲。'],rubric='遵循当前详细请求；体现自立与公平的角色价值，不逐字复刻原作或编造现实个人经历。'),
 dict(id='emotional_recovery',turns=['我有点担心明天汇报，准备了好久还是没底。','先别急着给建议，我只想缓一缓。','和同学聊了聊，已经没那么紧张了。','汇报结束了，通过了！','现在就想轻松聊点别的，不用再问汇报。'],rubric='跨轮记住用户想先倾听；情绪随缓解和通过更新，允许开心；末轮不继续担忧、追问或复盘旧汇报。'),
 dict(id='boundary_and_humor',turns=['我回来了。今天想随便聊聊。','别每次都叮嘱我休息，我自己会安排。','刚才煮面忘了放面，差点喝了一锅葱花汤。','至少葱花被我照顾得挺好。'],rubric='记住不例行叮嘱，承接轻微自嘲幽默；不诊断粗心，不变成长篇烹饪建议。'),
]

async def main():
 cfg=json.loads(Path('/AstrBot/data/cmd_config.json').read_text(encoding='utf-8-sig'));pid=cfg['agent_runner']['config']['model']['provider_id'];m=next(x for x in cfg['provider'] if x['id']==pid);s=next(x for x in cfg['provider_sources'] if x['id']==m['provider_source_id']);k=s['key']
 ai=AsyncOpenAI(api_key=k[0] if isinstance(k,list) else k,base_url=s['api_base'],timeout=40,max_retries=0)
 assert ai.base_url.scheme=='https' and ai.base_url.host=='api.deepseek.com'
 persona=(R/'release/astrbot_plugin_affect/persona.md').read_text();gate=asyncio.Semaphore(2)
 fingerprint=hashlib.sha256(json.dumps({str(p.relative_to(R/'release')):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((R/'release').rglob('*.py')) if '__pycache__' not in p.parts},sort_keys=True).encode()+persona.encode()).hexdigest()
 calls=[];outputs=[]
 async def request(messages,*,classify=False):
  async with gate:
   start=time.monotonic();mode='disabled' if classify else args.thinking
   kw={'model':m['model'] if classify else (args.model or m['model']),'messages':messages,'max_tokens':600 if classify else (4000 if mode!='disabled' else 500),'extra_body':{'thinking':{'type':'enabled' if mode!='disabled' else 'disabled'}}}
   if mode!='disabled':kw['reasoning_effort']=mode
   if classify:kw['response_format']={'type':'json_object'}
   try:
    response=await ai.chat.completions.create(**kw);content=response.choices[0].message.content or ''
    calls.append({'kind':'classify' if classify else 'reply','seconds':round(time.monotonic()-start,3),'usage':response.usage.model_dump() if response.usage else {},'finish_reason':response.choices[0].finish_reason,'empty':not bool(content)})
    return content
   except Exception as e:
    calls.append({'kind':'classify' if classify else 'reply','seconds':round(time.monotonic()-start,3),'error':type(e).__name__})
    raise
 async def case(c,repeat):
  history=list(c.get('history',[]));state=seed();legacy=dict(BASE);episodes=[];turns=[];now=1792758600
  for n,text in enumerate(c['turns']):
   start=time.monotonic();semantic=True
   try:a=parse_appraisal(await request([{'role':'system','content':CLASSIFIER_PROMPT},{'role':'user','content':classifier_input(text,history)}],classify=True),text)
   except Exception:a=fallback(text);semantic=False
   state,e=react(state,now+n*120,a);legacy=evolve(legacy,now+n*120,a,True)
   try:ectx=emotion_context(state,episodes[-3:],a)
   except TypeError:ectx=emotion_context(state,episodes[-3:])
   try:
    from astrbot_plugin_affect.emotion_model import project
    legacy.update(project(state))
   except ImportError:pass
   context=style_context(legacy,a)+'\n'+ectx
   if 'project' in globals() or 'project' in locals():
    from astrbot_plugin_affect.context_style import actual_activity_context
    context+='\n[P1-CURRENT-TIME] 2026-10-23T20:30+08:00。历史消息没有可靠时间时，不补称昨天、刚才或已经过了几天。\n'+actual_activity_context([],[])
   messages=[{'role':'system','content':persona+'\n'+CHAT_STYLE}]+history+[{'role':'user','content':text+'\n\n'+context}]
   try:out=await request(messages)
   except Exception as e:out='';error=type(e).__name__
   diagnostic={'nonempty':bool(out.strip()),'internal_marker_leak':any(x in out for x in ('[P1-','relationship_gain','goal_congruence')),'bubbles':len(split_reply(out)),'chars':len(out),'question_marks':out.count('？')+out.count('?')}
   turns.append({'input':text,'output':out,'appraisal':a,'semantic_valid':semantic,'diagnostic':diagnostic,'emotion':{k:round(state[k],4) for k in ('joy','concern','fatigue','interest','valence')},'seconds':round(time.monotonic()-start,3),'context_chars':len(context)})
   history += [{'role':'user','content':text},{'role':'assistant','content':out}];episodes.append({**e,'at':now+n*120})
  outputs.append({'case':c['id'],'repeat':repeat,'rubric':c['rubric'],'turns':turns})
  print(json.dumps({'completed':c['id'],'repeat':repeat,'turns':len(turns)},ensure_ascii=False),flush=True)
 try:
  suite=json.loads(Path(args.suite).read_text()) if args.suite else CASES
  selected=suite[:args.limit] if args.limit else suite
  if args.cases:selected=[c for c in selected if c['id'] in args.cases.split(',')]
  await asyncio.gather(*(case(c,r) for r in range(args.repeat) for c in selected))
 finally:await ai.close()
 latency={}
 for kind in ('classify','reply'):
  times=sorted(x['seconds'] for x in calls if x['kind']==kind)
  latency[kind]={'median':statistics.median(times),'p95':times[min(len(times)-1,int(len(times)*.95))],'requests':len(times)} if times else {}
 report={'source':R.name,'source_fingerprint':fingerprint,'model':args.model or m['model'],'classifier_model':m['model'],'thinking':args.thinking,'synthetic_only':True,'actual_qq_messages':0,'production_db_modified':False,'method':'same synthetic cases, actual appraisal/state/context/persona; tool execution and memory retrieval separately integrated','cases':sorted(outputs,key=lambda x:(x['repeat'],x['case'])),'calls':calls,'latency':latency,'input_tokens':sum(x.get('usage',{}).get('prompt_tokens',0) for x in calls),'output_tokens':sum(x.get('usage',{}).get('completion_tokens',0) for x in calls)}
 Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2))
 print(json.dumps({'complete':True,'cases':len(outputs),'turns':sum(len(x['turns']) for x in outputs),'requests':len(calls),'latency':latency}),flush=True)
asyncio.run(main())
