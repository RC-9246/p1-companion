"""Approved DeepSeek synthetic agency evaluation; no actual recipients or user histories."""
import asyncio,json,sys,tempfile,time
from pathlib import Path
from types import SimpleNamespace as N
from openai import AsyncOpenAI
from urllib.parse import urlsplit
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'release'))
from astrbot_plugin_affect.agency_runtime import Agency,PLAN
async def main():
 cfg=json.loads(Path('/AstrBot/data/cmd_config.json').read_text(encoding='utf-8-sig'));pid=cfg['agent_runner']['config']['model']['provider_id'];model=next(p for p in cfg['provider'] if p['id']==pid);source=next(x for x in cfg['provider_sources'] if x['id']==model['provider_source_id']);u=urlsplit(source['api_base']);assert u.scheme=='https' and u.hostname=='api.deepseek.com';keys=source['key'];ai=AsyncOpenAI(api_key=keys[0] if isinstance(keys,list) else keys,base_url=source['api_base'],max_retries=0,timeout=38)
 usage=[]
 class Context:
  async def get_current_chat_provider_id(self,*args):return 'synthetic-test'
  @property
  def provider_manager(self):return self
  async def get_provider_by_id(self,*args):return N(client=ai,get_model=lambda:model['model'])
 def record(*args):
  result=args[-1];usage.append({'effort':args[2],'completion_tokens':result.usage.completion_tokens,'prompt_tokens':result.usage.prompt_tokens})
 with tempfile.TemporaryDirectory() as tmp:
  persona=(R/'release/astrbot_plugin_affect/friend_persona.md').read_text();p=N(context=Context(),enabled=lambda:True,qq=N(active=lambda:True,allowed=lambda row:True,owner=lambda scope:True),persona=persona,friend_persona=persona,store=N(take_budget=lambda *a,**k:True),thinking=N(record=record));a=Agency(p,tmp);await a.start();row={'identity':'v1:'+'f'*64,'kind':'private','peer':'90001','bot':'90002','ref':'synthetic'}
  try:
   start=time.monotonic();choice=await a.complete(row,PLAN,{'current_scope':'private','owner_video_access':True,'state':{'fatigue':.3,'interest':.55},'actual_context':a.store.context(row['identity'])},deep=True)
   assert choice['activity'] in ('rest','research','organize','reflection','watch','experiment') and choice['topic'] in __import__('astrbot_plugin_affect.agency_store',fromlist=['TOPICS']).TOPICS
   hours=choice.get('day_hours',6.5);assert type(hours) in (int,float) and 5<=hours<=8
   answer=await a.complete(row,'只依据来源写一两句资料笔记，不增加经历；只返回JSON {"note":"...","interest":0.0,"done":true}。',{'sources':[{'url':'https://docs.python.org/3/','title':'Python documentation','text':'This is the official Python documentation.','kind':'visited_page'}]},deep=True);assert isinstance(answer['note'],str) and answer['note']
   report={'approved_destination':'api.deepseek.com','synthetic_model_requests':2,'activity_choice_valid':True,'selected_activity':choice['activity'],'selected_topic':choice['topic'],'day_hours':hours,'grounded_note_shape_valid':True,'max_effort_usage':usage,'seconds':round(time.monotonic()-start,2),'private_history_sent':False,'real_qq_messages':0};(R/'evidence/live-agency-model.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False))
  finally:await a.stop();await ai.close()
asyncio.run(main())
