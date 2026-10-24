"""Only Bilibili-owned HTTPS destinations; public-address pinning is done by the proxy."""
import ipaddress,re,socket
from urllib.parse import urlsplit
ROOTS=('bilibili.com','hdslb.com','bilivideo.com')
SAFE_POST={
 ('api.bilibili.com','/x/click-interface/web/heartbeat'),
 ('api.bilibili.com','/x/click-interface/click/web/h5'),
}
# Private collection operations are unlocked only for one UI transaction at a time.
PRIVATE_POST={'/x/v3/fav/folder/add','/x/v3/fav/resource/deal','/x/v2/history/toview/add','/x/v2/history/toview/del'}

def private_request(url,method,fields,grant,now):
 if not grant or now>=grant.get('expires',0) or method!='POST' or destination(url)!='api.bilibili.com':return False
 path=urlsplit(url).path
 if path not in PRIVATE_POST:return False
 if path=='/x/v3/fav/folder/add':
  return grant['kind']=='folder' and fields.get('privacy')==['1'] and fields.get('title')==[grant['title']]
 if path.startswith('/x/v2/history/toview/'):
  return grant['kind']=='watchlater' and path.endswith('/del' if grant['remove'] else '/add') and fields.get('aid')==[grant['aid']]
 return grant['kind']=='favorite' and fields.get('rid')==[grant['rid']] and fields.get('type')==['2'] and (
  (not grant['remove'] and fields.get('add_media_ids')==[grant['folder']] and not fields.get('del_media_ids',[''])[0]) or
  (grant['remove'] and fields.get('del_media_ids')==[grant['folder']] and not fields.get('add_media_ids',[''])[0]))

def host(value):
 if not isinstance(value,str) or not re.fullmatch(r'[a-z0-9.-]{1,200}',value) or '..' in value or value.endswith('.'):
  raise ValueError('invalid_host')
 try:ipaddress.ip_address(value)
 except ValueError:pass
 else:raise ValueError('ip_not_allowed')
 if not any(value==d or value.endswith('.'+d) for d in ROOTS):raise ValueError('domain_not_allowed')
 return value

def destination(url):
 if not isinstance(url,str) or len(url)>8192:raise ValueError('invalid_url')
 p=urlsplit(url)
 if p.scheme!='https' or p.port not in (None,443) or p.username or p.password:raise ValueError('https_only')
 return host((p.hostname or '').lower())

def read_request(url,method):
 h=destination(url);p=urlsplit(url).path
 if any(x in p.lower() for x in ('/logout','/exit','/report','/share/add','/reply/add','/dm/post','/coin/add','/archive/like','/relation/modify','/dynamic/create','/message/send','/pay/')):return False
 return method in ('GET','HEAD') or (method=='POST' and (h,p) in SAFE_POST)

def public_addresses(value):
 host(value);rows=socket.getaddrinfo(value,443,type=socket.SOCK_STREAM)
 if not rows:raise ValueError('dns_empty')
 for row in rows:
  if not ipaddress.ip_address(row[4][0]).is_global:raise ValueError('nonpublic_address')
 return [(f,k,p,a) for f,k,p,_,a in rows]

def bvid(value):
 if not isinstance(value,str) or not re.fullmatch(r'BV[0-9A-Za-z]{10}',value):raise ValueError('invalid_video_id')
 return value

def query(value):
 if not isinstance(value,str) or not 1<=len(value.strip())<=60 or re.search(r'(?i)https?[:/]|[\r\n/@]|(?:token|password|cookie|sessdata|密码|密钥)\s*[:=：]|\d{7,}',value):raise ValueError('public_topic_required')
 return value.strip()
