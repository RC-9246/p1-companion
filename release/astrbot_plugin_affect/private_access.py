"""Explicit private companion admission, separate from owner-only account authority."""
import asyncio,copy,hmac,json,os,re,secrets,time
from pathlib import Path
from .identity import identity_from_event,make_identity_key

def owner_identity(event,data,*,private_only=True):
    try:
        if event.get_platform_id()!='qq_snowluma' or (private_only and not event.is_private_chat()):return None
        key=identity_from_event(event);v=json.loads((Path(data)/'allowed_identities.json').read_text())
        entries=v.get('allowed_identities')
        if v.get('version')!=1 or not isinstance(entries,list) or not entries or not all(isinstance(x,str) and re.fullmatch(r'v1:[0-9a-f]{64}',x) for x in entries):return None
        return key if any(hmac.compare_digest(key,x) for x in entries) else None
    except (OSError,ValueError,TypeError,AttributeError):return None

def _atomic(path,value):
    path=Path(path);tmp=path.with_name('.'+path.name+'.'+secrets.token_hex(6)+'.tmp')
    try:
        with os.fdopen(os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w') as f:
            json.dump(value,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
        fd=os.open(path.parent,os.O_RDONLY)
        try:os.fsync(fd)
        finally:os.close(fd)
    finally:tmp.unlink(missing_ok=True)

def private_memory_keys(data,bot,peer):
    """Legacy memory compatibility is a stable identity mapping, never a live role."""
    root=Path(data);key=make_identity_key('qq_snowluma',bot,peer);path=root/'private_memory_legacy.json'
    value=json.loads((path if path.exists() else root/'allowed_identities.json').read_text())
    entries=value.get('identities') if path.exists() else value.get('allowed_identities')
    if value.get('version')!=1 or not isinstance(entries,list) or not all(isinstance(x,str) and re.fullmatch(r'v1:[0-9a-f]{64}',x) for x in entries):raise ValueError('legacy_memory_map_invalid')
    return (str(peer),'qq_snowluma:FriendMessage:'+str(peer)) if key in entries else (key,key)

class PrivateAccess:
    """Human QQ commands only. Two-file grants have private before/after recovery images."""
    def __init__(self,context,data):
        self.context=context;self.data=Path(data);self.lock=asyncio.Lock();self.ready=False
        self.config_path=self.data.parents[1]/'cmd_config.json';self.owner_path=self.data/'allowed_identities.json'
        self.pending=self.data/'access_pending.json';self.backups=self.data/'access_backups'
    def config(self):
        cfg=self.context.get_config()
        if not callable(getattr(cfg,'save_config_async',None)) or Path(getattr(cfg,'config_path','')).resolve()!=self.config_path.resolve():raise ValueError('native_config_save_unavailable')
        return cfg
    def supported(self):
        try:return self.ready and dict(self.config())==json.loads(self.config_path.read_text(encoding='utf-8-sig'))
        except (OSError,ValueError,TypeError,AttributeError):return False
    async def save(self,cfg,settings):
        # A cancelled command must await the local writer before attempting rollback.
        task=asyncio.create_task(cfg.save_config_async({'platform_settings':settings}))
        try:return await asyncio.shield(task)
        except asyncio.CancelledError:
            try:await task
            except Exception:pass
            raise
    def record_dir(self,record):
        if not isinstance(record,str) or not re.fullmatch(r'[0-9a-f]{24}',record):raise ValueError('invalid_access_recovery_record')
        p=self.backups/record
        if p.is_symlink() or not p.is_dir():raise ValueError('invalid_access_recovery_record')
        return p
    async def restore(self,record,cfg):
        p=self.record_dir(record)
        before=json.loads((p/'config-before.json').read_text());after=json.loads((p/'config-after.json').read_text())
        ob=json.loads((p/'owners-before.json').read_text());oa=json.loads((p/'owners-after.json').read_text())
        owners=json.loads(self.owner_path.read_text());disk=json.loads(self.config_path.read_text(encoding='utf-8-sig'))
        if owners not in (ob,oa) or disk not in (before,after):raise ValueError('access_recovery_conflict')
        # Withdraw an unfinished owner promotion before restoring chat admission.
        if owners!=ob:_atomic(self.owner_path,ob)
        cfg['platform_settings']=copy.deepcopy(before['platform_settings'])
        if disk!=before:
            if not await self.save(cfg,copy.deepcopy(before['platform_settings'])):raise ValueError('access_recovery_conflict')
        if json.loads(self.config_path.read_text(encoding='utf-8-sig'))!=before:raise ValueError('access_recovery_conflict')
        _atomic(p/'result.json',{'state':'rolled_back','at':time.time()});self.pending.unlink(missing_ok=True)
    async def _recover(self):
        if not self.pending.exists():return False
        record=json.loads(self.pending.read_text())['record'];p=self.record_dir(record)
        result=p/'result.json'
        if result.exists() and json.loads(result.read_text()).get('state')=='committed':self.pending.unlink();return False
        await self.restore(record,self.config());return True
    async def recover(self):
        async with self.lock:
            result=await self._recover();self.ensure_memory_map();self.ready=True;return result
    def ensure_memory_map(self):
        path=self.data/'private_memory_legacy.json'
        if path.exists():
            value=json.loads(path.read_text());entries=value.get('identities')
            if value.get('version')!=1 or not isinstance(entries,list) or not all(isinstance(x,str) and re.fullmatch(r'v1:[0-9a-f]{64}',x) for x in entries):raise ValueError('legacy_memory_map_invalid')
            return
        # If the mapping was removed, reconstruct the pre-command owners from the
        # earliest retained before-image, not from an expanded current role list.
        candidates=sorted(self.backups.glob('*/owners-before.json'),key=lambda p:p.stat().st_mtime) if self.backups.exists() else []
        owners=json.loads((candidates[0] if candidates else self.owner_path).read_text());entries=owners.get('allowed_identities')
        if owners.get('version')!=1 or not isinstance(entries,list) or not entries or not all(isinstance(x,str) and re.fullmatch(r'v1:[0-9a-f]{64}',x) for x in entries):raise ValueError('legacy_memory_map_invalid')
        _atomic(path,{'version':1,'identities':entries})
    async def grant(self,event,peer,*,owner=False):
        if type(owner) is not bool or not isinstance(peer,str) or not re.fullmatch(r'[1-9][0-9]{4,19}',peer) or peer==str(event.get_self_id()):raise ValueError('invalid_qq_number')
        actor=owner_identity(event,self.data)
        if not actor or event.get_extra('_p1_agency_background',False):raise ValueError('owner_private_command_required')
        async with self.lock:
            await self._recover()
            if not self.ready:raise ValueError('access_not_ready')
            self.ensure_memory_map()
            cfg=self.config();umo='qq_snowluma:FriendMessage:'+peer
            if self.context.get_config(umo) is not cfg:raise ValueError('separate_config_profile')
            before=json.loads(self.config_path.read_text(encoding='utf-8-sig'))
            if dict(cfg)!=before:raise ValueError('configuration_out_of_sync')
            settings=before.get('platform_settings',{})
            if settings.get('enable_id_white_list') is not True or not isinstance(settings.get('id_whitelist'),list):raise ValueError('explicit_whitelist_required')
            owners=json.loads(self.owner_path.read_text());key=make_identity_key('qq_snowluma',event.get_self_id(),peer)
            if owner_identity(event,self.data)!=actor:raise ValueError('owner_revoked')
            after=copy.deepcopy(before);newowners=copy.deepcopy(owners)
            new_white=umo not in settings['id_whitelist'];new_owner=owner and key not in owners['allowed_identities']
            if not new_white and not new_owner:return {'changed':False,'owner':key in owners['allowed_identities']}
            if new_white:after['platform_settings']['id_whitelist'].append(umo)
            if new_owner:newowners['allowed_identities'].append(key)
            self.backups.mkdir(mode=0o700,exist_ok=True);record=secrets.token_hex(12);point=self.backups/record;point.mkdir(mode=0o700)
            fd=os.open(self.backups,os.O_RDONLY)
            try:os.fsync(fd)
            finally:os.close(fd)
            for name,value in [('config-before',before),('config-after',after),('owners-before',owners),('owners-after',newowners)]:_atomic(point/(name+'.json'),value)
            _atomic(self.pending,{'record':record})
            try:
                if new_white and not await self.save(cfg,copy.deepcopy(after['platform_settings'])):raise ValueError('configuration_superseded')
                if json.loads(self.config_path.read_text(encoding='utf-8-sig'))!=after or dict(cfg)!=after:raise ValueError('configuration_superseded')
                if json.loads(self.owner_path.read_text())!=owners or owner_identity(event,self.data)!=actor:raise ValueError('owner_revoked_or_changed')
                # No awaits between owner publication and the durable commit marker.
                if new_owner:_atomic(self.owner_path,newowners)
                _atomic(point/'result.json',{'state':'committed','at':time.time(),'owner_added':new_owner,'whitelist_added':new_white})
                self.pending.unlink(missing_ok=True)
                return {'changed':True,'owner':key in newowners['allowed_identities'],'record':record}
            except BaseException:
                await self.restore(record,cfg)
                raise

def live_private_stage(stage,event,context):
    """Copy the native whitelist predicate's live inputs without mutating a shared stage."""
    if event.get_platform_id()!='qq_snowluma' or not event.is_private_chat():return stage
    values=context.get_config(event.unified_msg_origin)['platform_settings']
    if type(values.get('enable_id_white_list')) is not bool or not isinstance(values.get('id_whitelist'),list):raise ValueError('private_whitelist_config_invalid')
    current=copy.copy(stage);current.enable_whitelist_check=values['enable_id_white_list']
    current.whitelist=[str(x).strip() for x in values['id_whitelist'] if str(x).strip()]
    for attr in ('wl_ignore_admin_on_group','wl_ignore_admin_on_friend','id_whitelist_log'):
        field='wl_log' if attr=='id_whitelist_log' else attr
        setattr(current,field,values.get(attr,getattr(stage,field,False)))
    return current

def companion_identity(event,context=None,*,data=None,config=None):
    try:
        if event.get_platform_id()!='qq_snowluma' or not event.is_private_chat():return None
        identity=identity_from_event(event)
        root=Path(data or os.environ.get('P1_COMPANION_DATA','/AstrBot/data/plugin_data/affect'))
        # Owner authorization is intentionally NOT broadened by this function.
        try:
            v=json.loads((root/'allowed_identities.json').read_text())
            entries=v.get('allowed_identities')
            owner=(v.get('version')==1 and isinstance(entries,list) and bool(entries)
                   and all(isinstance(x,str) and re.fullmatch(r'v1:[0-9a-f]{64}',x) for x in entries)
                   and any(hmac.compare_digest(identity,x) for x in entries))
        except (OSError,ValueError,TypeError):owner=False
        if config is None and context is not None:
            try:config=context.get_config(event.unified_msg_origin)
            except (AttributeError,KeyError,TypeError):pass
        if config is None:
            try:config=json.loads((root.parents[1]/'cmd_config.json').read_text())
            except (OSError,ValueError):config={}
        # Use only framework configuration and adapter sender fields, never message text.
        entries=config.get('platform_settings',{}).get('id_whitelist',[])
        enabled=config.get('platform_settings',{}).get('enable_id_white_list',False)
        sender=str(event.get_sender_id());bot=str(event.get_self_id())
        explicit=(enabled is True and isinstance(entries,list) and sender.isdigit() and bot.isdigit()
                  and ('qq_snowluma:FriendMessage:'+sender) in entries)
        expanded=False
        if not owner and not explicit:
            try:
                from .qq_policy import load,reference
                from .qq_store import QQStore
                p=load(root/'qq_policy.json')
                if p['enabled'] and p['scope']=='all_existing':
                    import time
                    row=QQStore(root/'affect.db').target(reference('t','private',bot,sender))
                    expanded=bool(row and row['alive'] and 0<=time.time()-row['synced']<=600)
            except (OSError,ValueError,TypeError,__import__('sqlite3').Error):pass
        return identity if owner or explicit or expanded else None
    except (OSError,ValueError,TypeError,AttributeError,IndexError):return None
