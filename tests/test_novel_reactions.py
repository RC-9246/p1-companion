"""Generated image policy fixtures and real 10-minute/three-turn gates."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import hashlib,json,sys,tempfile,unittest
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'release'))
from astrbot_plugin_affect.reactions import Catalog,ReactionStore,approved_source,valid_image
from astrbot_plugin_p1_group_memory.store import Store,scope_key
from astrbot_plugin_affect.emotion_model import seed
from neutral_assets import expanded
I='v1:'+'a'*64

def key(n):return hashlib.sha256(str(n).encode()).hexdigest()

class NovelReactions(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.folder=expanded(Path(self.tmp.name))
 def test_fourteen_synthetic_publisher_metadata_fixtures(self):
  c=Catalog(self.folder);new=[x for x in c.assets.values() if x.get('medium')=='light_novel_art']
  self.assertEqual(len(new),14)
  self.assertTrue(all(x['illustrator']=='Hiten' and x['reviewed'] and valid_image(c.read(x['id']),'.png') for x in new))
  self.assertEqual(len({x['sha256'] for x in new}),14)
  self.assertTrue(all(x['medium']=='light_novel_art' for x in c.search('轻小说 原画 Hiten')))
 def test_publisher_url_redirect_lookalikes_and_unknown_art_rejected(self):
  c=Catalog(self.folder);row=c.assets['saki_novel_portrait']
  for change in [{'url':row['url']+'?redirect=https://evil.example'}, {'url':row['url'].replace('promo.kadokawa.co.jp','promo.kadokawa.co.jp.evil.example')},{'url':row['url'].replace('character_img02','unreviewed')},{'source':'https://evil.example/'},{'illustrator':'other'},{'file':'../private.png'},{'medium':'anime_still'}]:
   self.assertFalse(approved_source(dict(row,**change)))
 def test_png_digest_and_format_guard(self):
  c=Catalog(self.folder);data=c.read('saki_novel_portrait')
  self.assertTrue(valid_image(data,'.png'));self.assertFalse(valid_image(data,'.jpg'));self.assertFalse(valid_image(data[:-1],'.png'))
 def test_private_exact_cooldown_and_delivered_turn_threshold(self):
  with tempfile.TemporaryDirectory() as t:
   s=ReactionStore(Path(t)/'r.db');s.migrate();self.assertTrue(s.reserve(I,key(0),'saki_novel_portrait',10000));s.finish(I,key(0),True)
   for n in range(2):s.note_text(I,key(n+1),10001+n)
   self.assertFalse(s.can_use(I,10600));self.assertFalse(s.reserve(I,key(50),'saki_novel_portrait',10600))
   s.note_text(I,key(3),10003);self.assertFalse(s.can_use(I,10599));self.assertFalse(s.reserve(I,key(51),'saki_novel_portrait',10599))
   self.assertTrue(ReactionStore(s.path).can_use(I,10600));self.assertTrue(s.reserve(I,key(52),'saki_novel_portrait',10600))
 def test_group_boundary_daily_cap_atomicity_and_neighbor_isolation(self):
  with tempfile.TemporaryDirectory() as t:
   s=Store(Path(t)/'g.db');s.migrate();a=scope_key('bot','a');b=scope_key('bot','b');s.seed_affect(a,{},seed(),10000)
   self.assertTrue(s.reserve_reaction(a,'first','saki_novel_portrait',10000));s.reaction_done(a,'first',False)
   def turns(n):
    state=seed();state['interactions']=n
    with s.db() as c:c.execute('UPDATE group_persona SET state=? WHERE scope=?',(json.dumps(state),a))
   turns(2);self.assertFalse(s.can_react(a,10600));self.assertFalse(s.reserve_reaction(a,'too_few','saki_smile',10600))
   turns(3);self.assertFalse(s.can_react(a,10599));self.assertFalse(s.reserve_reaction(a,'too_soon','saki_smile',10599));self.assertTrue(s.can_react(b,10001))
   with ThreadPoolExecutor(4) as pool:out=list(pool.map(lambda n:s.reserve_reaction(a,'race'+str(n),'saki_smile',10600),range(4)))
   self.assertEqual(sum(out),1)
   for n in (2,3):
    turns(n*3);self.assertTrue(s.reserve_reaction(a,'daily'+str(n),'saki_smile',10000+n*600))
   turns(12);self.assertFalse(s.can_react(a,12400));self.assertFalse(s.reserve_reaction(a,'cap','saki_smile',12400));self.assertTrue(s.can_react(b,12400))
