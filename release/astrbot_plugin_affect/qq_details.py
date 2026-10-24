"""Small native QQ actions bound to observed IDs and verified ownership."""
import asyncio,base64,json,re,time
from .qq_policy import record_sensitive
async def detail(plugin,event,action='capabilities',ref='',value=''):
 qq=plugin.qq;actor=qq.actor(event) if qq else None
 if not actor:return {'ok':False,'error':'forbidden'}
 if action=='capabilities':return {'ok':True,'actions':['react','recall_own','share_artifact','share_file'],'reaction_ids':['14','66','76','124'],'unknown_receipts_not_retried':True,'note':'Native extension support is tested per action; unsupported actions return failure.'}
 row=qq.resolve(actor,value if action in ('share_artifact','share_file') and value else '')
 if action in ('react','recall_own'):
  record=await asyncio.to_thread(qq.store.message,ref)
  if not record or record['target']!=actor['ref'] or time.time()-record['at']>86400:raise ValueError('current_message_required')
  native=await qq.native_message(record)
  if action=='recall_own':
   if str((native.get('sender') or {}).get('user_id',''))!=row['bot'] or time.time()-record['at']>110:raise ValueError('only_recent_own_message')
   method='delete_msg';params={'message_id':int(record['raw_id'])}
  else:
   if value not in ('14','66','76','124'):raise ValueError('reaction_not_allowed')
   method='set_msg_emoji_like';params={'message_id':int(record['raw_id']),'emoji_id':value,'set':True}
  async def verify(_):
   # A zero/None extension result is not treated as authoritative delivery.
   if action=='recall_own':
    try:again=await qq.native_message(record)
    except Exception:return False
    return bool(again.get('is_deleted') or again.get('recalled'))
   emojis=await qq.api('get_msg_emoji_likes',message_id=int(record['raw_id']))
   return isinstance(emojis,list) and any(isinstance(x,dict) and str(x.get('emoji_id',''))==value and any(str(u.get('user_id',''))==row['bot'] for u in x.get('users',[])) for x in emojis)
  return await qq.perform(row,'detail:'+str(event.message_obj.message_id),action,method,params,guard=lambda:qq.action_allowed(event),verify=verify)
 if action in ('share_artifact','share_file'):
  agency=plugin.agency;scope=agency.scope(event);cfg=await asyncio.to_thread(agency.store.ensure,scope)
  if cfg['level']<3:raise ValueError('level_3_required')
  from contextlib import closing
  with closing(agency.store.db()) as c:r=c.execute('SELECT * FROM artifact WHERE id=? AND scope=? AND (expires=0 OR expires>?)',(ref,scope,time.time())).fetchone()
  if not r:raise ValueError('artifact_not_found')
  p=agency.store.directory(scope)/(r['id']+'.'+r['format'])
  if p.is_symlink() or p.resolve().parent!=agency.store.directory(scope).resolve():raise ValueError('invalid_artifact_path')
  body=p.read_text()
  if record_sensitive(r['title']+'\n'+body):raise ValueError('private_artifact_not_shareable')
  if row['ref']!=actor['ref']:
   if not actor['owner'] or qq.policy()['cross_forward']!='allow':raise ValueError('cross_scope_not_authorized')
   with closing(agency.store.db()) as c:
    for id in json.loads(r['sources']):
     doc=c.execute('SELECT private,expires FROM document WHERE scope=? AND id=?',(scope,id)).fetchone()
     if not doc or doc['private'] or doc['expires']<=time.time():raise ValueError('private_document_source')
  if action=='share_file':
   raw=body.encode('utf-8')
   if len(raw)>256000:raise ValueError('artifact_file_too_large')
   name=re.sub(r'[\\/:*?"<>|\r\n]','_',r['title'])[:70]+'.'+r['format']
   async def verify_file(receipt):
    return isinstance(receipt,dict) and isinstance(receipt.get('file_id'),(str,int)) and bool(str(receipt['file_id']).strip())
   return await qq.perform(row,'artifact-file:'+r['id'],'file','upload_private_file' if row['kind']=='private' else 'upload_group_file',{'user_id' if row['kind']=='private' else 'group_id':int(row['peer']),'file':'base64://'+base64.b64encode(raw).decode(),'name':name},guard=lambda:qq.action_allowed(event),verify=verify_file)
  # Source cards are native text; generated files use the separate verified upload path.
  text=qq.plain(r['title']+'\n'+body[:700]);return await qq.perform(row,'artifact:'+r['id'],'message','send_private_msg' if row['kind']=='private' else 'send_group_msg',{'user_id' if row['kind']=='private' else 'group_id':int(row['peer']),'message':[{'type':'text','data':{'text':text}}]},text=text,guard=lambda:qq.action_allowed(event))
 return {'ok':False,'error':'unsupported_action'}
