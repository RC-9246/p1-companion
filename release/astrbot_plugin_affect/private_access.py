"""Explicit private companion admission, separate from owner-only account authority."""
import hmac,json,os,re
from pathlib import Path
from .identity import identity_from_event

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
