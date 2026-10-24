"""Real HTTP concurrency; browser and secrets are synthetic, no external traffic."""
import asyncio,importlib.util,json,sys,threading,unittest,urllib.request,urllib.error
from pathlib import Path
from types import ModuleType
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
R=Path(__file__).resolve().parents[1]

class BrowserConcurrency(unittest.TestCase):
 def test_health_and_busy_response_do_not_wait_for_page_and_only_one_browser_runs(self):
  fake=ModuleType('playwright.async_api');fake.async_playwright=lambda:None
  policy_spec=importlib.util.spec_from_file_location('audit_browser_policy',R/'browser/policy.py');policy=importlib.util.module_from_spec(policy_spec);policy_spec.loader.exec_module(policy)
  original=Path.read_text
  def read(p,*a,**kw):return 'synthetic-token' if str(p)=='/run/secrets/browser_token' else original(p,*a,**kw)
  spec=importlib.util.spec_from_file_location('audit_browser',R/'browser/broker.py');broker=importlib.util.module_from_spec(spec)
  with patch.dict(sys.modules,{'playwright.async_api':fake,'policy':policy}),patch.object(Path,'read_text',read):spec.loader.exec_module(broker)
  entered=threading.Event();release=threading.Event();calls=[]
  async def browse(url):
   calls.append(url);entered.set();await asyncio.to_thread(release.wait,3)
   return {'ok':True,'links':[],'title':'synthetic'}
  broker.browse=browse;broker.domains=lambda p:{'docs.python.org'}
  server=broker.Server(('127.0.0.1',0),broker.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  base='http://127.0.0.1:'+str(server.server_port)
  def call(subject='a'):
   req=urllib.request.Request(base+'/browse',data=json.dumps({'subject':'v1:'+subject*64,'action':'open','url':'https://docs.python.org/3/'}).encode(),headers={'Authorization':'Bearer synthetic-token'})
   try:
    with urllib.request.urlopen(req,timeout=2) as r:return r.status,json.load(r)
   except urllib.error.HTTPError as e:return e.code,json.load(e)
  try:
   with ThreadPoolExecutor(1) as pool:
    pending=pool.submit(call);self.assertTrue(entered.wait(1))
    with urllib.request.urlopen(base+'/health',timeout=1) as r:self.assertTrue(json.load(r)['ok'])
    status,value=call('b');self.assertEqual(status,429);self.assertEqual(value['error'],'browser_busy');self.assertEqual(len(calls),1)
    release.set();self.assertEqual(pending.result()[0],200)
   self.assertIn('v1:'+'a'*64,broker.SESSIONS);self.assertNotIn('v1:'+'b'*64,broker.SESSIONS)
  finally:release.set();server.shutdown();server.server_close();thread.join(2)
