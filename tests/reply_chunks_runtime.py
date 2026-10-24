"""Real AstrBot decoration + respond stages, fake QQ transport, preserved 2–5s queue."""
import asyncio,inspect,json,os,sys,tempfile
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'release'));sys.path.insert(0,str(ROOT/'tests'))
from test_companion import init_db
from astrbot.core.message.message_event_result import MessageChain
from astrbot.core.message.components import Plain
from astrbot.core.pipeline.result_decorate.stage import ResultDecorateStage
from astrbot.core.pipeline.respond.stage import RespondStage
from astrbot_plugin_affect.identity import make_identity_key
async def drive(stage,event):
 value=stage.process(event)
 if inspect.isasyncgen(value):
  async for _ in value:pass
 else:await value
async def main():
 with tempfile.TemporaryDirectory() as t:
  data=Path(t);os.environ['P1_COMPANION_DATA']=t;init_db(data/'affect.db')
  identity=make_identity_key('qq_snowluma','10001','20002');(data/'allowed_identities.json').write_text(json.dumps({'version':1,'allowed_identities':[identity]}))
  from astrbot_plugin_affect.main import AffectPlugin
  from astrbot_plugin_affect.companion_store import CompanionStore
  p=AffectPlugin(object());p.store=CompanionStore(data/'affect.db');p.store.migrate();delays=[]
  async def pause(x):delays.append(x)
  p.reply_pause=pause
  class Result:
   result_content_type=None;use_t2i_=False;async_stream=None
   def __init__(self,text,model=True):self.chain=[Plain(text)];self.model=model
   def is_model_result(self):return self.model
   def is_llm_result(self):return self.model
   def get_plain_text(self):return ''.join(c.text for c in self.chain if isinstance(c,Plain))
   def derive(self,chain):return MessageChain(chain)
  class Event:
   plugins_name=[];unified_msg_origin='synthetic';message_obj=SimpleNamespace(message_id='style-test')
   def __init__(self,text,model=True):self.result=Result(text,model);self.extra={};self.sent=[]
   def get_platform_id(self):return 'qq_snowluma'
   def get_platform_name(self):return 'aiocqhttp'
   def get_self_id(self):return '10001'
   def get_sender_id(self):return '20002'
   def get_sender_name(self):return 'synthetic'
   def is_private_chat(self):return True
   def get_extra(self,k,d=None):return self.extra.get(k,d)
   def set_extra(self,k,v):self.extra[k]=v
   def get_result(self):return self.result
   def is_stopped(self):return False
   def _outline_chain(self,c):return 'synthetic'
   def clear_result(self):self.result=None
   async def send(self,message):self.sent.append(''.join(c.text for c in message.chain if isinstance(c,Plain)))
  cfg=json.loads(Path('/AstrBot/data/cmd_config.json').read_text(encoding='utf-8-sig'))
  cfg['platform_settings']['segmented_reply'].update(enable=True,only_llm_result=True,interval_method='random',interval='0,0',split_mode='regex',regex=r'\A[\s\S]+\Z',content_cleanup_rule='')
  cfg['platform_settings'].update(reply_prefix='',reply_with_mention=False,reply_with_quote=False,forward_threshold=999999)
  cfg['provider_tts_settings']['enable']=False;cfg['content_safety']['also_use_in_response']=False;cfg['t2i']=False
  async def no_tts(*args):return None
  ctx=SimpleNamespace(astrbot_config=cfg,plugin_manager=SimpleNamespace(context=SimpleNamespace(get_using_tts_provider_async=no_tts)))
  d=ResultDecorateStage();r=RespondStage();await d.initialize(ctx);await r.initialize(ctx)
  cases=[('casual','嗯，今天先休息一下。\n\n剩下的事情，明天再接着做。',True,2),('one','嗯，去忙吧。',True,1),('bounded','第一件事。\n\n第二件事。\n\n第三件事。\n\n第四件事。',True,3),('code','代码如下。\n\n```python\nprint("a")\n\nprint("b")\n```\n\n运行后再看。',True,1),('command','状态如下。\n\n操作正常。',False,1),('links','参考这一个。\n\nhttps://example.com/path?q=1&x=2',True,2)]
  results=[]
  for name,text,model,want in cases:
   e=Event(text,model);before=len(delays);await p.ensure_reply_delay(e);await p.ensure_reply_delay(e)
   await drive(d,e);await drive(r,e)
   assert len(e.sent)==want,(name,e.sent)
   from astrbot_plugin_affect.reply_chunks import qq_reply
   expected=''.join(qq_reply(text)) if model else text
   assert ''.join(e.sent).replace('\n','').replace(' ','')==expected.replace('\n','').replace(' ','')
   assert len(delays)-before==want and all(2<=x<=5 for x in delays[before:])
   if name=='links':assert e.sent[-1]=='https://example.com/path?q=1&x=2'
   results.append({'case':name,'messages':len(e.sent),'passed':True})
  print(json.dumps({'native_pipeline_chat_bubbles':True,'cases':results,'each_send_delayed_2_to_5':True,'native_extra_delay':r.interval,'qq_messages_sent':0},ensure_ascii=False,indent=2))
asyncio.run(main())
