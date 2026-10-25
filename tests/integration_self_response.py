"""Actual AstrBot group hooks with source-bound reactions and isolated ledgers."""
import asyncio,json,os,sys,tempfile,time
from pathlib import Path
from types import SimpleNamespace as N
R=Path(__file__).resolve().parents[1];sys.path[:0]=[str(R/'release'),str(R/'tests')]
from test_companion import init_db
from test_self_response import signal,TEXT
from astrbot.core.provider.entities import ProviderRequest
async def run():
 with tempfile.TemporaryDirectory() as tmp:
  d=Path(tmp)/'data/plugin_data/affect';d.mkdir(parents=True);os.environ['P1_COMPANION_DATA']=str(d);init_db(d/'affect.db')
  from astrbot_plugin_affect.companion_store import CompanionStore
  from astrbot_plugin_p1_group_affect.main import P1GroupAffect
  from astrbot_plugin_p1_group_memory.store import scope_key
  store=CompanionStore(d/'affect.db');store.migrate()
  class Client:
   base_url=N(scheme='https',host='api.deepseek.com')
   def __init__(self):self.chat=N(completions=self)
   def with_options(self,**kw):return self
   async def create(self,**kw):
    text=json.loads(kw['messages'][-1]['content'])['current'];raw=signal(text) if text==TEXT else {'intent':'casual','emotion':'neutral','relation':'none','target':'none','confidence':.9}
    return N(choices=[N(message=N(content=json.dumps(raw,ensure_ascii=False)))])
  client=Client();ctx=N();plugin=N(store=store,reaction_catalog=None,health=lambda *_:None);ctx._p1_companion=plugin
  ga=P1GroupAffect(ctx);await ga.initialize()
  async def provider(event):return N(client=client,get_model=lambda:'synthetic')
  groups=N(plugin=plugin,provider=provider,memory=N(key=lambda e:e.scope),allowed=lambda e:True)
  class Event:
   def __init__(self,scope,member,text):self.scope=scope;self.member=member;self.message_obj=N(message_str=text);self.extra={}
   def get_extra(self,k,v=None):return self.extra.get(k,v)
   def set_extra(self,k,v):self.extra[k]=v
  async def turn(scope,member,text,index):
   await ga.ensure(scope);meta=ga.store.meta(scope);event=Event(scope,member,text)
   scene={'current':{'speaker':member,'text':text,'id':'event-'+str(index)},'messages':[],'epoch':meta['epoch']}
   req=ProviderRequest();await ga.prepare(event,req,scene,groups)
   pending=event.get_extra('_p1_group_affect_pending');pending.update(ready=True,ack=True)
   assert await ga.delivered(event,groups)
   return str(req.extra_user_content_parts),event
  one=scope_key('10001','30003');two=scope_key('10001','30004')
  a,event=await turn(one,'memberA',TEXT,1);g,p,_=ga.store.affect(one,'memberA');assert 'thread' not in g and p['thread']['feeling']=='competitive';assert '不服气' in a
  b,_=await turn(one,'memberB','今天聊点别的',2);assert '不服气' not in b
  other,_=await turn(two,'memberA','今天聊点别的',3);assert '不服气' not in other
  carry,_=await turn(one,'memberA','然后呢',4);assert '不服气' in carry
  assert not await ga.delivered(event,groups)
  await ga.terminate()
 print(json.dumps({'real_astrbot_hooks':True,'groups':2,'members':2,'member_reaction_carries':True,'group_global_state_contains_no_member_thread':True,'other_group_and_member_isolated':True,'delivery_ack_and_dedup':True,'qq_messages':0,'real_model_calls':0}))
if __name__=='__main__':asyncio.run(run())
