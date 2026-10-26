import asyncio,copy,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace as NS
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'release'))
from astrbot_plugin_affect.private_access import companion_identity,owner_identity,PrivateAccess,live_private_stage,private_memory_keys
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

class NativeConfig(dict):
 def __init__(self,path,value):super().__init__(value);self.config_path=str(path);self.fail_once='';self.delay=0
 async def save_config_async(self,replace_config):
  self.update(copy.deepcopy(replace_config));await asyncio.sleep(self.delay)
  fail=self.fail_once;self.fail_once=''
  if fail=='before':raise OSError('synthetic writer failure')
  Path(self.config_path).write_text(json.dumps(dict(self)))
  if fail=='after':raise OSError('synthetic post-write failure')
  return True

class GrantTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.data=Path(self.tmp.name)/'astrbot/data/plugin_data/affect';self.data.mkdir(parents=True)
  self.path=self.data.parents[1]/'cmd_config.json';self.before={'platform_settings':{'enable_id_white_list':True,'id_whitelist':['qq_snowluma:FriendMessage:20001']},'provider':[{'key':'synthetic-unchanged-secret'}]}
  self.path.write_text(json.dumps(self.before));self.cfg=NativeConfig(self.path,copy.deepcopy(self.before));self.owners={'version':1,'allowed_identities':[make_identity_key('qq_snowluma','10001','20001')]}
  (self.data/'allowed_identities.json').write_text(json.dumps(self.owners));self.context=NS(get_config=lambda *a:self.cfg);self.access=PrivateAccess(self.context,self.data);await self.access.recover()
 def event(self,sender='20001',private=True,platform='qq_snowluma',background=False):
  return NS(get_sender_id=lambda:sender,get_self_id=lambda:'10001',is_private_chat=lambda:private,get_platform_id=lambda:platform,get_extra=lambda k,d=None:background if k=='_p1_agency_background' else d,unified_msg_origin='qq_snowluma:FriendMessage:'+sender)
 async def asyncTearDown(self):self.tmp.cleanup()
 async def test_add_member_has_independent_identity_without_owner_or_history_writes(self):
  sentinel=self.data/'existing-history.db';sentinel.write_bytes(b'unchanged existing memory')
  r=await self.access.grant(self.event(),'30003');self.assertTrue(r['changed']);self.assertFalse(r['owner'])
  key=companion_identity(self.event('30003'),data=self.data,config=self.cfg);self.assertEqual(key,make_identity_key('qq_snowluma','10001','30003'));self.assertNotEqual(key,self.owners['allowed_identities'][0])
  self.assertIsNone(owner_identity(self.event('30003'),self.data));self.assertEqual(json.loads((self.data/'allowed_identities.json').read_text()),self.owners)
  after=json.loads(self.path.read_text());after['platform_settings']['id_whitelist'].remove('qq_snowluma:FriendMessage:30003');self.assertEqual(after,self.before);self.assertEqual(sentinel.read_bytes(),b'unchanged existing memory')
  self.assertFalse(self.access.pending.exists());self.assertEqual((self.access.backups/r['record']/'config-before.json').stat().st_mode&0o777,0o600)
 async def test_owner_grant_also_enrolls_and_repeat_or_add_white_never_demotes(self):
  r=await self.access.grant(self.event(),'30003',owner=True);self.assertTrue(r['owner']);self.assertIsNotNone(owner_identity(self.event('30003'),self.data))
  for role in (True,False):
   again=await self.access.grant(self.event(),'30003',owner=role);self.assertFalse(again['changed']);self.assertTrue(again['owner'])
  self.assertEqual(len(list(self.access.backups.iterdir())),1)
 async def test_promoting_existing_member_preserves_its_memory_identity(self):
  await self.access.grant(self.event(),'30003');before=companion_identity(self.event('30003'),data=self.data,config=self.cfg)
  await self.access.grant(self.event(),'30003',owner=True);self.assertEqual(companion_identity(self.event('30003'),data=self.data,config=self.cfg),before)
  self.assertEqual(self.cfg['platform_settings']['id_whitelist'].count('qq_snowluma:FriendMessage:30003'),1)
 async def test_memory_legacy_map_is_not_changed_by_new_owners_and_can_recover(self):
  self.assertEqual(private_memory_keys(self.data,'10001','20001')[0],'20001')
  key=make_identity_key('qq_snowluma','10001','30003');await self.access.grant(self.event(),'30003',owner=True)
  self.assertEqual(private_memory_keys(self.data,'10001','30003'),(key,key))
  self.assertNotEqual(private_memory_keys(self.data,'10002','20001')[0],'20001')
  (self.data/'private_memory_legacy.json').unlink();fresh=PrivateAccess(self.context,self.data);await fresh.recover()
  self.assertEqual(private_memory_keys(self.data,'10001','30003'),(key,key));self.assertEqual(private_memory_keys(self.data,'10001','20001')[0],'20001')
 async def test_nonowner_group_other_platform_and_background_cannot_grant(self):
  for e in (self.event('20002'),self.event(private=False),self.event(platform='webchat'),self.event(background=True)):
   with self.assertRaises(ValueError):await self.access.grant(e,'30003',owner=True)
  self.assertEqual(json.loads(self.path.read_text()),self.before);self.assertFalse(self.access.backups.exists())
 async def test_invalid_numbers_and_independent_profile_are_rejected(self):
  for peer in ('00000','1234','10001','9'*21,'30003; bad','-30003',30003):
   with self.assertRaises(ValueError):await self.access.grant(self.event(),peer)
  self.context.get_config=lambda *a:{} if a else self.cfg
  with self.assertRaisesRegex(ValueError,'separate_config_profile'):await self.access.grant(self.event(),'30003')
  self.assertFalse(self.access.backups.exists())
 async def test_writer_failures_restore_both_files_and_live_config(self):
  for fail in ('before','after'):
   self.cfg.fail_once=fail
   with self.assertRaises(OSError):await self.access.grant(self.event(),'30003',owner=True)
   self.assertEqual(json.loads(self.path.read_text()),self.before);self.assertEqual(dict(self.cfg),self.before);self.assertEqual(json.loads(self.access.owner_path.read_text()),self.owners);self.assertFalse(self.access.pending.exists())
 async def test_cancelled_writer_is_awaited_before_rollback(self):
  self.cfg.delay=.05;task=asyncio.create_task(self.access.grant(self.event(),'30003',owner=True));await asyncio.sleep(.005);task.cancel()
  with self.assertRaises(asyncio.CancelledError):await task
  await asyncio.sleep(.06);self.assertEqual(json.loads(self.path.read_text()),self.before);self.assertEqual(dict(self.cfg),self.before);self.assertIsNone(owner_identity(self.event('30003'),self.data))
 async def test_process_recovery_rolls_back_uncommitted_images_without_touching_memories(self):
  r=await self.access.grant(self.event(),'30003',owner=True);p=self.access.backups/r['record'];(p/'result.json').unlink();self.access.pending.write_text(json.dumps({'record':r['record']}))
  fresh=PrivateAccess(self.context,self.data);self.assertTrue(await fresh.recover());self.assertTrue(fresh.ready)
  self.assertEqual(json.loads(self.path.read_text()),self.before);self.assertEqual(json.loads(fresh.owner_path.read_text()),self.owners);self.assertIsNone(companion_identity(self.event('30003'),data=self.data,config=self.cfg))
 async def test_parallel_owner_commands_serialize_without_losing_grants(self):
  self.cfg.delay=.01
  await asyncio.gather(*(self.access.grant(self.event(),peer,owner=True) for peer in ('30003','30004')))
  self.assertEqual(len(json.loads(self.access.owner_path.read_text())['allowed_identities']),3)
  self.assertTrue(all(owner_identity(self.event(peer),self.data) for peer in ('20001','30003','30004')));self.assertEqual(dict(self.cfg),json.loads(self.path.read_text()))
 async def test_live_whitelist_stage_copies_cache_and_honors_revocation(self):
  original=NS(enable_whitelist_check=True,whitelist=['old'],wl_ignore_admin_on_group=False,wl_ignore_admin_on_friend=False,wl_log=False)
  await self.access.grant(self.event(),'30003');e=self.event('30003');fresh=live_private_stage(original,e,self.context)
  self.assertIn(e.unified_msg_origin,fresh.whitelist);self.assertEqual(original.whitelist,['old'])
  self.cfg['platform_settings']['id_whitelist'].remove(e.unified_msg_origin)
  self.assertNotIn(e.unified_msg_origin,live_private_stage(original,e,self.context).whitelist)
  self.assertIs(live_private_stage(original,self.event(platform='webchat'),self.context),original)
