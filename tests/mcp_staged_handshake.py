"""Actual AstrBot MCP client + staged server/store. Metadata only; no QQ or DB mutation."""
import asyncio,json,tempfile,shutil
from pathlib import Path
from datetime import timedelta
from astrbot.core.agent.mcp_client import MCPClient
R=Path(__file__).resolve().parents[1]
async def main():
 with tempfile.TemporaryDirectory() as t:
  root=Path(t);text=(R/'services/mcp/server.py').read_text();literal="sys.path.insert(0,'/AstrBot/data/plugins/astrbot_plugin_affect')";assert text.count(literal)==1
  (root/'server.py').write_text(text.replace(literal,'sys.path.insert(0,'+repr(str(R/'release/astrbot_plugin_affect'))+')'));shutil.copy2(R/'services/mcp/search_policy.py',root/'search_policy.py')
  client=MCPClient()
  try:
   await client.connect_to_server({'command':'python','args':[str(root/'server.py')]},'p1_companion_stage');await client.list_tools_and_save()
   names=sorted(x.name for x in client.tools);assert set(names)=={'p1_mcp_capabilities','p1_mcp_read','p1_mcp_search','p1_mcp_workflow','p1_mcp_document_formats','p1_mcp_experiment','p1_mcp_transform','p1_mcp_sources','p1_mcp_service_status'}
   raw=await client.call_tool_with_reconnect('p1_mcp_capabilities',{},timedelta(seconds=10));assert not raw.isError
   value=json.loads(''.join(x.text for x in raw.content if x.type=='text'));assert isinstance(value,dict)
   resources=await client.session.list_resources();prompts=await client.session.list_prompts();assert len(resources.resources)==2 and len(prompts.prompts)==1
   print(json.dumps({'mcp_resources':2,'mcp_prompts':1,'staged_native_mcp_handshake':True,'shared_store_standalone_import':True,'registered_tools':names,'capabilities_received':True,'real_qq_messages':0,'production_db_modified':False}))
  finally:await client.cleanup()
asyncio.run(main())
