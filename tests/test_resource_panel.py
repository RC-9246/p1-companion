import importlib.util,json,socket,sys,tempfile,threading,time,unittest,http.client
from pathlib import Path
from unittest.mock import patch
R=Path(__file__).resolve().parents[1];P=R/'services/monitor'
def module(name,file):
 s=importlib.util.spec_from_file_location(name,P/file);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
C=module('monitor_collector','collector.py');V=module('monitor_viewer','server.py')
class MetricsTests(unittest.TestCase):
 def test_host_cpu_uses_all_cores_and_excludes_idle_iowait(self):
  self.assertEqual(C.cpu_percent([0]*8,[5,0,5,80,10,0,0,0]),10);self.assertIsNone(C.cpu_percent(None,[0]*8));self.assertIsNone(C.cpu_percent([10]*8,[0]*8))
 def test_container_cpu_is_whole_host_and_memory_excludes_cache(self):
  old={'cpu_stats':{'system_cpu_usage':100,'cpu_usage':{'total_usage':10}}};now={'cpu_stats':{'system_cpu_usage':200,'cpu_usage':{'total_usage':30}},'memory_stats':{'usage':120,'limit':1000,'stats':{'inactive_file':20}},'pids_stats':{'current':4}}
  v=C.container_values(now,old,500);self.assertEqual(v,{'cpu_percent':20,'memory_bytes':100,'memory_limit_bytes':None,'pids':4});self.assertIsNone(C.container_values(now,None,500)['cpu_percent'])
 def test_v1_cache_counter_and_unavailable_counters_are_not_fake_cpu_zero(self):
  v=C.container_values({'memory_stats':{'usage':100,'limit':200,'stats':{'total_inactive_file':40}}},None,500)
  self.assertEqual(v['memory_bytes'],60);self.assertEqual(v['memory_limit_bytes'],200);self.assertIsNone(v['cpu_percent'])
 def test_docker_client_never_accepts_control_or_unbounded_paths(self):
  d=C.Docker('/nonexistent')
  try:
   for p in ('/v1.51/containers/foo/stop','/containers/json','/v1.51/containers/../../../etc/passwd','/exec/x/json'):
    with self.assertRaisesRegex(ValueError,'docker_read_path_denied'):d.get(p)
  finally:d.close()
 def test_snapshot_excludes_container_commands_labels_env_and_logs(self):
  d=C.Docker();d.version='1.51';key='a'*64
  summary=[{'Id':key,'Names':['/astrbot'],'State':'running','Status':'Up 1 day (healthy)','Command':'password=synthetic_secret','Labels':{'token':'synthetic_secret'}}]
  def get(path):return summary if path.endswith('all=1') else {'cpu_stats':{},'memory_stats':{'usage':100,'stats':{}},'Env':['synthetic_secret']}
  d.get=get
  try:
   rows=d.sample(1000);encoded=json.dumps(rows);self.assertNotIn('synthetic_secret',encoded);self.assertNotIn('Env',encoded);self.assertEqual(rows[0]['label'],'AstrBot');self.assertTrue(rows[0]['metrics_available'])
  finally:d.close()
 def test_closed_health_schema_omits_persona_accounts_and_raw_repair_details(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp);(p/'companion_health.json').write_text(json.dumps({'at':1,'group_memory_ready':True,'private_expression_profile':'synthetic_private','account':'1234567890'}));(p/'maintenance_health.json').write_text(json.dumps({'at':2,'databases':{'affect':True},'repairs':[{'secret':'synthetic_private'}],'disabled':False}))
   class D:
    def close(self):pass
   c=C.Collector(data=p,docker=D());r=c.runtime();self.assertNotIn('synthetic_private',json.dumps(r));self.assertNotIn('1234567890',json.dumps(r));self.assertEqual(r['latest_repair_actions'],1)
 def test_malformed_health_is_nonfatal_and_atomic_files_are_readable(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'health.json';p.write_text('[]');self.assertEqual(C.safe_json(p),{});p.write_text('{bad');self.assertEqual(C.safe_json(p),{});C.atomic(p,{'at':1});self.assertEqual(json.loads(p.read_text()),{'at':1});self.assertEqual(p.stat().st_mode&0o777,0o644)

class HTTPTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.snapshot=self.root/'snapshot.json';self.snapshot.write_text(json.dumps({'schema':1,'at':time.time(),'host':{},'history':[]}));self.server=V.Server(('127.0.0.1',0),snapshot=self.snapshot,assets=P/'dist');self.port=self.server.server_port;self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
 def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join(2);self.tmp.cleanup()
 def request(self,path,method='GET',host=None):
  c=http.client.HTTPConnection('127.0.0.1',self.port,timeout=2)
  try:c.request(method,path,headers={'Host':host or '127.0.0.1:'+str(self.port)});r=c.getresponse();return r.status,dict(r.getheaders()),r.read()
  finally:c.close()
 def test_static_and_live_metrics_with_security_headers(self):
  s,h,b=self.request('/');self.assertEqual(s,200);self.assertIn('运行概览',b.decode());self.assertEqual(h['X-Frame-Options'],'DENY');self.assertIn("connect-src 'self'",h['Content-Security-Policy']);s,h,b=self.request('/api/status');self.assertEqual(s,200);self.assertFalse(json.loads(b)['stale']);self.assertNotIn('Access-Control-Allow-Origin',h)
 def test_stale_data_is_explicit_and_health_fails(self):
  self.snapshot.write_text(json.dumps({'schema':1,'at':time.time()-60}));s,h,b=self.request('/api/status');self.assertEqual(s,200);self.assertTrue(json.loads(b)['stale']);self.assertEqual(self.request('/health')[0],503)
 def test_missing_corrupt_and_large_snapshots_fail_without_leaking_paths(self):
  for data in ('bad','x'*524289):
   self.snapshot.write_text(data);s,h,b=self.request('/api/status');self.assertEqual(s,503);self.assertNotIn(str(self.root).encode(),b)
  self.snapshot.unlink();self.assertEqual(self.request('/api/status')[0],503)
 def test_mutations_and_arbitrary_paths_are_denied(self):
  for method in ('POST','PUT','DELETE','PATCH'):self.assertEqual(self.request('/api/restart',method)[0],405)
  for path in ('/../../etc/passwd','/containers/json','/snapshot.json','/logs','/%2e%2e/etc/passwd'):self.assertEqual(self.request(path)[0],404)
 def test_rebinding_hosts_are_denied_and_head_has_no_body(self):
  self.assertEqual(self.request('/api/status',host='attacker.example')[0],403);s,h,b=self.request('/',method='HEAD');self.assertEqual(s,200);self.assertEqual(b,b'')

class UnitTests(unittest.TestCase):
 def test_collector_and_viewer_are_separate_and_resource_bounded(self):
  c=(P/'p1-resource-collector.service').read_text();v=(P/'p1-resource-panel.service').read_text();self.assertIn('WatchdogSec=45',c);self.assertIn('RestrictAddressFamilies=AF_UNIX',c);self.assertIn('DynamicUser=yes',v);self.assertIn('InaccessiblePaths=-/run/docker.sock',v);self.assertIn('MemoryMax=64M',c);self.assertIn('MemoryMax=32M',v)
if __name__=='__main__':unittest.main()
