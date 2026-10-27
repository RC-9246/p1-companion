"""Unprivileged loopback viewer. No Docker socket, commands, logs or write routes."""
import argparse,json,os,threading,time
from http.server import BaseHTTPRequestHandler,HTTPServer
from socketserver import ThreadingMixIn
from pathlib import Path

ASSETS={'/':('index.html','text/html; charset=utf-8'),'/app.js':('app.js','text/javascript; charset=utf-8'),'/style.css':('style.css','text/css; charset=utf-8')}
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def setup(self):super().setup();self.connection.settimeout(4)
    def reply(self,status,body,mime='application/json; charset=utf-8',head=False):
        self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('X-Frame-Options','DENY');self.send_header('Referrer-Policy','no-referrer');self.send_header('Cross-Origin-Resource-Policy','same-origin');self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; object-src 'none'");self.end_headers()
        if not head:self.wfile.write(body)
    def get(self,head=False):
        host=self.headers.get('Host','');allowed={'127.0.0.1','localhost',f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}
        if host not in allowed:return self.reply(403,b'{"error":"host_denied"}',head=head)
        path=self.path.split('?',1)[0]
        if path in ASSETS:
            name,mime=ASSETS[path];return self.reply(200,(self.server.assets/name).read_bytes(),mime,head)
        if path not in ('/api/status','/health'):return self.reply(404,b'{"error":"not_found"}',head=head)
        try:
            with self.server.snapshot.open('rb') as f:raw=f.read(524289)
            if len(raw)>524288:raise ValueError('snapshot_size')
            data=json.loads(raw);age=max(0,time.time()-float(data['at']));data['stale']=age>15;data['age_seconds']=round(age,1)
            data['viewer_rss_bytes']=int(Path('/proc/self/statm').read_text().split()[1])*os.sysconf('SC_PAGE_SIZE') if Path('/proc/self/statm').exists() else None
            if path=='/health':data={'service':'p1-resource-panel','ready':not data['stale'],'sample_age_seconds':data['age_seconds']}
            return self.reply(503 if data.get('ready') is False else 200,json.dumps(data,ensure_ascii=False,allow_nan=False).encode(),head=head)
        except (OSError,ValueError,KeyError,TypeError):return self.reply(503,b'{"error":"waiting_for_collector"}',head=head)
    def do_GET(self):self.get()
    def do_HEAD(self):self.get(True)
    def do_POST(self):self.reply(405,b'{"error":"read_only"}')
    do_PUT=do_POST;do_DELETE=do_POST;do_PATCH=do_POST

class Server(ThreadingMixIn,HTTPServer):
    daemon_threads=True;allow_reuse_address=True
    def __init__(self,address,*,snapshot,assets):
        self.snapshot=Path(snapshot);self.assets=Path(assets);self.slots=threading.BoundedSemaphore(8);super().__init__(address,Handler)
    def process_request(self,request,address):
        if not self.slots.acquire(False):self.shutdown_request(request);return
        try:super().process_request(request,address)
        except BaseException:self.slots.release();raise
    def process_request_thread(self,request,address):
        try:super().process_request_thread(request,address)
        finally:self.slots.release()
def main():
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=6190);p.add_argument('--snapshot',default='/run/p1-monitor/snapshot.json');p.add_argument('--assets',type=Path,default=Path(__file__).parent/'dist');a=p.parse_args()
    Server(('127.0.0.1',a.port),snapshot=a.snapshot,assets=a.assets).serve_forever(poll_interval=.5)
if __name__=='__main__':main()
