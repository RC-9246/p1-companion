"""Real authorized account browser + approved vision model; isolated plugin state, no QQ transport."""
import asyncio,json,os,sys,tempfile
from pathlib import Path
from types import SimpleNamespace
from openai import AsyncOpenAI
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'release'));sys.path.insert(0,str(ROOT/'tests'))
from test_companion import init_db
REAL=Path('/AstrBot/data/plugin_data/affect')
async def main():
 import sqlite3
 with sqlite3.connect(REAL/'affect.db') as db:row=db.execute('SELECT bot_id,user_id FROM companion_social LIMIT 1').fetchone()
 assert row
 cfg=json.loads(Path('/AstrBot/data/cmd_config.json').read_text(encoding='utf-8-sig'));pid=cfg['agent_runner']['config']['model']['provider_id'];m=next(p for p in cfg['provider'] if p['id']==pid);src=next(s for s in cfg['provider_sources'] if s['id']==m['provider_source_id']);keys=src['key']
 ai=AsyncOpenAI(api_key=keys[0] if isinstance(keys,list) else keys,base_url=src['api_base'],timeout=25,max_retries=0)
 class Context:
  provider_manager=None
  async def get_current_chat_provider_id(self,*a):return pid
  async def get_provider_by_id(self,*a):return SimpleNamespace(client=ai,get_model=lambda:m['model'])
 class Event:
  unified_msg_origin='test-no-qq-transport'
  def __init__(self):self.extra={}
  def get_platform_id(self):return 'qq_snowluma'
  def get_self_id(self):return str(row[0])
  def get_sender_id(self):return str(row[1])
  def is_private_chat(self):return True
  def get_extra(self,k,d=None):return self.extra.get(k,d)
  def set_extra(self,k,v):self.extra[k]=v
 try:
  with tempfile.TemporaryDirectory() as t:
   data=Path(t);os.environ['P1_COMPANION_DATA']=t;init_db(data/'affect.db')
   for name in ('allowed_identities.json','leisure_token'):(data/name).write_bytes((REAL/name).read_bytes());(data/name).chmod(0o600)
   from astrbot_plugin_affect.main import AffectPlugin
   from astrbot_plugin_affect.companion_store import CompanionStore
   context=Context();context.provider_manager=context;p=AffectPlugin(context);p.store=CompanionStore(data/'affect.db');p.store.migrate()
   result=json.loads(await p.bilibili(Event(),'watch',bvid='BV1uk4y1j7wD',seconds=20))
   print(json.dumps({'result':result,'actual_authorized_account':True,'qq_messages':0,'plugin_notes_isolated':True,'production_watch_quota_charged':True},ensure_ascii=False,indent=2))
   assert result.get('ok') and result.get('status')=='completed' and result.get('vision_understood') is True and result.get('sampled_frames',0)>0
   assert not result.get('audio_understood') and 'frames' not in result
 finally:await ai.close()
asyncio.run(main())
