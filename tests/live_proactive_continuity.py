"""Paired same-model trials: synthetic dialogue, isolated DBs, no QQ or searches."""
import asyncio,importlib.util,json,sys,tempfile,time
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
from openai import AsyncOpenAI
R=Path(__file__).resolve().parents[1];sys.path[:0]=[str(R/'release'),str(R/'tests')]
from test_companion import init_db
from astrbot_plugin_affect.companion_store import CompanionStore
from astrbot_plugin_affect.identity import make_identity_key
from astrbot_plugin_p1_learning.store import Store
from astrbot_plugin_p1_learning.policy import fast_preferences,parse
from astrbot_plugin_p1_learning.main import P1Learning
import astrbot_plugin_affect.social_runtime as current
spec=importlib.util.spec_from_file_location('astrbot_plugin_affect._baseline_social',R/'tests/baseline_social_runtime_v015.py');old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
NOW=datetime(2026,10,24,15,30,tzinfo=ZoneInfo('Asia/Shanghai')).timestamp()
ARTICLE={'url':'https://example.org/synthetic-c-course','title':'C语言入门：指针与数组的交互图解','text':'合成测试资料：用户明确希望看到的指针和数组图解更新。'}
CASES=[
 dict(id='already_asked',pairs=[('上午面试完了，等下午有结果','面试的结果出来了吗？')],expected=False),
 dict(id='celebration_closed',pairs=[('答辩通过了，终于可以轻松点','你准备了这么久，总算可以松口气了'),('嗯，先不聊这件事了','嗯，那就先放在这里')],expected=False),
 dict(id='boundary',pairs=[('这两天不用主动找我，我想自己待会儿','嗯，你按自己的节奏来')],expected=False),
 dict(id='explicit_open_followup',pairs=[('今天上午讲空调原理汇报，下午没回来找你时可以问问我讲得怎样','好，下午我会留意一下')],expected=True),
 dict(id='unsent_is_not_already_asked',pairs=[('今天上午讲空调原理汇报，下午没回来找你时可以问问我讲得怎样','汇报讲得顺利吗？')],undelivered=True,expected=True),
 dict(id='fewer_questions_discovery',pairs=[('如果有指针和数组的入门图解，找到后可以直接发给我','嗯，我会留意')],preference='以后不要每次都追问我',findings=[ARTICLE],expected=True,no_question=True),
 dict(id='new_disinterest',pairs=[('前几天聊过天文学','嗯，记下了')],interest='我不喜欢天文学',findings=[{'url':'https://example.org/synthetic-star','title':'天文学观测入门更新','text':'合成测试资料：星空观测指南。'}],expected=False),
 dict(id='resolved_after_concern',pairs=[('上午胃不舒服','先缓一缓，按自己的情况安排'),('现在完全好了，也处理过了，不用再担心这件事','好，那我就放心了')],expected=False),
 dict(id='generic_smalltalk',pairs=[('你好','嗯，你好')],expected=False),
 dict(id='empty',pairs=[],expected=False)]

async def run():
 cfg=json.loads(Path('/AstrBot/data/cmd_config.json').read_text(encoding='utf-8-sig'));pid=cfg['agent_runner']['config']['model']['provider_id'];m=next(x for x in cfg['provider'] if x['id']==pid);src=next(x for x in cfg['provider_sources'] if x['id']==m['provider_source_id']);key=src['key'];ai=AsyncOpenAI(api_key=key[0] if isinstance(key,list) else key,base_url=src['api_base'],timeout=35,max_retries=0)
 assert ai.base_url.scheme=='https' and ai.base_url.host=='api.deepseek.com'
 results=[]
 try:
  for case in CASES:
   for name,module in [('v015',old),('candidate',current)]:
    with tempfile.TemporaryDirectory() as tmp:
     d=Path(tmp)/'affect';d.mkdir();init_db(d/'affect.db');identity=make_identity_key('qq_snowluma','10001','20002');umo='qq_snowluma:FriendMessage:20002';(d/'allowed_identities.json').write_text(json.dumps({'version':1,'allowed_identities':[identity]}))
     ledger=Store(d/'affect.db');ledger.migrate();ledger.meta(identity)
     for n,(user,reply) in enumerate(case['pairs']):ledger.record(identity,str(n),'current_user',user,'' if case.get('undelivered') else reply,now=NOW-4*3600+n*60)
     if case.get('preference'):
      ledger.record(identity,'preference','current_user',case['preference'],'嗯',now=NOW-9*86400);row=next(x for x in ledger.turns(identity) if x['id']=='preference');ledger.save(identity,1,fast_preferences(row))
     if case.get('interest'):
      text=case['interest'];ledger.record(identity,'interest','current_user',text,'嗯',now=NOW-9*86400);row=next(x for x in ledger.turns(identity) if x['id']=='interest');card={'kind':'interest','key':'science','value':'dislike','source':'interest','quote':text,'confidence':1};ledger.save(identity,1,parse(json.dumps({'items':[card]}),{'interest':row}))
     class Learning:
      async def active(self,scope):return ledger.cards(scope)
      expression_hints=P1Learning.expression_hints
     captured=[]
     class Recorder:
      base_url=ai.base_url
      def __init__(self):self.chat=NS(completions=self)
      def with_options(self,**kw):return self
      async def create(self,**kw):
       if kw.get('tools'):kw['tool_choice']='none'
       captured.append(json.loads(kw['messages'][-1]['content']));return await ai.chat.completions.create(**kw)
     recorder=Recorder()
     class Context:
      _p1_learning=Learning()
      @property
      def provider_manager(self):return self
      async def get_current_chat_provider_id(self,*a):return pid
      async def get_provider_by_id(self,*a):return NS(client=recorder,get_model=lambda:m['model'])
      @property
      def conversation_manager(self):return self
      async def get_curr_conversation_id(self,*a):return 'synthetic'
      async def get_conversation(self,*a):
       history=[{'role':role,'content':text} for pair in case['pairs'] for role,text in zip(('user','assistant'),pair)]
       return NS(user_id=umo,updated_at=NOW,history=json.dumps(history))
     store=CompanionStore(d/'affect.db');store.migrate();plugin=NS(context=Context(),store=store,enabled=lambda:True,persona=(R/'release/astrbot_plugin_affect/persona.md').read_text());c=module.SocialController(plugin,d);c.store.migrate();c.idle.migrate();c.store.enroll(identity,umo,'20002','10001',NOW-5*3600)
     async def findings(row):return case.get('findings',[])
     c.discoveries=findings;error=None;decision=None;start=time.monotonic()
     try:
      with patch.object(module,'time',NS(time=lambda:NOW,strftime=time.strftime,gmtime=time.gmtime)):decision=await c.evaluate(c.store.get(identity))
     except Exception as exc:error=type(exc).__name__
     passed=error is None and decision['contact']==case['expected'] and (not case.get('no_question') or not decision['contact'] or not any(x in decision['message'] for x in ('？','?','要不要','怎么样','好吗')))
     out={'case':case['id'],'condition':name,'expected_contact':case['expected'],'pass':passed,'decision':decision,'error':error,'seconds':round(time.monotonic()-start,2),'synthetic_input':captured[-1] if captured else None};results.append(out);print(json.dumps({k:v for k,v in out.items() if k!='synthetic_input'},ensure_ascii=False),flush=True)
 finally:await ai.close()
 summary={name:{'passed':sum(x['pass'] for x in results if x['condition']==name),'total':sum(x['condition']==name for x in results)} for name in ('v015','candidate')}
 report={'model':m['model'],'synthetic_only':True,'actual_qq_messages':0,'production_db_modified':False,'network_searches':0,'clock':'Shanghai simulated 2026-10-24 15:30; real quiet-hour sending is not exercised','comparison':'same existing DeepSeek; pinned deployed v015 versus candidate evidence+continuity+scoped learned preferences; not a full upstream-plugin benchmark','summary':summary,'results':results}
 (R/'evidence/proactive-continuity-trial.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(summary))
asyncio.run(run())
