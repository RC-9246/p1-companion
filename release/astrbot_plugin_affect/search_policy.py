"""Only short, nonpersonal topic queries to a fixed public search endpoint."""
import ipaddress
import re
from urllib.parse import urlsplit

def query(value):
    if not isinstance(value,str) or not 2<=len(value.strip())<=100:
        raise ValueError('invalid_query')
    if re.search(r'(?i)(password|token|secret|sk-|密码|口令|密钥|身份证|住址|私人|手机号|QQ号|我的邮箱|我的日程|我的聊天)|[/:@]|\d{5,}',value):
        raise ValueError('private_query_rejected')
    return value.strip()

def public_url(value):
    p=urlsplit(value)
    if p.scheme!='https' or not p.hostname or p.username or p.password or p.port not in (None,443):
        return False
    host=p.hostname.lower()
    if '.' not in host or host.endswith(('.local','.internal','.localhost','.test','.invalid','.arpa')):
        return False
    try:ipaddress.ip_address(host);return False
    except ValueError:pass
    return True
