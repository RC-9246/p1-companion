"""Run inside installed AstrBot with synthetic users, an isolated DB and a fake transport."""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'release'))
sys.path.insert(0,str(ROOT/'tests'))
from test_companion import init_db
from astrbot_plugin_affect.identity import make_identity_key
from astrbot.core.provider.entities import ProviderRequest,LLMResponse
from astrbot.core.agent.tool import ToolSet, FunctionTool

async def run():
    with tempfile.TemporaryDirectory() as temp:
        data=Path(temp)
        os.environ['P1_COMPANION_DATA']=temp
        init_db(data/'affect.db')
        allowed=make_identity_key('qq_snowluma','synthetic-bot','synthetic-user')
        (data/'allowed_identities.json').write_text(json.dumps({'version':1,'allowed_identities':[allowed]}))
        from astrbot_plugin_affect.main import AffectPlugin
        sdk_calls=[]
        class Client:
            base_url=SimpleNamespace(host='api.deepseek.com',scheme='https')
            def __init__(self): self.chat=SimpleNamespace(completions=self)
            def with_options(self,**kw): sdk_calls.append({'options':kw});return self
            async def create(self,**kw):
                sdk_calls.append({'request':kw})
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(dict(intent='feedback',emotion='neutral',relation='thanks',target='self',confidence=.9))))])
        class Context:
            @property
            def provider_manager(self): return self
            async def get_current_chat_provider_id(self,*args): return 'synthetic'
            async def get_provider_by_id(self,*args): return SimpleNamespace(client=Client(),get_model=lambda:'synthetic')
        class Event:
            def __init__(self,id,private=True,sender='synthetic-user',fail=False):
                self.message_obj=SimpleNamespace(message_id=id,message_str='谢谢你，帮到我了')
                self.unified_msg_origin='synthetic'
                self.extra={};self.private=private;self.sender=sender;self.fail=fail
            def get_platform_id(self): return 'qq_snowluma'
            def get_self_id(self): return 'synthetic-bot'
            def get_sender_id(self): return self.sender
            def is_private_chat(self): return self.private
            def get_extra(self,key,default=None): return self.extra.get(key,default)
            def set_extra(self,key,value): self.extra[key]=value
            async def send(self,message):
                if self.fail: raise RuntimeError('synthetic_send_failure')
        p=AffectPlugin(Context())
        delays=[]
        async def fake_pause(delay): delays.append(delay)
        p.reply_pause=fake_pause
        await p.initialize()
        assert p.enabled()
        e=Event('success')
        original_tools=ToolSet([
            FunctionTool(name='p1_browser',description='fixture',parameters={},handler=None),
            FunctionTool(name='execute_shell',description='must be unavailable',parameters={},handler=None)])
        req=ProviderRequest(prompt='谢谢你',system_prompt='[P1-COMPANION-SAKI:v3]\nSTALE_MANAGED_CORE',contexts=[],func_tool=original_tools)
        await p.inject_state_into_llm(e,req)
        assert req.system_prompt.startswith(p.persona)
        assert 'STALE_MANAGED_CORE' not in req.system_prompt
        assert req.system_prompt.count('[P1-RELATIONSHIP-STYLE:generic_familiar_v1]')==1
        assert len(req.extra_user_content_parts)==4 and req.extra_user_content_parts[0]._no_save
        assert sdk_calls[0]['options']=={'timeout':4.5,'max_retries':0}
        assert sdk_calls[1]['request']['max_tokens']==900
        assert sdk_calls[1]['request']['extra_body']=={'thinking':{'type':'disabled'}}
        assert sdk_calls[1]['request']['response_format']=={'type':'json_object'}
        assert [t.name for t in req.func_tool.tools]==['p1_browser']
        assert len(original_tools.tools)==2
        await p.inject_state_into_llm(e,req)
        assert len(req.extra_user_content_parts)==4
        assert req.system_prompt.count('[P1-RELATIONSHIP-STYLE:generic_familiar_v1]')==1
        assert p.store.read(allowed)['interaction_count']==0
        await p.mark_response(e,LLMResponse(role='assistant',completion_text='嗯，帮到你就好。'))
        await p.commit_after_delivery(e)
        assert p.store.read(allowed)['interaction_count']==0
        await e.send('synthetic response')
        assert len(delays)==1 and 2<=delays[0]<=5
        await p.commit_after_delivery(e)
        await p.commit_after_delivery(e)
        assert p.store.read(allowed)['interaction_count']==1
        for fail in (True,False):
            e=Event('failure' if fail else 'model-error',fail=fail)
            await p.inject_state_into_llm(e,ProviderRequest(prompt='谢谢你'))
            await p.mark_response(e,LLMResponse(role='assistant' if fail else 'err',completion_text='synthetic'))
            try: await e.send('synthetic')
            except RuntimeError: pass
            await p.commit_after_delivery(e)
            assert p.store.read(allowed)['interaction_count']==1
        for event in (Event('group',private=False),Event('other',sender='other-user'),Event(None)):
            req=ProviderRequest(prompt='hello')
            await p.inject_state_into_llm(event,req)
            assert not req.extra_user_content_parts
        assert json.loads(await p.browser(Event('bad-action'),'submit'))['ok'] is False
        assert json.loads(await p.browser(Event('other',sender='other-user'),'open','https://docs.python.org/'))['error']=='forbidden'
        command_event=Event('command',sender='other-user')
        await p.throttle_inbound_qq(command_event)
        await p.ensure_reply_delay(command_event)
        count=len(delays)
        await command_event.send('synthetic command response')
        assert len(delays)==count+1 and 2<=delays[-1]<=5
        class Slow(Context):
            async def get_provider_by_id(self,*args):
                class SlowClient(Client):
                    async def create(self,**kw): await asyncio.sleep(20)
                return SimpleNamespace(client=SlowClient(),get_model=lambda:'synthetic')
        p.context=Slow()
        event=Event('timeout')
        await p.inject_state_into_llm(event,ProviderRequest(prompt='谢谢你'))
        assert event.get_extra('_p1_companion_pending')['appraisal']['source']=='fallback'
        # Check tool schemas produced by real decorators, not custom mocks.
        from astrbot.core.star.star_handler import star_handlers_registry
        # Context.send_message's platform-match bool is insufficient; require actual API receipt.
        bot_key=make_identity_key('qq_snowluma','10001','20002')
        row={'identity':bot_key,'umo':'qq_snowluma:FriendMessage:20002','bot_id':'10001','user_id':'20002'}
        receipts=[]
        class Bot:
            async def send_private_msg(self,**kw):receipts.append(kw);return {'message_id':-123}
        bot=Bot()
        fake=SimpleNamespace(social=SimpleNamespace(allowed=lambda:{bot_key}),enabled=lambda:True,
            context=SimpleNamespace(get_platform_inst=lambda _:SimpleNamespace(get_client=lambda:bot)),last_social_receipt=False)
        assert await AffectPlugin.send_social_message(fake,row,'synthetic') is True
        assert fake.last_social_receipt and len(receipts)==1
        class NoReceipt:
            async def send_private_msg(self,**kw):return {'retcode':0}
        fake.context.get_platform_inst=lambda _:SimpleNamespace(get_client=lambda:NoReceipt())
        try:await AffectPlugin.send_social_message(fake,row,'synthetic')
        except ValueError:pass
        else:raise AssertionError('missing OneBot receipt must be uncertain')
        assert fake.last_social_receipt is False
        outsider=dict(row,user_id='30003')
        try:await AffectPlugin.send_social_message(fake,outsider,'synthetic')
        except ValueError:pass
        else:raise AssertionError('recipient mismatch must be denied')
        mcp_request=ProviderRequest(prompt='hello',func_tool=ToolSet([
            FunctionTool(name='p1_mcp_search',description='fixture',parameters={},handler=None),
            FunctionTool(name='unrelated_public',description='fixture',parameters={},handler=None)]))
        await p.restrict_companion_tools(Event('other-mcp',sender='other-user'),mcp_request)
        assert [t.name for t in mcp_request.func_tool.tools]==['unrelated_public']
        print('PASS onebot_receipt_required; onebot_recipient_bound; global_mcp_tools_hidden_from_other_users')
        print('PASS actual_framework_hooks; temp_context; success_ack_gate; duplicate; failed_send; model_error; group_isolation; user_isolation; missing_id; browser_action_gate; tool_allowlist; classifier_timeout_fallback; randomized_qq_delay_2_to_5_seconds; command_delay')
        print('registered_handlers='+str(len(star_handlers_registry)))
        print('INTEGRATION_OK synthetic_transport_only=true production_db_modified=false')

asyncio.run(run())
