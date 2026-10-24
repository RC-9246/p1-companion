"""Use real AstrBot components and OneBot serialization with a fake QQ endpoint."""
import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'release'));sys.path.insert(0,str(ROOT/'tests'))
from test_companion import init_db
from astrbot_plugin_affect.identity import make_identity_key
from astrbot.core.message.message_event_result import MessageChain
from astrbot.core.message.components import Plain,Image
from astrbot.core.provider.entities import ProviderRequest,LLMResponse

async def run():
 with tempfile.TemporaryDirectory() as t:
  data=Path(t);os.environ['P1_COMPANION_DATA']=t;init_db(data/'affect.db')
  identity=make_identity_key('qq_snowluma','10001','20002')
  (data/'allowed_identities.json').write_text(json.dumps({'version':1,'allowed_identities':[identity]}))
  from astrbot_plugin_affect.main import AffectPlugin
  class Bot:
   def __init__(self):self.calls=[];self.receipt={'message_id':-123};self.broken=False
   async def send_private_msg(self,**kw):
    self.calls.append(kw)
    if self.broken:raise TimeoutError('synthetic unknown delivery')
    return self.receipt
  bot=Bot()
  context=SimpleNamespace(get_platform_inst=lambda _:SimpleNamespace(get_client=lambda:bot))
  class Event:
   def __init__(self,id,sender='20002',private=True):
    self.extra={};self.text_calls=[];self.sender=sender;self.private=private
    self.message_obj=SimpleNamespace(message_id=id,message_str='哈哈，发张微笑的表情包看看')
   def get_platform_id(self):return 'qq_snowluma'
   def get_self_id(self):return '10001'
   def get_sender_id(self):return self.sender
   def is_private_chat(self):return self.private
   def get_extra(self,k,default=None):return self.extra.get(k,default)
   def set_extra(self,k,v):self.extra[k]=v
   async def send(self,message):self.text_calls.append(message)
  p=AffectPlugin(context);await p.initialize();delays=[]
  async def pause(x):delays.append(x)
  p.reply_pause=pause
  async def assess(*args):return dict(intent='casual',emotion='happy',relation='none',target='none',confidence=.95,source='semantic')
  p.assess=assess
  async def prepare(id):
   e=Event(id);await p.inject_state_into_llm(e,ProviderRequest(prompt=e.message_obj.message_str))
   r=json.loads(await p.saki_reaction(e,'search','微笑'));assert len(r['assets'])==12 and r['total_assets']==46
   chosen=json.loads(await p.saki_reaction(e,'use',asset_id='saki_novel_portrait'));assert chosen['ok']
   await p.mark_response(e,LLMResponse(role='assistant',completion_text='嗯，偶尔也可以这样。'))
   return e
  e=await prepare('one');await e.send(MessageChain([Plain('嗯，偶尔也可以这样。')]))
  await p.commit_after_delivery(e)
  assert len(bot.calls)==1 and not e.text_calls and len(delays)==1 and 2<=delays[0]<=5
  payload=bot.calls[0];assert payload['user_id']==20002
  assert [r['type'] for r in payload['message']]==['text','image']
  encoded=payload['message'][1]['data']['file'];assert encoded.startswith('base64://')
  assert hashlib.sha256(base64.b64decode(encoded[9:])).hexdigest()==p.reaction_catalog.assets['saki_novel_portrait']['sha256']
  assert p.store.read(identity)['interaction_count']==1
  assert json.loads(await p.saki_reaction(e,'use',asset_id='saki_novel_portrait'))['ok'] is False
  await e.send(MessageChain([Plain('second segment')]))
  assert len(bot.calls)==1 and len(e.text_calls)==1 # Never attach twice after segmentation.
  for outside in (Event('other','30003'),Event('group',private=False)):
   assert json.loads(await p.saki_reaction(outside,'search'))['error']=='forbidden'
  # Reset only the synthetic reaction DB between independent scenarios.
  def clear():
   with sqlite3.connect(p.reactions.path) as db:db.execute('DELETE FROM reaction_outbox');db.execute('DELETE FROM reaction_text')
  clear();e=await prepare('disabled');p.reactions.toggle(identity,False)
  await e.send(MessageChain([Plain('文字照常。')]))
  assert len(bot.calls)==1 and e.text_calls
  p.reactions.toggle(identity,True)
  clear();e=await prepare('missing');p.reaction_catalog.read=lambda _:(_ for _ in ()).throw(ValueError('synthetic missing image'))
  await e.send(MessageChain([Plain('文字仍然正常。')]))
  assert len(bot.calls)==1 and e.text_calls
  from astrbot_plugin_affect.reactions import Catalog
  p.reaction_catalog=Catalog(ROOT/'release/astrbot_plugin_affect')
  clear();e=await prepare('uncertain');bot.broken=True
  try:await e.send(MessageChain([Plain('synthetic')]))
  except TimeoutError:pass
  else:raise AssertionError('unknown send must not look successful')
  await p.commit_after_delivery(e)
  assert p.store.read(identity)['interaction_count']==1
  with sqlite3.connect(p.reactions.path) as db:assert db.execute('SELECT state FROM reaction_outbox').fetchone()[0]=='unknown'
  assert not p.reactions.can_use(identity,__import__('time').time())
  clear();e=await prepare('missing-receipt');bot.broken=False;bot.receipt={'retcode':0}
  try:await e.send(MessageChain([Plain('synthetic')]))
  except ValueError:pass
  else:raise AssertionError('OneBot image receipt required')
  clear();bot.receipt={'message_id':-321};e=Event('explicit-command');e.message_obj.message_str='/伙伴表情 发送'
  e.stop_event=lambda:None;e.plain_result=lambda text:MessageChain([Plain(text)])
  before=len(bot.calls);e.get_result=lambda:None;await p.ensure_reply_delay(e)
  async for result in p.reaction_control(e,'发送'):await e.send(result)
  assert len(bot.calls)==before+1, 'command_must_send_a_new_payload'
  assert bot.calls[-1]['message'][1]['type']=='image'
  assert base64.b64decode(bot.calls[-1]['message'][1]['data']['file'][9:]).startswith(b'\xff\xd8\xff')
  await p.terminate()
  print(json.dumps({'reaction_runtime':True,'actual_astrbot_components':True,'one_text_image_payload':True,
   'exact_reviewed_image_hash':True,'new_asset_id':'saki_novel_portrait','png_and_jpeg_supported':True,'delay_2_to_5':True,'cross_user_and_group_denied':True,
   'disable_and_missing_file_text_fallback':True,'uncertain_not_replayed':True,'onebot_receipt_required':True,
   'real_qq_messages':0,'production_database_modified':False},ensure_ascii=False))

asyncio.run(run())
