"""CONNECT only, exact host allowlist, resolve once then connect to the checked public IP."""
import select
import socket
import socketserver
import time
from policy import domains, hostname, public_addresses

class Proxy(socketserver.StreamRequestHandler):
    def handle(self):
        try:
            self.connection.settimeout(8)
            line=self.rfile.readline(4097).decode('ascii').strip()
            if len(line)>4096:
                return
            parts=line.split()
            if len(parts)!=3 or parts[0]!='CONNECT' or not parts[1].endswith(':443'):
                raise ValueError('connect_only')
            host=hostname(parts[1][:-4])
            if host not in domains('/policy/domains.json'):
                raise ValueError('domain_not_approved')
            total=0
            while True:
                h=self.rfile.readline(4097)
                total+=len(h)
                if total>16384:
                    raise ValueError('oversized_headers')
                if h in (b'\r\n',b'\n',b''):
                    break
            addresses=public_addresses(host)
            peer=None
            for family,kind,proto,address in addresses:
                candidate=socket.socket(family,kind,proto)
                candidate.settimeout(6)
                try:
                    candidate.connect(address)
                    peer=candidate
                    break
                except OSError:
                    candidate.close()
            if peer is None:
                raise OSError('connect_failed')
            with peer:
                self.wfile.write(b'HTTP/1.1 200 Connection Established\r\n\r\n')
                self.wfile.flush()
                deadline=time.monotonic()+30
                transferred=0
                while time.monotonic()<deadline and transferred<3_000_000:
                    ready,_,_=select.select([self.connection,peer],[],[],2)
                    for src in ready:
                        chunk=src.recv(32768)
                        if not chunk:
                            return
                        transferred+=len(chunk)
                        (peer if src is self.connection else self.connection).sendall(chunk)
        except Exception:
            try:
                self.wfile.write(b'HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
            except OSError:
                pass

class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address=True
    daemon_threads=True
    request_queue_size=8

if __name__=='__main__':
    Server(('0.0.0.0',8888),Proxy).serve_forever()
