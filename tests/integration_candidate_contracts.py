"""Run two pinned upstream hooks with fake events, classifier and temp storage only."""
import asyncio,importlib.util,json,sys,tempfile,types
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
from astrbot.api.star import StarTools
from astrbot.core.provider.entities import ProviderRequest,LLMResponse
R=Path(__file__).resolve().parents[1]
def load(name,path,package=False):
 if package:
  pkg=types.ModuleType(name);pkg.__path__=[str(path.parent)];sys.modules[name]=pkg;name+='.main'
 spec=importlib.util.spec_from_file_location(name,path);mod=importlib.util.module_from_spec(spec);sys.modules[name]=mod;spec.loader.exec_module(mod);return mod
async def run():
 with tempfile.TemporaryDirectory() as t,patch.object(StarTools,'get_data_dir',return_value=Path(t)):
  fav=load('audit_favourpro',R/'references/astrbot_plugin_favourpro/main.py');p=fav.FavourProPlugin(NS(),{})
  ev=NS(get_sender_id=lambda:'20002',unified_msg_origin='qq_snowluma:FriendMessage:20002')
  response=LLMResponse(role='assistant',completion_text='合成回复\n[Favour: -15, Attitude: 困惑, Relationship: 陌生人]')
  await p.on_llm_resp(ev,response)
  changed=p.manager.get_user_state('20002');assert changed['favour']==-15
  group=NS(get_sender_id=lambda:'20002',unified_msg_origin='qq_snowluma:GroupMessage:30003');assert p.manager.get_user_state('20002',p._get_session_id(group))==changed
  deb=load('audit_debounce',R/'references/astrbot_plugin_debounce/main.py',True);q=deb.DebouncePlugin(NS(),{'enabled':True,'usage_scope':'private','timeout_seconds':0})
  class Classifier:
   async def predict(self,text):return ((.1,.1) if text=='以后' else (.99,.99))
  q.classifier=Classifier()
  class Event:
   def __init__(self,text,id):self.message_str=text;self.message_obj=NS(session_id='synthetic-private',message_id=id,message_str=text);self.stopped=False
   def is_private_chat(self):return True
   def get_messages(self):return []
   def stop_event(self):self.stopped=True
  first=Event('以后','1');await q.on_llm_request(first,ProviderRequest(prompt=first.message_str));assert first.stopped
  second=Event('回复简短一些','2');req=ProviderRequest(prompt=second.message_str);await q.on_llm_request(second,req)
  assert req.prompt=='以后 回复简短一些' and second.message_obj.message_str=='回复简短一些';await q.terminate()
  result={'actual_pinned_upstream_hooks':True,'favourpro_default_cross_private_group_state':True,'favourpro_state_changes_before_delivery':True,'debounce_prompt_merged_but_event_source_remains_fragment':True,'classifier':'synthetic scores, no ONNX/JEV execution','temporary_storage_only':True,'candidate_plugins_installed_in_production':False,'network_calls':0,'actual_qq_messages':0}
  (R/'evidence/candidate-contracts.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False,indent=2))
asyncio.run(run())
