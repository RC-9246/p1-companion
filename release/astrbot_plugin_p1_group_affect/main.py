"""Group-specific personality and affect; never opens private affect or memory rows."""
import asyncio,base64,json,time,re
from astrbot.api import logger
from astrbot.api.star import Star
from astrbot.api.event import filter
from astrbot.core.agent.message import TextPart
try:
 from ..astrbot_plugin_affect.main import DATA
 from ..astrbot_plugin_affect.emotion_model import seed,react,describe,interaction_context,coping,perspective
 from ..astrbot_plugin_affect.appraisal import CLASSIFIER_PROMPT,parse_appraisal,fallback
 from ..astrbot_plugin_affect.reactions import eligible_context
 from ..astrbot_plugin_p1_group_memory.store import Store,scope_key
except ImportError:
 from astrbot_plugin_affect.main import DATA
 from astrbot_plugin_affect.emotion_model import seed,react,describe,interaction_context,coping,perspective
 from astrbot_plugin_affect.appraisal import CLASSIFIER_PROMPT,parse_appraisal,fallback
 from astrbot_plugin_affect.reactions import eligible_context
 from astrbot_plugin_p1_group_memory.store import Store,scope_key
PROFILE={'version': 1, 'core': 'generic_public_v1', 'axes': {'independence': 0.7, 'restraint': 0.7, 'respect_boundaries': 0.95}, 'public_relationship': '各成员分别积累，不继承私聊关系'}
TAG=re.compile(r'<sticker\s+name="(saki_[a-z_]+)"\s*/>')
CLEAN=re.compile(r'<sticker\b[^>]*?(?:/>|$)',re.S)

class P1GroupAffect(Star):
 def __init__(self,context):
  super().__init__(context);self.context=context;self.store=Store(DATA.parent/'p1_groups/groups.db');self.gate=asyncio.Semaphore(1)
 async def initialize(self):
  await asyncio.to_thread(self.store.migrate);self.context._p1_group_affect=self
  try:
   policy=json.loads((DATA/'groups.json').read_text())
   if policy.get('version')==1:
    for r in policy.get('groups',[])[:20]:await asyncio.to_thread(self.store.seed_affect,scope_key(r['bot'],r['group']),PROFILE,seed(),time.time())
  except (OSError,ValueError,KeyError,TypeError):pass
  self.health();logger.info('[P1 Group Affect] READY dimensions=21 scope=bot_group_member')
 def health(self):
  p=getattr(self.context,'_p1_companion',None)
  if p:p.health('ready')
 async def ensure(self,scope):
  await asyncio.to_thread(self.store.seed_affect,scope,PROFILE,seed(),time.time())
 async def terminate(self):
  if getattr(self.context,'_p1_group_affect',None) is self:del self.context._p1_group_affect
 async def prepare(self,event,request,scene,groups):
  scope=groups.memory.key(event);member=scene['current']['speaker'];now=time.time()
  await asyncio.to_thread(self.store.seed_affect,scope,PROFILE,seed(),now)
  pending=event.get_extra('_p1_group_affect_pending')
  if not pending:
   text=scene['current']['text'];a=fallback(text)
   try:
    if await asyncio.to_thread(groups.plugin.store.take_budget,120,bucket=5):
     async with self.gate:
      provider=await groups.provider(event)
      payload={'current':text[:1000],'speaker':member,'recent':scene['messages'][-8:]}
      out=await asyncio.wait_for(provider.client.with_options(timeout=4,max_retries=0).chat.completions.create(model=provider.get_model(),messages=[{'role':'system','content':CLASSIFIER_PROMPT+'\n这是公开群聊，只评估当前发言者对当前话题的态度；其他人的情绪不得归给当前发言者，不推断私人关系。'},{'role':'user','content':json.dumps(payload,ensure_ascii=False)}],temperature=0,max_tokens=900,response_format={'type':'json_object'},extra_body={'thinking':{'type':'disabled'}}),5)
      a=parse_appraisal(out.choices[0].message.content,text)
   except Exception as exc:logger.info('[P1 Group Affect] appraisal_fallback code='+type(exc).__name__)
   pending={'scope':scope,'member':member,'appraisal':a,'event':scene['current']['id'],'epoch':scene['epoch'],'ready':False,'ack':False,'failed':False}
   event.set_extra('_p1_group_affect_pending',pending)
  group,person,profile=await asyncio.to_thread(self.store.affect,scope,member)
  public_appraisal={k:v for k,v in pending['appraisal'].items() if k!='self_response'}
  group_state=dict(group or seed());group_state.pop('thread',None)
  gs=react(group_state,now,public_appraisal);ps=react(person or seed(),now,pending['appraisal'])
  # Existing emotion_model returns (state,episode); persist only the state.
  if isinstance(gs,tuple):gs=gs[0]
  if isinstance(ps,tuple):ps=ps[0]
  hint={'current_exchange':interaction_context(pending['appraisal']),'coping':coping(ps,pending['appraisal']),'own_reaction_to_current_member':perspective(ps,pending['appraisal']),'stable_persona':profile or PROFILE,'this_group_simulation':describe(gs),'current_member_simulation':describe(ps,pending['appraisal']),'member_delivered_interactions':(person or seed())['interactions']}
  request.extra_user_content_parts.append(TextPart(text='[P1-GROUP-AFFECT:v1]\n'+json.dumps(hint,ensure_ascii=False)+'\n这些是本群专属的模拟倾向，不是主观感受或用户心理事实。状态只微调表达，不盖过眼前语境；认真求助、纠错、离开和不回复都不是冒犯。不输出参数、内心独白或括号动作。不把某人的心情说成全群或自己的遭遇。').mark_as_temp())
  catalog=groups.plugin.reaction_catalog
  if catalog and eligible_context(pending['appraisal'],scene['current']['text']) and await asyncio.to_thread(self.store.can_react,scope,now):
   request.system_prompt+='\n[P1-GROUP-STICKERS:v1] 轻松且有帮助时可偶尔在回复末尾选一张配图，格式 <sticker name="精确ID"/>。最多1张，严肃/纠错/安慰不用。下面只是官方动画剧照或轻小说原画选项，不是现实经历或当前群成员关系；想看轻小说原画时可优先选对应原画，其他时候以表情贴切为先；标签不表示已送达：'+json.dumps({k:('轻小说原画' if v.get('medium')=='light_novel_art' else '动画剧照')+' / '+v['category']+'：'+v['label'] for k,v in catalog.assets.items()},ensure_ascii=False)
 @filter.on_llm_response(priority=15)
 async def response(self,event,response):
  p=event.get_extra('_p1_group_affect_pending')
  if not p:return
  text=str(getattr(response,'completion_text','') or '');ids=TAG.findall(text);response.completion_text=CLEAN.sub('',text).strip()
  companion=getattr(self.context,'_p1_companion',None);catalog=getattr(companion,'reaction_catalog',None)
  if ids and catalog and ids[0] in catalog.assets and eligible_context(p['appraisal'],str(getattr(event.message_obj,'message_str',''))):
   event.set_extra('_p1_group_sticker',ids[0])
   if not response.completion_text:response.completion_text='嗯'
  p['ready']=(getattr(response,'role',None)=='assistant' and bool(response.completion_text) and not getattr(response,'tools_call_name',[]))
 async def image(self,event,message,groups):
  p=event.get_extra('_p1_group_affect_pending');asset=event.get_extra('_p1_group_sticker');catalog=groups.plugin.reaction_catalog
  if event.get_extra('_p1_learning_no_images'):return message,False
  if not p or not p['ready'] or not asset or not catalog or event.get_extra('_p1_group_image_attempted'):return message,False
  if asset not in catalog.assets:return message,False
  from astrbot.core.message.components import Image
  data=await asyncio.to_thread(catalog.read,asset)
  if not await asyncio.to_thread(self.store.reserve_reaction,p['scope'],p['event'],asset,time.time()):return message,False
  event.set_extra('_p1_group_image_attempted',True)
  return message.derive([*message.chain,Image.fromBase64(base64.b64encode(data).decode())]),True
 async def delivered(self,event,groups):
  p=event.get_extra('_p1_group_affect_pending')
  if not p or not p['ready'] or not p['ack'] or p['failed'] or not groups.allowed(event):return False
  group,person,profile=await asyncio.to_thread(self.store.affect,p['scope'],p['member']);now=time.time()
  public_appraisal={k:v for k,v in p['appraisal'].items() if k!='self_response'}
  group_state=dict(group or seed());group_state.pop('thread',None)
  gs=react(group_state,now,public_appraisal);ps=react(person or seed(),now,p['appraisal'])
  if isinstance(gs,tuple):gs=gs[0]
  if isinstance(ps,tuple):ps=ps[0]
  return await asyncio.to_thread(self.store.commit_affect,p['scope'],p['event'],p['member'],gs,ps,profile or PROFILE,now,p['epoch'])
