"""Both PNG sizes through actual group sticker hooks and OneBot serialization; no network."""
import asyncio,base64,hashlib,json,os,sys,tempfile
from pathlib import Path
from types import SimpleNamespace
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'release'))
async def main():
 with tempfile.TemporaryDirectory() as t:
  os.environ['P1_COMPANION_DATA']=t
  from astrbot_plugin_affect.reactions import Catalog
  from astrbot_plugin_p1_group_affect.main import P1GroupAffect
  from astrbot_plugin_p1_group_memory.store import scope_key,Store
  from astrbot.core.provider.entities import LLMResponse
  from astrbot.core.message.message_event_result import MessageChain
  from astrbot.core.message.components import Plain
  from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
  catalog=Catalog(R/'release/astrbot_plugin_affect');ctx=SimpleNamespace(_p1_companion=SimpleNamespace(reaction_catalog=catalog));p=P1GroupAffect(ctx);p.store=Store(Path(t)/'groups.db');p.store.migrate()
  groups=SimpleNamespace(plugin=SimpleNamespace(reaction_catalog=catalog));results=[]
  class Event:
   def __init__(self,n):
    self.extra={'_p1_group_affect_pending':{'scope':scope_key('10001',str(30003+n)),'event':'event'+str(n),'ready':False,'appraisal':dict(intent='question',emotion='neutral',relation='none',confidence=.95)}}
    self.message_obj=SimpleNamespace(message_str='来张轻小说原画的伙伴表情包')
   def get_extra(self,k,d=None):return self.extra.get(k,d)
   def set_extra(self,k,v):self.extra[k]=v
  for n,id in enumerate(['saki_novel_portrait','saki_novel_cooking']):
   e=Event(n);r=LLMResponse(role='assistant',completion_text='嗯，这张<sticker name="'+id+'"/>');await p.response(e,r)
   assert r.completion_text=='嗯，这张' and e.get_extra('_p1_group_sticker')==id
   message,added=await p.image(e,MessageChain([Plain(r.completion_text)]),groups);assert added
   payload=await AiocqhttpMessageEvent._parse_onebot_json(message);assert [x['type'] for x in payload]==['text','image']
   data=base64.b64decode(payload[1]['data']['file'][9:]);assert data.startswith(b'\x89PNG\r\n\x1a\n') and hashlib.sha256(data).hexdigest()==catalog.assets[id]['sha256']
   again,added=await p.image(e,MessageChain([Plain('第二段')]),groups);assert not added
   p.store.reaction_done(e.extra['_p1_group_affect_pending']['scope'],e.extra['_p1_group_affect_pending']['event'],False)
   assert not p.store.can_react(e.extra['_p1_group_affect_pending']['scope'],__import__('time').time())
   results.append(dict(asset=id,bytes=len(data),exact_png_hash=True,duplicate_segment_denied=True))
  print(json.dumps(dict(native_group_png=True,cases=results,real_qq_messages=0,production_db_modified=False),ensure_ascii=False))
asyncio.run(main())
