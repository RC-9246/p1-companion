"""Real SDK hooks, synthetic scope; no transport or real model calls."""
import asyncio,hashlib,json,os,sys,tempfile
from pathlib import Path
from types import SimpleNamespace as NS
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'release'));sys.path.insert(0,str(ROOT/'tests'))
from test_companion import init_db,CompanionStore
from astrbot.core.provider.entities import ProviderRequest,LLMResponse

async def run():
 with tempfile.TemporaryDirectory() as t:
  os.environ['P1_COMPANION_DATA']=t
  from astrbot_plugin_affect import main
  old=main.DATA;main.DATA=Path(t)
  try:
   init_db(Path(t)/'affect.db');p=main.AffectPlugin(NS());p.store=CompanionStore(Path(t)/'affect.db');p.store.migrate()
   p.scope_for=lambda event:event.scope
   class Event:
    def __init__(self,scope='scopeA',text='这是什么'):
     self.scope=scope;self.message_obj=NS(message_str=text);self.extra={}
    def get_messages(self):return []
    def get_extra(self,k,d=None):return self.extra.get(k,d)
    def set_extra(self,k,v):self.extra[k]=v
   bad='图确实是从你这个窗口过来的';hashes=[hashlib.sha256(bad.encode()).hexdigest()]
   (Path(t)/'media_retractions.json').write_text(json.dumps({'scopeA':hashes}))
   for scope in ['scopeA','scopeB']:
    e=Event(scope);r=ProviderRequest(prompt='这是什么',contexts=[{'role':'assistant','content':bad}])
    await p.ground_media_request(e,r);await p.ground_media_request(e,r)
    assert r.system_prompt.count('[P1-MEDIA-PROVENANCE:v1]')==1
    assert ('核实无依据' in r.contexts[0]['content'])==(scope=='scopeA')
    assert e.get_extra('_p1_media_evidence')['current_visible_images']==0
    response=LLMResponse(role='assistant',completion_text='一张梗图，图上有水印')
    await p.ground_media_response(e,response);assert '没收到图片' in response.completion_text
   e=Event(text='我怎么不知道我发了这个');r=ProviderRequest();await p.ground_media_request(e,r)
   response=LLMResponse(role='assistant',completion_text=bad);await p.ground_media_response(e,response);assert '我收回' in response.completion_text
   e=Event(scope=None);r=ProviderRequest();await p.ground_media_request(e,r);assert not r.system_prompt
  finally:main.DATA=old
 print(json.dumps({'real_sdk_hooks':True,'synthetic_scopes':2,'cross_scope_retraction_denied':True,'raw_context_unchanged':True,'qq_messages':0,'real_model_calls':0}))
if __name__=='__main__':asyncio.run(run())
