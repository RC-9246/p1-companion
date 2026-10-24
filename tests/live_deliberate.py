"""Real voluntary max helper; temporary audit DB and synthetic question only."""
import asyncio,json,sys,tempfile
from pathlib import Path
from types import SimpleNamespace as N
from openai import AsyncOpenAI
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'release'))
from astrbot_plugin_affect.thinking import Thinking
async def run():
 cfg=json.loads(Path('/AstrBot/data/cmd_config.json').read_text());m=next(x for x in cfg['provider'] if x['id']==cfg['agent_runner']['config']['model']['provider_id']);s=next(x for x in cfg['provider_sources'] if x['id']==m['provider_source_id']);k=s['key'];client=AsyncOpenAI(api_key=k[0] if isinstance(k,list) else k,base_url=s['api_base'],max_retries=0)
 assert client.base_url.scheme=='https' and client.base_url.host=='api.deepseek.com'
 async def pid(*a):return 'approved'
 async def provider(*a):return N(client=client,get_model=lambda:m['model'])
 with tempfile.TemporaryDirectory() as tmp:
  extra={};e=N(unified_msg_origin='synthetic',get_extra=lambda k,d=None:extra.get(k,d),set_extra=lambda k,v:extra.__setitem__(k,v))
  p=N(scope_for=lambda e:'v1:'+'a'*64,enabled=lambda:True,store=N(take_budget=lambda *a,**k:True),context=N(get_current_chat_provider_id=pid,provider_manager=N(get_provider_by_id=provider)))
  thinking=Thinking(p,Path(tmp));thinking.migrate()
  answer=await thinking.deliberate(e,'合成场景：一个群友说他拿到了想要的机会，却舍不得现在的同学。没有人问建议。作为伙伴，该怎样接话才自然，又保留自己的判断？')
  with thinking.db() as c:usage=c.execute("select effort,status,reasoning_tokens,completion_tokens from p1_thinking_audit where kind='voluntary'").fetchone()
  report={'real_voluntary_max':True,'synthetic_only':True,'result':answer,'usage':{'effort':usage[0],'status':usage[1],'reasoning_tokens':usage[2],'completion_tokens':usage[3]},'actual_qq_messages':0,'production_database_modified':False}
  (R/'evidence/live-deliberate.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False,indent=2));assert answer['ok'] and usage[0]=='max' and usage[1]=='complete'
 await client.close()
asyncio.run(run())
