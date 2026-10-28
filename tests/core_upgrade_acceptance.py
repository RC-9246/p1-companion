#!/usr/bin/env python3
"""Opt-in real Docker/systemd fault lab. Never mounts production data.

Uses an existing local workbench image as a Python base, builds tiny fixture
programs without network, and maps every logical container to a unique prefix.
It does not download or upgrade AstrBot/SnowLuma or send QQ/model requests.
"""
import argparse, contextlib, copy, hashlib, importlib.util, json, os, shutil
import signal, sqlite3, subprocess, tempfile, time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
S = importlib.util.spec_from_file_location('updater', ROOT / 'services/updater/manager.py')
U = importlib.util.module_from_spec(S)
S.loader.exec_module(U)

PROGRAM = '''import os,time,json,pathlib,sqlite3,http.server
p=pathlib.Path('/AstrBot/data');p.mkdir(exist_ok=True)
role=os.environ.get('ROLE','old')
if role=='new' and (p/'permanent-failure').exists():raise SystemExit(8)
with sqlite3.connect(p/'facts.db') as c:
 c.execute('CREATE TABLE IF NOT EXISTS facts(text)')
 if role=='schema':c.execute('CREATE TABLE IF NOT EXISTS incompatible(value)')
if role=='bad':raise SystemExit(9)
h=p/'plugin_data/affect';h.mkdir(parents=True,exist_ok=True)
(h/'companion_health.json').write_text(json.dumps({'phase':'ready','at':int(time.time()),**{k:True for k in %r}}))
class Handler(http.server.BaseHTTPRequestHandler):
 def do_GET(self):self.send_response(200);self.end_headers();self.wfile.write(b'fixture')
 def log_message(self,*a):pass
http.server.HTTPServer(('0.0.0.0',6185),Handler).serve_forever()
''' % (U.HEALTH_KEYS,)


class LabDocker(U.Docker):
    def __init__(self, prefix):
        self.prefix = prefix
        super().__init__()

    def mapped(self, name):
        return name if name.startswith(self.prefix) else self.prefix + name

    def inspect(self, name):
        obj = super().inspect(self.mapped(name))
        if obj:
            obj['Name'] = '/' + name.removeprefix(self.prefix)
        return obj

    def stop(self, name):
        return super().stop(self.mapped(name))

    def start(self, name):
        return super().start(self.mapped(name))

    def remove(self, name):
        return super().remove(self.mapped(name))

    def rename(self, name, new):
        return super().rename(self.mapped(name), self.mapped(new))

    def create(self, name, spec):
        return super().create(self.mapped(name), spec)

    def restart_policy(self, name, value):
        return super().restart_policy(self.mapped(name), value)

    def freeze(self, name, ident):
        return super().freeze(self.mapped(name), ident)

    def probe(self, name, kind, canary=False, fresh_after=0):
        return super().probe(self.mapped(name), kind, canary, fresh_after)


class LabSystem:
    def __init__(self, root):
        self.home = root / 'control'
        self.home.mkdir(mode=0o700, exist_ok=True)
        self.paused = False

    def timer_states(self):
        return {x: {'active': False, 'enabled': False} for x in U.TIMERS}

    def arm(self):
        pass  # Actual systemd entrypoint is exercised separately against an idle root.

    def quiesce(self):
        self.paused = True

    def restore_timers(self, states):
        self.paused = False


def command(args, timeout=90):
    p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if p.returncode:
        raise RuntimeError('lab_command_failed:' + args[0])
    return p.stdout


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--run', action='store_true')
    ap.add_argument('--output', type=Path)
    a = ap.parse_args()
    if not a.run:
        print(json.dumps({'dry_run': True, 'requires': 'Linux root, Docker, systemd, existing p1-workbench image',
                          'production_upgrade': False, 'external_network': False}))
        return
    assert os.geteuid() == 0 and Path('/run/systemd/system').is_dir()
    os.umask(0o077)
    stamp = str(time.time_ns())
    base = Path(tempfile.mkdtemp(prefix='p1-core-upgrade-lab-')).resolve()
    prefix = 'p1-upgrade-lab-' + stamp + '-'
    net = prefix + 'net'
    images, rows, systems = {}, [], []
    original_checkpoint, original_resource = U.CHECKPOINT, U.RESOURCE_CONFIG
    originals = json.loads(command(['docker', 'inspect', 'astrbot', 'snowluma']))
    before = [(v['Id'], v['State']['StartedAt'], v['RestartCount']) for v in originals]
    try:
        image = json.loads(command(['docker', 'inspect', 'p1-workbench']))[0]['Image']
        base_tag = json.loads(command(['docker', 'image', 'inspect', image]))[0]['RepoTags'][0]
        assert json.loads(command(['docker', 'image', 'inspect', base_tag]))[0]['Id'] == image
        build = base / 'build'
        build.mkdir()
        (build / 'program.py').write_text(PROGRAM)
        for role in ('old', 'new', 'bad', 'schema'):
            (build / 'Dockerfile').write_text('FROM ' + base_tag + '\nUSER root\nCOPY program.py /core-upgrade-fixture.py\nENV ROLE=' + role + '\nENTRYPOINT []\nCMD ["python","/core-upgrade-fixture.py"]\n')
            tag = 'p1-core-upgrade-fixture:' + stamp + '-' + role
            command(['docker', 'build', '--network=none', '-q', '-t', tag, str(build)])
            images[role] = json.loads(command(['docker', 'image', 'inspect', tag]))[0]['Id']
        command(['docker', 'network', 'create', '--internal', net])

        def case(name, role='new'):
            root = base / ('case-' + str(len(systems)))
            data = root / 'astrbot/data'
            data.mkdir(parents=True)
            with sqlite3.connect(data / 'facts.db') as c:
                c.execute('CREATE TABLE facts(text)')
                c.execute("INSERT INTO facts VALUES ('before')")
            d = LabDocker(prefix + str(len(systems)) + '-')
            sy = LabSystem(root)
            systems.append((d, sy))
            spec = {'Image': images['old'], 'Labels': {'com.docker.compose.service': 'astrbot',
                    'com.docker.compose.project': 'fixture', 'com.docker.compose.project.config_files': str(root / 'astrbot/compose.yaml')},
                    'HostConfig': {'NetworkMode': net, 'Memory': 128 * 1024**2,
                                   'Binds': [str(data) + ':/AstrBot/data']}}
            d.create('astrbot', spec)
            d.start('astrbot')
            e = U.Engine(root, d, sy)
            e.poll, e.boot_wait, e.canary_wait, e.watch_seconds = .3, 6, 8, 0
            assert e.wait('astrbot', 'astrbot', 8)
            e.resolve = lambda *args: images[role]
            U.CHECKPOINT, U.RESOURCE_CONFIG = root / 'checkpoint', root / 'resource/config.json'
            return root, data, d, e

        def apply(e):
            with patch.object(U, 'catalog', return_value={'versions': [{'version': 'v4.29.3'}]}):
                return e.apply('astrbot', 'v4.29.3')

        root, data, d, e = case('healthy')
        assert apply(e)['state'] == 'observing'
        assert e.tick()['state'] == 'succeeded'
        rows.append({'case': 'real_image_switch_and_commit', 'ok': True})
        assert not list((root / 'backups').glob('*/canary-data/0/*private*'))
        obj = d.inspect('astrbot')
        assert obj['HostConfig']['Memory'] == 128 * 1024**2 and set(obj['NetworkSettings']['Networks']) == {net}
        rows.append({'case': 'runtime_limits_network_and_mounts_preserved', 'ok': True})
        with sqlite3.connect(data / 'facts.db') as c:
            c.execute("INSERT INTO facts VALUES ('new chat after upgrade')")
        assert e.tick(True)['state'] == 'rolled_back'
        with sqlite3.connect(data / 'facts.db') as c:
            assert [r[0] for r in c.execute('SELECT text FROM facts')] == ['before', 'new chat after upgrade']
        rows.append({'case': 'manual_rollback_after_commit_keeps_new_chat', 'ok': True})

        root, data, d, e = case('bad', 'bad')
        old_id = d.inspect('astrbot')['Id']
        assert apply(e)['state'] == 'rolled_back'
        assert d.inspect('astrbot')['Id'] == old_id
        rows.append({'case': 'bad_image_rejected_without_live_data_start', 'ok': True})

        root, data, d, e = case('schema', 'schema')
        result = apply(e)
        assert result['state'] == 'rolled_back' and result['error'] == 'schema_migration_requires_review'
        with sqlite3.connect(data / 'facts.db') as c:
            assert not c.execute("SELECT name FROM sqlite_master WHERE name='incompatible'").fetchall()
        rows.append({'case': 'real_sqlite_migration_rejected_on_copy', 'ok': True})

        root, data, d, e = case('repair')
        assert apply(e)['state'] == 'observing'
        d.stop('astrbot')
        v = e.tick()
        assert v['state'] == 'succeeded' and v['repairs'] == ['restart_candidate']
        rows.append({'case': 'probation_stopped_process_repaired', 'ok': True})

        root, data, d, e = case('persistent-failure')
        assert apply(e)['state'] == 'observing'
        (data / 'permanent-failure').touch()
        with sqlite3.connect(data / 'facts.db') as c:
            c.execute("INSERT INTO facts VALUES ('retain during failure')")
        d.stop('astrbot')
        v = e.tick()
        assert v['state'] == 'rolled_back' and len(v['repairs']) == 2
        with sqlite3.connect(data / 'facts.db') as c:
            assert c.execute('SELECT count(*) FROM facts').fetchone()[0] == 2
        rows.append({'case': 'persistent_failure_bounded_repair_then_rollback_keeps_data', 'ok': True})

        root, data, d, e = case('killed-before-cutover')
        original = e.canary
        def kill_after_canary(*args):
            original(*args)
            os.kill(os.getpid(), signal.SIGKILL)
        e.canary = kill_after_canary
        pid = os.fork()
        if pid == 0:
            apply(e)
            os._exit(20)
        _, status = os.waitpid(pid, 0)
        assert os.WIFSIGNALED(status) and os.WTERMSIG(status) == signal.SIGKILL
        e.canary = original
        assert e.tick()['state'] == 'rolled_back'
        rows.append({'case': 'sigkill_before_cutover_recovers_from_persistent_journal', 'ok': True})

        root, data, d, e = case('killed-after-cutover')
        original = d.start
        def kill_after_live_start(name):
            original(name)
            if name == 'astrbot' and d.inspect(name)['Image'] == images['new']:
                time.sleep(1)
                os.kill(os.getpid(), signal.SIGKILL)
        d.start = kill_after_live_start
        pid = os.fork()
        if pid == 0:
            apply(e)
            os._exit(20)
        _, status = os.waitpid(pid, 0)
        assert os.WIFSIGNALED(status) and os.WTERMSIG(status) == signal.SIGKILL
        d.start = original
        assert e.tick()['state'] == 'rolled_back'
        rows.append({'case': 'sigkill_after_live_start_recovers_previous_runtime', 'ok': True})

        # Native persistent entrypoint, but no active transaction or production target.
        native_root = base / 'native-idle'
        native_root.mkdir()
        sy = U.System(native_root)
        unit = 'p1-core-update-' + sy.key
        try:
            sy.arm()
            command(['systemctl', 'start', unit + '.service'])
            assert command(['systemctl', 'is-enabled', unit + '.timer']).strip() == 'enabled'
            assert command(['systemctl', 'show', '-p', 'Result', '--value', unit + '.service']).strip() == 'success'
            rows.append({'case': 'native_persistent_timer_and_idle_service_entrypoint', 'ok': True})
        finally:
            subprocess.run(['systemctl', 'disable', '--now', unit + '.timer'], capture_output=True)
            subprocess.run(['systemctl', 'stop', unit + '.service'], capture_output=True)
            for suffix in ('.timer', '.service'):
                (Path('/etc/systemd/system') / (unit + suffix)).unlink(missing_ok=True)
            subprocess.run(['systemctl', 'daemon-reload'], capture_output=True)
            shutil.rmtree(sy.home)
    finally:
        U.CHECKPOINT, U.RESOURCE_CONFIG = original_checkpoint, original_resource
        for d, sy in systems:
            for name in command(['docker', 'ps', '-aq', '--filter', 'name=' + d.prefix]).split():
                subprocess.run(['docker', 'rm', '-f', name], capture_output=True)
        subprocess.run(['docker', 'network', 'rm', net], capture_output=True)
        for role in images:
            subprocess.run(['docker', 'image', 'rm', 'p1-core-upgrade-fixture:' + stamp + '-' + role], capture_output=True)
        # Remove only rollback images created by this lab's transaction IDs.
        for p in base.glob('case-*/control/active.json'):
            with contextlib.suppress(Exception):
                image = U.read(p).get('rollback_image')
                if image:
                    subprocess.run(['docker', 'image', 'rm', image], capture_output=True)
        after_objects = json.loads(command(['docker', 'inspect', 'astrbot', 'snowluma']))
        after = [(v['Id'], v['State']['StartedAt'], v['RestartCount']) for v in after_objects]
        production_unchanged = before == after
        result = {'schema': 1, 'at': int(time.time()), 'tests': rows,
                  'passed': len(rows), 'production_core_unchanged': production_unchanged,
                  'real_docker': bool(rows), 'real_process_sigkill': sum('sigkill' in r['case'] for r in rows) == 2,
                  'native_idle_systemd_entrypoint': any('native_persistent' in r['case'] for r in rows),
                  'real_upstream_upgrade': False, 'whole_host_reboot_tested': False,
                  'account_login_and_qq_delivery_tested': False}
        if a.output:
            a.output.parent.mkdir(parents=True, exist_ok=True)
            a.output.write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result))
        shutil.rmtree(base)
        assert production_unchanged


if __name__ == '__main__':
    main()
