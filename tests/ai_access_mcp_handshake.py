"""Actual pinned-SDK stdio handshake; public source and synthetic reports only."""
import asyncio,json,os,sys,tempfile,time
from pathlib import Path
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
R=Path(__file__).resolve().parents[1]
NAMES={'p1_project_overview','p1_verify_source','p1_deployment_plan','p1_deployment_check','p1_runtime_health','p1_handoff_template'}
def value(result):
 assert not result.isError
 return json.loads(''.join(x.text for x in result.content if x.type=='text'))
async def exercise(extra,live=False):
 params=StdioServerParameters(command=sys.executable,args=[str(R/'ai/mcp_server.py'),*extra],env={'PYTHONDONTWRITEBYTECODE':'1'})
 async with stdio_client(params) as (r,w):
  async with ClientSession(r,w) as c:
   await c.initialize();tools=await c.list_tools();assert {t.name for t in tools.tools}==NAMES
   for t in tools.tools:
    assert t.annotations.readOnlyHint is True and t.annotations.destructiveHint is False
   assert value(await c.call_tool('p1_project_overview',{}))['live_runtime_checked'] is False
   assert value(await c.call_tool('p1_verify_source',{}))['ok'] is True
   assert value(await c.call_tool('p1_deployment_plan',{}))['executed'] is False
   status=value(await c.call_tool('p1_runtime_health',{}))
   if not live:
    assert status['error']=='live_root_not_configured'
    assert value(await c.call_tool('p1_deployment_check',{}))['error']=='live_root_not_configured'
   else:
    assert status['maintenance']['services']['astrbot'] is True
    assert 'synthetic-secret-not-for-model' not in json.dumps(status)
    assert status['account_login_verified'] is False
   handoff=value(await c.call_tool('p1_handoff_template',{}));assert handoff['phase']=='not_started'
   resources=await c.list_resources();prompts=await c.list_prompts()
   assert len(resources.resources)==2 and len(prompts.prompts)==1
   assert (await c.read_resource('companion://project/manifest')).contents
   assert (await c.get_prompt('companion_takeover',{})).messages
async def main():
 await exercise([])
 with tempfile.TemporaryDirectory(prefix='p1-ai-access-') as tmp:
  root=Path(tmp).resolve();data=root/'astrbot/data/plugin_data/affect';data.mkdir(parents=True)
  (data/'maintenance_health.json').write_text(json.dumps({'at':time.time(),'services':{'astrbot':True},'token':'synthetic-secret-not-for-model'}))
  await exercise(['--live-root',str(root)],True)
 print(json.dumps({'real_sdk_stdio_handshake':True,'sdk_line':'1.x pinned 1.30.0','tools':6,'resources':2,'prompts':1,'default_live_access_denied':True,'synthetic_fixed_root_health_filtered':True,'production_runtime_read':False,'model_calls':0,'qq_messages':0,'network_listener_created':False}))
asyncio.run(main())
