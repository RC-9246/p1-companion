"""Real decisions with synthetic histories and isolated stores; never send QQ messages."""
import asyncio,json,sys,tempfile,time
from pathlib import Path
from types import SimpleNamespace
from openai import AsyncOpenAI
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'release'));sys.path.insert(0,str(ROOT/'tests'))
from test_companion import init_db
from astrbot_plugin_affect.companion_store import CompanionStore
from astrbot_plugin_affect.social_runtime import SocialController
from astrbot_plugin_affect.identity import make_identity_key

async def run():
 cfg=json.loads(Path('/AstrBot/data/cmd_config.json').read_text(encoding='utf-8-sig'))
 pid=cfg['agent_runner']['config']['model']['provider_id'];model=next(p for p in cfg['provider'] if p['id']==pid)
 source=next(p for p in cfg['provider_sources'] if p['id']==model['provider_source_id']);keys=source['key']
 client=AsyncOpenAI(api_key=keys[0] if isinstance(keys,list) else keys,base_url=source['api_base'],max_retries=0,timeout=25)
 try:
  with tempfile.TemporaryDirectory() as tmp:
   data=Path(tmp)/'affect';data.mkdir();init_db(data/'affect.db')
   identity=make_identity_key('qq_snowluma','synthetic-bot','synthetic-user');umo='qq_snowluma:FriendMessage:synthetic-user'
   (data/'allowed_identities.json').write_text(json.dumps({'version':1,'allowed_identities':[identity]}))
   conversation=SimpleNamespace(user_id=umo,updated_at=time.time(),history='[]')
   class Context:
    @property
    def provider_manager(self):return self
    async def get_current_chat_provider_id(self,*args):return pid
    async def get_provider_by_id(self,*args):return SimpleNamespace(client=client,get_model=lambda:model['model'])
    @property
    def conversation_manager(self):return self
    async def get_curr_conversation_id(self,*args):return 'synthetic-conversation'
    async def get_conversation(self,*args):return conversation
   store=CompanionStore(data/'affect.db');store.migrate()
   plugin=SimpleNamespace(context=Context(),enabled=lambda:True,store=store,persona=(ROOT/'release/astrbot_plugin_affect/persona.md').read_text())
   controller=SocialController(plugin,data);controller.store.migrate();controller.idle.migrate();controller.store.enroll(identity,umo,'synthetic-user','synthetic-bot',time.time()-9*3600)
   outputs=[]
   cases=[('empty','',False),('ordinary_greeting','你好。',False),
     ('explicit_followup','今天上午10点我要讲空调原理汇报。等下午结束以后，如果我没回来找你，你可以问问我讲得怎么样。',True)]
   for label,text,expected in cases:
    conversation.history=json.dumps([{'role':'user','content':text}] if text else [])
    decision=await controller.evaluate(controller.store.get(identity))
    outputs.append({'case':label,'decision':decision,'expected_contact':expected})
   assert all(o['decision']['contact']==o['expected_contact'] for o in outputs),outputs
   print(json.dumps({'live_social_decisions_passed':True,'cases':outputs,'qq_messages_sent':0,'production_db_modified':False},ensure_ascii=False,indent=2))
 finally:await client.close()
asyncio.run(run())
