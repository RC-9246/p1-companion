import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'release'))
from astrbot_plugin_memoria.memoria.db import MemoriaDB

class MemoryConfirmationTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.db=await MemoriaDB.create(self.tmp.name)
  self.mid=await self.db.upsert_memory_candidate('synthetic-a','user','synthetic-a','preference','我喜欢简短回复',.65,'agent')
 async def asyncTearDown(self):self.tmp.cleanup()
 async def row(self):return (await self.db.list_memories('synthetic-a',None,None,20))[0]
 async def test_human_confirmation_promotes_confidence_atomically(self):
  self.assertTrue(await self.db.update_memory_status(self.mid,'synthetic-a','active',verified=True))
  row=await self.row();self.assertEqual(row.status,'active');self.assertEqual(row.confidence,1.)
 async def test_unverified_status_change_cannot_claim_human_confirmation(self):
  self.assertTrue(await self.db.update_memory_status(self.mid,'synthetic-a','active'))
  self.assertEqual((await self.row()).confidence,.65)
 async def test_wrong_owner_cannot_confirm_and_archive_cannot_raise_confidence(self):
  self.assertFalse(await self.db.update_memory_status(self.mid,'synthetic-b','active',verified=True))
  self.assertEqual((await self.row()).status,'candidate')
  self.assertTrue(await self.db.update_memory_status(self.mid,'synthetic-a','archived',verified=True))
  self.assertEqual((await self.row()).confidence,.65)
  self.assertFalse(await self.db.update_memory_status(self.mid,'synthetic-a','invalid',verified=True))
