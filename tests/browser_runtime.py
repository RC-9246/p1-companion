"""Run in p1-browser. Dedicated synthetic session; no real account or chat metadata."""
import json
import socket
from pathlib import Path
import urllib.request
import urllib.error

token=Path('/run/secrets/browser_token').read_text().strip()
base='http://127.0.0.1:8765'
def call(action,url='',link_id=0,subject='v1:'+'f'*64):
    req=urllib.request.Request(base+'/browse',data=json.dumps({'subject':subject,'action':action,'url':url,'link_id':link_id}).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
    try:
        return json.load(urllib.request.urlopen(req,timeout=29))
    except urllib.error.HTTPError as e:
        return json.load(e)

result={'health':json.load(urllib.request.urlopen(base+'/health')),'checks':[]}
try:
    with socket.create_connection(('1.1.1.1',443),timeout=2):
        direct=False
except OSError:
    direct=True
result['checks'].append({'case':'direct_internet_denied','passed':direct})
with socket.create_connection(('p1-browser-egress',8888),timeout=3) as conn:
    conn.sendall(b'CONNECT 169.254.169.254:443 HTTP/1.1\r\nHost: 169.254.169.254\r\n\r\n')
    denied=conn.recv(100).startswith(b'HTTP/1.1 403')
result['checks'].append({'case':'proxy_metadata_ip_denied','passed':denied})
for label,action,url in [('ip','open','https://127.0.0.1/'),('not_approved','open','https://example.com/'),('query','open','https://docs.python.org/?secret=x'),('write','submit','https://docs.python.org/')]:
    v=call(action,url)
    result['checks'].append({'case':label,'passed':not v.get('ok'),'code':v.get('error')})
v=call('open','https://docs.python.org/3/')
result['public_open']={k:v.get(k) for k in ('ok','error','title','url','mode')}
if v.get('ok'):
    result['public_open']['text_chars']=len(v['text'])
    result['public_open']['links']=len(v['links'])
    own=call('links')
    other=call('links',subject='v1:'+'e'*64)
    result['checks'].append({'case':'session_isolation','passed':own.get('ok') and not other.get('ok')})
    if own.get('links'):
        clicked=call('click',link_id=1)
        result['click']={k:clicked.get(k) for k in ('ok','error','title','url')}
print(json.dumps(result,ensure_ascii=False,indent=2))
