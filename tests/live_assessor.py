"""Exercise production assess() through the installed provider class, with synthetic text."""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'release'));sys.path.insert(0,str(ROOT/'tests'))
from test_companion import init_db

async def run():
    with tempfile.TemporaryDirectory() as tmp:
        os.environ['P1_COMPANION_DATA']=tmp
        init_db(Path(tmp)/'affect.db')
        from astrbot_plugin_affect.main import AffectPlugin
        from astrbot.core.provider.sources.openai_source import ProviderOpenAIOfficial
        cfg=json.loads(Path('/AstrBot/data/cmd_config.json').read_text(encoding='utf-8-sig'))
        pid=cfg['agent_runner']['config']['model']['provider_id']
        model=next(x for x in cfg['provider'] if x['id']==pid)
        source=next(x for x in cfg['provider_sources'] if x['id']==model['provider_source_id'])
        provider=ProviderOpenAIOfficial(dict(source,**model),cfg['provider_settings'])
        class Context:
            @property
            def provider_manager(self): return self
            async def get_current_chat_provider_id(self,*a): return pid
            async def get_provider_by_id(self,*a): return provider
        p=AffectPlugin(Context());await p.initialize()
        value=await p.assess(SimpleNamespace(unified_msg_origin='synthetic-private'),SimpleNamespace(contexts=[]),'谢谢你，刚才的说明帮到我了。')
        assert value['source']=='semantic' and value['relation']=='thanks',value
        print(json.dumps({'production_assessor_passed':True,'installed_provider_class':type(provider).__name__,'actual_result':value,'qq_messages_sent':0,'production_database_modified':False},ensure_ascii=False))
        await provider.client.close();await p.terminate()

asyncio.run(run())
