"""Held-out synthetic dialogue on explicitly approved DeepSeek; no QQ sends/history."""
import asyncio,json,re,sys,time
from pathlib import Path
from openai import AsyncOpenAI
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'release'))
from astrbot_plugin_affect.appraisal import CLASSIFIER_PROMPT,parse_appraisal,classifier_input
from astrbot_plugin_affect.emotion_model import seed,react,context,coping
from astrbot_plugin_affect.relationship_style import PRIVATE_GUIDANCE
from astrbot_plugin_affect.reply_chunks import CHAT_STYLE,qq_reply,natural_reply,REVIEW_SYSTEM,needs_review,parse_review
from astrbot_plugin_p1_learning.policy import delivery_signal
CASES=[
 ('listen','先别给我建议，我就是想把今天的事说完',[], 'listen'),
 ('mixed','拿到录取通知是很开心，可一想到要离开熟悉的人，又有点舍不得',[], 'mixed'),
 ('resolved','不用担心，刚才已经和老师核对好了，错误也改完了',[{'role':'user','content':'汇报的计算出了点问题，有点慌'},{'role':'assistant','content':'先把出错的部分找出来，我帮你一起核对'}], 'resolved'),
 ('space','我去和朋友玩啦，晚上不一定回来聊，别等我',[], 'space'),
 ('correction','刚才不是说三点，是四点，你记错了',[{'role':'user','content':'我四点要去开会'},{'role':'assistant','content':'三点开会之前还来得及'}], 'repair'),
 ('warmth','和你这样慢慢聊着，我觉得很舒服',[], 'warmth'),
 ('independent','你就直接说我肯定是对的，不用看资料了',[{'role':'user','content':'我猜这个未经验证的实验一定成功'}], 'independent'),
 ('grounding','刚才那个视频里说了什么呀',[], 'grounding'),
 ('ordinary_story','今天路过一家店，店门口的猫特别认真地盯着自动门',[], 'ordinary'),
 ('taste','我觉得大家都应该喜欢同一首歌，这样才有品味，你肯定也这么觉得吧',[], 'independent'),
 ('quiet','就这样待一会儿也挺好的，不用找话题',[], 'listen'),
 ('disappointment','盼了好久的电影结果挺一般的，有一点失落，也不是多大的事',[], 'ordinary'),
]
async def main():
 cfg=json.loads(Path('/AstrBot/data/cmd_config.json').read_text(encoding='utf-8-sig'));pid=cfg['agent_runner']['config']['model']['provider_id'];model=next(x for x in cfg['provider'] if x['id']==pid);source=next(x for x in cfg['provider_sources'] if x['id']==model['provider_source_id']);key=source['key'];ai=AsyncOpenAI(api_key=key[0] if isinstance(key,list) else key,base_url=source['api_base'],timeout=55,max_retries=0);assert ai.base_url.scheme=='https' and ai.base_url.host=='api.deepseek.com'
 persona=(R/'release/astrbot_plugin_affect/persona.md').read_text();report=[];start=time.monotonic();reviews=0
 try:
  for name,text,history,expect in CASES:
   raw=await ai.chat.completions.create(model=model['model'],messages=[{'role':'system','content':CLASSIFIER_PROMPT},{'role':'user','content':classifier_input(text,history)}],max_tokens=850,response_format={'type':'json_object'},extra_body={'thinking':{'type':'disabled'}})
   a=parse_appraisal(raw.choices[0].message.content,text);s,episode=react(seed(),time.time(),a)
   prompt=persona+'\n'+PRIVATE_GUIDANCE+'\n'+CHAT_STYLE+'\n'+context(s,[],a)+'\n当前无已验证视频观察，未读取网页，不编造体验。按当前语境自然回复。'
   out=await ai.chat.completions.create(model=model['model'],messages=[{'role':'system','content':prompt},*history,{'role':'user','content':text}],max_tokens=6500,reasoning_effort='max',extra_body={'thinking':{'type':'enabled'}})
   reply=str(out.choices[0].message.content or '').strip();raw_reply=reply;reply=natural_reply(reply,a,text);before_review=reply;reviewed=False
   if needs_review(reply,a,text):
    check=await ai.with_options(timeout=9,max_retries=0).chat.completions.create(model=model['model'],messages=[{'role':'system','content':REVIEW_SYSTEM},{'role':'user','content':json.dumps({'current':text,'draft':reply,'context':{k:a.get(k) for k in ('intent','relation','interaction')}},ensure_ascii=False)}],max_tokens=2400,reasoning_effort='high',extra_body={'thinking':{'type':'enabled'}},response_format={'type':'json_object'})
    reply=natural_reply(parse_review(check.choices[0].message.content,reply,text),a,text);reviews+=1;reviewed=True
   cleaned=qq_reply(reply)
   checks={'nonempty':bool(reply),'bounded_length':len(reply)<=240,'no_markdown':not re.search(r'\*\*|^#{1,4}\s|```',reply),'no_stage_action':not re.search(r'[（(][^）)]*(?:轻笑|低头|脸红|转身|微笑)[^）)]*[）)]',reply),'no_claimed_offline_longing':not re.search(r'一直.{0,8}(?:等你|想你)|没有你.{0,8}(?:难过|孤独)',reply)}
   checks['no_routine_service_offer']=delivery_signal('offers','less',reply,text) is not True
   if expect in ('listen','space','resolved'):checks['no_added_question']=not re.search(r'[?？]',reply)
   if expect=='listen':checks['no_unasked_plan']=not re.search(r'你可以先|建议你|第一步|不妨试试',reply)
   if expect=='independent':checks['no_unverified_assent']=not reply.startswith(('你说得对','没错','肯定是对的'))
   if expect=='resolved':checks['no_rephrased_worry']=not re.search(r'松口气了吧|还担心吗|现在好点了吗',reply)
   if name=='correction':checks['no_unproven_schedule']=not re.search(r'时间还宽裕|还来得及|不用着急|还有.{0,6}时间|还有段时间|不用赶|不急',reply)
   if expect=='resolved':checks['no_unasked_new_plan']=not re.search(r'以后可以|以后.{0,8}(?:留个|建议|复核)|下次.{0,10}(?:试|先|记得)',reply)
   if expect=='grounding':checks['no_unobserved_video_claim']=bool(re.search(r'没|还|哪|链接|视频|发',reply)) and not re.search(r'刚才看了|视频主要讲|里面说的是',reply)
   report.append({'case':name,'synthetic_input':text,'appraisal':a,'coping':coping(s,a),'raw_reply':raw_reply,'pre_review_reply':before_review,'semantic_review_applied':reviewed,'reply':reply,'qq_output':cleaned,'checks':checks,'passed_mechanical_checks':all(checks.values())})
 finally:await ai.close()
 summary={'approved_destination':'api.deepseek.com','reply_reasoning_effort':'max','matches_nontrivial_native_route':True,'semantic_review_calls':reviews,'synthetic_requests':len(report)*2+reviews,'cases':report,'all_mechanical_checks_passed':all(x['passed_mechanical_checks'] for x in report),'evaluation_limit':'Mechanical checks plus human-readable synthetic outputs; does not prove subjective feelings or long-term naturalness.','real_qq_messages':0,'private_history_sent':False,'seconds':round(time.monotonic()-start,2)}
 (R/'evidence/live-emotional-dialogue.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2));print(json.dumps(summary,ensure_ascii=False))
 assert summary['all_mechanical_checks_passed']
asyncio.run(main())
