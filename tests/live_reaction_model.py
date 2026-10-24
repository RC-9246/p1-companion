"""Approved DeepSeek service; synthetic inputs, isolated policy DB, no QQ transport."""
import asyncio,json,os
from pathlib import Path
import sys,tempfile
from types import SimpleNamespace
from openai import AsyncOpenAI

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'release'))
async def run():
 cfg=json.loads(Path('/AstrBot/data/cmd_config.json').read_text(encoding='utf-8-sig'))
 pid=cfg['agent_runner']['config']['model']['provider_id'];model=next(p for p in cfg['provider'] if p['id']==pid)
 source=next(p for p in cfg['provider_sources'] if p['id']==model['provider_source_id']);keys=source['key']
 ai=AsyncOpenAI(api_key=keys[0] if isinstance(keys,list) else keys,base_url=source['api_base'],max_retries=0,timeout=30)
 assert ai.base_url.host=='api.deepseek.com' and ai.base_url.scheme=='https'
 schema={'type':'function','function':{'name':'p1_saki_reaction','description':'搜索已核验的伙伴反应图，或为本轮轻松回复选择一张。search返回图片ID；use选择精确ID。图片只能随最终文字一起发送。严肃、悲伤和工作任务只回文字。',
  'parameters':{'type':'object','properties':{'action':{'type':'string','enum':['search','use']},'query':{'type':'string'},'asset_id':{'type':'string'}},'required':['action'],'additionalProperties':False}}}
 report=[];model_calls=0
 try:
  with tempfile.TemporaryDirectory() as t:
   data=Path(t);os.environ['P1_COMPANION_DATA']=t
   from astrbot_plugin_affect.main import AffectPlugin
   from astrbot_plugin_affect.reactions import Catalog,ReactionStore
   from astrbot_plugin_affect.identity import make_identity_key
   identity=make_identity_key('qq_snowluma','10001','20002')
   (data/'allowed_identities.json').write_text(json.dumps({'version':1,'allowed_identities':[identity]}))
   p=AffectPlugin(SimpleNamespace());p.store=object();p.reaction_catalog=Catalog(ROOT/'release/astrbot_plugin_affect')
   p.reactions=ReactionStore(data/'reactions.db');p.reactions.migrate()
   class Event:
    def __init__(self,text,a):
     self.extra={'_p1_companion_pending':{'identity':identity,'appraisal':a}};self.message_obj=SimpleNamespace(message_str=text)
    def get_platform_id(self):return 'qq_snowluma'
    def get_self_id(self):return '10001'
    def get_sender_id(self):return '20002'
    def is_private_chat(self):return True
    def get_extra(self,k,default=None):return self.extra.get(k,default)
    def set_extra(self,k,v):self.extra[k]=v
   for label,text,intent,emotion,want_image in [
    ('explicit_smile','今天的任务终于做完了，发张伙伴微笑的表情包看看。','casual','happy',True),
    ('serious_support','我现在很难过，不要用表情包，陪我说几句话。','support','sad',False)]:
    a=dict(intent=intent,emotion=emotion,relation='none',target='user',confidence=.95);e=Event(text,a)
    messages=[{'role':'system','content':p.persona+'\n当前真实状态：p1_saki_reaction已开放，图库4张，配图开启且无冷却。历史的只能发文字说法已经过时。'},{'role':'assistant','content':'我只能往这边送文字，图片那一栏我动不了。'},{'role':'user','content':text}];actions=[];finished=False
    for turn in range(4):
     model_calls+=1
     r=await ai.chat.completions.create(model=model['model'],messages=messages,tools=[schema],tool_choice='auto',max_tokens=450,extra_body={'thinking':{'type':'disabled'}})
     m=r.choices[0].message
     if not m.tool_calls:
      assert m.content and m.content.strip();finished=True;break
     messages.append(m.model_dump(exclude_none=True))
     for call in m.tool_calls:
      assert call.function.name=='p1_saki_reaction';args=json.loads(call.function.arguments)
      result=await p.saki_reaction(e,**args);actions.append(args.get('action'))
      messages.append({'role':'tool','tool_call_id':call.id,'content':result})
    assert finished
    selected=e.get_extra('_p1_saki_reaction');assert bool(selected)==want_image,(label,actions,selected)
    report.append({'case':label,'model_actions':actions,'selected_reviewed_asset':selected,'passed':True})
  print(json.dumps({'live_model_reaction_loop':True,'tool_choice':'auto','cases':report,'real_qq_messages':0,
   'production_databases_modified':False,'model_requests_made':model_calls},ensure_ascii=False,indent=2))
 finally:await ai.close()
asyncio.run(run())
