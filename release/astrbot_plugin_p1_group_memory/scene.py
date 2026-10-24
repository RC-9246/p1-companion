"""Scoped adaptation of Context-Aware target normalization (MIT, see UPSTREAM)."""
import hashlib,time
from .store import clean,event_key,scope_key

def normalize_at_target(bot_id,target_id,target_name):
    # Adapted from muyouzhi6/astrbot_plugin_context_aware, MIT, copyright 2026 木有知.
    normalized=str(target_id or '').strip()
    if normalized==str(bot_id):return 'saki','伙伴'
    if normalized in ('all','0'):return 'all','全体'
    return normalized,str(target_name or normalized).strip() or normalized

def member_key(bot,group,sender):
    return hashlib.sha256((scope_key(bot,group)+'\0'+str(sender)).encode()).hexdigest()[:12]

def extract(event):
    from astrbot.core.message.components import At,AtAll,Reply,Plain,Image,Record,Video,File
    bot=str(event.get_self_id());group=str(event.get_group_id());scope=scope_key(bot,group);sender=str(event.get_sender_id())
    member=member_key(bot,group,sender);name=clean(event.get_sender_name() if hasattr(event,'get_sender_name') else '',24) or '群友'
    mentions=[];reply='';quoted=[];parts=[]
    for item in event.get_messages():
        if isinstance(item,AtAll):mentions.append({'member':'all','name':'全体'})
        elif isinstance(item,At):
            key,display=normalize_at_target(bot,str(item.qq),getattr(item,'name',''))
            if key not in ('saki','all'):key=member_key(bot,group,key)
            if display.isdigit():display='群友'
            row={'member':key,'name':clean(display,24)}
            if row not in mentions:mentions.append(row)
        elif isinstance(item,Reply):
            reply=event_key(scope,item.id)
            quoted.append({'from':'saki' if str(item.sender_id)==bot else member_key(bot,group,item.sender_id),'name':clean(getattr(item,'sender_nickname',''),24),'text':clean(getattr(item,'message_str',''),300)})
        elif isinstance(item,Plain):parts.append(item.text)
        elif isinstance(item,(Image,Record,Video,File)):parts.append('['+type(item).__name__+'，未解析内容]')
    text=''.join(parts).strip() or str(getattr(event.message_obj,'message_str','')).strip()
    at=getattr(event.message_obj,'timestamp',None)
    if not isinstance(at,(int,float)) or isinstance(at,bool):at=time.time()
    return {'scope':scope,'event':event_key(scope,event.message_obj.message_id),'speaker':member,'display':name,'text':clean(text),'at':at,'reply':reply,'mentions':mentions,'quoted':quoted,'role':'member'}
