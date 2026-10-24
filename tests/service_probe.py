"""Real broker probes, public page and internal health only. No QQ/model sends."""
import argparse,hashlib,json,statistics,time,urllib.request,urllib.error
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
D=Path('/AstrBot/data/plugin_data/affect')
def request(url,payload=None,token=None,timeout=30):
 data=json.dumps(payload).encode() if payload is not None else None
 headers={'Content-Type':'application/json'} if data is not None else {}
 if token:headers['Authorization']='Bearer '+token
 req=urllib.request.Request(url,data=data,headers=headers)
 try:
  with urllib.request.urlopen(req,timeout=timeout) as r:return r.status,json.load(r)
 except urllib.error.HTTPError as e:return e.code,json.load(e)
def run(n,out):
 token=(D/'browser_token').read_text().strip();subject='v1:'+hashlib.sha256(('five-round-public-'+str(n)+'-'+str(time.time_ns())).encode()).hexdigest()
 payload={'subject':subject,'action':'open','url':'https://docs.python.org/3/'};samples=[]
 started=time.monotonic()
 with ThreadPoolExecutor(1) as pool:
  opening=pool.submit(request,'http://p1-browser:8765/browse',payload,token)
  time.sleep(.2)
  for _ in range(5):
   pending=not opening.done();tick=time.perf_counter();status,body=request('http://p1-browser:8765/health',timeout=3)
   samples.append({'ms':round((time.perf_counter()-tick)*1000,3),'ok':status==200 and body.get('ok') is True,'page_pending':pending})
  status,page=opening.result(timeout=32)
 elapsed=time.monotonic()-started
 _,leisure=request('http://p1-leisure:8766/health',timeout=5);ns,n8n=request('http://p1-n8n:5678/healthz',timeout=5)
 bad_status,bad=request('http://p1-browser:8765/browse',dict(payload,url='https://127.0.0.1/'),token)
 auth_status,_=request('http://p1-browser:8765/browse',payload,'synthetic-invalid-token')
 report={'round':n,'real_brokers':True,'public_page_ok':status==200 and page.get('ok') is True,'public_page_status':status,'public_page_error':page.get('error'),'upstream_status':page.get('status'),'public_page_url':page.get('url'),'public_page_ms':round(elapsed*1000,1),'health_during_page':samples,'health_p50_ms':round(statistics.median(x['ms'] for x in samples),3),'health_max_ms':max(x['ms'] for x in samples),'private_address_denied':bad_status==400 and not bad.get('ok'),'invalid_token_denied':auth_status==403,'leisure_health_ok':leisure.get('ok') is True,'public_interaction_disabled':leisure.get('public_interactions') is False,'n8n_health_ok':ns==200,'actual_qq_messages':0,'model_requests':0,'private_content_sent':False}
 report['passed']=all([report['public_page_ok'],all(x['ok'] for x in samples),report['private_address_denied'],report['invalid_token_denied'],report['leisure_health_ok'],report['public_interaction_disabled'],report['n8n_health_ok']])
 Path(out).write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2));assert report['passed']
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--round',type=int,required=True);p.add_argument('--out',required=True);a=p.parse_args();run(a.round,a.out)
