"""Opt-in synthetic dialogue experiment using an explicitly supplied DeepSeek key.

No QQ, browser, production memory or live chat input. Each case has its own
scratch state; fake delivery IDs are labelled synthetic. The private character
card, credential file and raw outputs are never publication artifacts.
"""
import argparse,asyncio,hashlib,json,os,statistics,sys,tempfile,time
from pathlib import Path
from types import SimpleNamespace as N
P=argparse.ArgumentParser(description=__doc__);P.add_argument('--run',action='store_true');P.add_argument('--source',type=Path,required=True);P.add_argument('--cases',type=Path,required=True);P.add_argument('--credentials',type=Path,required=True);P.add_argument('--persona',type=Path,required=True);P.add_argument('--group-persona',type=Path);P.add_argument('--output',type=Path,required=True);P.add_argument('--variant',choices=('A','B','C','D'),required=True);P.add_argument('--max-calls',type=int,default=320);P.add_argument('--limit',type=int,default=0);P.add_argument('--effort',choices=('high','max'),default='max');a=P.parse_args()
if not a.run:raise SystemExit('No calls made. Supply --run only for an authorized synthetic evaluation.')
sys.path[:0]=[str(a.source/'release')]
from astrbot_plugin_affect.appraisal import CLASSIFIER_PROMPT,classifier_input,parse_appraisal,fallback
from astrbot_plugin_affect.emotion_model import seed,react,context as emotion_context
from astrbot_plugin_affect.reply_chunks import CHAT_STYLE,natural_reply,qq_reply,needs_review,parse_review,REVIEW_SYSTEM
from astrbot_plugin_affect.context_style import style_context
from openai import AsyncOpenAI
secret=json.loads(a.credentials.read_text());client=AsyncOpenAI(api_key=secret['key'],base_url=secret['base_url'],timeout=50,max_retries=0)
if client.base_url.host!='api.deepseek.com' or client.base_url.scheme!='https':raise SystemExit('unapproved_evaluation_destination')
persona=a.persona.read_text();group_persona=a.group_persona.read_text() if a.group_persona else persona;cases=json.loads(a.cases.read_text());cases=cases[:a.limit] if a.limit else cases
stats={'calls':0,'completed':0,'errors':0,'input_tokens':0,'output_tokens':0,'reasoning_tokens':0,'seconds':0.};lock=asyncio.Lock();gate=asyncio.Semaphore(3);results=[];began=time.monotonic()
async def invoke(messages,kind,json_mode=False,deep=False):
 async with lock:
  if stats['calls']>=a.max_calls or stats['output_tokens']>=600000:raise RuntimeError('evaluation_budget')
  stats['calls']+=1
 start=time.monotonic()
 try:
  out=await client.chat.completions.create(model=secret['model'],messages=messages,temperature=.45 if kind=='generation' else 0,max_tokens=4096 if deep else (1100 if kind=='classifier' else 1200),extra_body={'thinking':{'type':'enabled' if deep else 'disabled'}},**({'reasoning_effort':a.effort} if deep else {}),**({'response_format':{'type':'json_object'}} if json_mode else {}))
  usage=out.usage;detail=getattr(usage,'completion_tokens_details',None)
  async with lock:
   stats['completed']+=1;stats['input_tokens']+=int(getattr(usage,'prompt_tokens',0) or 0);stats['output_tokens']+=int(getattr(usage,'completion_tokens',0) or 0);stats['reasoning_tokens']+=int(getattr(detail,'reasoning_tokens',0) or 0);stats['seconds']+=time.monotonic()-start
  return out.choices[0].message.content or ''
 except Exception:
  async with lock:stats['errors']+=1
  raise
async def run_case(case):
 async with gate:
  with tempfile.TemporaryDirectory(prefix='synthetic-emotion-') as tmp:
   state=seed();episodes=[];history=list(case.get('history',[]));turns=[];store=None;experience=None;lessons=None
   scope='v1:'+hashlib.sha256(('synthetic:'+case['id']).encode()).hexdigest()
   if a.variant in ('C','D'):
    from astrbot_plugin_affect.agency_store import AgencyStore
    from astrbot_plugin_affect.experience import Experience
    store=AgencyStore(tmp);store.migrate();store.ensure(scope);experience=Experience(store);experience.migrate()
   if a.variant=='D':
    from astrbot_plugin_p1_learning.store import Store as Learning
    from astrbot_plugin_p1_learning.policy import fast_preferences,fast_lessons,relevant_cards,hints,temporary_preferences
    lessons=Learning(Path(tmp)/'learning.db');lessons.migrate();lessons.meta(scope)
   # Seed only exact synthetic user history, through the same actual classifier.
   if experience:
    for i,row in enumerate(history[-2:]):
     if row.get('role')!='user':continue
     try:
      raw=await invoke([{'role':'system','content':CLASSIFIER_PROMPT},{'role':'user','content':classifier_input(row['content'],[])}],'classifier',True)
      appraisal=parse_appraisal(raw,row['content']);experience.observe(scope,'synthetic:history:'+str(i),row['content'],appraisal,0)
     except Exception:pass
   for index,text in enumerate(case['turns']):
    before=time.monotonic();recent=history[-12:];assessment=fallback(text);classifier='fallback';reviewed=False
    try:
     payload=json.loads(classifier_input(text,recent))
     if experience:payload['concerns']=experience.view(scope,'',3,actor='')
     raw=await invoke([{'role':'system','content':CLASSIFIER_PROMPT},{'role':'user','content':json.dumps(payload,ensure_ascii=False)}],'classifier',True)
     assessment=parse_appraisal(raw,text);classifier='semantic'
    except Exception:pass
    preview,episode=react(state,time.time()+index,assessment);contexts=emotion_context(preview,episodes[-4:]);system=(group_persona if case.get('family')=='group' else persona)+'\n'+CHAT_STYLE+'\n'+contexts
    if case.get('family')=='group':system+='\n这是公开群聊，发言人和引用已标在资料中；不继承私聊关系。没有被找且无具体贡献时可用一句“[旁听]”表示此轮不发送。'
    if experience:system+='\n'+experience.hint(scope,text)
    if lessons:
     cards=relevant_cards([*lessons.temporaries(scope),*lessons.cards(scope)],text,2)
     if cards:system+='\n当前范围的明确表达反馈：'+json.dumps(hints(cards),ensure_ascii=False)
    messages=[{'role':'system','content':system},*recent,{'role':'user','content':text}]
    try:
     draft=await invoke(messages,'generation',deep=True)
     if not draft.strip():raise ValueError('empty_generation')
     final=natural_reply(draft,assessment,text)
     if needs_review(final,assessment,text):
      packet={'current':text,'draft':final,'context':assessment}
      if a.variant!='A':packet['shared_generation_evidence']={'recent':recent,'scoped_facts':experience.view(scope,text,3) if experience else [],'visual_pixels_supplied_to_reviewer':False}
      try:
       raw=await invoke([{'role':'system','content':REVIEW_SYSTEM},{'role':'user','content':json.dumps(packet,ensure_ascii=False)}],'review',True,False)
       final=natural_reply(parse_review(raw,final,text),assessment,text);reviewed=True
      except Exception:pass
     bubbles=qq_reply(final,text);state=preview;episodes.append(episode)
     receipt='synthetic:'+case['id']+':'+str(index)
     if experience:
      experience.observe(scope,receipt,text,assessment,0)
      if len(text)>=6:experience.put(scope,'episode',text[:60],'合成用户：'+text[:200]+'\n模型回复：'+final[:300],'resolved',[{'kind':'user_quote','ref':receipt,'quote':text[:160]},{'kind':'delivered_reply','ref':receipt+':reply','quote':final[:160]}],0,receipt=receipt)
     if lessons:
      lessons.record(scope,receipt,'synthetic-user',text,final);row=next(r for r in lessons.turns(scope) if r['id']==receipt);epoch=lessons.meta(scope)['epoch'];lessons.save(scope,epoch,fast_preferences(row)+fast_lessons(row));lessons.save_temporary(scope,epoch,temporary_preferences(row,time.time()))
     turns.append({'input':text,'appraisal':assessment,'classifier':classifier,'state':state,'retrieved_continuity':experience.view(scope,text,3) if experience else [],'draft':draft,'output':final,'bubbles':bubbles,'reviewed':reviewed,'seconds':round(time.monotonic()-before,3)})
     history.extend([{'role':'user','content':text},{'role':'assistant','content':final}])
    except Exception as exc:
     turns.append({'input':text,'error':type(exc).__name__,'output':'','seconds':round(time.monotonic()-before,3)});break
   results.append({'case':case['id'],'history':case.get('history',[]),'family':case.get('family','development'),'rubric':case['rubric'],'turns':turns,'completed':len(turns)==len(case['turns']) and all('error' not in t for t in turns)})
   save()
def save():
 report={'schema':1,'variant':a.variant,'model':secret['model'],'destination':'api.deepseek.com','effort':a.effort,'case_file_sha256':hashlib.sha256(a.cases.read_bytes()).hexdigest(),'persona_sha256':hashlib.sha256(persona.encode()).hexdigest(),'calls':stats.copy(),'processed_cases':len(results),'completed_cases':sum(x['completed'] for x in results),'expected_cases':len(cases),'cases':sorted(results,key=lambda r:r['case']),'real_qq_messages':0,'production_database_modified':False,'delivery_receipts':'synthetic only','code_sha256':{name:hashlib.sha256((a.source/'release/astrbot_plugin_affect'/name).read_bytes()).hexdigest() for name in ('appraisal.py','emotion_model.py','reply_chunks.py')},'raw_outputs_private':True,'wall_seconds':round(time.monotonic()-began,2)}
 a.output.parent.mkdir(parents=True,exist_ok=True);temp=a.output.with_suffix('.next');temp.write_text(json.dumps(report,ensure_ascii=False,indent=2));temp.chmod(0o600);os.replace(temp,a.output)
async def main():
 try:await asyncio.gather(*(run_case(case) for case in cases))
 finally:save();await client.close()
asyncio.run(main())
