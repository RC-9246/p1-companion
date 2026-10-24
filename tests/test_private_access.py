import json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace as NS
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'release'))
from astrbot_plugin_affect.private_access import companion_identity
from astrbot_plugin_affect.identity import make_identity_key
class AccessTests(unittest.TestCase):
 def event(self,sender='20002',bot='10001',private=True):
  return NS(get_sender_id=lambda:sender,get_self_id=lambda:bot,is_private_chat=lambda:private,get_platform_id=lambda:'qq_snowluma',unified_msg_origin='untrusted-umo')
 def test_all_current_and_future_private_whitelist(self):
  with tempfile.TemporaryDirectory() as d:
   config={'platform_settings':{'enable_id_white_list':True,'id_whitelist':['qq_snowluma:FriendMessage:'+str(n) for n in range(20002,20006)]}}
   values=[companion_identity(self.event(str(n)),data=d,config=config) for n in range(20002,20006)]
   self.assertEqual(len(set(values)),4);self.assertNotIn(None,values)
   self.assertIsNone(companion_identity(self.event('30003'),data=d,config=config))
   config['platform_settings']['id_whitelist'].append('qq_snowluma:FriendMessage:30003')
   self.assertIsNotNone(companion_identity(self.event('30003'),data=d,config=config))
   config['platform_settings']['id_whitelist'].remove('qq_snowluma:FriendMessage:30003')
   self.assertIsNone(companion_identity(self.event('30003'),data=d,config=config))
   self.assertIsNone(companion_identity(self.event(private=False),data=d,config=config))
   self.assertNotEqual(companion_identity(self.event(),data=d,config=config),companion_identity(self.event(bot='10002'),data=d,config=config))
 def test_disabled_empty_malformed_config_does_not_admit_everyone(self):
  with tempfile.TemporaryDirectory() as d:
   for cfg in ({},{'platform_settings':{'enable_id_white_list':False,'id_whitelist':['qq_snowluma:FriendMessage:20002']}},{'platform_settings':{'enable_id_white_list':True,'id_whitelist':[]}},None,{'platform_settings':None}):
    self.assertIsNone(companion_identity(self.event(),data=d,config=cfg))
 def test_preserve_original_owner_identity(self):
  with tempfile.TemporaryDirectory() as d:
   identity=make_identity_key('qq_snowluma','10001','20002')
   Path(d,'allowed_identities.json').write_text(json.dumps({'version':1,'allowed_identities':[identity]}))
   self.assertEqual(companion_identity(self.event(),data=d,config={}),identity)
   self.assertIsNone(companion_identity(self.event('20003'),data=d,config={}))
