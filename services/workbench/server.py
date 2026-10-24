"""Private internal, token protected, single-worker parser/experiment service."""
import hmac,json,os,subprocess,threading,tempfile
from http.server import BaseHTTPRequestHandler,HTTPServer
from socketserver import ThreadingMixIn
from pathlib import Path
from decoder import SUPPORTED
TOKEN=Path('/run/secrets/workbench_token').read_text().strip();SLOT=threading.Lock()
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def setup(self):super().setup();self.connection.settimeout(8)
 def reply(self,n,v):
  raw=json.dumps(v,ensure_ascii=False).encode();self.send_response(n);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
 def do_GET(self):self.reply(200,{'ok':True,'formats':SUPPORTED,'network':'internal_only','max_file_bytes':16777216,'code_production_access':False}) if self.path=='/health' else self.reply(404,{})
 def do_POST(self):
  if not hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+TOKEN):return self.reply(403,{'ok':False})
  if self.path not in ('/decode','/experiment'):return self.reply(404,{})
  if not SLOT.acquire(blocking=False):return self.reply(429,{'ok':False,'error':'worker_busy'})
  try:
   size=int(self.headers.get('Content-Length','0'))
   if not 0<size<=24*1024*1024:raise ValueError('request_limit')
   raw=self.rfile.read(size);data=json.loads(raw)
   if self.path=='/decode':
    p=subprocess.run(['python','-I','/opt/workbench/runner.py'],input=raw,capture_output=True,timeout=50)
    answer=json.loads(p.stdout) if p.returncode==0 else {'ok':False,'error':'worker_resource_limit'}
   else:
    from experiment import check
    code=data['code'];check(code)
    # The child has no secrets in env or mounted production files; AST is an additional fence.
    command='import resource;resource.setrlimit(resource.RLIMIT_CPU,(4,5));resource.setrlimit(resource.RLIMIT_AS,(134217728,134217728));resource.setrlimit(resource.RLIMIT_FSIZE,(8192,8192));'+code
    with tempfile.TemporaryFile() as output,tempfile.TemporaryFile() as errors:
     p=subprocess.run(['python','-I','-c',command],stdout=output,stderr=errors,timeout=6,cwd='/tmp',env={'PATH':'/usr/local/bin:/usr/bin','PYTHONIOENCODING':'utf-8'})
     output.seek(0);errors.seek(0)
     answer={'ok':p.returncode==0,'output':output.read(8192).decode('utf-8',errors='replace'),'error':errors.read(1000).decode('utf-8',errors='replace'),'production_modified':False}
   self.reply(200,answer)
  except subprocess.TimeoutExpired:self.reply(408,{'ok':False,'error':'worker_timeout'})
  except Exception:self.reply(400,{'ok':False,'error':'invalid_worker_request'})
  finally:SLOT.release()
class Server(ThreadingMixIn,HTTPServer):
 daemon_threads=True
 def __init__(self,*args):self.slots=threading.BoundedSemaphore(8);super().__init__(*args)
 def process_request(self,request,address):
  if not self.slots.acquire(False):self.shutdown_request(request);return
  try:super().process_request(request,address)
  except BaseException:self.slots.release();raise
 def process_request_thread(self,request,address):
  try:super().process_request_thread(request,address)
  finally:self.slots.release()
if __name__=='__main__':Server(('0.0.0.0',8767),Handler).serve_forever()
