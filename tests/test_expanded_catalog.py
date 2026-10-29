import json,sys,tempfile,shutil,unittest
from pathlib import Path
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'release'))
from astrbot_plugin_affect.reactions import Catalog,ReactionStore
from neutral_assets import expanded
I='v1:'+'a'*64;J='v1:'+'b'*64
class ExpandedCatalog(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.folder=expanded(Path(self.tmp.name));self.c=Catalog(self.folder)
 def test_visual_reviewed_unique_full_catalog_and_categories(self):
  self.assertEqual(len(self.c.assets),46);self.assertEqual(sum(self.c.categories().values()),46);self.assertEqual(len(self.c.categories()),8)
  self.assertEqual(len({a['sha256'] for a in self.c.assets.values()}),46)
 def test_specific_new_reaction_search_and_payload_limit(self):
  self.assertEqual(self.c.search('睡觉')[0]['id'],'saki_sleepy');self.assertEqual(self.c.search('疲惫')[0]['id'],'saki_tired')
  self.assertLessEqual(len(self.c.search()),12)
  self.assertTrue(all('file' not in r and 'sha256' not in r for r in self.c.search()))
 def test_recent_avoids_repeats_within_relevant_ties(self):
  first=self.c.search('微笑')[0]['id'];next_id=self.c.search('微笑',[first])[0]['id']
  self.assertNotEqual(first,next_id);self.assertEqual(self.c.search('睡觉',['saki_sleepy'])[0]['id'],'saki_sleepy')
 def test_recent_is_scoped_read_only_and_survives_restart(self):
  with tempfile.TemporaryDirectory() as t:
   path=Path(t)/'r.db';s=ReactionStore(path);s.migrate();s.reserve(I,'a'*64,'saki_tired',100000);s.finish(I,'a'*64,True)
   self.assertEqual(ReactionStore(path).recent(I),['saki_tired']);self.assertEqual(s.recent(J),[])
   with self.assertRaises(ValueError):s.recent(I,100)
 def test_duplicate_or_excess_catalog_is_rejected(self):
  base=json.loads((self.folder/'reactions.json').read_text())
  with tempfile.TemporaryDirectory() as t:
   d=Path(t);shutil.copytree(self.folder/'reaction_assets',d/'reaction_assets')
   v=json.loads(json.dumps(base));v['assets'][1]['sha256']=v['assets'][0]['sha256'];(d/'reactions.json').write_text(json.dumps(v))
   with self.assertRaises(AssertionError):Catalog(d)
   v=json.loads(json.dumps(base));v['assets']*=3;(d/'reactions.json').write_text(json.dumps(v))
   with self.assertRaises(AssertionError):Catalog(d)
