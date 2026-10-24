"""Bilibili-only TLS proxy. No request content, account data or query logging."""
import select,socket,socketserver,threading,time
from policy import host,public_addresses
SLOTS=threading.BoundedSemaphore(64)
class Proxy(socketserver.StreamRequestHandler):
 def handle(self):
  if not SLOTS.acquire(blocking=False):return
  try:
   self.connection.settimeout(12);line=self.rfile.readline(4097).decode('ascii').strip();parts=line.split()
   if len(line)>4096 or len(parts)!=3 or parts[0]!='CONNECT' or not parts[1].endswith(':443'):raise ValueError('connect_only')
   target=host(parts[1][:-4]);total=0
   while True:
    h=self.rfile.readline(4097);total+=len(h)
    if total>16384:raise ValueError('oversized_headers')
    if h in (b'\r\n',b'\n',b''):break
   peer=None
   for family,kind,proto,address in sorted(public_addresses(target),key=lambda x:x[0]!=socket.AF_INET)[:6]:
    candidate=socket.socket(family,kind,proto);candidate.settimeout(3)
    try:candidate.connect(address);peer=candidate;break
    except OSError:candidate.close()
   if peer is None:raise OSError('connect_failed')
   with peer:
    self.wfile.write(b'HTTP/1.1 200 Connection Established\r\n\r\n');self.wfile.flush()
    deadline=time.monotonic()+90;transferred=0
    while time.monotonic()<deadline and transferred<60_000_000:
     ready,_,_=select.select([self.connection,peer],[],[],2)
     for src in ready:
      chunk=src.recv(32768)
      if not chunk:return
      transferred+=len(chunk);(peer if src is self.connection else self.connection).sendall(chunk)
  except Exception:
   try:self.wfile.write(b'HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
   except OSError:pass
  finally:SLOTS.release()
class Server(socketserver.ThreadingTCPServer):
 allow_reuse_address=True;daemon_threads=True;request_queue_size=16
if __name__=='__main__':Server(('0.0.0.0',8889),Proxy).serve_forever()
