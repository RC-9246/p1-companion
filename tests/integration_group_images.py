"""Native SDK collection/preparation with synthetic pixels and isolated scopes."""
import asyncio,json,os,sys,tempfile
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import patch
R=Path(__file__).resolve().parents[1];sys.path[:0]=[str(R/'release'),str(R/'tests')]
from test_companion import init_db
from astrbot.core.message.components import At,Plain,Image,Reply
from astrbot.core.platform.message_type import MessageType
from astrbot.core.provider.entities import ProviderRequest
from astrbot.core.astr_main_agent import collect_initial_request,prepare_request_images,MainAgentBuildConfig

async def run(live=False):
 with tempfile.TemporaryDirectory() as tmp:
  d=Path(tmp);os.environ['P1_COMPANION_DATA']=tmp;init_db(d/'affect.db')
  from astrbot_plugin_affect.main import AffectPlugin,atomic_json
  from astrbot_plugin_affect.companion_store import CompanionStore
  from astrbot_plugin_affect.qq_runtime import QQController
  atomic_json(d/'groups.json',{'version':1,'groups':[{'bot':'10001','group':'30003'},{'bot':'10001','group':'30004'}]})
  async def pid(*a):return 'synthetic'
  async def provider(*a):return N(client=N(base_url=N(host='api.deepseek.com',scheme='https')))
  ctx=N(get_current_chat_provider_id=pid,provider_manager=N(get_provider_by_id=provider),get_config=lambda *a,**kw:{'provider':[]})
  p=AffectPlugin(ctx);p.store=CompanionStore(d/'affect.db');p.store.migrate();p.thinking.migrate()
  from PIL import Image as Pixels,ImageDraw
  file=d/'synthetic.png';pixels=Pixels.new('RGB',(320,180),'white');draw=ImageDraw.Draw(pixels)
  draw.rectangle((20,30,140,150),fill='red');draw.ellipse((200,40,300,140),fill='blue');pixels.save(file)
  corrupt=d/'corrupt.png';corrupt.write_bytes(b'not image pixels')
  oversized=d/'oversized.png'
  with oversized.open('wb') as f:f.truncate(8*1024*1024+1)
  resolved=[];tracked=[];api_calls=[]
  # A resolved copy mimics downloaded ownership without actual network access.
  async def resolve(image):
   resolved.append(image.url or image.file)
   if 'broken' in str(image.url or image.file):raise OSError('synthetic failure')
   if 'corrupt' in str(image.url or image.file):return str(corrupt)
   if 'oversized' in str(image.url or image.file):return str(oversized)
   return str(file)
  class Event:
   seq=0
   def __init__(self,parts,text='图片里的两个图形是什么颜色和形状？',group='30003'):
    Event.seq+=1;self.message_obj=N(message_str=text,message_id=str(Event.seq),message=parts);self.extra={};self.group=group;self.stopped=False;self.unified_msg_origin='qq_snowluma:GroupMessage:'+group
   @property
   def message_str(self):return self.message_obj.message_str
   def get_platform_id(self):return 'qq_snowluma'
   def get_platform_name(self):return 'aiocqhttp'
   def get_message_type(self):return MessageType.GROUP_MESSAGE
   def get_self_id(self):return '10001'
   def get_group_id(self):return self.group
   def get_sender_id(self):return '20002'
   def is_private_chat(self):return False
   def get_messages(self):return self.message_obj.message
   def get_extra(self,k,v=None):return self.extra.get(k,v)
   def set_extra(self,k,v):self.extra[k]=v
   def stop_event(self):self.stopped=True
   def track_temporary_local_file(self,path):tracked.append(path)
   def untrack_temporary_local_file(self,path):pass
   async def send(self,*a):raise AssertionError('no QQ send expected')
  raw={'group_id':30003,'message_type':'group','message_id':77,'sender':{'user_id':20002},'message':[{'type':'image','data':{'url':'https://gchat.qpic.cn/synthetic.png'}}]}
  async def api(action,**kw):api_calls.append((action,kw));return raw
  async def noop(*a):pass
  q=N(ready=True,api=api,qq_image_url=lambda url:QQController.qq_image_url(None,url),active=lambda:False,observe=noop,prompt=noop,group_open=lambda *a:False)
  async def prepare(e):
   assert await p.groups.route(e)
   req=e.get_extra('provider_request') or ProviderRequest(image_urls=['PRIVATE_SENTINEL'])
   if e.get_extra('provider_request') is not None:
    # Real native collector must not download the same image for a second time.
    req,_=await collect_initial_request(e,ctx,MainAgentBuildConfig(tool_call_timeout=10))
   req.contexts=[{'role':'user','content':'PRIVATE_SENTINEL'}];req.image_urls.append('PRIVATE_SENTINEL')
   await p.groups.prepare(e,req)
   assert 'PRIVATE_SENTINEL' not in str(req)
   before=len(resolved)
   await prepare_request_images(req,e,max_size=1280,prepared={},supports_image=True)
   assert len(resolved)==before
   await p.groups.finish(e)
   return req
  async def vision(req):
   import base64
   from openai import AsyncOpenAI
   cfg=json.loads(Path('/AstrBot/data/cmd_config.json').read_text(encoding='utf-8-sig'));model=next(x for x in cfg['provider'] if x['id']==cfg['agent_runner']['config']['model']['provider_id']);source=next(x for x in cfg['provider_sources'] if x['id']==model['provider_source_id']);keys=source['key']
   client=AsyncOpenAI(api_key=keys[0] if isinstance(keys,list) else keys,base_url=source['api_base'],timeout=45,max_retries=0)
   assert client.base_url.host=='api.deepseek.com' and client.base_url.scheme=='https'
   parts=[{'type':'text','text':req.prompt}]
   for ref in req.image_urls:
    data=Path(ref).read_bytes();parts.append({'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(data).decode()}})
   try:
    out=await client.chat.completions.create(model=model['model'],messages=[{'role':'system','content':req.system_prompt},{'role':'user','content':parts}],max_tokens=300,extra_body={'thinking':{'type':'disabled'}})
    reply=str(out.choices[0].message.content or '')
    checks={'red': '红' in reply,'blue':'蓝' in reply,'rectangle':any(s in reply for s in ('方','矩形')),'circle':'圆' in reply}
    assert all(checks.values()),checks
    return {'checks':checks,'reply_characters':len(reply),'passed':True}
   finally:await client.close()
  results=[]
  try:
   with patch.object(Image,'convert_to_file_path',resolve):
    direct=Event([At(qq='10001'),Image(file='https://gchat.qpic.cn/direct.png')]);req=await prepare(direct)
    assert len(req.image_urls)==1 and len(resolved)==1 and tracked
    assert 'current_images' in str(req.extra_user_content_parts)
    if live:results.append(await vision(req))
    # Same-group receipt is required even when an embedded quote image exists.
    p.qq=q
    quote=lambda:Event([At(qq='10001'),Reply(id='77',sender_id='20002',chain=[Image(file='https://gchat.qpic.cn/synthetic.png')])])
    req=await prepare(quote());assert len(req.image_urls)==1 and api_calls[-1][0]=='get_msg'
    if live:results.append(await vision(req))
    for change in ({'group_id':30004},{'message_type':'private'},{'sender':{'user_id':99999}},{'message_id':78}):
     original=raw.copy();raw.update(change);before=len(resolved);req=await prepare(quote())
     assert not req.image_urls and len(resolved)==before;raw.clear();raw.update(original)
    raw['message']=[{'type':'image','data':{'url':'https://example.com/forged.png'}}]
    req=await prepare(quote());assert not req.image_urls
    p.qq=None
    req=await prepare(Event([At(qq='10001'),Image(file='https://gchat.qpic.cn/broken.png')]))
    assert not req.image_urls
    for invalid in ('corrupt','oversized'):
     req=await prepare(Event([At(qq='10001'),Image(file='https://gchat.qpic.cn/'+invalid+'.png')]))
     assert not req.image_urls
    e=Event([At(qq='10001')]);assert await p.groups.route(e)
    # Reusing an old event's binding cannot import its pixels into another turn.
    e.set_extra('_p1_group_image_binding',direct.get_extra('_p1_group_image_binding'))
    r=ProviderRequest(image_urls=[str(file)]);await p.groups.prepare(e,r);assert not r.image_urls
    await p.groups.finish(e)
    many=Event([At(qq='10001')]+[Image(file='https://gchat.qpic.cn/a.png') for _ in range(6)])
    req=await prepare(many);assert many.get_extra('_p1_group_image_binding')['limited'] and len(req.image_urls)<=4
    other=Event([At(qq='10001'),Image(file='unused')],group='30005');assert not await p.groups.route(other)
  finally:
   for task in p.groups.expiry.values():task.cancel()
   if p.groups.expiry:await asyncio.gather(*p.groups.expiry.values(),return_exceptions=True)
  report={'native_request_collection_and_preparation':True,'current_pixels_preserved':True,'quoted_same_group_pixels_preserved':True,'cross_group_private_sender_and_message_mismatches_denied':True,'quoted_non_qq_hosts_denied':True,'no_duplicate_image_download':True,'temporary_files_tracked':True,'failed_corrupt_and_oversized_images_rejected':True,'history_and_cross_event_images_removed':True,'image_count_bound':4,'qq_messages':0,'production_database_modified':False,'synthetic_model_checks':results,'model_requests':len(results)}
  (R/'evidence'/('group-image-live.json' if live else 'group-image-native.json')).write_text(json.dumps(report,indent=2));print(json.dumps(report))
if __name__=='__main__':asyncio.run(run('--live' in sys.argv))
