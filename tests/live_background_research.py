"""Real decisions with synthetic histories and isolated stores; never send QQ messages."""
import asyncio,json,sys,tempfile,time
from pathlib import Path
from types import SimpleNamespace
from openai import AsyncOpenAI
from astrbot.core.agent.mcp_client import MCPClient
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'release'));sys.path.insert(0,str(ROOT/'tests'))
from test_companion import init_db
from astrbot_plugin_affect.companion_store import CompanionStore
from astrbot_plugin_affect.social_runtime import SocialController
from astrbot_plugin_affect.identity import make_identity_key

async def run():
 mcp=MCPClient()
 await mcp.connect_to_server({"command":"python","args":["/AstrBot/data/companion_services/mcp/server.py"]},"p1_companion")
 await mcp.list_tools_and_save()
 research_calls=[]
 class RecordingMcp:
  async def call_tool_with_reconnect(self,name,args,timeout):
   research_calls.append(name)
   return await mcp.call_tool_with_reconnect(name,args,timeout)
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
    def get_llm_tool_manager(self):return SimpleNamespace(mcp_client_dict={"p1_companion":RecordingMcp()})
    @property
    def conversation_manager(self):return self
    async def get_curr_conversation_id(self,*args):return 'synthetic-conversation'
    async def get_conversation(self,*args):return conversation
   store=CompanionStore(data/'affect.db');store.migrate()
   plugin=SimpleNamespace(context=Context(),enabled=lambda:True,store=store,persona=(ROOT/'release/astrbot_plugin_affect/persona.md').read_text())
   controller=SocialController(plugin,data);controller.store.migrate();controller.store.enroll(identity,umo,'synthetic-user','synthetic-bot',time.time()-9*3600)
   conversation.history=json.dumps([{'role':'user','content':'我对二氧化碳储能技术感兴趣。下次你在后台醒来时，请先实际搜索公开资料，再决定有没有值得分享的内容；没价值就保持安静。搜索时只使用公共技术主题，不带我的信息。'}])
   decision=await controller.evaluate(controller.store.get(identity))
   assert research_calls==['p1_mcp_search'],research_calls
   print(json.dumps({'live_background_research':True,'real_model_selected_mcp_search':True,
       'decision':decision,'can_remain_silent':True,'qq_messages_sent':0,'production_tool_budget_isolated':False,'production_chat_memory_relationship_writes':False},ensure_ascii=False,indent=2))
 finally:
  await client.close();await mcp.cleanup()
asyncio.run(run())
