from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import logging
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'release'))
from astrbot_plugin_affect.reactions import Catalog,ReactionStore,eligible_context
from astrbot_plugin_affect.privacy_logging import PrivacyFilter
I='v1:'+'a'*64;J='v1:'+'b'*64
def event(n):return hashlib.sha256(str(n).encode()).hexdigest()
A=dict(intent='casual',emotion='happy',relation='none',confidence=.9)

class ReactionPolicyTests(unittest.TestCase):
    def test_existing_database_and_legacy_rows_preserved(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/'affect.db'
            with sqlite3.connect(path) as db:
                db.execute('CREATE TABLE legacy(value TEXT)');db.execute("INSERT INTO legacy VALUES('keep')")
            s=ReactionStore(path);s.migrate();s.migrate()
            with sqlite3.connect(path) as db:
                self.assertEqual(db.execute('SELECT value FROM legacy').fetchall(),[('keep',)])
                self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
    def test_encoded_image_payload_never_enters_logs(self):
        for prefix in ('base64://','data:image/jpeg;base64,'):
            r=logging.LogRecord('fixture',logging.ERROR,'/thirdparty/qq.py',1,'failed payload '+prefix+'PRIVATE_IMAGE',(),None)
            PrivacyFilter().filter(r);self.assertNotIn('PRIVATE_IMAGE',r.getMessage())
    def test_reviewed_character_catalog_and_hashes(self):
        c=Catalog(ROOT/'release/astrbot_plugin_affect')
        self.assertEqual(len(c.assets),46)
        self.assertEqual(c.search('好奇')[0]['id'],'saki_listening')
        for row in c.search():self.assertTrue(c.read(row['id']).startswith((b'\xff\xd8\xff',b'\x89PNG\r\n\x1a\n')))
    def test_tamper_and_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t)/'plugin';shutil.copytree(ROOT/'release/astrbot_plugin_affect',d)
            p=d/'reaction_assets/saki_smile.jpg';p.write_bytes(p.read_bytes()+b'tampered')
            with self.assertRaises(ValueError):Catalog(d)
            p.unlink();p.symlink_to(ROOT/'release/astrbot_plugin_affect/reaction_assets/saki_smile.jpg')
            with self.assertRaises(ValueError):Catalog(d)
    def test_paths_urls_and_unreviewed_entries_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t);manifest=json.loads((ROOT/'release/astrbot_plugin_affect/reactions.json').read_text())
            for field,value in [('file','../../secret'),('url','http://169.254.169.254/'),('reviewed',False)]:
                bad=json.loads(json.dumps(manifest));bad['assets'][0][field]=value;(d/'reactions.json').write_text(json.dumps(bad))
                with self.assertRaises(AssertionError):Catalog(d)
    def test_serious_negative_and_uncertain_contexts_text_only(self):
        self.assertTrue(eligible_context(A,'哈哈，有点好笑'))
        for change in ({'emotion':'sad'},{'emotion':'anxious'},{'intent':'planning'},{'intent':'support'},{'relation':'criticism'},{'confidence':.6}):
            self.assertFalse(eligible_context(dict(A,**change),'哈哈'))
        for text in ('今天有人去世了','这是严肃问题','别发表情','/随便一个命令'):
            self.assertFalse(eligible_context(A,text))
        self.assertTrue(eligible_context(dict(A,intent='question'),'发张表情包看看'))
    def test_persisted_switch_cooldown_turns_and_identity_scope(self):
        with tempfile.TemporaryDirectory() as t:
            s=ReactionStore(Path(t)/'reactions.db');s.migrate();now=100000
            self.assertTrue(s.reserve(I,event(1),'saki_smile',now));s.finish(I,event(1),True)
            self.assertFalse(s.can_use(I,now+601))
            for n in range(3):s.note_text(I,event(n+2),now+1+n)
            self.assertFalse(s.can_use(I,now+599));self.assertTrue(s.can_use(I,now+601))
            self.assertTrue(s.can_use(J,now+1))
            s.toggle(I,False);self.assertFalse(ReactionStore(s.path).can_use(I,now+5000));s.toggle(I,True)
            self.assertTrue(s.can_use(I,now+5000))
    def test_atomic_duplicate_and_concurrent_reservation(self):
        with tempfile.TemporaryDirectory() as t:
            s=ReactionStore(Path(t)/'reactions.db');s.migrate()
            with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(lambda n:s.reserve(I,event(n),'saki_smile',100000),range(8)))
            self.assertEqual(sum(results),1)
    def test_unknown_delivery_and_restart_never_replayed(self):
        with tempfile.TemporaryDirectory() as t:
            s=ReactionStore(Path(t)/'reactions.db');s.migrate()
            self.assertTrue(s.reserve(I,event(1),'saki_smile',100000));s.finish(I,event(1),False)
            for n in range(4):s.note_text(I,event(n+2),100001+n)
            newer=ReactionStore(s.path);newer.migrate()
            self.assertFalse(newer.reserve(I,event(1),'saki_smile',102000))
    def test_rolling_daily_limit_and_no_raw_content(self):
        with tempfile.TemporaryDirectory() as t:
            s=ReactionStore(Path(t)/'reactions.db');s.migrate()
            for n in range(6):
                now=100000+2000*n;self.assertTrue(s.reserve(I,event(n),'saki_smile',now))
                for k in range(4):s.note_text(I,event(100+n*4+k),now+1+k)
            self.assertFalse(s.can_use(I,120000));self.assertTrue(s.can_use(I,190000))
            with self.assertRaises(ValueError):s.reserve('raw-qq-id',event(30),'saki_smile',190000)
            with self.assertRaises(ValueError):s.reserve(I,event(30),'../../private',190000)
            self.assertEqual(s.path.stat().st_mode&0o777,0o600)

if __name__=='__main__':unittest.main()
