"""Actual group-note implementation and existing DeepSeek, synthetic temporary group only."""
import asyncio,json,os,sys,tempfile,time
from pathlib import Path
from types import SimpleNamespace as N
from openai import AsyncOpenAI
R=Path(__file__).resolve().parents[1];sys.path[:0]=[str(R/'release'),str(R/'tests')]
async def main():
 cfg=json.loads(Path('/AstrBot/data/cmd_config.json').read_text(encoding='utf-8-sig'));pid=cfg['agent_runner']['config']['model']['provider_id'];model=next(p for p in cfg['provider'] if p['id']==pid);src=next(s for s in cfg['provider_sources'] if s['id']==model['provider_source_id'])
 assert src['api_base'].startswith('https://api.deepseek.com')
 keys=src['key'];client=AsyncOpenAI(api_key=keys[0] if isinstance(keys,list) else keys,base_url=src['api_base'],timeout=15,max_retries=0);observed=[]
 class Wrapper:
  base_url=client.base_url
  def __init__(self):self.chat=N(completions=self)
  def with_options(self,**kw):return self
  async def create(self,**kw):
   out=await client.chat.completions.create(**kw);observed.append({'finish_reason':out.choices[0].finish_reason,'completion_tokens':out.usage.completion_tokens,'synthetic_json_output':out.choices[0].message.content});return out
 async def provider(*a):return N(client=Wrapper(),get_model=lambda:model['model'])
 try:
  with tempfile.TemporaryDirectory() as t:
   os.environ['P1_COMPANION_DATA']=str(Path(t)/'affect')
   from astrbot_plugin_p1_group_memory.main import P1GroupMemory
   from astrbot_plugin_p1_group_memory.store import scope_key,event_key
   from astrbot.core.message.components import Plain
   p=P1GroupMemory(N());p.store.migrate();scope=scope_key('10001','30003');now=time.time()
   topics=['群友甲说明天带一本轻小说来讨论','群友乙说读书会改为下午三点','群友甲补充不是周三，是周四','群友乙说大家可以先看动画前两集']
   for n in range(30):p.store.add(scope,event_key(scope,str(n)),str(n%2),'甲' if n%2==0 else '乙',topics[n%4],now-90+n)
   event=N(get_self_id=lambda:'10001',get_group_id=lambda:'30003',get_platform_id=lambda:'qq_snowluma',get_sender_id=lambda:'20002',get_sender_name=lambda:'甲',get_messages=lambda:[Plain(topics[-1])],message_obj=N(message_id='29',message_str=topics[-1],timestamp=now),get_extra=lambda *a:None,set_extra=lambda *a:None)
   groups=N(allowed=lambda e:True,provider=provider,plugin=N(store=N(take_budget=lambda *a,**kw:True)))
   error=None
   try:await p.summarize(event,groups)
   except Exception as e:error=type(e).__name__
   notes=p.store.history(scope)['notes']
   report={'actual_deepseek':True,'actual_group_notes_implementation':True,'synthetic_only':True,'notes_saved':len(notes),'error':error,'model':observed,'actual_qq_messages':0,'production_database_modified':False}
   (R/'evidence/live-group-notes-audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False,indent=2))
 finally:await client.close()
asyncio.run(main())
