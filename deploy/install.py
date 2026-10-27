"""Additive first-install coordinator, Python stdlib only; no remote account setup.

The original installers are copied to a private staging area and parameterized
there. This entry point never edits repository scripts or the user's Compose.
"""
from __future__ import annotations
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import subprocess
import sys
import time

SOURCE = Path(__file__).resolve().parents[1]
PLUGINS = ('astrbot_plugin_affect', 'astrbot_plugin_memoria', 'astrbot_plugin_p1_reflection',
           'astrbot_plugin_p1_stickers', 'astrbot_plugin_p1_group_memory',
           'astrbot_plugin_p1_group_affect', 'astrbot_plugin_p1_qq_style', 'astrbot_plugin_p1_learning')
TOOLS = {'p1-browser': 'p1-companion', 'p1-browser-egress': 'p1-companion',
         'p1-workbench': 'p1-workbench', 'p1-leisure': 'p1-leisure',
         'p1-leisure-egress': 'p1-leisure', 'p1-n8n': 'p1-workflows'}
NETWORKS = ('p1-companion-control', 'p1-companion-egress')
READY = ('agency_ready', 'group_memory_ready', 'group_affect_ready', 'learning_ready', 'qq_plain_ready')
TERMINAL = ('committed', 'rolled_back', 'rollback_failed')

class DeployError(RuntimeError):
    pass

def check(condition, code):
    if not condition:
        raise DeployError(code)

def atomic(path, value):
    path = Path(path)
    temp = path.with_name(path.name + '.new')
    with temp.open('w', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write('\n'); f.flush(); os.fsync(f.fileno())
    temp.chmod(0o600); os.replace(temp, path)

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def safe_root(value):
    p = Path(value)
    check(p.is_absolute() and re.fullmatch(r'/[A-Za-z0-9_./-]+', value), 'root_path_invalid')
    check('..' not in p.parts and p == p.resolve() and len(p.parts) >= 3, 'root_path_unsafe')
    check(str(p) not in ('/home', '/srv', '/etc', '/usr', '/var', '/var/lib', '/tmp'), 'root_path_unsafe')
    for q in (p, *p.parents):
        check(not q.is_symlink(), 'root_symlink_denied')
    return p

def identity(value):
    check(bool(re.fullmatch(r'[1-9][0-9]{4,19}', value)), 'qq_id_invalid')
    return value

def verify_source(source):
    source = Path(source).resolve()
    manifest = read(source/'source-manifest.json')
    check(isinstance(manifest, dict) and bool(manifest), 'source_manifest_missing')
    for rel, digest in manifest.items():
        p = source/rel
        check(not Path(rel).is_absolute() and '..' not in Path(rel).parts and
              p.resolve().is_relative_to(source) and not p.is_symlink() and p.is_file(), 'source_path_invalid')
        check(hashlib.sha256(p.read_bytes()).hexdigest() == digest, 'source_hash_mismatch')
    for rel in ('scripts/bootstrap.py', 'deploy/install.py', 'deploy/AstrBot.Dockerfile'):
        check(rel in manifest, 'source_manifest_incomplete')
    return hashlib.sha256((source/'source-manifest.json').read_bytes()).hexdigest()

def probe(args, cwd=None, timeout=25):
    try:
        p = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        raise DeployError('command_unavailable_or_timed_out') from None
    return p

def inspect(name):
    p = probe(['docker', 'inspect', '--format', '{{json .State}}', name])
    return json.loads(p.stdout) if p.returncode == 0 else None

def field(name, template):
    p = probe(['docker', 'inspect', '--format', template, name])
    check(p.returncode == 0, 'core_container_unavailable')
    return p.stdout.strip()

def healthy(state):
    return bool(state and state.get('Running') and not state.get('OOMKilled') and
                state.get('Health', {}).get('Status', 'healthy') == 'healthy')

def host_memory():
    try:
        values = {}
        for line in Path('/proc/meminfo').read_text().splitlines():
            key, value = line.split(':', 1)
            if key in ('MemTotal', 'MemAvailable'): values[key] = int(value.split()[0])*1024
        return values
    except (OSError, ValueError): return {}

def compose(root, project, module):
    paths = {'p1-companion': root/'public-browser/compose.yaml',
             'p1-workbench': root/'astrbot/data/companion_services/workbench/compose.yaml',
             'p1-leisure': root/'astrbot/data/companion_services/leisure/compose.yaml',
             'p1-workflows': root/'astrbot/data/companion_services/workflows/compose.yaml'}
    return ['docker', 'compose', '-p', project, '-f', str(paths[project]), *module]

def doctor(root, source=SOURCE):
    """Read-only. Do not print configuration, container environment, or raw errors."""
    errors, warnings = [], []
    def required(ok, code):
        if not ok: errors.append(code)
    required(sys.version_info >= (3, 11), 'python_3_11_required')
    required(platform.system() == 'Linux', 'linux_host_required')
    required(platform.machine() in ('aarch64', 'arm64', 'x86_64', 'amd64'), 'unsupported_cpu_architecture')
    memory = host_memory()
    required(memory.get('MemTotal', 0) >= 3*1024**3, 'at_least_4gb_class_host_required')
    required(memory.get('MemAvailable', 0) >= 1024**3, 'at_least_1_gib_available_memory_required')
    try: digest = verify_source(source)
    except (OSError, ValueError, DeployError): digest = ''; errors.append('source_verification_failed')
    data = root/'astrbot/data'
    for p in (root/'astrbot/compose.yaml', root/'snowluma/compose.yaml', data/'cmd_config.json'):
        required(p.is_file() and not p.is_symlink(), 'missing_core_layout')
    try:
        cfg = read(data/'cmd_config.json')
        required(any(isinstance(x, dict) and x.get('enable', True) for x in cfg.get('provider', [])), 'configure_chat_model_first')
        required(any(isinstance(x, dict) and x.get('id') == 'qq_snowluma' for x in cfg.get('platform', [])), 'configure_qq_snowluma_platform_first')
    except (OSError, ValueError, TypeError): errors.append('core_config_unreadable')
    existing = []
    try:
        required(probe(['docker', 'info', '--format', '{{.ServerVersion}}']).returncode == 0, 'docker_daemon_unavailable')
        required(probe(['docker', 'compose', 'version']).returncode == 0, 'docker_compose_v2_required')
        for name in ('astrbot', 'snowluma'): required(healthy(inspect(name)), 'core_container_not_healthy')
        mounts = json.loads(field('astrbot', '{{json .Mounts}}'))
        required(any(m.get('Destination') == '/AstrBot/data' and m.get('Type') == 'bind' and
                     Path(m.get('Source', '/')) == data for m in mounts), 'astrbot_data_bind_mismatch')
        labels = json.loads(field('astrbot', '{{json .Config.Labels}}')) or {}
        required(labels.get('com.docker.compose.service') == 'astrbot', 'core_compose_service_must_be_astrbot')
        required(labels.get('com.docker.compose.project.config_files') == str(root/'astrbot/compose.yaml'), 'core_compose_layout_not_supported')
        required(field('astrbot', '{{.Config.User}}') in ('', 'root', '0', '0:0'), 'custom_nonroot_core_requires_manual_install')
        core = probe(['docker', 'compose', '-f', str(root/'astrbot/compose.yaml'), 'config', '--format', 'json'], cwd=root/'astrbot')
        required(core.returncode == 0, 'core_compose_cannot_resolve')
        if core.returncode == 0:
            service = json.loads(core.stdout).get('services', {}).get('astrbot', {})
            required(not service.get('network_mode'), 'custom_core_network_mode_requires_manual_install')
        for name in TOOLS:
            if inspect(name) is not None: existing.append(name)
        for name in NETWORKS:
            if probe(['docker', 'network', 'inspect', name]).returncode == 0: existing.append(name)
    except (OSError, ValueError, TypeError, DeployError): errors.append('docker_layout_check_failed')
    if existing: errors.append('existing_companion_services_use_manual_upgrade')
    if shutil.which('systemctl'):
        for unit in ('p1-companion-maintain.timer', 'p1-companion-watchdog.timer'):
            if (probe(['systemctl', 'is-enabled', '--quiet', unit]).returncode == 0 or
                    probe(['systemctl', 'is-active', '--quiet', unit]).returncode == 0):
                errors.append('existing_host_recovery_use_manual_upgrade')
    for rel in ('plugin_data/affect', 'companion_services', 'companion_v020_lab', 'companion_workflows'):
        if (data/rel).exists(): errors.append('existing_companion_data_use_manual_upgrade')
    if (root/'public-browser').exists(): errors.append('existing_companion_browser_use_manual_upgrade')
    ancestor = root
    while not ancestor.exists(): ancestor = ancestor.parent
    if shutil.disk_usage(ancestor).free < 8*1024**3:
        errors.append('at_least_8_gib_free_disk_required')
    warnings += ['QQ_and_model_must_already_work', 'first_build_requires_registry_and_package_network',
                 'Bilibili_login_and_real_message_acceptance_are_manual', 'automatic_host_repair_not_enabled_by_installer']
    return {'ok': not errors, 'errors': sorted(set(errors)), 'warnings': warnings,
            'manifest_sha256': digest, 'read_only': True, 'existing_companion_objects': len(existing)}

def materialize(source, dest, root):
    manifest = read(source/'source-manifest.json')
    for rel in (*manifest, 'source-manifest.json'):
        src, target = source/rel, dest/rel
        target.parent.mkdir(parents=True, exist_ok=True)
        content = src.read_bytes()
        if rel in manifest:
            check(hashlib.sha256(content).hexdigest() == manifest[rel], 'source_changed_during_staging')
        text = content.decode('utf-8')
        if src.suffix in ('.py', '.yaml', '.service', '.timer', '.json'):
            text = text.replace('/srv/p1-agent', str(root)).replace('/home/p1admin/p1-agent', str(root))
        target.write_text(text); target.chmod(0o644)

# A child cannot mutate until its PID/start time is durably journaled.
GATE = 'import os,sys; b=sys.stdin.buffer.read(1); sys.exit(125) if b!=b"G" else os.execvp(sys.argv[1],sys.argv[1:])'

def process_start(pid):
    try:
        fields = Path('/proc', str(pid), 'stat').read_text().rsplit(')', 1)[1].split()
        return None if fields[0] == 'Z' else fields[19]
    except (OSError, IndexError): return None

class Job:
    def __init__(self, path):
        self.path = Path(path); self.state = read(self.path/'state.json')
    def save(self): atomic(self.path/'state.json', self.state)
    def command(self, label, args, timeout=180, cwd=None):
        print('  '+label, flush=True)
        log = self.path/(label+'.log')
        with log.open('ab') as output:
            log.chmod(0o600)
            p = subprocess.Popen([sys.executable, '-c', GATE, *args], cwd=cwd, stdin=subprocess.PIPE,
                                 stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
            self.state['active'] = {'pid': p.pid, 'start': process_start(p.pid)}; self.save()
            try:
                p.communicate(b'G', timeout=timeout)
                check(p.returncode == 0, label+'_failed')
            except BaseException:
                with contextlib.suppress(ProcessLookupError): os.killpg(p.pid, signal.SIGKILL)
                p.wait()
                raise
            finally:
                self.state.pop('active', None); self.save()
        self.state['steps'].append(label); self.save()
    def wait(self, predicate, code, seconds=180):
        end = time.monotonic()+seconds
        while time.monotonic() < end:
            if predicate(): return
            time.sleep(2)
        raise DeployError(code)
    def core(self, override=None):
        r = Path(self.state['root'])
        command = ['docker', 'compose', '-p', self.state['core_project'], '-f', str(r/'astrbot/compose.yaml')]
        if override: command += ['-f', str(override)]
        return command+['up', '-d', '--no-deps', '--no-build', '--pull', 'never', 'astrbot']

def backup_paths(root):
    data = root/'astrbot/data'
    return [data/'cmd_config.json', data/'mcp_server.json',
            *[data/'plugins'/name for name in PLUGINS], root/'public-browser',
            *[data/name for name in ('companion_services', 'companion_v020_lab', 'companion_workflows', 'plugin_data/affect')]]

def snapshot(job):
    root = Path(job.state['root']); records = []
    for n, p in enumerate(backup_paths(root)):
        check(not p.is_symlink(), 'managed_path_symlink_denied')
        for parent in p.parents:
            if parent == root: break
            check(not parent.is_symlink(), 'managed_parent_symlink_denied')
        record = {'path': str(p), 'exists': p.exists(), 'slot': str(n)}
        dest = job.path/'before'/str(n)
        if p.is_dir(): shutil.copytree(p, dest, symlinks=True)
        elif p.exists(): dest.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(p, dest)
        records.append(record)
    job.state['before'] = records; job.state['snapshot_complete'] = True; job.save()

def restore_paths(job):
    allowed = {str(p) for p in backup_paths(Path(job.state['root']))}
    for row in job.state.get('before', []):
        p = Path(row['path']); check(str(p) in allowed, 'rollback_path_denied')
        dest = job.path/'replaced'/row['slot']
        if p.exists() or p.is_symlink():
            dest.parent.mkdir(parents=True, exist_ok=True)
            check(not dest.exists(), 'rollback_already_replaced')
            os.replace(p, dest)
        old = job.path/'before'/row['slot']
        if row['exists']:
            if old.is_dir(): shutil.copytree(old, p, symlinks=True)
            else: p.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(old, p)

@contextlib.contextmanager
def deploy_lock(root):
    import fcntl
    lock = root/'backups/companion-deploy.lock'; lock.parent.mkdir(parents=True, exist_ok=True)
    check(not lock.is_symlink(), 'deployment_lock_symlink_denied')
    with lock.open('a') as f:
        os.chmod(lock, 0o600)
        try: fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: raise DeployError('another_deployment_is_running') from None
        yield

def rollback(job):
    job.state = read(job.path/'state.json')
    if job.state['status'] in ('committed', 'rolled_back'): return
    active = job.state.get('active')
    if active and process_start(active['pid']) == active.get('start'):
        with contextlib.suppress(ProcessLookupError): os.killpg(active['pid'], signal.SIGKILL)
    job.state.pop('active', None); job.state['status'] = 'rolling_back'; job.save()
    try:
        if job.state.get('mutations_started'):
            # Stop this run's core before restoring source/config; preserve all DBs.
            if inspect('astrbot') is not None:
                check(field('astrbot', '{{index .Config.Labels "com.docker.compose.project"}}') ==
                      job.state['core_project'], 'rollback_foreign_core_refused')
                job.command('rollback_stop_core', ['docker', 'stop', '--time', '10', 'astrbot'])
            for name, project in TOOLS.items():
                if inspect(name) is None: continue
                label = field(name, '{{index .Config.Labels "com.docker.compose.project"}}')
                check(label == project, 'rollback_foreign_container_refused')
                job.command('rollback_'+name, ['docker', 'rm', '-f', name])
            restore_paths(job)
            job.command('rollback_original_core', job.core(job.path/'original-image.json'), cwd=Path(job.state['root'])/'astrbot')
            job.wait(lambda: healthy(inspect('astrbot')), 'rollback_core_not_healthy')
            for name in NETWORKS:
                r = probe(['docker', 'network', 'inspect', name])
                if r.returncode != 0: continue
                network = json.loads(r.stdout)[0]
                expected = 'p1-companion'
                check(network.get('Labels', {}).get('com.docker.compose.project') == expected, 'rollback_foreign_network_refused')
                if not network.get('Containers'): job.command('rollback_network_'+name, ['docker', 'network', 'rm', name])
        job.state['status'] = 'rolled_back'; job.save()
    except BaseException:
        job.state['status'] = 'rollback_failed'; job.save(); raise

def watchdog(path):
    job = Job(path)
    while True:
        state = read(job.path/'state.json')
        if state['status'] in TERMINAL: return
        if process_start(state['parent_pid']) != state['parent_start']:
            with deploy_lock(Path(state['root'])): rollback(Job(path))
            return
        time.sleep(2)

def apply(root, bot, owner, source=SOURCE, social=False):
    check(os.geteuid() == 0, 'apply_requires_sudo')
    with deploy_lock(root):
        report = doctor(root, source)
        check(report['ok'], 'preflight_failed:'+','.join(report['errors']))
        check(process_start(os.getpid()) is not None, 'linux_procfs_required')
        project = field('astrbot', '{{index .Config.Labels "com.docker.compose.project"}}')
        check(bool(re.fullmatch('[a-z0-9][a-z0-9_-]*', project)), 'invalid_compose_project')
        image = field('astrbot', '{{.Image}}')
        check(bool(re.fullmatch(r'sha256:[a-f0-9]{64}', image)), 'original_image_id_invalid')
        point = root/'backups'/('oneclick-'+time.strftime('%Y%m%d-%H%M%S')+'-'+str(os.getpid()))
        point.mkdir(mode=0o700)
        atomic(point/'state.json', {'schema': 1, 'root': str(root), 'status': 'preparing',
                                  'manifest_sha256': report['manifest_sha256'], 'steps': [],
                                  'core_project': project, 'parent_pid': os.getpid(),
                                  'parent_start': process_start(os.getpid()), 'started_at': int(time.time())})
        job = Job(point)
        materialize(source, point/'source', root)
        # Frozen local copy is used by the watcher even if the checkout changes.
        with (point/'watchdog.log').open('ab') as output:
            subprocess.Popen([sys.executable, str(point/'source/deploy/install.py'), '--watchdog', str(point)],
                             stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                             start_new_session=True, close_fds=True)
        atomic(point/'original-image.json', {'services': {'astrbot': {'image': image}}})
        generated = point/'source'
        try:
            base = 'p1-companion-base:'+point.name
            target = 'p1-companion-astrbot:'+point.name
            browser = 'p1-companion-browser:'+point.name
            worker = 'p1-companion-workbench:'+point.name
            for rel in ('browser/compose.yaml', 'services/leisure/compose.yaml', 'services/workbench/compose.yaml'):
                f = generated/rel
                f.write_text(f.read_text().replace('p1-companion-browser:0.20.0', browser).replace('p1-companion-workbench:0.20.0', worker))
            job.command('tag_installed_base', ['docker', 'tag', image, base])
            job.command('build_core_dependencies', ['docker', 'build', '--build-arg', 'BASE_IMAGE='+base,
                        '-f', str(generated/'deploy/AstrBot.Dockerfile'), '-t', target, str(generated)], 2400)
            job.command('build_browser', ['docker', 'build', '-t', browser, str(generated/'browser')], 2400)
            job.command('build_workbench', ['docker', 'build', '--build-arg', 'BROWSER_IMAGE='+browser,
                        '-t', worker, str(generated/'services/workbench')], 1800)
            job.command('offline_neutral_checks', [sys.executable, str(generated/'scripts/selftest.py')], 180)
            # All slow builds happen before the first core stop.
            snapshot(job)
            corecfg = json.loads(probe(['docker', 'compose', '-f', str(root/'astrbot/compose.yaml'), 'config', '--format', 'json'], cwd=root/'astrbot').stdout)
            nets = corecfg['services']['astrbot'].get('networks', {'default': {}})
            nets['companion_control'] = {}
            atomic(point/'companion-override.json', {'services': {'astrbot': {'image': target, 'networks': nets}},
                   'networks': {'companion_control': {'external': True, 'name': 'p1-companion-control'}}})
            job.state['mutations_started'] = True; job.state['status'] = 'installing'; job.save()
            job.command('stop_core', ['docker', 'stop', '--time', '10', 'astrbot'])
            cmd = [sys.executable, str(generated/'scripts/bootstrap.py'), '--root', str(root), '--bot-id', bot, '--owner-id', owner, '--apply']
            if social: cmd.append('--enable-social')
            job.command('install_plugins_and_config', cmd)
            for project in ('p1-companion', 'p1-workbench', 'p1-leisure'):
                job.command('start_'+project, compose(root, project, ['up', '-d', '--pull', 'never']))
            job.command('initialize_workflows', [sys.executable, str(generated/'scripts/setup_workflows.py')], 900)
            job.wait(lambda: healthy(inspect('p1-n8n')), 'workflow_health_timeout', 240)
            job.command('secure_workflow_setup', [sys.executable, str(generated/'scripts/secure_workflows.py')])
            job.command('start_integrated_core', job.core(point/'companion-override.json'), cwd=root/'astrbot')
            def ready():
                try: return all(read(root/'astrbot/data/plugin_data/affect/companion_health.json').get(k) for k in READY)
                except (OSError, ValueError, TypeError): return False
            job.wait(lambda: all(healthy(inspect(n)) for n in ('astrbot', 'snowluma', *TOOLS)) and ready(), 'stack_or_plugins_not_ready', 240)
            # Import exact runtime dependencies through the real container interpreter.
            job.command('verify_core_dependencies', ['docker', 'exec', 'astrbot', 'python', '-c',
                        'import mcp,aiohttp,aiosqlite,qrcode,PIL,playwright; print("runtime_dependencies_ok")'])
            tracked = [root/'astrbot/data/cmd_config.json', root/'astrbot/data/mcp_server.json']
            for name in PLUGINS:
                tracked += [p for p in (root/'astrbot/data/plugins'/name).rglob('*') if p.is_file() and
                            '__pycache__' not in p.parts and p.suffix != '.pyc']
            job.state['installed_hashes'] = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in tracked}
            job.state['installed_image'] = field('astrbot', '{{.Image}}')
            atomic(root/'backups/oneclick-latest.json', {'point': str(point)})
            job.state['status'] = 'committed'; job.state['committed_at'] = int(time.time()); job.save()
            return {'installed': True, 'services_checked': 8, 'plugin_packages_installed': 8,
                    'plugin_ready_flags_checked': len(READY), 'recovery_point': str(point),
                    'source_compose_files_edited': False, 'host_repair_enabled': False,
                    'manual_acceptance': ['QQ_real_message_and_login', 'Bilibili_QR_login_if_used', 'model_max_alias_if_needed']}
        except BaseException:
            rollback(job)
            raise

def parser():
    p = argparse.ArgumentParser(description='P1 Companion：已有 AstrBot 的受检一键集成（不会代替账号登录）')
    p.add_argument('--root', default='/srv/p1-agent'); p.add_argument('--bot-id'); p.add_argument('--owner-id')
    p.add_argument('--check', action='store_true', help='只读环境诊断')
    p.add_argument('--apply', action='store_true', help='安装；失败恢复源码、配置与核心镜像，保留数据库')
    p.add_argument('--enable-social', action='store_true', help='首次安装开启白名单自主社交，默认关闭')
    p.add_argument('--status', action='store_true', help='查看本安装器的最后一次成功安装和容器状态')
    p.add_argument('--rollback', type=Path, help='恢复最近一次安装；拒绝覆盖安装后的配置/源码修改')
    p.add_argument('--watchdog', help=argparse.SUPPRESS)
    return p

def main():
    os.umask(0o077)
    a = parser().parse_args()
    try:
        if a.watchdog:
            check(os.geteuid() == 0, 'watchdog_requires_root')
            point = Path(a.watchdog).resolve()
            check(point.name.startswith('oneclick-') and point.parent.name == 'backups' and
                  point.stat().st_uid == 0 and not point.stat().st_mode & 0o077, 'watchdog_path_invalid')
            watchdog(point); return 0
        root = safe_root(a.root)
        if a.status:
            latest = read(root/'backups/oneclick-latest.json')
            job = Job(latest['point'])
            print(json.dumps({'status': job.state['status'], 'recovery_point': str(job.path),
                              'services': {n: healthy(inspect(n)) for n in ('astrbot', 'snowluma', *TOOLS)},
                              'account_login_not_tested': True}, ensure_ascii=False, indent=2))
            return 0
        if a.rollback:
            check(os.geteuid() == 0, 'rollback_requires_sudo')
            point = a.rollback.resolve()
            check(point.parent == root/'backups' and point.name.startswith('oneclick-') and
                  point.stat().st_uid == 0 and not point.stat().st_mode & 0o077, 'rollback_point_invalid')
            with deploy_lock(root):
                job = Job(point)
                check(job.state['root'] == str(root), 'rollback_root_mismatch')
                if job.state['status'] == 'committed':
                    check(read(root/'backups/oneclick-latest.json')['point'] == str(point), 'rollback_not_latest_install')
                    for rel, digest in job.state['installed_hashes'].items():
                        p = root/rel
                        check(p.resolve().is_relative_to(root) and not p.is_symlink() and
                              hashlib.sha256(p.read_bytes()).hexdigest() == digest, 'post_install_changes_require_manual_restore')
                    check(field('astrbot', '{{.Image}}') == job.state['installed_image'], 'post_install_image_changed')
                    job.state['status'] = 'rollback_requested'; job.save()
                rollback(job)
                print(json.dumps({'status': job.state['status'], 'databases_restored': False,
                                  'replaced_files_preserved_in': str(point/'replaced')}, ensure_ascii=False))
            return 0
        if a.apply:
            bot, owner = a.bot_id, a.owner_id
            if sys.stdin.isatty():
                bot = bot or input('机器人 QQ 号：').strip()
                owner = owner or input('主人 QQ 号：').strip()
            check(bool(bot and owner), 'provide_bot_id_and_owner_id')
            identity(bot); identity(owner); check(bot != owner, 'bot_and_owner_must_differ')
            print(json.dumps(apply(root, bot, owner, social=a.enable_social), ensure_ascii=False, indent=2)); return 0
        report = doctor(root)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        print('检查通过后：sudo bash deploy.sh --apply --bot-id 你的机器人QQ --owner-id 你的QQ')
        return 0 if report['ok'] else 1
    except (DeployError, OSError, ValueError, subprocess.SubprocessError) as exc:
        # Never leak captured service/model/config output to the terminal.
        code = str(exc) if isinstance(exc, DeployError) else type(exc).__name__
        print('未完成：'+code+'。详见 docs/easy-deploy.md；私有恢复点内保留本机日志。', file=sys.stderr)
        return 1

if __name__ == '__main__':
    raise SystemExit(main())
