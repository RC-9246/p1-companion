"""Approved existing DeepSeek, synthetic text only. No QQ and no production DB writes."""
import asyncio,json,os,sys,tempfile
from pathlib import Path
from types import SimpleNamespace
from openai import AsyncOpenAI
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'release'));sys.path.insert(0,str(R/'tests'))
from test_companion import init_db
from astrbot_plugin_affect.appraisal import CLASSIFIER_PROMPT,parse_appraisal,classifier_input
from astrbot_plugin_affect.emotion_model import seed,react,context as emotional_context
from astrbot_plugin_affect.identity import make_identity_key

async def run():
 cfg=json.loads(Path('/AstrBot/data/cmd_config.json').read_text(encoding='utf-8-sig'));pid=cfg['agent_runner']['config']['model']['provider_id'];model=next(p for p in cfg['provider'] if p['id']==pid);source=next(p for p in cfg['provider_sources'] if p['id']==model['provider_source_id']);keys=source['key'];client=AsyncOpenAI(api_key=keys[0] if isinstance(keys,list) else keys,base_url=source['api_base'],max_retries=0,timeout=25)
 assert client.base_url.host=='api.deepseek.com' and client.base_url.scheme=='https'
 calls=0;cases=[]
 try:
  for name,text in [('distress','今天事情太多了，有点难过，不知道先做什么。'),('correction','你刚才算错了，麻烦重新核对。'),('boundary','我现在要去忙，不用再追问了。'),('thanks','谢谢，刚才确实帮到我了。')]:
   raw=await client.chat.completions.create(model=model['model'],messages=[{'role':'system','content':CLASSIFIER_PROMPT},{'role':'user','content':classifier_input(text,[])}],max_tokens=350,response_format={'type':'json_object'},extra_body={'thinking':{'type':'disabled'}});calls+=1
   a=parse_appraisal(raw.choices[0].message.content,text);state,episode=react(seed(),1792755000,a)
   assert state['trust']>=seed()['trust']
   if name=='distress':assert state['concern']>0 and state['valence']>=0
   if name=='thanks':assert state['joy']>seed()['joy'] and state['trust']>seed()['trust']
   cases.append({'case':name,'appraisal':{k:a[k] for k in ('intent','emotion','relation','target')},'appraisal_valid':True,'evaluation_present':'evaluation' in a,'episode':episode['kind'],'trust_not_punished':True})
  with tempfile.TemporaryDirectory() as t:
   os.environ['P1_COMPANION_DATA']=t;data=Path(t);init_db(data/'affect.db');identity=make_identity_key('qq_snowluma','10001','20002');(data/'allowed_identities.json').write_text(json.dumps({'version':1,'allowed_identities':[identity]}))
   from astrbot_plugin_affect.companion_store import CompanionStore
   CompanionStore(data/'affect.db').migrate()
   from astrbot_plugin_p1_reflection.main import P1Reflection
   class Context:
    @property
    def provider_manager(self):return self
    async def get_current_chat_provider_id(self,*args):return pid
    async def get_provider_by_id(self,*args):return SimpleNamespace(client=client,get_model=lambda:model['model'])
   p=P1Reflection(Context());await p.initialize()
   result=await p.reflect('synthetic',identity,6,[{'role':'user','content':'日常聊天不用一次讲太多，可以拆两句。'},{'role':'assistant','content':'嗯，我会说短一点。'},{'role':'user','content':'刚才的答案有个错误，帮我核对一下。'},{'role':'assistant','content':'这里确实算错了，我重新核对。'}]);calls+=1
   assert result and result['confidence'] in ('low','medium','high');cases.append({'case':'periodic_reflection','parsed_by_pinned_upstream_analyzer':True,'result':result});await p.terminate()
  from astrbot_plugin_affect.idle import PROMPT,decision
  for name,values in [('curious',dict(novelty_need=.8,rest_need=.1)),('tired',dict(novelty_need=.1,rest_need=.9))]:
   raw=await client.chat.completions.create(model=model['model'],messages=[{'role':'system','content':PROMPT},{'role':'user','content':json.dumps(values)}],max_tokens=180,response_format={'type':'json_object'},extra_body={'thinking':{'type':'disabled'}});calls+=1
   d=decision(raw.choices[0].message.content);cases.append({'case':'idle_'+name,'bounded_decision':d})
  print(json.dumps({'approved_live_service':'api.deepseek.com','model_requests':calls,'cases':cases,'real_qq_messages':0,'production_db_modified':False},ensure_ascii=False,indent=2))
 finally:await client.close()
asyncio.run(run())
