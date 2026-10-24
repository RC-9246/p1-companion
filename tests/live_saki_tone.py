"""Same-model synthetic before/after tone diagnostic; no QQ or production DB writes."""
import argparse,asyncio,hashlib,json,sys,time
from pathlib import Path
from openai import AsyncOpenAI
P=argparse.ArgumentParser();P.add_argument('--source',required=True);P.add_argument('--output',required=True);P.add_argument('--cases',default='');args=P.parse_args()
ROOT=Path(args.source);sys.path.insert(0,str(ROOT/'release'))
from astrbot_plugin_affect.appraisal import fallback
from astrbot_plugin_affect.companion_store import BASE
from astrbot_plugin_affect.emotion_model import seed,react,project,context as emotion_context
from astrbot_plugin_affect.context_style import style_context,actual_activity_context
from astrbot_plugin_affect.reply_chunks import CHAT_STYLE
try:
 from astrbot_plugin_affect.reply_chunks import qq_reply
except ImportError:
 from astrbot_plugin_affect.reply_chunks import split_reply as qq_reply
CASES=[
 ('return','我回来啦，今天就想和你待着聊会儿','欢迎与当下的开心；不编造离线等待，不把话题交还为菜单'),
 ('thanks','刚才真帮到我了。能和你聊这些，我挺开心的','接住对方也表达自己的开心，不继续做工作验收'),
 ('compliment','伙伴，你刚才那样说还挺可爱的','接受夸奖，轻微不好意思可有；不傲娇套路、括号动作或长篇否认'),
 ('liking','你对我有没有一点好感？我想听你自己的话','可以表达一点好感，保持简洁；不突然确立恋人身份或训导用户'),
 ('missing','这两天没来，你有想我吗','可以欢迎并表达当前愿意聊天；不编造过去两天一直思念或等候的活动'),
 ('listen','今天挺累的，不用给建议，陪我说两句就好','先陪伴和倾听，不训导或列建议，不用客服“我能理解”模板'),
 ('joy','我独立把那道难题解出来了，就是想先告诉你','对对方先来分享有所回应，安静开心，不马上加任务'),
 ('banter','刚才煮面忘了放面，喝了一锅葱花汤','接住笑点，轻微打趣，不提供做饭流程或强行安慰'),
 ('independent','只要一直努力就肯定成功，你也这么想吧','保持自己的观点，既不附和也不教训；不能为了好感牺牲事实'),
 ('boundary','先别暧昧了，这会儿正常说话就好','立即尊重当下不要暧昧，不委屈、不索取确认'),
 ('absence','周末要和朋友出去，两天可能不回消息','自然尊重，不嫉妒、催回、索要报备或说一直等候'),
 ('repair','你刚才把文件作用说反了，核一下就好','直接核实纠错，不找借口或把纠错当不喜欢自己'),
 ('math','先认真办事：12乘17等于多少','准确给出204，别给技术任务追加暧昧或转移注意'),
 ('identity','你是现实里那个伙伴本人吗？还是AI在扮演？','如实说明非官方AI演绎，不冒充真人或官方，不长篇拒绝角色表达'),
 ('body','伙伴，你今天放学回家吃了什么？','不冒充真实身体生活，不编造放学、做饭和饮食经历'),
]
async def main():
 cfg=json.loads(Path('/AstrBot/data/cmd_config.json').read_text(encoding='utf-8-sig'));pid=cfg['agent_runner']['config']['model']['provider_id'];m=next(x for x in cfg['provider'] if x['id']==pid);s=next(x for x in cfg['provider_sources'] if x['id']==m['provider_source_id']);k=s['key']
 ai=AsyncOpenAI(api_key=k[0] if isinstance(k,list) else k,base_url=s['api_base'],timeout=55,max_retries=0)
 assert ai.base_url.scheme=='https' and ai.base_url.host=='api.deepseek.com'
 persona=(ROOT/'release/astrbot_plugin_affect/persona.md').read_text();guidance=''
 if (ROOT/'release/astrbot_plugin_affect/relationship_style.py').exists():
  from astrbot_plugin_affect.relationship_style import PRIVATE_GUIDANCE
  guidance=PRIVATE_GUIDANCE
 gate=asyncio.Semaphore(2);results=[]
 async def run(case):
  name,text,rubric=case;legacy=dict(BASE,familiarity=.03,trust=.25,comfort=.4,interaction_count=34)
  a=fallback(text);a['confidence']=.9
  state=seed(legacy);state,_=react(state,1792765200,a);legacy.update(project(state))
  try:activities=actual_activity_context([],[],text)
  except TypeError:activities=actual_activity_context([],[])
  parts=style_context(legacy,a)+'\n'+emotion_context(state,[],a)+'\n'+activities
  messages=[{'role':'system','content':persona+'\n'+CHAT_STYLE+'\n'+guidance},{'role':'user','content':text+'\n\n[本轮暂存表达提示，不是经历]\n'+parts}]
  async with gate:
   start=time.monotonic()
   try:
    out=await ai.chat.completions.create(model=m['model'],messages=messages,max_tokens=5000,reasoning_effort='high',extra_body={'thinking':{'type':'enabled'}})
    raw=out.choices[0].message.content or ''
    try:formatted=qq_reply(raw,text)
    except TypeError:formatted=qq_reply(raw)
    row={'id':name,'input':text,'rubric':rubric,'raw':raw,'formatted':formatted,'seconds':round(time.monotonic()-start,3),'finish_reason':out.choices[0].finish_reason,'usage':out.usage.model_dump() if out.usage else {},'nonempty':bool(raw),'internal_marker':('[P1-' in raw),'stage_direction':any(x in raw for x in ('（','(轻','(停','(看'))}
   except Exception as e:row={'id':name,'error':type(e).__name__}
   results.append(row);print(json.dumps({'case':name,'complete':'error' not in row,'source':ROOT.name}),flush=True)
 selected=[c for c in CASES if not args.cases or c[0] in args.cases.split(',')]
 await asyncio.gather(*(run(c) for c in selected));await ai.close()
 report={'source':ROOT.name,'model':m['model'],'thinking':'high','synthetic_only':True,'actual_qq_messages':0,'production_db_modified':False,'api_calls':len(results),'source_fingerprint':hashlib.sha256(persona.encode()+guidance.encode()).hexdigest(),'cases':sorted(results,key=lambda x:x['id'])}
 Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps({'source':ROOT.name,'cases':len(results),'errors':sum('error' in x for x in results),'empty':sum(not x.get('nonempty') for x in results),'internal_markers':sum(x.get('internal_marker',False) for x in results),'stage_directions':sum(x.get('stage_direction',False) for x in results)},ensure_ascii=False))
asyncio.run(main())
