"""Conservative credential guard; never prints matched content."""
import re
import hashlib
import hmac
import json
from pathlib import Path

_CREDENTIAL=re.compile(r'(?i)(?:sk-[a-z0-9_-]{12,}|gh[pousr]_[a-z0-9]{12,}|AKIA[A-Z0-9]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|(?:密码|口令|password|token|api[_ -]?key|secret)\s*[:：=是为]?\s*[^\s,，。;；]{1,})')

def memory_safe(content):
    return isinstance(content,str) and 0<len(content.strip())<=1200 and not _CREDENTIAL.search(content)

def scrub_credentials(content):
    return _CREDENTIAL.sub('[已隐藏凭据]',content)

def permitted_event(event,allowlist_path=None,context=None):
    """Each explicitly whitelisted private chat receives its own identity scope."""
    if allowlist_path is None:
        try:
            try:from ..astrbot_plugin_affect.private_access import companion_identity
            except ImportError:from astrbot_plugin_affect.private_access import companion_identity
            return bool(companion_identity(event,context))
        except (ImportError,AttributeError,ValueError,TypeError):return False
    try:
        if event.get_platform_id()!='qq_snowluma' or not event.is_private_chat():return False
        fields=[str(event.get_platform_id()).strip(),str(event.get_self_id()).strip(),str(event.get_sender_id()).strip()]
        if not all(fields):return False
        key='v1:'+hashlib.sha256(json.dumps(fields,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
        v=json.loads(Path(allowlist_path).read_text());entries=v.get('allowed_identities')
        return (v.get('version')==1 and isinstance(entries,list) and bool(entries)
                and all(isinstance(x,str) and re.fullmatch('v1:[0-9a-f]{64}',x) for x in entries)
                and any(hmac.compare_digest(key,x) for x in entries))
    except (OSError,ValueError,TypeError,AttributeError):return False
