"""Local, read-only host/Docker metrics. Publishes a closed JSON schema in tmpfs."""
import argparse,collections,concurrent.futures,http.client,json,math,os,platform,re,resource,secrets,shutil,socket,time
from pathlib import Path

LABELS={'astrbot':('AstrBot','对话主控'),'snowluma':('SnowLuma','QQ 接入'),'p1-browser':('公开浏览器','公开网页读取'),'p1-browser-egress':('公开网络代理','浏览器出口'),'p1-leisure':('B站浏览器','空闲视频活动'),'p1-leisure-egress':('视频网络代理','视频出口'),'p1-workbench':('工作台','文件解析与实验'),'p1-n8n':('n8n','自动化工作流')}
MODULES={'group_memory_ready':'群记忆','group_affect_ready':'群情感','learning_ready':'表达学习','qq_plain_ready':'QQ 表达','agency_ready':'自主空间','qq_actions_ready':'QQ 工具','private_access_commands_ready':'权限命令'}

def integer(v,default=0):return v if type(v) is int and v>=0 else default
def safe_json(path,limit=262144):
    try:
        with Path(path).open('rb') as f:b=f.read(limit+1)
        value=json.loads(b) if len(b)<=limit else {}
        return value if isinstance(value,dict) else {}
    except (OSError,ValueError):return {}
def atomic(path,data):
    path=Path(path);path.parent.mkdir(mode=0o755,parents=True,exist_ok=True);tmp=path.with_name('.snapshot-'+secrets.token_hex(5))
    try:
        with tmp.open('x') as f:json.dump(data,f,ensure_ascii=False,allow_nan=False,separators=(',',':'));f.flush();os.fchmod(f.fileno(),0o644)
        os.replace(tmp,path)
    finally:tmp.unlink(missing_ok=True)
def cpu_percent(before,after):
    if before is None or len(before)<8 or len(after)<8:return None
    d=[b-a for a,b in zip(before[:8],after[:8])];total=sum(d)
    return round(max(0,min(100,(total-d[3]-d[4])/total*100)),2) if total>0 and all(x>=0 for x in d) else None
def container_values(current,previous,host_memory):
    cpu=current.get('cpu_stats') or {};old=(previous or {}).get('cpu_stats') or {}
    used=integer((cpu.get('cpu_usage') or {}).get('total_usage'));oldused=integer((old.get('cpu_usage') or {}).get('total_usage'))
    system=integer(cpu.get('system_cpu_usage'));oldsystem=integer(old.get('system_cpu_usage'))
    pct=round(max(0,min(100,(used-oldused)/(system-oldsystem)*100)),2) if previous and used>=oldused and system>oldsystem else None
    mem=current.get('memory_stats') or {};stats=mem.get('stats') or {};raw=integer(mem.get('usage'))
    inactive=integer(stats.get('inactive_file'),integer(stats.get('total_inactive_file')))
    limit=integer(mem.get('limit'));working=max(0,raw-inactive)
    return {'cpu_percent':pct,'memory_bytes':working,'memory_limit_bytes':limit if 0<limit<host_memory else None,'pids':integer((current.get('pids_stats') or {}).get('current'))}

class UnixHTTP(http.client.HTTPConnection):
    def __init__(self,path,timeout=.8):super().__init__('localhost',timeout=timeout);self.path=str(path)
    def connect(self):
        self.sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);self.sock.settimeout(self.timeout);self.sock.connect(self.path)

class Docker:
    def __init__(self,path='/var/run/docker.sock'):self.path=path;self.version=None;self.previous={};self.pool=concurrent.futures.ThreadPoolExecutor(max_workers=3,thread_name_prefix='metrics')
    def get(self,path):
        if path!='/version' and not re.fullmatch(r'/v1\.[0-9]{1,3}/containers/(?:json\?all=1|[a-f0-9]{12,64}/stats\?stream=false&one-shot=true)',path):raise ValueError('docker_read_path_denied')
        c=UnixHTTP(self.path)
        try:
            c.request('GET',path,headers={'Connection':'close'});r=c.getresponse();b=r.read(2097153)
            if r.status!=200 or len(b)>2097152:raise ValueError('docker_read_unavailable')
            return json.loads(b)
        finally:c.close()
    def sample(self,total):
        if self.version is None:
            v=self.get('/version').get('ApiVersion','')
            if not isinstance(v,str) or not re.fullmatch(r'1\.[0-9]{1,3}',v):raise ValueError('docker_api_version_invalid')
            self.version=v
        base='/v'+self.version+'/containers/';rows=self.get(base+'json?all=1')
        if not isinstance(rows,list):raise ValueError('docker_list_invalid')
        summaries=[]
        for item in rows[:64]:
            if not isinstance(item,dict) or not re.fullmatch(r'[a-f0-9]{12,64}',str(item.get('Id',''))):continue
            name=str((item.get('Names') or ['container'])[0]).lstrip('/')[:80]
            name=re.sub(r'[^a-zA-Z0-9_.-]','_',name);state=item.get('State','unknown')
            state=state if state in ('running','paused','restarting','exited','created','dead','removing') else 'unknown'
            status=str(item.get('Status',''))
            health='unhealthy' if '(unhealthy)' in status else 'starting' if '(health: starting)' in status else 'healthy' if '(healthy)' in status else None
            label,purpose=LABELS.get(name,(name,'其他容器'))
            summaries.append({'key':item['Id'],'name':name,'label':label,'purpose':purpose,'state':state,'health':health})
        futures={r['key']:self.pool.submit(self.get,base+r['key']+'/stats?stream=false&one-shot=true') for r in summaries if r['state']=='running'}
        result=[];new={}
        for row in summaries:
            key=row.pop('key');row.update(cpu_percent=None,memory_bytes=None,memory_limit_bytes=None,pids=None,metrics_available=False)
            try:
                if key in futures:
                    current=futures[key].result(timeout=4);row.update(container_values(current,self.previous.get(key),total));row['metrics_available']=True;new[key]=current
            except (OSError,ValueError,TimeoutError,http.client.HTTPException):pass
            result.append(row)
        self.previous=new;return sorted(result,key=lambda r:r['memory_bytes'] or 0,reverse=True)
    def close(self):self.pool.shutdown(wait=True,cancel_futures=True)

class Collector:
    def __init__(self,*,proc='/proc',sysroot='/sys',data='/home/p1admin/p1-agent/astrbot/data/plugin_data/affect',disk='/home/p1admin/p1-agent',docker=None):
        self.proc=Path(proc);self.sysroot=Path(sysroot);self.data=Path(data);self.disk=disk;self.docker=docker or Docker();self.prev_cpu={};self.prev_net=None;self.prev_time=None;self.prev_own_cpu=None;self.history=collections.deque(maxlen=360)
    def host(self,now):
        mem={k:int(v.split()[0])*1024 for k,v in (line.split(':',1) for line in (self.proc/'meminfo').read_text().splitlines())}
        cpu={parts[0]:list(map(int,parts[1:9])) for line in (self.proc/'stat').read_text().splitlines() if (parts:=line.split()) and re.fullmatch(r'cpu[0-9]*',parts[0])}
        usage=cpu_percent(self.prev_cpu.get('cpu'),cpu['cpu']);cores=[cpu_percent(self.prev_cpu.get(k),cpu[k]) for k in sorted(cpu) if k!='cpu'];self.prev_cpu=cpu
        total=mem['MemTotal'];available=mem.get('MemAvailable',mem.get('MemFree',0));disk=shutil.disk_usage(self.disk)
        temperatures=[]
        for p in self.sysroot.glob('class/thermal/thermal_zone*/temp'):
            try:
                value=float(p.read_text())/1000
                if math.isfinite(value) and 0<=value<=150:temperatures.append(value)
            except (OSError,ValueError):pass
        swap_total=mem.get('SwapTotal',0);swap_used=max(0,swap_total-mem.get('SwapFree',0));zram=None
        try:
            z=list(map(int,(self.sysroot/'block/zram0/mm_stat').read_text().split()));zram={'logical_bytes':z[0],'physical_bytes':z[2]}
        except (OSError,ValueError,IndexError):pass
        pressure={}
        for name in ('memory','io'):
            try:
                lines=(self.proc/'pressure'/name).read_text().splitlines();pressure[name]={p[0]:float(next(x.split('=')[1] for x in p[1:] if x.startswith('avg10='))) for line in lines if (p:=line.split()) and p[0] in ('some','full')}
            except (OSError,ValueError,StopIteration):pressure[name]={}
        rx=tx=0
        try:
            for line in (self.proc/'net/dev').read_text().splitlines()[2:]:
                name,values=line.split(':',1);name=name.strip();v=values.split()
                if name=='lo' or name.startswith(('veth','docker','br-','tun','tailscale')):continue
                rx+=int(v[0]);tx+=int(v[8])
        except (OSError,ValueError,IndexError):pass
        net={'receive_bytes_second':None,'send_bytes_second':None}
        elapsed=now-self.prev_time if self.prev_time else None
        if self.prev_net and elapsed and elapsed>0:
            net={'receive_bytes_second':round(max(0,rx-self.prev_net[0])/elapsed,1),'send_bytes_second':round(max(0,tx-self.prev_net[1])/elapsed,1)}
        self.prev_net=(rx,tx)
        return {'cpu_percent':usage,'core_percent':cores,'cpu_count':len(cores) or os.cpu_count(),'memory_total_bytes':total,'memory_available_bytes':available,'memory_percent':round((total-available)/total*100,2),'disk_total_bytes':disk.total,'disk_free_bytes':disk.free,'disk_percent':round((disk.total-disk.free)/disk.total*100,2),'temperature_celsius':round(max(temperatures),1) if temperatures else None,'swap_total_bytes':swap_total,'swap_used_bytes':swap_used,'zram':zram,'load_average':[round(x,2) for x in os.getloadavg()],'uptime_seconds':float((self.proc/'uptime').read_text().split()[0]),'pressure':pressure,'network':net,'architecture':platform.machine()}
    def runtime(self):
        health=safe_json(self.data/'companion_health.json');maint=safe_json(self.data/'maintenance_health.json');db=maint.get('databases') or {};db=db if isinstance(db,dict) else {}
        return {'modules':[{'label':label,'ready':health.get(key) is True} for key,label in MODULES.items() if key in health],
            'module_report_at':health.get('at') if type(health.get('at')) in (int,float) else None,
            'maintenance_report_at':maint.get('at') if type(maint.get('at')) in (int,float) else None,
            'automatic_repair_enabled':not maint.get('disabled',False) if maint else None,
            'latest_repair_actions':len(maint.get('repairs',[])) if isinstance(maint.get('repairs'),list) else 0,
            'databases':[{'label':name,'healthy':db[name] is True} for name in ('affect','memoria','groups','agency','astrbot','knowledge') if name in db]}
    def sample(self):
        started=time.monotonic();now=time.time();host=self.host(started);docker_ok=True
        try:containers=self.docker.sample(host['memory_total_bytes'])
        except (OSError,ValueError,TimeoutError,http.client.HTTPException):containers=[];docker_ok=False
        process=resource.getrusage(resource.RUSAGE_SELF);own_cpu=process.ru_utime+process.ru_stime
        own_pct=(own_cpu-self.prev_own_cpu)/(started-self.prev_time)/(os.cpu_count() or 1)*100 if self.prev_time and self.prev_own_cpu is not None and started>self.prev_time else None
        self.prev_own_cpu=own_cpu;self.prev_time=started
        self.history.append({'at':now,'cpu_percent':host['cpu_percent'],'memory_percent':host['memory_percent'],'temperature_celsius':host['temperature_celsius']})
        rss=int((self.proc/'self/statm').read_text().split()[1])*os.sysconf('SC_PAGE_SIZE')
        return {'schema':1,'at':now,'sample_interval_seconds':5,'history_window_seconds':1800,'host':host,'containers_available':docker_ok,'containers':containers,'runtime':self.runtime(),'history':list(self.history),
            'collector':{'rss_bytes':rss,'cpu_percent':round(own_pct,3) if own_pct is not None else None,'collection_milliseconds':round((time.monotonic()-started)*1000,1)}}

def notify(message):
    address=os.environ.get('NOTIFY_SOCKET')
    if not address:return
    if address.startswith('@'):address='\0'+address[1:]
    try:
        with socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM) as s:s.settimeout(.2);s.connect(address);s.sendall(message.encode())
    except OSError:pass

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,default=Path('/run/p1-monitor/snapshot.json'));p.add_argument('--data',default='/home/p1admin/p1-agent/astrbot/data/plugin_data/affect');p.add_argument('--disk',default='/home/p1admin/p1-agent');p.add_argument('--once',action='store_true');a=p.parse_args()
    c=Collector(data=a.data,disk=a.disk);last=None;ready=False
    try:
        while True:
            start=time.monotonic()
            try:
                snapshot=c.sample();atomic(a.output,snapshot);state='ready' if snapshot['containers_available'] else 'docker_unavailable'
                if not ready:notify('READY=1');ready=True
                notify('WATCHDOG=1')
            except Exception as exc:state='sample_failed_'+type(exc).__name__
            if state!=last:print(json.dumps({'collector_state':state}),flush=True);last=state
            if a.once:break
            time.sleep(max(.1,5-(time.monotonic()-start)))
    finally:c.docker.close()
if __name__=='__main__':main()
