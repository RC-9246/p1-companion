import sys,types,unittest,json,tempfile,sqlite3
from pathlib import Path
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'release'))
from astrbot_plugin_affect.idle import decision,IdleController
from test_companion import init_db,I,J
class IdlePolicy(unittest.TestCase):
 def test_choice_is_closed_and_duration_bounded(self):
  self.assertEqual(decision(json.dumps({'activity':'rest','topic':'reading','seconds':0}))['seconds'],0)
  for patch in ({'seconds':601},{'seconds':True},{'topic':'私人账号密码'},{'activity':'comment'},{'url':'https://evil.test'}):
   with self.assertRaises(ValueError):decision(json.dumps(dict({'activity':'watch','topic':'reading','seconds':60},**patch)))
 def test_claim_is_persistent_and_unknown_reservations_are_charged(self):
  with tempfile.TemporaryDirectory() as t:
   data=Path(t);init_db(data/'affect.db');c=IdleController(types.SimpleNamespace(plugin=None,data=data));c.migrate();now=1792745000
   self.assertIsNone(c.claim(I,now));claim=c.claim(I,now+7201);self.assertIsNotNone(claim)
   restarted=IdleController(types.SimpleNamespace(plugin=None,data=data));self.assertIsNone(restarted.claim(I,now+7202))
   self.assertEqual(restarted.stats(I,now+7202)['choices_today'],1);self.assertEqual(restarted.stats(I,now+7202)['remaining_seconds'],28080)
   self.assertEqual(restarted.stats(J,now+7202)['choices_today'],0)
 def test_failed_known_work_only_releases_known_unused_reserve(self):
  with tempfile.TemporaryDirectory() as t:
   data=Path(t);init_db(data/'affect.db');c=IdleController(types.SimpleNamespace(plugin=None,data=data));c.migrate();now=1792745000
   c.claim(I,now);key,reserve=c.claim(I,now+7201);c.finish(key,'interrupted',{},7,{})
   self.assertEqual(c.stats(I,now+7202)['remaining_seconds'],28793)

class JSONModeContract(unittest.IsolatedAsyncioTestCase):
 async def test_every_idle_prompt_gets_required_json_keyword(self):
  import types
  from types import SimpleNamespace
  calls=[]
  class Client:
   base_url=SimpleNamespace(host='api.deepseek.com',scheme='https')
   def __init__(self):self.chat=SimpleNamespace(completions=self)
   def with_options(self,**kw):return self
   async def create(self,**kw):
    calls.append(kw);return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"index":0}'))])
  class Context:
   @property
   def provider_manager(self):return self
   async def get_current_chat_provider_id(self,*args):return 'synthetic'
   async def get_provider_by_id(self,*args):return SimpleNamespace(client=Client(),get_model=lambda:'synthetic')
  with tempfile.TemporaryDirectory() as t:
   row={'identity':I,'umo':'synthetic','version':4}
   plugin=SimpleNamespace(enabled=lambda:True,store=SimpleNamespace(take_budget=lambda *args:True),context=Context(),persona='合成人格')
   social=SimpleNamespace(plugin=plugin,data=Path(t),allowed=lambda:{I},store=SimpleNamespace(get=lambda _:row))
   idle=IdleController(social)
   self.assertEqual(json.loads(await idle.complete(row,'选择一个候选，只返回对象。',{}))['index'],0)
   self.assertIn('json',calls[0]['messages'][0]['content'].lower())
   self.assertEqual(calls[0]['response_format'],{'type':'json_object'})
