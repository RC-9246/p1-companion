"""Transaction-level tests: no daemon, network, QQ, systemd or model calls."""
import copy
import hashlib
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

R = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('core_update', R / 'services/updater/manager.py')
U = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(U)
OLD, NEW, FROZEN = ['sha256:' + x * 64 for x in 'abc']


class FakeSystem:
    def __init__(self, root):
        self.home = root / 'system'
        self.home.mkdir(mode=0o700)
        self.restored = 0
        self.armed = False
        self.paused = False

    def timer_states(self):
        return {x: {'active': True, 'enabled': True} for x in U.TIMERS}

    def arm(self):
        self.armed = True

    def quiesce(self):
        self.paused = True

    def restore_timers(self, states):
        self.restored += 1
        self.paused = False


class FakeDocker:
    def __init__(self, root, kind='astrbot'):
        self.root, self.kind = root, kind
        self.calls = []
        self.fail_candidate = False
        self.fail_canary = False
        self.fail_rollback_canary = False
        self.change_schema = False
        self.fail_recreate_once = False
        config = {'Image': OLD, 'Env': ['DEFAULT=old', 'PRIVATE=do-not-print'],
                  'Labels': {'com.docker.compose.service': kind,
                             'com.docker.compose.project': kind,
                             'com.docker.compose.project.config_files': str(root / kind / 'compose.yaml')},
                  'Cmd': ['python', 'main.py'], 'Entrypoint': None, 'User': 'root', 'WorkingDir': '/app'}
        mounts = []
        for i, destination in enumerate(U.POLICY[kind]['mounts']):
            p = root / kind / ('data' if i == 0 else 'volume' + str(i))
            p.mkdir(parents=True, exist_ok=True)
            mounts.append({'Type': 'bind', 'Source': str(p), 'Destination': destination, 'RW': True})
        self.items = {kind: {'Name': '/' + kind, 'Id': 'd' * 64, 'Image': OLD, 'Config': config,
                            'Mounts': mounts, 'HostConfig': {'NetworkMode': 'core', 'Memory': 1536 * 1024**2,
                                                           'Binds': [m['Source'] + ':' + m['Destination'] for m in mounts],
                                                           'PortBindings': {'6185/tcp': [{'HostPort': '6185'}]}},
                            'State': {'Running': True}, 'NetworkSettings': {'Networks': {'core': {'Aliases': [kind, 'd' * 12], 'IPAMConfig': None}}}}}
        self.original = copy.deepcopy(self.items[kind])
        self.images = {x: {'Id': x, 'Config': copy.deepcopy(config)} for x in (OLD, NEW, FROZEN)}

    def inspect(self, name):
        return copy.deepcopy(self.items.get(name))

    def image(self, name):
        return copy.deepcopy(self.images[name])

    def freeze(self, name, ident):
        self.calls.append(('freeze', name))
        return FROZEN

    def stop(self, name):
        self.calls.append(('stop', name))
        self.items[name]['State']['Running'] = False

    def start(self, name):
        self.calls.append(('start', name))
        self.items[name]['State']['Running'] = True
        if self.change_schema and self.items[name]['Image'] == NEW:
            p = Path(self.items[name]['Mounts'][0]['Source']) / 'facts.db'
            with sqlite3.connect(p) as c:
                c.execute('CREATE TABLE IF NOT EXISTS incompatible(x)')

    def remove(self, name):
        self.calls.append(('remove', name))
        del self.items[name]

    def rename(self, name, new):
        self.calls.append(('rename', name))
        self.items[new] = self.items.pop(name)
        self.items[new]['Name'] = '/' + new

    def create(self, name, spec):
        self.calls.append(('create', name))
        if self.fail_recreate_once and name == self.kind and name not in self.items:
            self.fail_recreate_once = False
            raise U.UpdateError('docker_operation_failed')
        old = self.original
        mounts = spec['HostConfig'].get('Mounts')
        mounts = [{'Type': 'bind', 'Source': m['Source'], 'Destination': m['Target'], 'RW': True} for m in mounts] if mounts else copy.deepcopy(old['Mounts'])
        self.items[name] = {'Name': '/' + name, 'Id': hashlib.sha256((name + str(len(self.calls))).encode()).hexdigest(),
                            'Image': spec['Image'], 'Config': copy.deepcopy(spec),
                            'Mounts': mounts, 'HostConfig': copy.deepcopy(spec['HostConfig']),
                            'State': {'Running': False}, 'NetworkSettings': copy.deepcopy(old['NetworkSettings'])}

    def probe(self, name, kind, canary=False, fresh_after=0):
        o = self.items.get(name)
        if not o or not o['State']['Running']:
            return False
        if o['Image'] == NEW and (self.fail_canary if canary else self.fail_candidate):
            return False
        if canary and o['Image'] == FROZEN and self.fail_rollback_canary:
            return False
        return True


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve() / 'agent'
        data = self.root / 'astrbot/data/plugin_data/affect'
        data.mkdir(parents=True)
        self.db = self.root / 'astrbot/data/facts.db'
        with sqlite3.connect(self.db) as c:
            c.execute('CREATE TABLE facts(text)')
            c.execute('INSERT INTO facts VALUES (?)', ('before',))
        self.docker = FakeDocker(self.root)
        self.system = FakeSystem(self.root)
        self.engine = U.Engine(self.root, self.docker, self.system)
        self.engine.poll = .0001
        self.engine.boot_wait = .004
        self.engine.canary_wait = .004
        self.engine.watch_seconds = 0
        patches = [patch.object(U, 'catalog', return_value={'versions': [{'version': 'v4.29.3'}]}),
                   patch.object(self.engine, 'resolve', return_value=NEW),
                   patch.object(U, 'CHECKPOINT', self.root / 'checkpoint'),
                   patch.object(U, 'RESOURCE_CONFIG', self.root / 'resource/config.json'),
                   patch.object(U, 'boot', return_value='boot-one'), patch.object(U, 'uptime', return_value=1000)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def apply(self):
        return self.engine.apply('astrbot', '4.29.3')

    def info(self):
        return U.read(self.system.home / 'active.json')

    def facts(self):
        with sqlite3.connect(self.db) as c:
            return [r[0] for r in c.execute('SELECT text FROM facts')]

    def test_success_needs_observation_before_commit(self):
        self.assertEqual(self.apply()['state'], 'observing')
        self.assertTrue(self.system.armed)
        self.assertTrue(self.system.paused)
        self.assertEqual(self.engine.tick()['state'], 'succeeded')
        self.assertFalse(self.system.paused)
        self.assertEqual(self.docker.items['astrbot']['Image'], NEW)

    def test_manual_rollback_keeps_new_conversations(self):
        self.apply()
        self.engine.tick()
        with sqlite3.connect(self.db) as c:
            c.execute('INSERT INTO facts VALUES (?)', ('new conversation',))
        self.assertEqual(self.engine.tick(True)['state'], 'rolled_back')
        self.assertEqual(self.facts(), ['before', 'new conversation'])
        self.assertEqual(self.docker.items['astrbot']['Image'], FROZEN)

    def test_canary_failure_does_not_start_candidate_on_live_data(self):
        self.docker.fail_canary = True
        self.assertEqual(self.apply()['state'], 'rolled_back')
        self.assertEqual(self.docker.items['astrbot']['Id'], 'd' * 64)
        self.assertEqual(self.facts(), ['before'])

    def test_schema_migration_is_rejected_on_copy(self):
        self.docker.change_schema = True
        result = self.apply()
        self.assertEqual(result['state'], 'rolled_back')
        self.assertEqual(result['error'], 'schema_migration_requires_review')
        with sqlite3.connect(self.db) as c:
            self.assertFalse(c.execute("SELECT 1 FROM sqlite_master WHERE name='incompatible'").fetchall())

    def test_old_version_must_accept_candidate_copy(self):
        self.docker.fail_rollback_canary = True
        self.assertEqual(self.apply()['error'], 'backward_compatibility_failed')
        self.assertEqual(self.docker.items['astrbot']['Image'], OLD)

    def test_failed_live_candidate_has_bounded_repairs_then_rollback(self):
        self.docker.fail_candidate = True
        result = self.apply()
        self.assertEqual(result['state'], 'rolled_back')
        self.assertEqual(result['repairs'], ['restart_candidate', 'recreate_candidate'])
        self.assertTrue(self.docker.items['astrbot']['State']['Running'])

    def test_probation_failure_automatically_rolls_back(self):
        self.apply()
        self.docker.fail_candidate = True
        self.assertEqual(self.engine.tick()['state'], 'rolled_back')
        self.assertEqual(self.docker.items['astrbot']['Image'], OLD)

    def test_restart_recovers_interrupted_transaction(self):
        self.apply()
        info = self.info()
        info['stage'] = 'recreate_candidate'
        U.atom(self.system.home / 'active.json', info)
        fresh = U.Engine(self.root, self.docker, self.system)
        fresh.poll = .0001
        fresh.boot_wait = .004
        fresh.canary_wait = .004
        self.assertEqual(fresh.tick()['state'], 'rolled_back')

    def test_crash_after_success_does_not_leave_maintenance_disabled(self):
        self.apply()
        info = self.info()
        info.update(state='succeeded', stage='observation_passed')
        U.atom(self.system.home / 'active.json', info)
        self.assertEqual(self.engine.tick()['state'], 'succeeded')
        self.assertFalse(self.system.paused)
        self.assertTrue(self.info()['timer_restore_done'])

    def test_new_database_schema_blocks_destructive_downgrade(self):
        self.apply()
        with sqlite3.connect(self.db) as c:
            c.execute('CREATE TABLE new_live_history(value)')
            c.execute("INSERT INTO new_live_history VALUES ('preserve')")
        self.assertEqual(self.engine.tick(True)['state'], 'rollback_blocked')
        with sqlite3.connect(self.db) as c:
            self.assertEqual(c.execute('SELECT * FROM new_live_history').fetchone()[0], 'preserve')
        self.assertTrue(self.system.paused)

    def test_live_backward_compatibility_failure_keeps_current_data(self):
        self.apply()
        self.docker.fail_rollback_canary = True
        self.assertEqual(self.engine.tick(True)['state'], 'rollback_blocked')
        self.assertEqual(self.facts(), ['before'])

    def test_foreign_replacement_is_never_deleted(self):
        self.apply()
        self.docker.items['astrbot']['Config']['Labels'][U.LABEL] = 'different-owner'
        before = self.docker.items['astrbot']['Id']
        self.assertEqual(self.engine.tick(True)['state'], 'rollback_blocked')
        self.assertEqual(self.docker.items['astrbot']['Id'], before)

    def test_second_upgrade_cannot_replace_active_transaction(self):
        self.apply()
        with self.assertRaisesRegex(U.UpdateError, 'upgrade_already_active'):
            self.apply()

    def test_unpublished_version_is_rejected_before_mutation(self):
        with self.assertRaisesRegex(U.UpdateError, 'release_not_in_stable_catalog'):
            self.engine.apply('astrbot', '9.9.9')
        self.assertEqual(self.docker.calls, [])

    def test_metadata_tampering_blocks_recovery(self):
        self.apply()
        (Path(self.info()['point']) / 'old.json').write_text('{}')
        with self.assertRaisesRegex(U.UpdateError, 'recovery_metadata_changed'):
            self.engine.tick(True)

    def test_corrupt_journal_is_not_reset(self):
        (self.system.home / 'active.json').write_text('{broken')
        with self.assertRaises(ValueError):
            self.engine.tick()
        self.assertEqual(self.docker.calls, [])

    def test_snapshot_disk_failure_starts_original(self):
        with patch.object(U.shutil, 'disk_usage', return_value=type('Disk', (), {'free': 1})()):
            self.assertEqual(self.apply()['state'], 'rolled_back')
        self.assertTrue(self.docker.items['astrbot']['State']['Running'])

    def test_lost_create_response_can_be_recovered(self):
        self.docker.fail_recreate_once = True
        self.assertEqual(self.apply()['state'], 'rolled_back')
        self.assertEqual(self.docker.items['astrbot']['Id'], 'd' * 64)

    def test_changed_checkpoint_does_not_get_overwritten(self):
        self.apply()
        p = self.root / 'checkpoint'
        p.mkdir(mode=0o700)
        U.atom(p / 'services.json', {'astrbot': {'image': 'sha256:' + 'e' * 64}})
        self.assertEqual(self.engine.tick()['state'], 'rollback_blocked')
        self.assertEqual(U.read(p / 'services.json')['astrbot']['image'], 'sha256:' + 'e' * 64)

    def test_checkpoint_promotes_only_selected_component(self):
        p = self.root / 'checkpoint'
        p.mkdir(mode=0o700)
        U.atom(p / 'services.json', {'astrbot': {'image': OLD}, 'snowluma': {'image': 'unchanged'}})
        self.apply()
        self.engine.tick()
        self.assertEqual(U.read(p / 'services.json'), {'astrbot': {'image': NEW}, 'snowluma': {'image': 'unchanged'}})

    def test_resource_guard_binding_tracks_upgrade_and_rollback(self):
        p = self.root / 'resource/config.json'
        U.atom(p, {'root': str(self.root), 'bindings': {'astrbot': {'image': OLD}, 'other': {'image': 'unchanged'}}})
        self.apply()
        self.assertEqual(U.read(p)['bindings']['astrbot']['image'], NEW)
        self.engine.tick(True)
        self.assertEqual(U.read(p)['bindings']['astrbot']['image'], OLD)
        self.assertEqual(U.read(p)['bindings']['other']['image'], 'unchanged')

    def test_new_boot_extends_observation(self):
        self.apply()
        with patch.object(U, 'boot', return_value='boot-two'):
            self.engine.watch_seconds = 900
            self.assertEqual(self.engine.tick()['state'], 'observing')
        self.assertEqual(self.info()['watch_uptime'], 1900)

    def test_status_never_contains_private_inspect_or_paths(self):
        self.apply()
        text = json.dumps(self.engine.status())
        self.assertNotIn('PRIVATE', text)
        self.assertNotIn('do-not-print', text)
        self.assertNotIn(str(self.root), text)

    def test_original_compose_is_not_written(self):
        p = self.root / 'astrbot/compose.yaml'
        p.write_text('operator-owned-original')
        self.apply()
        self.engine.tick()
        self.assertEqual(p.read_text(), 'operator-owned-original')

    def test_snowluma_keeps_all_three_data_mounts_and_login_file(self):
        self.docker = FakeDocker(self.root, 'snowluma')
        self.engine.docker = self.docker
        paths = [Path(m['Source']) for m in self.docker.original['Mounts']]
        for i, p in enumerate(paths):
            (p / 'private-login.json').write_text('synthetic-session-' + str(i))
        result = self.engine.apply('snowluma', '4.29.3')
        self.assertEqual(result['state'], 'observing')
        self.engine.tick()
        self.assertEqual(len(self.docker.items['snowluma']['Mounts']), 3)
        self.assertEqual(self.engine.tick(True)['state'], 'rolled_back')
        for i, p in enumerate(paths):
            self.assertEqual((p / 'private-login.json').read_text(), 'synthetic-session-' + str(i))

    def test_blocked_rollback_cannot_be_replaced_to_reset_budget(self):
        self.apply()
        self.docker.items['astrbot']['Config']['Labels'][U.LABEL] = 'foreign'
        self.engine.tick(True)
        with self.assertRaisesRegex(U.UpdateError, 'upgrade_already_active'):
            self.apply()

    def test_observation_after_repair_gets_a_full_new_window(self):
        self.apply()
        self.docker.stop('astrbot')
        self.engine.watch_seconds = 900
        self.assertEqual(self.engine.tick()['state'], 'observing')
        self.assertEqual(self.info()['watch_uptime'], 1900)


class BoundaryTests(unittest.TestCase):
    def test_closed_components(self):
        for v in ('shell', 'n8n', '../astrbot'):
            with self.assertRaises(U.UpdateError):
                U.component(v)

    def test_no_latest_prerelease_or_shell_tags(self):
        for v in ('latest', 'nightly', 'v1.2.3-rc1', 'v1.2.3;id', '--help', None):
            with self.assertRaises(U.UpdateError):
                U.version(v)
        self.assertEqual(U.version('1.2.3'), 'v1.2.3')

    def test_root_boundaries(self):
        for v in ('/', '/srv', '../x', '/srv/x/../y', '/srv/x;id'):
            with self.assertRaises(U.UpdateError):
                U.root_path(v)

    def test_plan_is_offline_and_unprivileged(self):
        p = subprocess.run([sys.executable, str(R / 'services/updater/manager.py'), '--root', '/srv/test', 'plan'],
                           capture_output=True, text=True, timeout=5)
        self.assertEqual(p.returncode, 0)
        self.assertTrue(json.loads(p.stdout)['dry_run'])

    def test_networkless_canary_has_no_ports_or_live_mounts(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t).resolve()
            d = FakeDocker(root)
            old = d.original
            p = root / 'clone'
            spec = U.create_spec(old, d.image(OLD), d.image(NEW), NEW, 'transaction', [p])
            self.assertEqual(spec['HostConfig']['NetworkMode'], 'none')
            self.assertEqual(spec['HostConfig']['PortBindings'], {})
            self.assertFalse(spec['HostConfig']['PublishAllPorts'])
            self.assertEqual(spec['HostConfig']['Mounts'][0]['Source'], str(p))
            self.assertNotIn('NetworkingConfig', spec)
            self.assertNotIn('com.docker.compose.service', spec['Labels'])

    def test_runtime_limits_and_networks_survive_cutover(self):
        with tempfile.TemporaryDirectory() as t:
            d = FakeDocker(Path(t).resolve())
            spec = U.create_spec(d.original, d.image(OLD), d.image(NEW), NEW, 'transaction')
            self.assertEqual(spec['HostConfig']['Memory'], 1536 * 1024**2)
            self.assertEqual(spec['NetworkingConfig']['EndpointsConfig']['core']['Aliases'], ['astrbot'])

    def test_new_image_defaults_and_operator_overrides_are_separate(self):
        with tempfile.TemporaryDirectory() as t:
            d = FakeDocker(Path(t).resolve())
            old = d.original
            defaults = d.image(OLD)
            defaults['Config']['Env'] = ['DEFAULT=old']
            new = d.image(NEW)
            new['Config'].update(Cmd=['python', 'new-main.py'], Env=['DEFAULT=new'])
            spec = U.create_spec(old, defaults, new, NEW, 'transaction')
            self.assertEqual(spec['Cmd'], ['python', 'new-main.py'])
            self.assertIn('PRIVATE=do-not-print', spec['Env'])
            self.assertIn('DEFAULT=new', spec['Env'])

    def test_privileged_and_extra_mounts_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            d = FakeDocker(Path(t).resolve())
            old = copy.deepcopy(d.original)
            old['HostConfig']['Privileged'] = True
            with self.assertRaises(U.UpdateError):
                U.validate_layout(d.root, 'astrbot', old, d)
            old = copy.deepcopy(d.original)
            old['Mounts'][0]['Destination'] = '/var/run/docker.sock'
            with self.assertRaises(U.UpdateError):
                U.validate_layout(d.root, 'astrbot', old, d)

    def test_sqlite_schema_drift_and_corruption_are_detected(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t).resolve()
            db = p / 'facts.db'
            with sqlite3.connect(db) as c:
                c.execute('CREATE TABLE fact(x)')
            before = U.schema_tree([p])
            with sqlite3.connect(db) as c:
                c.execute('ALTER TABLE fact ADD COLUMN y')
            self.assertNotEqual(before, U.schema_tree([p]))
            db.write_bytes(b'SQLite format 3\0' + b'bad' * 100)
            with self.assertRaises(U.UpdateError):
                U.schema_tree([p])

    def test_snapshot_preserves_symlinks_without_following(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t).resolve()
            a = p / 'a'
            a.mkdir()
            (a / 'outside').symlink_to('/etc')
            copies = U.snapshot([a], p / 'snapshot')
            self.assertTrue((copies[0] / 'outside').is_symlink())


if __name__ == '__main__':
    unittest.main()
