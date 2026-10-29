"""Actual SDK: local review edits, scope-clear/revoke races and compact sticker menus."""
import asyncio,json,os,sys,tempfile,time
from pathlib import Path
from types import SimpleNamespace as N
R=Path(__file__).resolve().parents[1];sys.path[:0]=[str(R/'release'),str(R/'tests')]
from test_companion import init_db
from test_qq_actions import Event as BaseEvent,API
from neutral_assets import expanded
from astrbot.core.provider.entities import ProviderRequest
from astrbot.core.platform.message_type import MessageType
from astrbot_plugin_affect.identity import make_identity_key

async def run():
 with tempfile.TemporaryDirectory() as tmp:
  d=Path(tmp)/'data/plugin_data/affect';d.mkdir(parents=True);os.environ['P1_COMPANION_DATA']=str(d);init_db(d/'affect.db')
  from astrbot_plugin_affect.main import AffectPlugin,atomic_json
  from astrbot_plugin_affect.companion_store import CompanionStore
  from astrbot_plugin_affect.qq_runtime import QQController
  from astrbot_plugin_affect.reactions import Catalog,ReactionStore
  from astrbot_plugin_p1_stickers.main import P1Stickers
  from astrbot_plugin_p1_group_affect.main import P1GroupAffect
  owner=make_identity_key('qq_snowluma','10001','20002')
  atomic_json(d/'allowed_identities.json',{'version':1,'allowed_identities':[owner]})
  atomic_json(d/'groups.json',{'version':1,'groups':[{'bot':'10001','group':'30003'}]})
  cfg={'platform_settings':{'enable_id_white_list':True,'id_whitelist':['qq_snowluma:FriendMessage:20002','qq_snowluma:FriendMessage:20003']}}
  atomic_json(d.parents[1]/'cmd_config.json',cfg)
  class Client(API):
   base_url=N(scheme='https',host='api.deepseek.com')
   def __init__(self):super().__init__();self.chat=N(completions=self);self.model_calls=[];self.hook=None
   def with_options(self,**kw):self.options=kw;return self
   async def create(self,**kw):
    self.model_calls.append(kw)
    if self.hook:await self.hook()
    raw={'issues':['time_guess'],'edits':[{'before':'那就来得及，','after':''}]}
    return N(choices=[N(message=N(content=json.dumps(raw,ensure_ascii=False)))])
  client=Client()
  class Context:
   def get_config(self,*a):return cfg
   def get_platform_inst(self,*a):return N(get_client=lambda:client)
   @property
   def provider_manager(self):return self
   async def get_current_chat_provider_id(self,*a):return 'synthetic'
   async def get_provider_by_id(self,*a):return N(client=client,get_model=lambda:'synthetic')
  ctx=Context();p=AffectPlugin(ctx);p.store=CompanionStore(d/'affect.db');p.store.migrate();p.qq=QQController(p,d)
  await p.agency.start()
  class Event(BaseEvent):
   def get_message_type(self):return MessageType.GROUP_MESSAGE if self.group else MessageType.FRIEND_MESSAGE
  original='嗯，是四点。那就来得及，我还挺期待你的汇报';expected='嗯，是四点。我还挺期待你的汇报'
  appraisal={'intent':'feedback','target':'self','relation':'criticism','confidence':.95}
  def event(group=''):
   e=Event(group=group,text='你记错了，是四点开会');e.set_extra('_p1_group_admitted',bool(group));return e
  private=event();scope=p.agency.scope(private);p.agency.store.ensure(scope);private.set_extra('_p1_agency_epoch',0)
  assert await p.review_reply(private,original,appraisal,private.message_obj.message_str)==expected
  assert client.options=={'timeout':6,'max_retries':0} and client.model_calls[-1]['extra_body']=={'thinking':{'type':'disabled'}}
  assert 'reasoning_effort' not in client.model_calls[-1]
  count=len(client.model_calls);assert await p.review_reply(private,original,appraisal,'你记错了')==original and len(client.model_calls)==count
  # A cleared private scope stops the review result, even when the call has succeeded.
  private=event();private.set_extra('_p1_agency_epoch',0)
  async def clear():p.agency.store.wipe(scope)
  client.hook=clear;assert await p.review_reply(private,original,appraisal,'你记错了')==original
  count=len(client.model_calls);private=event();private.set_extra('_p1_agency_epoch',0)
  assert await p.review_reply(private,original,appraisal,'你记错了')==original and len(client.model_calls)==count
  # Group affect compatibility key (v1) is different from the agency/memory key (g1).
  p.groups.valid=lambda e:bool(e.group);group=event('30003');gscope=p.agency.scope(group)
  assert gscope.startswith('g1:') and p.scope_for(group)!=gscope
  p.agency.store.ensure(gscope);group.set_extra('_p1_agency_epoch',0);client.hook=None
  assert await p.review_reply(group,original,appraisal,'你记错了')==expected
  group=event('30003');group.set_extra('_p1_agency_epoch',0)
  async def revoke():atomic_json(d/'groups.json',{'version':1,'groups':[]})
  client.hook=revoke;assert await p.review_reply(group,original,appraisal,'你记错了')==original
  atomic_json(d/'groups.json',{'version':1,'groups':[{'bot':'10001','group':'30003'}]});client.hook=None
  # Both private and group menus are bounded on a real, 46-item reviewed fixture catalog.
  catalog=Catalog(expanded(d/'fixture-assets'));p.reaction_catalog=catalog;p.reactions=ReactionStore(d/'affect.db');p.reactions.migrate();ctx._p1_companion=p
  stickers=P1Stickers(ctx);stickers.catalog=catalog;e=event();e.message_obj.message_str='轻小说原画看起来挺有意思';casual={'intent':'casual','emotion':'happy','relation':'none','target':'user','confidence':.95}
  e.set_extra('_p1_companion_pending',{'appraisal':casual});req=ProviderRequest();await stickers.describe(e,req)
  menu=json.loads(req.system_prompt.split('经审核的相关候选：',1)[1].split('。轻松',1)[0]);assert len(menu)==8 and all('轻小说' in x for x in menu.values())
  ga=P1GroupAffect(ctx);await ga.initialize();scene={'current':{'speaker':'memberA','text':e.message_obj.message_str,'id':'synthetic-menu'},'messages':[],'epoch':0}
  group=event('30003');group.set_extra('_p1_group_affect_pending',{'appraisal':casual});req=ProviderRequest()
  groups=N(memory=N(key=lambda _:gscope),plugin=p);await ga.prepare(group,req,scene,groups)
  menu=json.loads(req.system_prompt.split('候选：',1)[1]);assert len(menu)==8 and all('轻小说' in x for x in menu.values())
  assert ga.store.reserve_reaction(gscope,'synthetic-send','saki_novel_portrait',time.time())
  assert ga.store.recent_reactions(gscope)==['saki_novel_portrait']
  assert ga.store.recent_reactions('g1:'+'b'*64)==[]
  await ga.terminate();await p.agency.stop()
  print(json.dumps({'real_sdk':True,'localized_edit_preserves_opinion':True,'review_fast_no_retries':True,'review_once_per_event':True,'cleared_scope_before_and_after_call':True,'group_agency_key_not_legacy_affect_key':True,'revoke_after_call':True,'private_and_group_menus_max_8_from_46':True,'scoped_recent_stickers':True,'real_model_calls':0,'qq_messages':0,'production_db_modified':False}))

if __name__=='__main__':asyncio.run(run())
