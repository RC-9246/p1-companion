"""Fixed first-party account operations. Only verified private folders may change."""
import json,os,re,secrets,time
from pathlib import Path
from policy import bvid
API='https://api.bilibili.com'
DEFAULT_FOLDER='伙伴的私密收藏'

async def get(browser,path,params=None):
 allowed={'/x/web-interface/view','/x/v3/fav/folder/info','/x/v3/fav/folder/created/list-all','/x/v2/history/toview'}
 if path not in allowed:raise ValueError('account_endpoint_not_allowed')
 browser.phase='private_get_'+path.rsplit('/',1)[-1]
 r=await browser.ctx.request.get(API+path,params=params or {},timeout=20000,max_redirects=0)
 if r.status in (403,412,429):raise ValueError('human_verification_required')
 raw=await r.body()
 if len(raw)>500000:raise ValueError('account_response_too_large')
 v=json.loads(raw)
 if type(v.get('code')) is not int or v['code']!=0:raise ValueError('account_api_rejected')
 return v.get('data') or {}

def folder_title(value):
 if not isinstance(value,str) or not 1<=len(value)<=20 or re.search(r'[\r\n/\\\x00-\x1f]',value):raise ValueError('invalid_folder_title')
 return value

def private_info(data,uid):
 attr=data.get('attr');owner=str(data.get('upper',{}).get('mid',''))
 return type(attr) is int and bool(attr&1) and owner==uid

async def post(browser,path,data,grant=None):
 if path not in ('/x/v2/history/toview/add','/x/v2/history/toview/del','/x/v3/fav/folder/add','/x/v3/fav/resource/deal'):
  raise ValueError('private_action_not_allowed')
 cookies=await browser.ctx.cookies([API+'/'])
 csrf=next((x['value'] for x in cookies if x['name']=='bili_jct'),None)
 if not csrf:raise ValueError('csrf_cookie_missing')
 body={**data,'csrf':csrf}
 browser.phase='private_post_'+path.rsplit('/',1)[-1]
 browser.private_grant={**grant,'expires':time.monotonic()+20} if grant else None
 try:
  result=await browser.page.evaluate('''async ({url,data})=>{
   const r=await fetch(url,{method:'POST',credentials:'include',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:new URLSearchParams(data)});
   if(!r.ok) return {code:-1}; return await r.json();
  }''',{'url':API+path,'data':body})
 finally:browser.private_grant=None
 if not isinstance(result,dict) or type(result.get('code')) is not int or result['code']!=0:raise ValueError('private_action_rejected')
 return result.get('data') or {}

async def folder(browser,title,root):
 title=folder_title(title);path=Path(root)/'private_folders.json'
 mapping=json.loads(path.read_text()) if path.exists() else {}
 row=mapping.get(title)
 if row and row.get('owner')==browser.uid:
  info=await get(browser,'/x/v3/fav/folder/info',{'media_id':row['id']})
  if private_info(info,browser.uid):return row['id']
  raise ValueError('folder_no_longer_private')
 if len(mapping)>=12:raise ValueError('managed_folder_limit')
 pending_path=Path(root)/'pending_folders.json'
 pending=json.loads(pending_path.read_text()) if pending_path.exists() else []
 if title in pending:
  listing=await get(browser,'/x/v3/fav/folder/created/list-all',{'up_mid':browser.uid})
  candidates=[x for x in listing.get('list',[]) if x.get('title')==title]
  valid=[]
  for row in candidates:
   info=await get(browser,'/x/v3/fav/folder/info',{'media_id':str(row['id'])})
   if private_info(info,browser.uid):valid.append(str(row['id']))
  if len(valid)!=1:raise ValueError('folder_creation_uncertain_do_not_retry')
  created={'id':valid[0]}
 else:
  # A lost create response must never create a second folder on retry.
  pending.append(title);write_private(pending_path,pending)
  created=await post(browser,'/x/v3/fav/folder/add',{'title':title,'privacy':'1'},{'kind':'folder','title':title})
 id=str(created.get('id',''))
 if not id.isdigit():raise ValueError('folder_receipt_missing')
 info=await get(browser,'/x/v3/fav/folder/info',{'media_id':id})
 if not private_info(info,browser.uid):raise ValueError('folder_privacy_not_verified')
 mapping[title]={'id':id,'owner':browser.uid,'verified_private':True}
 write_private(path,mapping);write_private(pending_path,[x for x in pending if x!=title]);return id

def write_private(path,value):
 tmp=path.with_name('private-'+secrets.token_hex(4)+'.tmp');fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
 with os.fdopen(fd,'w') as f:json.dump(value,f,ensure_ascii=False);f.flush();os.fsync(f.fileno())
 os.replace(tmp,path)

async def change(browser,root,action,video_id,title=DEFAULT_FOLDER):
 bvid(video_id)
 if action not in ('watchlater_add','watchlater_remove','favorite_add','favorite_remove'):raise ValueError('private_action_not_allowed')
 async with browser.lock:
  await browser.ensure()
  if not await browser.auth_status():raise ValueError('login_required')
  video=await get(browser,'/x/web-interface/view',{'bvid':video_id})
  aid=str(video.get('aid',''))
  if video.get('bvid')!=video_id or not aid.isdigit():raise ValueError('video_not_verified')
  # The official page supplies Origin/Referer and the CSRF-protected browser request.
  await browser.navigate('https://www.bilibili.com/video/'+video_id+'/')
  output={'ok':True,'action':action,'bvid':video_id,'title':str(video.get('title',''))[:200],
   'url':'https://www.bilibili.com/video/'+video_id+'/','public_interaction':False}
  if action.startswith('watchlater_'):
   path='/x/v2/history/toview/'+('add' if action.endswith('_add') else 'del')
   await post(browser,path,{'aid':aid},{'kind':'watchlater','aid':aid,'remove':action.endswith('_remove')})
   listing=await get(browser,'/x/v2/history/toview')
   present=any(str(x.get('aid'))==aid for x in listing.get('list',[]))
   output['membership_verified']=present if action.endswith('_add') else not present
  else:
   id=await folder(browser,title,root)
   remove=action.endswith('_remove')
   grant={'kind':'favorite','folder':id,'rid':aid,'remove':remove}
   await post(browser,'/x/v3/fav/resource/deal',{'rid':aid,'type':'2','add_media_ids':'' if remove else id,'del_media_ids':id if remove else ''},grant)
   listing=await get(browser,'/x/v3/fav/folder/created/list-all',{'up_mid':browser.uid,'rid':aid,'type':'2'})
   match=next((x for x in listing.get('list',[]) if str(x.get('id'))==id),None)
   output['membership_verified']=bool(match is not None and bool(match.get('fav_state'))!=remove)
   output['private_folder']=title;output['folder_privacy_verified']=True
  if not output.get('membership_verified'):output.update(ok=False,error='membership_not_verified')
  return output
