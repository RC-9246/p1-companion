import importlib.util
from pathlib import Path
import socket,tempfile,unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]/'services/leisure'
def module(name,file):
 spec=importlib.util.spec_from_file_location(name,ROOT/file);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
P=module('bilibili_policy','policy.py');Q=module('bilibili_quota','quota.py').Quota
class LeisureSecurityTests(unittest.TestCase):
 def test_owned_https_only_no_private_or_confusable_destination(self):
  for u in ('https://www.bilibili.com/','https://s1.hdslb.com/bfs/a.js','https://cn-a.bilivideo.com/upgc/x.m4s'):
   self.assertTrue(P.destination(u))
  for u in ('http://www.bilibili.com/','https://www.bilibili.com.evil.org/','https://127.0.0.1/','https://169.254.169.254/','https://user:secret@www.bilibili.com/','https://www.bilibili.com:8080/'):
   with self.assertRaises(ValueError):P.destination(u)
 def test_get_does_not_permit_account_side_effects(self):
  for path in ('/x/web-interface/share/add','/login/exit/v2','/x/v2/reply/add','/x/v2/dm/post'):
   self.assertFalse(P.read_request('https://api.bilibili.com'+path,'GET'))
 def test_public_interaction_posts_and_unverified_favorites_denied(self):
  for path in ('/x/web-interface/archive/like','/x/web-interface/coin/add','/x/relation/modify','/x/v2/reply/add','/x/v2/dm/post','/x/dynamic/feed/create/dyn','/x/v3/fav/resource/deal','/x/v3/fav/folder/add'):
   self.assertFalse(P.read_request('https://api.bilibili.com'+path,'POST'))
  self.assertFalse(P.read_request('https://api.bilibili.com/x/v2/history/toview/add','POST'))
 def test_private_mutation_requires_exact_expiring_transaction(self):
  url='https://api.bilibili.com/x/v3/fav/resource/deal';grant={'kind':'favorite','expires':21,'folder':'123','rid':'456','remove':False}
  data={'type':['2'],'rid':['456'],'add_media_ids':['123']}
  self.assertTrue(P.private_request(url,'POST',data,grant,20))
  for bad in ({**data,'add_media_ids':['999']},{**data,'rid':['999']},{**data,'del_media_ids':['999']},{**data,'add_media_ids':['123','999']}):
   self.assertFalse(P.private_request(url,'POST',bad,grant,20))
  self.assertFalse(P.private_request(url,'POST',data,grant,22))
  self.assertFalse(P.private_request(url,'POST',data,None,20))
  later={'kind':'watchlater','aid':'456','remove':False,'expires':21}
  self.assertTrue(P.private_request('https://api.bilibili.com/x/v2/history/toview/add','POST',{'aid':['456']},later,20))
  self.assertFalse(P.private_request('https://api.bilibili.com/x/v2/history/toview/del','POST',{'aid':['456']},later,20))
 def test_public_dns_checked_before_connection(self):
  with patch.object(P.socket,'getaddrinfo',return_value=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('127.0.0.1',443))]):
   with self.assertRaises(ValueError):P.public_addresses('www.bilibili.com')
 def test_video_id_and_public_query_guards(self):
  self.assertEqual(P.bvid('BV1xx411c7mD'),'BV1xx411c7mD')
  for value in ('../../private','https://example.com/','BV1xx411c7mD?x=y'):
   with self.assertRaises(ValueError):P.bvid(value)
  for value in ('password=secret','https://example.com','uid123456789','a\nb'):
   with self.assertRaises(ValueError):P.query(value)
 def test_daily_eight_hour_ceiling_persists_and_unknown_not_replayed(self):
  with tempfile.TemporaryDirectory() as t:
   q=Q(Path(t)/'q.db');now=1792745000
   for n in range(32):q.reserve(900,now)
   self.assertEqual(Q(q.path).remaining(now),0)
   with self.assertRaises(ValueError):q.reserve(10,now)
   self.assertEqual(q.remaining(now+86400),28800)
 def test_atomic_concurrent_daily_reservations(self):
  with tempfile.TemporaryDirectory() as t:
   q=Q(Path(t)/'q.db');now=1792745000
   def reserve(n):
    try:q.reserve(900,now);return True
    except ValueError:return False
   with ThreadPoolExecutor(max_workers=10) as pool:self.assertEqual(sum(pool.map(reserve,range(40))),32)
 def test_known_cancellation_releases_unused_time(self):
  with tempfile.TemporaryDirectory() as t:
   q=Q(Path(t)/'q.db');now=1792745000;k=q.reserve(900,now);q.finish(k,20.2,'cancelled')
   self.assertEqual(q.remaining(now),28779)
   q.finish(k,1,'completed');self.assertEqual(q.remaining(now),28779)
   self.assertEqual(q.path.stat().st_mode&0o777,0o600)
 def test_observed_progress_persists_with_explicit_perception_limits(self):
  with tempfile.TemporaryDirectory() as t:
   q=Q(Path(t)/'q.db');q.record_progress('BV1xx411c7mD','synthetic',45.,120.,{'audio_understood':False,'sample_times':[10,40],'perception':'sampled_frames_only'})
   saved=Q(q.path).progress('BV1xx411c7mD');self.assertEqual(saved['position_seconds'],45);self.assertEqual(saved['sample_times'],[10,40]);self.assertFalse(saved['audio_understood'])
   with self.assertRaises(ValueError):q.record_progress('BV1xx411c7mD','synthetic',float('nan'),120,{})
if __name__=='__main__':unittest.main()

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock
sys.modules['policy']=P
PRIVATE=module('leisure_private_api','private_api.py')
class PrivateFolderSafetyTests(unittest.IsolatedAsyncioTestCase):
 def test_private_bit_and_owner_both_required(self):
  self.assertTrue(PRIVATE.private_info({'attr':1,'upper':{'mid':42}},'42'))
  for data in ({'attr':0,'upper':{'mid':42}},{'attr':1,'upper':{'mid':99}},{'attr':'1','upper':{'mid':42}}):self.assertFalse(PRIVATE.private_info(data,'42'))
 async def test_unknown_folder_creation_reconciled_without_second_post(self):
  import json
  with tempfile.TemporaryDirectory() as t:
   b=SimpleNamespace(uid='42');post=AsyncMock(side_effect=TimeoutError())
   with patch.object(PRIVATE,'post',post):
    with self.assertRaises(TimeoutError):await PRIVATE.folder(b,'test',t)
   read=AsyncMock(side_effect=[{'list':[{'title':'test','id':123}]},{'attr':1,'upper':{'mid':42}},{'attr':1,'upper':{'mid':42}}])
   with patch.object(PRIVATE,'get',read),patch.object(PRIVATE,'post',post):self.assertEqual(await PRIVATE.folder(b,'test',t),'123')
   self.assertEqual(post.await_count,1)
   self.assertEqual(json.loads((Path(t)/'pending_folders.json').read_text()),[])
 async def test_user_changed_folder_to_public_denied_before_write(self):
  import json
  with tempfile.TemporaryDirectory() as t:
   (Path(t)/'private_folders.json').write_text(json.dumps({'test':{'owner':'42','id':'123'}}))
   post=AsyncMock()
   with patch.object(PRIVATE,'get',AsyncMock(return_value={'attr':0,'upper':{'mid':42}})),patch.object(PRIVATE,'post',post):
    with self.assertRaisesRegex(ValueError,'folder_no_longer_private'):await PRIVATE.folder(SimpleNamespace(uid='42'),'test',t)
   post.assert_not_awaited()
