"""Approved real model sees only two public-video frame samples, never account credentials."""
import asyncio,json,sys
from pathlib import Path
from openai import AsyncOpenAI
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'release'))
from astrbot_plugin_affect.leisure import VISION
async def main():
 cfg=json.loads(Path('/AstrBot/data/cmd_config.json').read_text(encoding='utf-8-sig'));pid=cfg['agent_runner']['config']['model']['provider_id']
 model=next(p for p in cfg['provider'] if p['id']==pid);src=next(s for s in cfg['provider_sources'] if s['id']==model['provider_source_id']);keys=src['key']
 ai=AsyncOpenAI(api_key=keys[0] if isinstance(keys,list) else keys,base_url=src['api_base'],max_retries=0,timeout=30)
 assert ai.base_url.host=='api.deepseek.com' and ai.base_url.scheme=='https'
 observation=json.loads((ROOT/'evidence/video-observation-private.json').read_text());frames=observation['frames'];assert len(frames)>=2 and observation['status']=='completed'
 content=[{'type':'text','text':json.dumps({'untrusted_title':observation['title'],'untrusted_description':observation.get('description'),'frame_times':[f['at_seconds'] for f in frames]},ensure_ascii=False)}]
 for f in frames[:4]:content.append({'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+f['jpeg']}})
 try:
  r=await ai.chat.completions.create(model=model['model'],messages=[{'role':'system','content':VISION},{'role':'user','content':content}],max_tokens=650,response_format={'type':'json_object'},extra_body={'thinking':{'type':'disabled'}})
  value=json.loads(r.choices[0].message.content);assert set(value)=={'visible_details','impression','limits'} and value['visible_details']
  print(json.dumps({'ok':True,'actual_model':model['model'],'actual_frames_sent':len(frames),'timestamps':[f['at_seconds'] for f in frames],'video_bvid':observation['bvid'],'audio_understood':False,'whole_video_understood':False,'observation':value,'account_credentials_sent':False},ensure_ascii=False,indent=2))
 finally:await ai.close()
asyncio.run(main())
