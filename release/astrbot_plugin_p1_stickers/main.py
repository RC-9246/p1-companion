try:
 from ..astrbot_plugin_affect.module_policy import enabled as module_on
except ImportError:
 from astrbot_plugin_affect.module_policy import enabled as module_on
"""MemeManagerLite adaptation; AGPL-3.0; see UPSTREAM.md and LICENSE."""
import asyncio,re,json
from pathlib import Path
from astrbot.api import logger
from astrbot.api.star import Star
from astrbot.api.event import filter
try:
 from ..astrbot_plugin_affect.main import DATA
 from ..astrbot_plugin_affect.private_access import companion_identity
 from ..astrbot_plugin_affect.reactions import Catalog,ReactionStore,eligible_context
except ImportError:
 from astrbot_plugin_affect.main import DATA
 from astrbot_plugin_affect.private_access import companion_identity
 from astrbot_plugin_affect.reactions import Catalog,ReactionStore,eligible_context

TAG=re.compile(r'<sticker\s+name="(saki_[a-z_]+)"(?:\s+score="(?:0(?:\.\d+)?|1(?:\.0+)?)")?\s*/>')
CLEAN=re.compile(r'<sticker\b[^>]*?(?:/>|$)',re.S)
def extract(text,allowed):
 matches=TAG.findall(text);selected=next((x for x in matches if x in allowed),None)
 return CLEAN.sub('',text).strip(),selected

class P1Stickers(Star):
 def __init__(self,context):super().__init__(context);self.context=context;self.catalog=None
 async def initialize(self):
  try:from ..astrbot_plugin_affect.reactions import catalog_folder
  except ImportError:from astrbot_plugin_affect.reactions import catalog_folder
  self.catalog=Catalog(catalog_folder(Path(__file__).parent.parent/'astrbot_plugin_affect',DATA))
  logger.info('[P1 Stickers] READY reviewed='+str(len(self.catalog.assets)))
 @filter.on_llm_request(priority=-20)
 async def describe(self,event,req):
  if not module_on(DATA,'stickers'):return
  identity=companion_identity(event,self.context)
  if not identity or not self.catalog or not self.catalog.assets or (DATA/'companion.disabled').exists():return
  p=event.get_extra('_p1_companion_pending')
  store=ReactionStore(DATA/'affect.db')
  if not p or not eligible_context(p['appraisal'],event.message_obj.message_str) or not await asyncio.to_thread(store.can_use,identity,__import__('time').time()):return
  recent=await asyncio.to_thread(store.recent,identity)
  req.system_prompt+='\n[P1-STICKERS:v2] 经审核图库：'+json.dumps({x:('轻小说原画' if a.get('medium')=='light_novel_art' else '动画剧照')+' / '+a['category']+'：'+a['label'] for x,a in self.catalog.assets.items()},ensure_ascii=False)+'。最近已尝试或发送的图片ID：'+json.dumps(recent)+'。轻松且表情有帮助时，可以在自然回复末尾附一个 <sticker name="精确ID"/> 标签，由系统安全发送；也可以使用 p1_saki_reaction 工具，两者选其一。最多一张，不要每次都用。按当前语气选择；用户想看轻小说原画时优先选择标注轻小说原画的选项，平时仍以表情贴切和缩略图清楚为先，封面图带书名且可能包含悠太，不要强行用作单人表情。合适时优先换一张近期没用过的；用户明确指定时可以沿用。剧照和原画不是当前真实经历或关系，不得据图声称自己刚睡觉、出门或和用户共同经历原作剧情。安慰、严肃问题或纠错不用图。标签不是已送达回执。'
 @filter.on_llm_response(priority=20)
 async def select(self,event,resp):
  if not companion_identity(event,self.context) or not self.catalog or not self.catalog.assets or (DATA/'companion.disabled').exists():return
  if getattr(resp,'tools_call_name',None) or getattr(resp,'role','assistant')!='assistant':return
  text,selected=extract(str(getattr(resp,'completion_text','') or ''),self.catalog.assets)
  resp.completion_text=text
  pending=event.get_extra('_p1_companion_pending')
  if module_on(DATA,'stickers') and selected and pending and eligible_context(pending['appraisal'],event.message_obj.message_str):
   if not event.get_extra('_p1_saki_reaction'):event.set_extra('_p1_saki_reaction',selected)
   # AstrBot skips empty final replies. Keep a natural text carrier for the unified image transport.
   if not text:resp.completion_text='嗯。'
