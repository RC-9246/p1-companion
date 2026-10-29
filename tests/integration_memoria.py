import asyncio
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'release'))
from astrbot_plugin_memoria import main as memoria_main
from astrbot_plugin_memoria.privacy import permitted_event,memory_safe
from astrbot_plugin_memoria.memoria.db import MemoriaDB
from astrbot_plugin_memoria.memoria.dream import _fetch_transcript_from_db

class Event:
    def __init__(self,sender='111',private=True):
        self.sender=sender;self.private=private;self.session_id='111';self.extra={}
    def get_extra(self,key,default=None):return self.extra.get(key,default)
    def set_extra(self,key,value):self.extra[key]=value
    def get_platform_id(self): return 'qq_snowluma'
    def get_self_id(self): return 'synthetic-bot'
    def get_sender_id(self): return self.sender
    def is_private_chat(self): return self.private
    def is_admin(self): return False

async def run():
    with tempfile.TemporaryDirectory() as tmp:
        temp=Path(tmp)
        identity='v1:'+hashlib.sha256(json.dumps(['qq_snowluma','synthetic-bot','111'],ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
        allow=temp/'allow.json';allow.write_text(json.dumps({'version':1,'allowed_identities':[identity]}))
        assert permitted_event(Event(),allow)
        assert not permitted_event(Event('222'),allow)
        assert not permitted_event(Event(private=False),allow)
        allow.write_text('{}');assert not permitted_event(Event(),allow)
        assert memory_safe('我喜欢简洁的中文回答')
        assert not memory_safe('密码：fixture-secret-value')
        from astrbot_plugin_affect import main as AM
        AM.DATA=temp
        (temp/'allowed_identities.json').write_text(json.dumps({'version':1,'allowed_identities':[identity]}))
        p=memoria_main.MemoriaPlugin(SimpleNamespace(),{})
        p.db=await MemoriaDB.create(str(temp/'memory'))
        memoria_main.permitted_event=lambda e,**kw:e.private and e.sender=='111'
        good=json.loads(await p.tool_add_memory_candidate(Event(),'111','我喜欢简洁的中文回答'))
        assert good['ok'] and '候选' in good['message']
        denied=json.loads(await p.tool_add_memory_candidate(Event(),'222','cross-user'))
        assert denied['error']=='forbidden'
        secret=json.loads(await p.tool_add_memory_candidate(Event(),'111','密码：fixture-secret-value'))
        assert not secret['ok']
        records=await p.db.list_memories(p._memory_uid(Event()),None,'candidate',20)
        assert len(records)==1 and records[0].status=='candidate'
        original='日常回复保持简短，先回应当前问题，不要每次追加问题。'
        active_id=await p.db.add_memory('111','user','111','preference',original,1.,'manual','active')
        revised='日常回复保持简短，先回应当前问题，可以每次追加问题。'
        candidate_id=await p.db.upsert_memory_candidate('111','user','111','preference',revised,.9,'agent')
        assert candidate_id!=active_id
        active=await p.db.list_memories('111','preference','active',20)
        assert len(active)==1 and active[0].content==original and active[0].source=='manual'
        same_id=await p.db.upsert_memory_candidate('111','user','111','preference',original,.5,'agent')
        assert same_id==active_id
        assert (await p.db.list_memories('111','preference','active',20))[0].confidence==1.
        ctx=await p.db.build_memory_context('111','111','回复习惯')
        assert '更新20' in ctx and '不等于事情发生时间' in ctx
        assert not p._is_admin(Event())
        conv=temp/'conversations.db'
        with sqlite3.connect(conv) as db:
            db.execute('CREATE TABLE conversations(user_id TEXT,content TEXT,updated_at INTEGER)')
            for uid,text in [('111','SAFE current session'),('1112','OTHER private session')]:
                db.execute('INSERT INTO conversations VALUES (?,?,1)',('qq_snowluma:FriendMessage:'+uid,json.dumps([{'role':'user','content':text}])))
        rows=await _fetch_transcript_from_db(str(conv),'111','111','user',20)
        assert 'SAFE' in str(rows) and 'OTHER' not in str(rows)
        assert not await _fetch_transcript_from_db(str(conv),'other:GroupMessage:111','111','session',20)
        print('MEMORIA_INTEGRATION_OK private_allowlist=true cross_user_denied=true credentials_rejected=true candidate_not_active=true confirmed_memory_cannot_be_rewritten_by_candidate=true temporal_provenance=true exact_transcript_scope=true group_history_denied=true')

asyncio.run(run())
