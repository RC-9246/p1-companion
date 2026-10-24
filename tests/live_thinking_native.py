"""Existing approved DeepSeek account; real native provider, synthetic content only."""
import asyncio,json,sys,time
from pathlib import Path
from types import SimpleNamespace as N
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'release'))
from astrbot.core.provider.sources.openai_source import ProviderOpenAIOfficial
from astrbot.core.astr_main_agent import _select_provider
from astrbot_plugin_affect.thinking import effort_for,MAX_PROVIDER
async def run():
 cfg=json.loads(Path('/AstrBot/data/cmd_config.json').read_text(encoding='utf-8-sig'));providers={};captured=[]
 for model in cfg['provider']:
  if model['id'] not in (MAX_PROVIDER,'deepseek-source/deepseek-flash'):continue
  src=next(s for s in cfg['provider_sources'] if s['id']==model['provider_source_id'])
  config={**src,**model};config['timeout']=60
  if model['id']==MAX_PROVIDER:config['custom_extra_body']={**config['custom_extra_body'],'thinking':{'type':'enabled'}}
  p=ProviderOpenAIOfficial(config,cfg.get('provider_settings',{}));assert p.client.base_url.scheme=='https' and p.client.base_url.host=='api.deepseek.com'
  original=p.client.chat.completions.create
  async def record(*args,_original=original,_id=model['id'],**kw):
   out=await _original(*args,**kw);captured.append({'provider':_id,'thinking':kw.get('extra_body',{}).get('thinking'),'effort':kw.get('extra_body',{}).get('reasoning_effort',kw.get('reasoning_effort')),'usage':out.usage.model_dump() if out.usage else {},'finish_reason':out.choices[0].finish_reason});return out
  p.client.chat.completions.create=record;providers[model['id']]=p
 class Context:
  def get_provider_by_id(self,id):return providers.get(id)
  async def get_using_provider_async(self,**kw):return providers['deepseek-source/deepseek-flash']
 ctx=Context();results=[]
 cases=[('short_ack','晚安','high'),('mixed_emotion','合成场景：我拿到了很想要的机会，却又舍不得离开现在的同学。你怎么想？','max'),('group_view','合成群聊：大家在聊轻小说改编，有人喜欢克制表达，有人觉得太慢。伙伴，你怎么看？','max')]
 persona=(R/'release/astrbot_plugin_affect/persona.md').read_text()
 for id,text,want in cases:
  # A short acknowledgement is normally high; exclude the synthetic label from routing.
  effort=effort_for(text);assert effort==want
  event=N(unified_msg_origin='synthetic',get_extra=lambda k,d=None:MAX_PROVIDER if k=='selected_provider' and effort=='max' else d,set_extra=lambda *a:None)
  p=await _select_provider(event,ctx);assert p is providers[MAX_PROVIDER if effort=='max' else 'deepseek-source/deepseek-flash']
  start=time.monotonic();out=await p.text_chat(prompt=text,system_prompt=persona+'\n测试仅用合成场景，不进行外部操作。日常最多两句，保持具体与自然。',contexts=[])
  response=out.completion_text or '';assert response.strip()
  results.append({'case':id,'selected_provider':p.provider_config['id'],'requested_effort':effort,'native_selector_verified':True,'seconds':round(time.monotonic()-start,2),'reply':response,'reasoning_present':bool(out.reasoning_content),'request_and_usage':captured[-1]})
 report={'real_deepseek_native_provider':True,'synthetic_only':True,'actual_qq_messages':0,'production_database_modified':False,'calls':len(results),'cases':results}
 (R/'evidence/live-thinking-native.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False,indent=2))
 for p in providers.values():await p.client.close()
asyncio.run(run())
