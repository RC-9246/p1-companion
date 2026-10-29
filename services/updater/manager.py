#!/usr/bin/env python3
"""Administrator-operated core image upgrades; no model-generated repair commands.

The retained old container and immutable image are recovery assets, not backups of
new conversations. Rollback always keeps current live data. Networkless canaries
and schema gates deliberately reject migrations that are not known reversible.
"""
import argparse, contextlib, copy, fcntl, hashlib, http.client, json, os, re
import secrets, shutil, socket, sqlite3, stat, subprocess, sys, time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

POLICY = {
    'astrbot': {'repo': 'AstrBotDevs/AstrBot', 'image': 'soulter/astrbot',
                'mounts': ['/AstrBot/data']},
    'snowluma': {'repo': 'SnowLuma/SnowLuma', 'image': 'motricseven7/snowluma',
                 'mounts': ['/app/data', '/app/.config', '/app/.local/share']},
}
LABEL = 'org.p1-companion.core-upgrade'
TIMERS = ('p1-companion-maintain.timer', 'p1-companion-watchdog.timer')
TERMINAL = {'succeeded', 'rolled_back', 'rejected', 'rollback_blocked'}
HEALTH_KEYS = ('group_memory_ready', 'group_affect_ready', 'learning_ready',
               'qq_plain_ready', 'agency_ready')
ROOT_STATE = Path('/var/lib/p1-companion-updates')
CHECKPOINT = Path('/var/lib/p1-companion/recovery/current')
RESOURCE_CONFIG = Path('/var/lib/p1-companion-resource/config.json')


def boot():
    return Path('/proc/sys/kernel/random/boot_id').read_text().strip()


def uptime():
    return float(Path('/proc/uptime').read_text().split()[0])


def public_status(root):
    home = ROOT_STATE / hashlib.sha256(str(root_path(str(root))).encode()).hexdigest()[:16]
    if not (home / 'active.json').exists():
        return {'state': 'idle', 'automatic_version_installation': False}
    protected(home)
    v = read(home / 'active.json')
    return {k: v[k] for k in ('id', 'component', 'version', 'state', 'stage', 'repairs', 'error', 'at', 'watch_until') if k in v}


class UpdateError(RuntimeError):
    pass


def need(ok, code):
    if not ok:
        raise UpdateError(code)


def root_path(value):
    p = Path(value)
    need(p.is_absolute() and len(p.parts) >= 3 and '..' not in p.parts and
         re.fullmatch(r'/[A-Za-z0-9_./-]+', str(p)), 'invalid_root')
    need(not any(q.is_symlink() for q in (p, *p.parents)), 'symlink_denied')
    return p


def version(value):
    need(isinstance(value, str) and bool(re.fullmatch(r'v?[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,4}', value)),
         'stable_version_required')
    return 'v' + value.removeprefix('v')


def component(value):
    need(value in POLICY, 'component_denied')
    return value


def read(path):
    path = Path(path)
    need(not path.is_symlink() and path.stat().st_size <= 16 * 1024**2, 'untrusted_record')
    return json.loads(path.read_bytes())


def atom(path, value):
    path = Path(path)
    need(not any(p.is_symlink() for p in (path, *path.parents)), 'symlink_denied')
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name(path.name + '.' + secrets.token_hex(6) + '.next')
    try:
        with tmp.open('x', encoding='utf-8') as f:
            os.chmod(tmp, 0o600)
            json.dump(value, f, ensure_ascii=False, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        tmp.unlink(missing_ok=True)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def protected(path):
    p = Path(path)
    need(not any(q.is_symlink() for q in (p, *p.parents)), 'symlink_denied')
    s = p.stat()
    need(s.st_uid == os.geteuid() and not s.st_mode & 0o077, 'private_record_permissions')


@contextlib.contextmanager
def exclusive(path):
    p = Path(path)
    need(not any(q.is_symlink() for q in (p,*p.parents)), 'symlink_denied')
    p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd=os.open(p,os.O_RDWR|os.O_CREAT|getattr(os,'O_NOFOLLOW',0),0o600)
    with os.fdopen(fd,'a') as f:
        need(os.fstat(f.fileno()).st_nlink==1,'untrusted_lock')
        os.fchmod(f.fileno(),0o600)
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise UpdateError('operation_busy') from None
        yield


def lifecycle_lock(root):
    return Path(root)/'astrbot/data/plugin_data/affect/lifecycle.lock'


def run(args, timeout=60):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                           stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        raise UpdateError('bounded_command_failed') from None
    need(p.returncode == 0, 'bounded_command_failed')
    return p.stdout


def catalog(name):
    name = component(name)
    req = Request('https://api.github.com/repos/' + POLICY[name]['repo'] + '/releases?per_page=15',
                  headers={'User-Agent': 'p1-companion-core-updater', 'Accept': 'application/vnd.github+json'})
    try:
        with urlopen(req, timeout=15) as r:
            need(r.url.startswith('https://api.github.com/'), 'release_destination_changed')
            raw = r.read(2 * 1024**2 + 1)
        need(len(raw) <= 2 * 1024**2, 'release_response_too_large')
        rows = json.loads(raw)
        need(isinstance(rows, list), 'release_catalog_unavailable')
        result = []
        for row in rows:
            if row.get('draft') or row.get('prerelease'):
                continue
            try:
                tag = version(row['tag_name'])
            except (UpdateError, KeyError):
                continue
            result.append({'version': tag, 'released': str(row.get('published_at', ''))[:20],
                           'url': 'https://github.com/' + POLICY[name]['repo'] + '/releases/tag/' + tag})
        return {'component': name, 'versions': result, 'image_available_not_yet_checked': True}
    except UpdateError:
        raise
    except Exception:
        raise UpdateError('release_catalog_unavailable') from None


class UnixHTTP(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect('/var/run/docker.sock')


class Docker:
    """Fixed local Docker socket; no caller-supplied daemon, URL or shell command."""
    def __init__(self):
        self.api = ''
        v = self.request('GET', '/version')
        need(re.fullmatch(r'1\.[0-9]{2,3}', v.get('ApiVersion', '')), 'docker_api_unavailable')
        self.api = '/v' + v['ApiVersion']

    def request(self, method, path, body=None, missing=False, timeout=30):
        c = UnixHTTP('localhost', timeout=timeout)
        try:
            c.request(method, self.api + path, None if body is None else json.dumps(body),
                      {'Content-Type': 'application/json'})
            r = c.getresponse()
            raw = r.read(16 * 1024**2 + 1)
            need(len(raw) <= 16 * 1024**2, 'docker_response_too_large')
            if r.status == 404 and missing:
                return None
            need(200 <= r.status < 300 or r.status == 304, 'docker_operation_failed')
            return json.loads(raw) if raw else {}
        except UpdateError:
            raise
        except (OSError, ValueError, http.client.HTTPException):
            raise UpdateError('docker_unavailable') from None
        finally:
            c.close()

    def inspect(self, name):
        return self.request('GET', '/containers/' + quote(name, safe='') + '/json', missing=True)

    def image(self, name):
        return self.request('GET', '/images/' + quote(name, safe='') + '/json')

    def stop(self, name):
        self.request('POST', '/containers/' + quote(name, safe='') + '/stop?t=20', timeout=45)

    def start(self, name):
        self.request('POST', '/containers/' + quote(name, safe='') + '/start')

    def remove(self, name):
        self.request('DELETE', '/containers/' + quote(name, safe='') + '?force=true&v=false')

    def rename(self, name, new):
        self.request('POST', '/containers/' + quote(name, safe='') + '/rename?name=' + quote(new, safe=''))

    def create(self, name, spec):
        self.request('POST', '/containers/create?name=' + quote(name, safe=''), spec)

    def restart_policy(self, name, value):
        self.request('POST', '/containers/' + quote(name, safe='') + '/update', {'RestartPolicy': value})

    def freeze(self, name, ident):
        # Mounted data is excluded by Docker. Keep the old writable program layer,
        # including dependencies previously installed with docker exec, locally.
        return self.request('POST', '/commit?container=' + quote(name, safe='') +
                            '&pause=false&repo=p1-companion/rollback&tag=' + ident,
                            timeout=180)['Id']

    def probe(self, name, kind, canary=False, fresh_after=0):
        obj = self.inspect(name)
        if not obj or not obj['State'].get('Running') or obj['State'].get('OOMKilled'):
            return False
        if obj['State'].get('Health', {}).get('Status') == 'unhealthy':
            return False
        if kind == 'astrbot':
            started = obj['State'].get('StartedAt')
            if started:
                fresh_after = max(fresh_after, datetime.fromisoformat(started.replace('Z', '+00:00')).timestamp())
            script = """import json, pathlib, urllib.request, time
urllib.request.urlopen('http://127.0.0.1:6185/',timeout=3).close()
p=pathlib.Path('/AstrBot/data/plugin_data/affect/companion_health.json')
v=json.loads(p.read_text())
assert v.get('phase') in ('ready','serving') and max(%r,time.time()-300)<=v.get('at',0)<=time.time()+10
assert all(v.get(k) is True for k in %r)
""" % (int(fresh_after), HEALTH_KEYS)
            args = ['docker', 'exec', name, 'python', '-c', script]
        else:
            script = """const fs=require('fs');(async()=>{
const w=await fetch('http://127.0.0.1:5099/',{signal:AbortSignal.timeout(3000)});if(!w.ok)process.exit(2);
if(%s)process.exit(0);
let cfg=[];for(const f of fs.readdirSync('/app/data/config').filter(f=>/^onebot.*\\.json$/.test(f))){
let v=JSON.parse(fs.readFileSync('/app/data/config/'+f));cfg.push(...(v.networks?.httpServers||[]));}
let rows=cfg.filter(s=>s.enabled!==false&&s.enable!==false&&Number(s.port)===3000).slice(0,4);if(!rows.length)process.exit(3);
for(let s of rows){try{let r=await fetch('http://127.0.0.1:3000/get_status',{headers:{Authorization:'Bearer '+(s.accessToken||'')},signal:AbortSignal.timeout(3000)});
let v=await r.json();if(v.status==='ok'&&v.data?.online===true&&v.data?.good!==false)process.exit(0);}catch{}}
process.exit(4);
})().catch(()=>process.exit(5));""" % ('true' if canary else 'false')
            args = ['docker', 'exec', name, 'node', '-e', script]
        try:
            run(args, 15)
            return True
        except UpdateError:
            return False


def core_compose_layout(root,kind,labels):
    """Accept only the base file or the installer's committed integration overlay."""
    if labels.get('com.docker.compose.service')!=kind:return False
    files=labels.get('com.docker.compose.project.config_files','').split(',')
    if files==[str(root/kind/'compose.yaml')]:return True
    if kind!='astrbot' or len(files)!=2 or files[0]!=str(root/kind/'compose.yaml'):return False
    try:
        overlay=root_path(files[1]);rel=overlay.relative_to(root)
        if len(rel.parts)!=3 or rel.parts[0]!='backups' or not re.fullmatch(r'oneclick-[A-Za-z0-9_-]+',rel.parts[1]) or rel.parts[2]!='companion-override.json':return False
        state=read(overlay.parent/'state.json');data=read(overlay)
        return state.get('root')==str(root) and state.get('status')=='committed' and set(data)<= {'services','networks'} and set(data.get('services',{}))=={'astrbot'} and set(data['services']['astrbot'])<= {'image','networks'}
    except (ValueError,OSError,UpdateError):return False

def validate_layout(root, kind, obj, docker):
    need(obj and obj.get('Name') == '/' + kind, 'core_container_unavailable')
    labels = obj.get('Config', {}).get('Labels') or {}
    need(core_compose_layout(root,kind,labels),
         'unsupported_compose_layout')
    host = obj['HostConfig']
    need(not host.get('Privileged') and host.get('NetworkMode') not in ('host', 'none') and
         not host.get('PidMode') and not host.get('IpcMode', '').startswith('container:') and
         not host.get('VolumesFrom') and not host.get('ContainerIDFile'), 'unsupported_container_settings')
    destinations = set()
    for m in obj['Mounts']:
        need(m['Destination'] in POLICY[kind]['mounts'] and m.get('RW') is True and
             m['Type'] in ('bind', 'volume'), 'unsupported_mount')
        p = root_path(m['Source'])
        need(p.is_dir(), 'mount_unavailable')
        if m['Type'] == 'bind':
            need(p.is_relative_to(root / kind), 'mount_outside_component')
        else:
            vol = docker.request('GET', '/volumes/' + quote(m['Name'], safe=''))
            vl = vol.get('Labels') or {}
            need(vol.get('Driver') == 'local' and not vol.get('Options') and
                 vl.get('com.docker.compose.project') == labels.get('com.docker.compose.project') and
                 vol.get('Mountpoint') == str(p), 'foreign_or_remote_volume')
        destinations.add(m['Destination'])
    need(destinations == set(POLICY[kind]['mounts']), 'core_mounts_incomplete')
    for n in obj['NetworkSettings']['Networks'].values():
        need(not n.get('IPAMConfig'), 'static_network_requires_manual_upgrade')


def schema_tree(paths):
    result = {}
    for n, base in enumerate(paths):
        for p in Path(base).rglob('*'):
            if p.is_symlink() or p.suffix not in ('.db', '.sqlite', '.sqlite3') or not p.is_file():
                continue
            # Unrelated cache files with a .db suffix are not SQLite databases.
            with p.open('rb') as f:
                if f.read(16) != b'SQLite format 3\0':
                    continue
            try:
                with sqlite3.connect(p.as_uri() + '?mode=ro', uri=True, timeout=3) as c:
                    need(c.execute('PRAGMA quick_check').fetchone()[0] == 'ok', 'database_integrity_failed')
                    rows = c.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()
                    v = c.execute('PRAGMA user_version').fetchone()[0]
                    result[str(n) + '/' + str(p.relative_to(base))] = hashlib.sha256(json.dumps([v, rows], sort_keys=True).encode()).hexdigest()
            except sqlite3.Error:
                raise UpdateError('database_integrity_failed') from None
    return result


def tree_size(paths):
    count = total = 0
    for base in paths:
        for p in Path(base).rglob('*'):
            if p.is_symlink():
                continue
            s = p.stat()
            if stat.S_ISREG(s.st_mode):
                count += 1
                total += s.st_size
    need(count <= 250000, 'snapshot_file_budget_exceeded')
    return total


def snapshot(paths, destination):
    destination = Path(destination)
    need(not destination.exists(), 'snapshot_already_exists')
    size = tree_size(paths)
    need(shutil.disk_usage(destination.parent).free >= size * 2 + 1024**3, 'snapshot_disk_budget_exceeded')
    destination.mkdir(mode=0o700)
    for i, source in enumerate(paths):
        shutil.copytree(source, destination / str(i), symlinks=True,
                        ignore=lambda p, names: [n for n in names if not (Path(p) / n).is_symlink()
                                                and not stat.S_ISREG((Path(p) / n).stat().st_mode)
                                                and not stat.S_ISDIR((Path(p) / n).stat().st_mode)])
    return [destination / str(i) for i in range(len(paths))]


def create_spec(old, old_image, target_image, target_id, transaction, canary_paths=None):
    original, defaults, new = old['Config'], old_image['Config'], target_image['Config']
    config = {k: copy.deepcopy(v) for k, v in original.items() if k in
              ('Env', 'Labels', 'User', 'WorkingDir', 'ExposedPorts', 'Tty', 'OpenStdin', 'StdinOnce',
               'AttachStdin', 'AttachStdout', 'AttachStderr', 'StopSignal', 'StopTimeout', 'Volumes')}
    # Keep deliberate operator overrides, use new defaults for image-owned settings.
    for k in ('Cmd', 'Entrypoint', 'WorkingDir', 'User', 'Healthcheck'):
        config[k] = copy.deepcopy(new.get(k) if original.get(k) == defaults.get(k) else original.get(k))
    base_env = dict(x.split('=', 1) for x in defaults.get('Env', []))
    env = dict(x.split('=', 1) for x in new.get('Env', []))
    env.update({k: v for k, v in (x.split('=', 1) for x in original.get('Env', [])) if base_env.get(k) != v})
    config['Env'] = [k + '=' + v for k, v in env.items()]
    config['Image'] = target_id
    config['Labels'] = {**(config.get('Labels') or {}), LABEL: transaction}
    host = copy.deepcopy(old['HostConfig'])
    host['AutoRemove'] = False
    endpoints = {}
    for key, v in old['NetworkSettings']['Networks'].items():
        endpoints[key] = {'Aliases': [a for a in v.get('Aliases') or [] if a not in (old['Id'], old['Id'][:12])]}
    if canary_paths is not None:
        config['Labels'] = {LABEL: transaction, LABEL + '.canary': 'true'}
        host.update(NetworkMode='none', PortBindings={}, RestartPolicy={'Name': 'no'},
                    PublishAllPorts=False, Binds=None, Mounts=[{'Type': 'bind', 'Source': str(p), 'Target': m['Destination'], 'ReadOnly': False}
                                       for m, p in zip(old['Mounts'], canary_paths)])
        # No host namespace, IPC sharing or published ports in a canary.
        host.update(PidMode='', IpcMode='private', UTSMode='')
        endpoints = {}
        config.pop('ExposedPorts', None)
    config['HostConfig'] = host
    if endpoints:
        config['NetworkingConfig'] = {'EndpointsConfig': endpoints}
    return {k: v for k, v in config.items() if v is not None}


class System:
    def __init__(self, root):
        self.root = root
        self.key = hashlib.sha256(str(root).encode()).hexdigest()[:16]
        self.home = ROOT_STATE / self.key
        self.home.mkdir(parents=True, exist_ok=True, mode=0o700)
        protected(self.home)

    def timer_states(self):
        return {t: {'enabled': subprocess.run(['systemctl', 'is-enabled', '--quiet', t], capture_output=True).returncode == 0,
                    'active': subprocess.run(['systemctl', 'is-active', '--quiet', t], capture_output=True).returncode == 0}
                for t in TIMERS}

    def quiesce(self):
        run(['systemctl', 'stop', *TIMERS])
        for unit in ('p1-companion-maintain.service', 'p1-companion-watchdog.service'):
            end = time.monotonic() + 90
            while subprocess.run(['systemctl', 'show', '-p', 'ActiveState', '--value', unit], capture_output=True,
                                 text=True, timeout=15).stdout.strip() in ('active', 'activating', 'deactivating', 'reloading'):
                need(time.monotonic() < end, 'maintenance_busy')
                time.sleep(1)

    def restore_timers(self, states):
        for unit, row in states.items():
            need(unit in TIMERS, 'timer_denied')
            for verb in (('enable' if row['enabled'] else 'disable'), ('start' if row['active'] else 'stop')):
                subprocess.run(['systemctl', verb, unit], capture_output=True, timeout=30)
        need(self.timer_states() == states, 'maintenance_timer_restore_failed')

    def arm(self):
        helper = self.home / 'manager.py'
        raw = Path(__file__).read_bytes()
        tmp = self.home / 'manager.next'
        tmp.write_bytes(raw)
        tmp.chmod(0o700)
        os.replace(tmp, helper)
        name = 'p1-core-update-' + self.key
        unit = Path('/etc/systemd/system')
        service = '[Unit]\nDescription=Recover and observe P1 core upgrades\nAfter=docker.service\n[Service]\nType=oneshot\nUser=root\nUMask=0077\nExecStart=/usr/bin/python3 ' + str(helper) + ' --root ' + str(self.root) + ' tick\nTimeoutStartSec=1200\n'
        timer = '[Unit]\nDescription=P1 core upgrade observation\n[Timer]\nOnBootSec=45s\nOnUnitActiveSec=30s\n[Install]\nWantedBy=timers.target\n'
        for suffix, text in (('.service', service), ('.timer', timer)):
            p = unit / (name + suffix)
            need(not p.is_symlink() and (not p.exists() or p.read_text() == text), 'update_unit_conflict')
            p.write_text(text)
            p.chmod(0o644)
        run(['systemctl', 'daemon-reload'])
        run(['systemctl', 'enable', '--now', name + '.timer'])


class Engine:
    def __init__(self, root, docker=None, system=None):
        self.root = root_path(str(root))
        self.docker = docker or Docker()
        self.system = system or System(self.root)
        self.home = self.system.home
        self.boot_wait = 180
        self.canary_wait = 100
        self.watch_seconds = 900
        self.poll = 3

    def save(self, info):
        atom(self.home / 'active.json', info)

    def status(self):
        if not (self.home / 'active.json').exists():
            return {'state': 'idle', 'automatic_version_installation': False}
        v = read(self.home / 'active.json')
        return {k: v[k] for k in ('id', 'component', 'version', 'state', 'stage', 'repairs', 'error', 'at', 'watch_until') if k in v}

    def terminal_cleanup(self, info):
        if info['state'] not in ('succeeded', 'rolled_back', 'rejected'):
            return
        if info['state'] == 'succeeded':
            previous = self.docker.inspect(info['old_name'])
            if previous:
                need(previous['Id'] == info['old_id'], 'retained_container_changed')
                self.docker.remove(info['old_name'])
        self.system.restore_timers(info['timers'])
        info['timer_restore_done'] = True
        self.save(info)

    def bind_resource_guard(self, info, image):
        p = RESOURCE_CONFIG
        if not p.exists():
            return
        protected(p)
        with exclusive(p.parent / 'guard.lock'):
            v = read(p)
            need(v.get('root') == str(self.root), 'resource_guard_root_changed')
            row = v['bindings'][info['component']]
            need(row['image'] in {info['old_image'], info['target'], info.get('rollback_image')},
                 'resource_guard_binding_changed')
            row['image'] = image
            atom(p, v)

    def paths(self, info):
        return [Path(x['Source']) for x in read(Path(info['point']) / 'old.json')['Mounts']]

    def wait(self, name, kind, seconds, canary=False, fresh_after=0):
        end = time.monotonic() + seconds
        successes = 0
        previous = None
        while True:
            obj = self.docker.inspect(name)
            current = None if not obj else (obj['Id'], obj['State'].get('StartedAt'), obj.get('RestartCount', 0))
            if current != previous:
                successes = 0
                previous = current
            if self.docker.probe(name, kind, canary, fresh_after):
                successes += 1
                if successes >= 3:
                    return True
            else:
                successes = 0
            if time.monotonic() >= end:
                return False
            time.sleep(self.poll)

    def owned(self, name, info):
        obj = self.docker.inspect(name)
        need(not obj or (obj['Config'].get('Labels') or {}).get(LABEL) == info['id'], 'container_binding_changed')
        return obj

    def canary(self, info, image_id, paths):
        point = Path(info['point'])
        old = read(point / 'old.json')
        image = self.docker.image(image_id)
        spec = create_spec(old, read(point / 'old-image.json'), image, image_id, info['id'], paths)
        name = 'p1-canary-' + info['id']
        fresh = time.time()
        if info['component'] == 'astrbot':
            stamp = paths[0] / 'plugin_data/affect/companion_health.json'
            need(not stamp.is_symlink(), 'symlink_denied')
            stamp.unlink(missing_ok=True)
        self.docker.create(name, spec)
        try:
            self.docker.start(name)
            return self.wait(name, info['component'], self.canary_wait, True, fresh)
        finally:
            if self.owned(name, info):
                self.docker.remove(name)

    def resolve(self, kind, tag, source):
        ref = POLICY[kind]['image'] + ':' + version(tag)
        run(['docker', 'pull', ref], 900)
        base = self.docker.image(ref)
        need(re.fullmatch(r'sha256:[a-f0-9]{64}', base['Id']), 'invalid_image_identity')
        if kind == 'astrbot':
            # Rebuild known companion dependencies before stopping the live bot.
            need(source is not None, 'verified_source_required')
            source = root_path(str(source))
            manifest = read(source / 'source-manifest.json')
            for rel in ('deploy/AstrBot.Dockerfile', 'requirements-tested.txt'):
                p = source / rel
                need(not p.is_symlink() and digest(p) == manifest.get(rel), 'dependency_source_changed')
            target = 'p1-companion/astrbot:upgrade-' + base['Id'][7:19]
            base_tag = 'p1-companion/upgrade-base:' + base['Id'][7:19] + '-' + secrets.token_hex(4)
            run(['docker', 'tag', base['Id'], base_tag])
            # Never send an operator's entire checkout (possibly with private
            # files) as Docker build context. Only the two reviewed inputs.
            build = self.home / ('build-' + secrets.token_hex(4))
            build.mkdir(mode=0o700)
            try:
                shutil.copy2(source / 'deploy/AstrBot.Dockerfile', build / 'Dockerfile')
                shutil.copy2(source / 'requirements-tested.txt', build / 'requirements-tested.txt')
                run(['docker', 'build', '--network=default', '--build-arg', 'BASE_IMAGE=' + base_tag, '-f',
                     str(build / 'Dockerfile'), '-t', target, str(build)], 1800)
            finally:
                shutil.rmtree(build)
                if self.docker.image(base_tag)['Id'] == base['Id']:
                    run(['docker', 'image', 'rm', base_tag])
            return self.docker.image(target)['Id']
        return base['Id']

    def apply(self, kind, tag, source=None):
        kind, tag = component(kind), version(tag)
        with exclusive(self.home / 'operation.lock'), exclusive(lifecycle_lock(self.root)):
            module_state = Path('/var/lib/p1-companion-modules') / self.system.key / 'state.json' if hasattr(self.system, 'key') else None
            if module_state and module_state.exists():
                need(read(module_state).get('state') not in ('applying', 'rollback_blocked'), 'module_operation_pending')
            if (self.home / 'active.json').exists():
                need(read(self.home / 'active.json')['state'] in ('succeeded', 'rolled_back', 'rejected'), 'upgrade_already_active')
            # A requested version must be a published stable release, not an arbitrary image/tag.
            need(tag in {x['version'] for x in catalog(kind)['versions']}, 'release_not_in_stable_catalog')
            old = self.docker.inspect(kind)
            validate_layout(self.root, kind, old, self.docker)
            need(self.docker.probe(kind, kind), 'baseline_not_healthy')
            target = self.resolve(kind, tag, source)
            if target == old['Image']:
                return {'state': 'already_current', 'component': kind, 'version': tag}
            ident = time.strftime('%Y%m%d%H%M%S') + '-' + secrets.token_hex(4)
            point = self.root / 'backups' / ('core-upgrade-' + ident)
            point.mkdir(parents=True, mode=0o700)
            protected(point)
            atom(point / 'old.json', old)
            atom(point / 'old-image.json', self.docker.image(old['Image']))
            info = {'schema': 1, 'id': ident, 'root': str(self.root), 'component': kind, 'version': tag,
                    'state': 'preparing', 'stage': 'prepared', 'point': str(point), 'target': target,
                    'old_image': old['Image'], 'old_id': old['Id'], 'old_name': 'p1-previous-' + kind + '-' + ident,
                    'repairs': [], 'at': int(time.time()), 'timers': self.system.timer_states(),
                    'live_started': False, 'hashes': {'old.json': digest(point / 'old.json'), 'old-image.json': digest(point / 'old-image.json')}}
            self.save(info)
            try:
                self.system.arm()
                self.system.quiesce()
                with exclusive(self.root / 'astrbot/data/plugin_data/affect/maintenance.lock'):
                    need(self.docker.inspect(kind)['Id'] == old['Id'], 'baseline_changed')
                    self.docker.stop(kind)
                    info['rollback_image'] = self.docker.freeze(kind, ident)
                    self.save(info)
                    info['stage'] = 'snapshot'
                    self.save(info)
                    paths = snapshot(self.paths(info), point / 'before')
                    baseline = schema_tree(paths)
                    atom(point / 'schemas.json', baseline)
                    candidate_paths = snapshot(paths, point / 'canary-data')
                    info['stage'] = 'networkless_canary'
                    self.save(info)
                    need(self.canary(info, target, candidate_paths), 'candidate_canary_failed')
                    need(schema_tree(candidate_paths) == baseline, 'schema_migration_requires_review')
                    need(self.canary(info, info['rollback_image'], candidate_paths), 'backward_compatibility_failed')
                    need(schema_tree(candidate_paths) == baseline, 'schema_migration_requires_review')
                    self.docker.rename(kind, info['old_name'])
                    info.update(stage='live_start', live_started=True, state='observing')
                    self.save(info)  # Intent persists before creating/starting the candidate.
                    spec = create_spec(old, read(point / 'old-image.json'), self.docker.image(target), target, ident)
                    self.docker.create(kind, spec)
                    info['live_after'] = int(time.time())
                    self.save(info)
                    self.docker.start(kind)
                    if not self.wait(kind, kind, self.boot_wait, fresh_after=info['live_after']):
                        need(self.repair(info), 'candidate_health_failed')
                    self.bind_resource_guard(info, target)
                    info.update(stage='probation', watch_until=int(time.time()) + self.watch_seconds,
                                boot=boot(), watch_uptime=uptime() + self.watch_seconds)
                    self.save(info)
                return self.status()
            except Exception as exc:
                info['error'] = str(exc) if isinstance(exc, UpdateError) else 'upgrade_interrupted'
                self.save(info)
                self.rollback(info)
                return self.status()

    def validate(self, info):
        need(info.get('schema') == 1 and info.get('root') == str(self.root) and
             re.fullmatch(r'[0-9]{14}-[a-f0-9]{8}', info.get('id', '')), 'untrusted_update_journal')
        kind = component(info['component'])
        point = Path(info['point'])
        need(point == self.root / 'backups' / ('core-upgrade-' + info['id']), 'untrusted_recovery_point')
        protected(point)
        for f, h in info['hashes'].items():
            need(f in ('old.json', 'old-image.json') and digest(point / f) == h, 'recovery_metadata_changed')
        need(set(info['hashes']) == {'old.json', 'old-image.json'}, 'recovery_metadata_changed')
        old = read(point / 'old.json')
        need(old['Image'] == info['old_image'] and old['Id'] == info['old_id'] and
             info['old_name'] == 'p1-previous-' + kind + '-' + info['id'], 'recovery_binding_changed')
        return point, old

    def repair(self, info):
        kind = info['component']
        for action in ('restart_candidate', 'recreate_candidate'):
            if action in info['repairs']:
                continue
            need(self.owned(kind, info) is not None, 'candidate_missing')
            info['repairs'].append(action)
            info['stage'] = action
            self.save(info)  # Durable limits: a crash does not reset the repair budget.
            self.docker.stop(kind)
            if action == 'recreate_candidate':
                self.docker.remove(kind)
                point, old = self.validate(info)
                spec = create_spec(old, read(point / 'old-image.json'), self.docker.image(info['target']),
                                   info['target'], info['id'])
                self.docker.create(kind, spec)
            info['live_after'] = int(time.time())
            self.save(info)
            self.docker.start(kind)
            if self.wait(kind, kind, self.boot_wait, fresh_after=info['live_after']):
                return True
        return False

    def rollback(self, info):
        point, old = self.validate(info)
        kind = info['component']
        info.update(state='rolling_back',stage='rollback_preparing',timer_restore_done=False)
        self.save(info)
        try:
            self.system.quiesce()
            with exclusive(self.root / 'astrbot/data/plugin_data/affect/maintenance.lock'):
                canary_name = 'p1-canary-' + info['id']
                if self.owned(canary_name, info):
                    self.docker.remove(canary_name)
                current = self.docker.inspect(kind)
                if current and (current['Id'] == old['Id'] or
                                (current['Image'] == info.get('rollback_image', old['Image']) and
                                 current.get('Config',{}).get('Labels',{}).get(LABEL)==info['id'])):
                    # Process loss or rejection before any live candidate existed.
                    self.docker.start(kind)
                else:
                    if current:
                        self.owned(kind, info)
                        need(current['Image'] == info['target'], 'later_upgrade_blocks_rollback')
                        self.docker.stop(kind)
                    if info.get('live_started'):
                        paths = snapshot(self.paths(info), point / ('rollback-check-' + secrets.token_hex(4)))
                        need(schema_tree(paths) == read(point / 'schemas.json'), 'current_data_schema_incompatible')
                        need(self.canary(info, info.get('rollback_image', old['Image']), paths), 'current_data_not_backward_compatible')
                    if current:
                        self.docker.remove(kind)
                    previous = self.docker.inspect(info['old_name'])
                    if previous:
                        need(previous['Id'] == old['Id'], 'retained_container_changed')
                        self.docker.rename(info['old_name'], kind)
                    else:
                        fallback = info.get('rollback_image', old['Image'])
                        spec = create_spec(old, read(point / 'old-image.json'), self.docker.image(fallback), fallback, info['id'])
                        self.docker.create(kind, spec)
                    self.docker.start(kind)
                need(self.wait(kind, kind, self.boot_wait), 'previous_version_not_healthy')
                actual = self.docker.inspect(kind)['Image']
                self.checkpoint(info, actual)
                self.bind_resource_guard(info, actual)
                info.update(state='rolled_back', stage='previous_version_verified')
                self.save(info)
            self.terminal_cleanup(info)
        except Exception as exc:
            info.update(state='rollback_blocked', stage='manual_recovery_required',
                        error=str(exc) if isinstance(exc, UpdateError) else 'rollback_verification_failed')
            self.save(info)
            # Do not restart maintenance against incompatible state or overwrite current data.

    def checkpoint(self, info, image):
        p = CHECKPOINT / 'services.json'
        if not p.exists():
            return
        protected(CHECKPOINT)
        v = read(p)
        known = v.get(info['component'], {}).get('image')
        need(known in (info['old_image'], info['target'], info.get('rollback_image')), 'checkpoint_has_later_image')
        v[info['component']] = {'image': image}
        atom(p, v)

    def tick(self, manual_rollback=False):
        with exclusive(self.home / 'operation.lock'), exclusive(lifecycle_lock(self.root)):
            if not (self.home / 'active.json').exists():
                return self.status()
            info = read(self.home / 'active.json')
            self.validate(info)
            if manual_rollback:
                need(info['state'] != 'rolled_back', 'already_rolled_back')
                self.rollback(info)
                return self.status()
            if info['state'] in TERMINAL:
                if not info.get('timer_restore_done'):
                    self.terminal_cleanup(info)
                return self.status()
            if info['state'] != 'observing' or info.get('stage') != 'probation':
                self.rollback(info)
                return self.status()
            try:
                current = self.owned(info['component'], info)
                need(current and current['Image'] == info['target'], 'candidate_changed')
                if not self.wait(info['component'], info['component'], self.poll * 2,
                                 fresh_after=info.get('live_after', 0)):
                    if not self.repair(info):
                        raise UpdateError('probation_health_failed')
                    info['stage'] = 'probation'
                    info.update(watch_uptime=uptime() + self.watch_seconds,
                                watch_until=int(time.time()) + self.watch_seconds)
                    self.save(info)
                same_boot = boot() == info['boot']
                # A reboot starts a fresh observation window, rather than trusting wall time.
                if not same_boot:
                    info.update(boot=boot(), watch_uptime=uptime() + self.watch_seconds,
                                watch_until=int(time.time()) + self.watch_seconds)
                    self.save(info)
                if uptime() < info['watch_uptime']:
                    return self.status()
                with exclusive(self.root / 'astrbot/data/plugin_data/affect/maintenance.lock'):
                    self.checkpoint(info, info['target'])
                    info.update(state='succeeded', stage='observation_passed')
                    self.save(info)
                self.terminal_cleanup(info)
                return self.status()
            except Exception as exc:
                info['error'] = str(exc) if isinstance(exc, UpdateError) else 'observation_failed'
                self.save(info)
                self.rollback(info)
                return self.status()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', default='/srv/p1-agent')
    p.add_argument('--source', type=Path)
    p.add_argument('action', choices=('plan', 'check', 'status', 'apply', 'tick', 'rollback'), nargs='?', default='plan')
    p.add_argument('--component', choices=tuple(POLICY), default='astrbot')
    p.add_argument('--version')
    a = p.parse_args()
    try:
        root = root_path(a.root)
        if a.action == 'plan':
            value = {'dry_run': True, 'component': a.component, 'root': str(root),
                     'steps': ['resolve_stable_image', 'build_known_dependencies', 'stop_and_snapshot',
                               'networkless_canary', 'schema_and_backward_gate', 'cutover',
                               'bounded_repair', '15_minute_observation', 'commit_or_rollback'],
                     'data_restore': False, 'automatic_version_installation': False}
        elif a.action == 'check':
            value = catalog(a.component)
        else:
            need(os.geteuid() == 0 and sys.platform.startswith('linux'), 'linux_root_required')
            os.umask(0o077)
            e = Engine(root)
            if a.action == 'status':
                value = e.status()
            elif a.action == 'apply':
                value = e.apply(a.component, a.version, a.source)
            else:
                value = e.tick(a.action == 'rollback')
        print(json.dumps({'ok': True, **value}, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({'ok': False, 'error': str(exc) if isinstance(exc, UpdateError) else 'operation_unavailable'}, ensure_ascii=False))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
