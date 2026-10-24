"""Real MCP handshake and public n8n workflow, no private data or QQ messages."""
import asyncio,json
from datetime import timedelta
from pathlib import Path
from astrbot.core.agent.mcp_client import MCPClient

async def run():
    client=MCPClient()
    try:
        await client.connect_to_server({'command':'python','args':[str(Path(__file__).resolve().parents[1]/'services/mcp/server.py')]},'p1_companion')
        await client.list_tools_and_save()
        names=sorted(t.name for t in client.tools)
        assert names==sorted(['p1_mcp_capabilities','p1_mcp_read','p1_mcp_search','p1_mcp_workflow','p1_mcp_document_formats','p1_mcp_experiment','p1_mcp_transform','p1_mcp_sources','p1_mcp_service_status']),names
        def parsed(result):
            assert not result.isError
            return json.loads(''.join(x.text for x in result.content if x.type=='text'))
        denied=parsed(await client.call_tool_with_reconnect('p1_mcp_workflow',{'name':'send_email'},timedelta(seconds=35)))
        assert denied['error']=='workflow_not_approved'
        metadata=parsed(await client.call_tool_with_reconnect('p1_mcp_read',{'url':'http://169.254.169.254/latest/'},timedelta(seconds=35)))
        assert not metadata.get('ok')
        private=parsed(await client.call_tool_with_reconnect('p1_mcp_search',{'query':'password abcdef'},timedelta(seconds=20)))
        assert private.get('error')=='private_or_invalid_query'
        search=parsed(await client.call_tool_with_reconnect('p1_mcp_search',{'query':'Python official documentation'},timedelta(seconds=20)))
        assert search.get('ok') and search.get('items'),search
        result=parsed(await client.call_tool_with_reconnect('p1_mcp_workflow',{'name':'public_python_digest'},timedelta(seconds=35)))
        page=result['result'];assert page.get('ok'),page
        print(json.dumps({'mcp_handshake':True,'tools':names,'n8n_workflow_live':True,
             'title':page['title'],'source':page['url'],'unapproved_workflow_denied':True,
             'metadata_url_denied':True,'public_search_live':True,'private_search_denied':True,'qq_messages_sent':0},ensure_ascii=False,indent=2))
    finally:await client.cleanup()

asyncio.run(run())
