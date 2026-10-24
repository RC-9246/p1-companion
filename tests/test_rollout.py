import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import sqlite3,time
from types import SimpleNamespace
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('v09_rollout',Path(__file__).resolve().parents[1]/'tools/deploy.py')
rollout=importlib.util.module_from_spec(spec)
spec.loader.exec_module(rollout)

class RolloutSafetyTests(unittest.TestCase):
    def test_group_enrollment_policy_is_reversible(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);data=root/'data';point=root/'point'
            active=data/'plugin_data/affect/groups.json';saved=point/'config/plugin_data/affect/groups.json'
            active.parent.mkdir(parents=True);saved.parent.mkdir(parents=True)
            previous={'version':1,'groups':[]}
            saved.write_text(json.dumps(previous));active.write_text('{"version":1,"groups":[{"bot":"10001","group":"30003"}]}')
            db=active.parent/'affect.db';db.write_bytes(b'private state retained')
            rollout.restore_sources(data,point)
            self.assertEqual(json.loads(active.read_text()),previous)
            self.assertEqual(db.read_bytes(),b'private state retained')
    def test_new_mcp_and_social_policy_are_reverted_without_database_loss(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);data=root/'data';point=root/'point'
            for name in rollout.NAMES:
                old=point/'plugins'/name;old.mkdir(parents=True);(old/'main.py').write_text('previous')
                active=data/'plugins'/name;active.mkdir(parents=True);(active/'main.py').write_text('next')
                (active/'new_module.py').write_text('new feature')
            (point/'config').mkdir()
            for name in ('cmd_config.json','mcp_server.json'):
                (point/'config'/name).write_text('{"before":true}')
                (data/name).write_text('{"next":true}')
            affect=data/'plugin_data/affect';affect.mkdir(parents=True)
            (affect/'social_policy.json').write_text('{"enabled":true}')
            (affect/'social_probe_v09_0').touch()
            sentinel=affect/'affect.db';sentinel.write_bytes(b'keep post-release state')
            rollout.restore_sources(data,point)
            self.assertEqual(sentinel.read_bytes(),b'keep post-release state')
            self.assertFalse((affect/'social_policy.json').exists())
            self.assertTrue((affect/'social_probe_v09_0').exists())
            self.assertEqual(json.loads((data/'mcp_server.json').read_text()),{'before':True})
            for name in rollout.NAMES:
                self.assertEqual((data/'plugins'/name/'main.py').read_text(),'previous')
                self.assertFalse((data/'plugins'/name/'new_module.py').exists())
    def test_new_plugins_are_removed_when_no_prior_copy_existed(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);data=root/'data';point=root/'point';(point/'plugins').mkdir(parents=True)
            for name in rollout.NAMES:
                target=data/'plugins'/name;target.mkdir(parents=True);(target/'main.py').write_text('new')
            affect=data/'plugin_data/affect';affect.mkdir(parents=True);(affect/'affect.db').write_bytes(b'new rows')
            rollout.restore_sources(data,point)
            self.assertTrue(all(not (data/'plugins'/name).exists() for name in rollout.NAMES))
            self.assertEqual((affect/'affect.db').read_bytes(),b'new rows')
    def test_watchdog_rolls_back_only_uncommitted_release(self):
        with tempfile.TemporaryDirectory() as t:
            base=Path(t);point=base/'backups/companion-release-v020-test';point.mkdir(parents=True)
            (point/'rollback.json').write_text('{"deadline":0}')
            with patch.object(rollout,'BASE',base),patch.object(rollout,'rollback',return_value={'status':'synthetic'}) as revert:
                rollout.watchdog(point);revert.assert_called_once_with(point.resolve())
                revert.reset_mock();(point/'committed').touch()
                rollout.watchdog(point);revert.assert_not_called()
    def test_rollback_preserves_contact_pause_and_enabled_preference(self):
        with tempfile.TemporaryDirectory() as t:
            base=Path(t);data=base/'data';point=base/'backups/companion-release-v020-paused';(point/'plugins').mkdir(parents=True)
            (point/'rollback.json').write_text('{}');db=data/'plugin_data/affect/affect.db';db.parent.mkdir(parents=True)
            with sqlite3.connect(db) as c:
                c.executescript('CREATE TABLE companion_social(identity TEXT PRIMARY KEY,enabled INTEGER);CREATE TABLE companion_contact_pauses(identity TEXT PRIMARY KEY,until_at REAL);')
                c.execute('INSERT INTO companion_social VALUES(?,1)',('synthetic',));c.execute('INSERT INTO companion_contact_pauses VALUES(?,?)',('synthetic',time.time()+3600))
            with patch.object(rollout,'BASE',base),patch.object(rollout,'DATA',data),patch.object(rollout,'run',return_value=SimpleNamespace(returncode=0)):
                self.assertEqual(rollout.rollback(point)['status'],'rolled_back')
            with sqlite3.connect(db) as c:
                self.assertEqual(c.execute('SELECT enabled FROM companion_social').fetchone()[0],1)
                self.assertGreater(c.execute('SELECT until_at FROM companion_contact_pauses').fetchone()[0],time.time()+3500)

if __name__=='__main__':unittest.main()
