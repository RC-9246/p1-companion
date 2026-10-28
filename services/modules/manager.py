#!/usr/bin/env python3
"""Declarative feature/service composition, preserving data and core boundaries."""
import argparse, contextlib, hashlib, importlib.util, json, os, re, shutil, subprocess, sys, time
from pathlib import Path

_path = Path(__file__).resolve().parents[1] / 'updater/manager.py'
if not _path.is_file():
    _path = Path(__file__).with_name('updater.py')
if 'p1_core_updater' in sys.modules:
    U = sys.modules['p1_core_updater']
else:
    _s = importlib.util.spec_from_file_location('p1_core_updater', _path)
    U = importlib.util.module_from_spec(_s)
    sys.modules[_s.name] = U
    _s.loader.exec_module(U)
ModuleError = U.UpdateError
HOME = Path('/var/lib/p1-companion-modules')
CATALOG = Path(__file__).resolve().parents[2] / 'modules/catalog.json'
if not CATALOG.is_file():
    CATALOG = Path(__file__).with_name('catalog.json')
SERVICES = {'public_web': ('p1-browser-egress', 'p1-browser'),
            'bilibili': ('p1-leisure-egress', 'p1-leisure'),
            'workbench': ('p1-workbench',), 'workflows': ('p1-n8n',)}
UNITS = {'maintenance': ('p1-companion-maintain.timer', 'p1-companion-watchdog.timer'),
         'resource_guard': ('p1-resource-guard.timer',),
         'monitor': ('p1-resource-collector.service', 'p1-resource-panel.service')}
FEATURES = {'learning', 'reflection', 'stickers', 'qq_actions', 'autonomy', 'proactive', 'mcp'}
MAINTAIN = Path('/usr/local/sbin/p1-companion-maintain.py')
ALL_SERVICES = {n for names in SERVICES.values() for n in names}


def registry(path=CATALOG):
    v = U.read(path)
    U.need(v.get('schema') == 1 and isinstance(v.get('modules'), list), 'module_catalog_invalid')
    rows = {x['id']: x for x in v['modules']}
    U.need(len(rows) == len(v['modules']) and set(rows) == {'core', *FEATURES, *SERVICES, *UNITS},
           'module_adapter_missing')
    for key, row in rows.items():
        U.need(re.fullmatch('[a-z][a-z_]{1,30}', key) and isinstance(row.get('requires'), list)
               and set(row['requires']) <= set(rows) and key not in row['requires'], 'module_dependencies_invalid')
    U.need(rows['core'].get('required') is True, 'core_module_required')
    order = []
    def visit(key, stack):
        U.need(key not in stack, 'module_dependency_cycle')
        if key in order:
            return
        for dep in rows[key]['requires']:
            visit(dep, stack | {key})
        order.append(key)
    for key in rows:
        visit(key, set())
    for names in v.get('profiles', {}).values():
        U.need(isinstance(names, list) and set(names) <= set(rows), 'module_profile_invalid')
    return v, rows, order


def closure(selected, rows):
    U.need(isinstance(selected, (list, set, tuple)) and all(isinstance(x, str) for x in selected)
           and set(selected) <= set(rows), 'unknown_module')
    result = set(selected) | {'core'}
    while True:
        more = {d for k in result for d in rows[k]['requires']}
        if more <= result:
            return result
        result |= more


def plan(selected, current, catalog_path=CATALOG):
    _, rows, order = registry(catalog_path)
    target = closure(selected, rows)
    return {'requested': sorted(set(selected)), 'enabled': [k for k in order if k in target],
            'dependencies_added': sorted(target - set(selected) - {'core'}),
            'enable': [k for k in order if k in target and k not in current],
            'disable': [k for k in reversed(order) if k in current and k not in target],
            'data_deleted': False, 'core_removable': False}


def disable_plan(disabled, current, catalog_path=CATALOG):
    _, rows, _ = registry(catalog_path)
    U.need('core' not in disabled and set(disabled) <= set(rows), 'core_module_required')
    removed = set(disabled)
    while True:
        dependents = {k for k, r in rows.items() if set(r['requires']) & removed}
        if dependents <= removed:
            break
        removed |= dependents
    return plan(set(current) - removed, current, catalog_path)


class Host:
    def __init__(self, root, home):
        self.root, self.home = root, home

    def unit(self, name):
        p = subprocess.run(['systemctl', 'show', '-p', 'LoadState', '--value', name],
                           capture_output=True, text=True, timeout=15)
        installed = p.stdout.strip() == 'loaded'
        return {'installed': installed,
                'enabled': installed and subprocess.run(['systemctl', 'is-enabled', '--quiet', name], capture_output=True, timeout=15).returncode == 0,
                'active': installed and subprocess.run(['systemctl', 'is-active', '--quiet', name], capture_output=True, timeout=15).returncode == 0}

    def set_unit(self, name, enabled, before=None):
        U.need(name in {n for ns in UNITS.values() for n in ns}, 'host_unit_denied')
        original = before or self.unit(name)
        U.need(not enabled or original['installed'], 'module_requires_setup')
        if not original['installed']:
            return
        U.run(['systemctl', 'enable' if enabled else 'disable', '--now', name])

    def restore_unit(self, name, before):
        if not before['installed']:
            return
        U.run(['systemctl', 'enable' if before['enabled'] else 'disable', name])
        U.run(['systemctl', 'start' if before['active'] else 'stop', name])
        U.need(self.unit(name) == before, 'module_unit_restore_failed')

    def arm(self):
        # Freeze both executables and the reviewed registry outside runtime mounts.
        for name, source in (('manager.py', Path(__file__)), ('updater.py', Path(U.__file__)),
                             ('catalog.json', CATALOG)):
            p = self.home / name
            tmp = self.home / (name + '.next')
            U.need(not tmp.is_symlink() and not p.is_symlink(), 'symlink_denied')
            shutil.copyfile(source, tmp)
            tmp.chmod(0o600 if name.endswith('json') else 0o700)
            os.replace(tmp, p)
        name = 'p1-modules-' + self.home.name
        service = '[Unit]\nDescription=Recover interrupted P1 module changes\nAfter=docker.service\n[Service]\nType=oneshot\nUser=root\nUMask=0077\nExecStart=/usr/bin/python3 ' + str(self.home / 'manager.py') + ' --root ' + str(self.root) + ' recover\nTimeoutStartSec=900\n'
        timer = '[Unit]\nDescription=P1 module transaction recovery\n[Timer]\nOnBootSec=45s\nOnUnitActiveSec=45s\n[Install]\nWantedBy=timers.target\n'
        for suffix, raw in (('.service', service), ('.timer', timer)):
            p = Path('/etc/systemd/system') / (name + suffix)
            U.need(not p.is_symlink() and (not p.exists() or p.read_text() in (raw,raw.replace('TimeoutStartSec=900','TimeoutStartSec=300'))), 'module_unit_conflict')
            p.write_text(raw)
            p.chmod(0o644)
        U.run(['systemctl', 'daemon-reload'])
        U.run(['systemctl', 'enable', '--now', name + '.timer'])


class Controller:
    def __init__(self, root, docker=None, host=None, catalog_path=CATALOG):
        self.root = U.root_path(str(root))
        self.catalog_path = catalog_path
        self.catalog, self.rows, self.order = registry(catalog_path)
        self.home = HOME / hashlib.sha256(str(self.root).encode()).hexdigest()[:16]
        self.docker = docker or U.Docker()
        self.host = host or Host(self.root, self.home)
        self.mirror = self.root / 'astrbot/data/plugin_data/affect/modules_enabled.json'
        self.poll, self.wait_seconds = 1, 90

    def current(self):
        if (self.home / 'state.json').exists():
            U.protected(self.home)
            v = U.read(self.home / 'state.json')
            U.need(v.get('schema') == 1 and v.get('root') == str(self.root) and
                   set(v.get('enabled', [])) <= set(self.rows) and 'core' in v['enabled'], 'module_state_invalid')
            return v
        enabled = {'core', *FEATURES}
        for key, names in SERVICES.items():
            if all((self.docker.inspect(n) or {}).get('State', {}).get('Running') for n in names):
                enabled.add(key)
        for key, names in UNITS.items():
            if all(self.host.unit(n)['active'] for n in names):
                enabled.add(key)
        return {'schema': 1, 'root': str(self.root), 'enabled': sorted(enabled), 'state': 'legacy', 'generation': 0}

    def status(self):
        v = self.current()
        return {'state': v['state'], 'generation': v['generation'], 'enabled': v['enabled'],
                'modules': self.catalog['modules'], 'profiles': self.catalog['profiles'],
                'data_deleted': False, 'error': v.get('error', '')}

    def binding(self, name, obj):
        labels = obj.get('Config', {}).get('Labels') or {}
        files = labels.get('com.docker.compose.project.config_files', '').split(',')
        U.need(obj.get('Name') == '/' + name and labels.get('com.docker.compose.service') and files
               and all(U.root_path(p).is_relative_to(self.root) for p in files), 'foreign_module_container')
        U.need(not obj['HostConfig'].get('Privileged') and obj['HostConfig'].get('NetworkMode') not in ('host', 'none'),
               'unsupported_module_container')
        U.need(obj.get('Image', '').startswith('sha256:'), 'module_image_invalid')
        return obj

    def accept_core(self):
        if (self.root/'.p1-companion-setup.json').exists():
            p=self.root/'.p1-companion-install-accepted.json'
            U.need(p.is_file() and U.read(p).get('human_confirmed') is True,'finish_installation_before_modules')
        for name in ('astrbot', 'snowluma'):
            obj = self.docker.inspect(name)
            U.need(obj is not None, 'companion_core_required')
            labels = obj['Config'].get('Labels') or {}
            U.need(labels.get('com.docker.compose.project.config_files') == str(self.root / name / 'compose.yaml'),
                   'core_root_mismatch')
        health = self.root / 'astrbot/data/plugin_data/affect/companion_health.json'
        U.need(health.is_file() and U.read(health).get('module_policy_schema') == 1, 'runtime_module_upgrade_required')
        if any(self.host.unit(n)['installed'] for n in UNITS['maintenance']):
            p = MAINTAIN
            U.need(p.is_file() and b'MODULE_POLICY_SCHEMA=1' in p.read_bytes(), 'maintenance_module_upgrade_required')
        record = U.ROOT_STATE / self.home.name / 'active.json'
        if record.exists():
            U.need(U.read(record)['state'] in U.TERMINAL, 'core_upgrade_in_progress')

    def prepared(self):
        p = self.home / 'bindings.json'
        if p.exists():
            return U.read(p)
        bindings = {}
        for name in ALL_SERVICES:
            obj = self.docker.inspect(name)
            if obj:
                bindings[name] = {'container': self.binding(name, obj), 'image': self.docker.image(obj['Image'])}
        U.atom(p, bindings)
        return bindings

    def publish(self, enabled, generation):
        U.atom(self.home / 'desired.json', {'schema': 1, 'root': str(self.root),
               'disabled_services': sorted(n for k, names in SERVICES.items() if k not in enabled for n in names)})
        U.atom(self.mirror, {'schema': 1, 'enabled': sorted(enabled), 'generation': generation})
        self.mirror.chmod(0o644)

    def check_owned(self, name, row):
        obj = self.docker.inspect(name)
        if obj:
            self.binding(name, obj)
            before = row['container']
            U.need(obj['Image'] == before['Image'] and
                   [(m['Type'], m['Source'], m['Destination']) for m in obj['Mounts']] ==
                   [(m['Type'], m['Source'], m['Destination']) for m in before['Mounts']], 'module_binding_changed')
        return obj

    def service(self, name, enabled, bindings, remove=False):
        U.need(name in ALL_SERVICES, 'module_service_denied')
        row = bindings.get(name)
        U.need(row is not None or not enabled, 'module_requires_setup')
        if row is None:
            return
        obj = self.check_owned(name, row)
        if enabled:
            if obj is None:
                before = row['container']
                self.docker.image(before['Image'])  # No pull or arbitrary build here.
                spec = U.create_spec(before, row['image'], row['image'], before['Image'], 'module-manager')
                self.docker.create(name, spec)
            restart = row['container']['HostConfig'].get('RestartPolicy', {'Name': 'unless-stopped'})
            self.docker.restart_policy(name, restart)
            self.docker.start(name)
            end = time.monotonic() + self.wait_seconds
            good=0;last=None
            while True:
                current = self.docker.inspect(name)
                fingerprint=None if not current else (current['Id'],current['State'].get('StartedAt'),current.get('RestartCount',0))
                if fingerprint!=last:good=0;last=fingerprint
                if current and current['State'].get('Running') and current['State'].get('Health', {}).get('Status', 'healthy') == 'healthy':
                    good+=1
                    if good>=3:return
                else:good=0
                U.need(time.monotonic() < end, 'module_service_not_healthy')
                time.sleep(self.poll)
        elif obj:
            self.docker.restart_policy(name, {'Name': 'no'})
            self.docker.stop(name)
            if remove:
                self.docker.remove(name)  # Docker v=false: all data volumes retained.

    def preflight(self, target, bindings):
        for key in target:
            for name in SERVICES.get(key, ()):
                U.need(name in bindings, 'module_requires_setup')
                self.check_owned(name, bindings[name])
            for name in UNITS.get(key, ()):
                U.need(self.host.unit(name)['installed'], 'module_requires_setup')

    def apply(self, selected, remove=False):
        self.home.mkdir(mode=0o700, parents=True, exist_ok=True)
        U.protected(self.home)
        with U.exclusive(self.home / 'operation.lock'):
            self.accept_core()
            previous = self.current()
            U.need(previous['state'] not in ('applying', 'rollback_blocked'), 'module_operation_pending')
            change = plan(selected, previous['enabled'], self.catalog_path)
            target = change['enabled']
            if remove:
                change['disable'] = [k for k in reversed(self.order) if k not in target and
                                     (k in previous['enabled'] or k in SERVICES)]
                change['remove_services'] = sorted(n for k, names in SERVICES.items() if k not in target for n in names)
            bindings = self.prepared()
            self.preflight(target, bindings)
            before_services = {n: {'running': bool((self.docker.inspect(n) or {}).get('State', {}).get('Running')),
                                   'restart': (self.docker.inspect(n) or {}).get('HostConfig', {}).get('RestartPolicy'),
                                   'exists': self.docker.inspect(n) is not None} for n in bindings}
            before_units = {n: self.host.unit(n) for names in UNITS.values() for n in names}
            point = self.home / ('transaction-' + str(time.time_ns()) + '.json')
            U.atom(point, {'before': previous, 'before_services': before_services, 'before_units': before_units,
                           'bindings_sha256': U.digest(self.home / 'bindings.json')})
            v = {'schema': 1, 'root': str(self.root), 'state': 'applying', 'enabled': previous['enabled'],
                 'target': target, 'generation': previous['generation'] + 1, 'point': point.name,
                 'parent_pid': os.getpid(), 'started': time.time(), 'mutations_started': False, 'recovery_attempts': 0}
            U.atom(self.home / 'state.json', v)
            try:
                self.host.arm()
                with U.exclusive(self.root / 'astrbot/data/plugin_data/affect/maintenance.lock'):
                    v['mutations_started']=True
                    U.atom(self.home / 'state.json',v)
                    self.publish(target, v['generation'])
                    for key in reversed(self.order):
                        if key in target:continue
                        for name in reversed(SERVICES.get(key, ())):
                            self.service(name, False, bindings, remove)
                        for name in reversed(UNITS.get(key, ())):
                            self.host.set_unit(name, False, before_units[name])
                    for key in self.order:
                        if key not in target:continue
                        for name in SERVICES.get(key, ()):
                            self.service(name, True, bindings)
                        for name in UNITS.get(key, ()):
                            self.host.set_unit(name, True, before_units[name])
                    v.update(state='ready', enabled=target)
                    U.atom(self.home / 'state.json', v)
                return {**self.status(), 'plan': change}
            except Exception as exc:
                v['error'] = str(exc) if isinstance(exc, ModuleError) else 'module_apply_failed'
                U.atom(self.home / 'state.json', v)
                self.rollback(v)
                return self.status()

    def rollback(self, v, manual=False):
        try:
            if not v.get('mutations_started'):
                v['state']='rolled_back';U.atom(self.home/'state.json',v);return
            U.need(manual or v.get('recovery_attempts',0)<2,'module_recovery_budget_exhausted')
            v['recovery_attempts']=v.get('recovery_attempts',0)+1
            U.atom(self.home/'state.json',v)
            U.need(re.fullmatch('transaction-[0-9]+\\.json', v['point']), 'module_transaction_invalid')
            point = U.read(self.home / v['point'])
            U.need(U.digest(self.home / 'bindings.json') == point['bindings_sha256'], 'module_binding_changed')
            bindings = U.read(self.home / 'bindings.json')
            with U.exclusive(self.root / 'astrbot/data/plugin_data/affect/maintenance.lock'):
                enabled = point['before']['enabled']
                self.publish(enabled, v['generation'])
                for key in self.order:
                    for name in SERVICES.get(key, ()):
                        if name in bindings:
                            before = point['before_services'][name]
                            self.service(name, before['running'], bindings, remove=not before['exists'])
                            if before.get('restart') is not None and self.docker.inspect(name):
                                self.docker.restart_policy(name, before['restart'])
                    for name in UNITS.get(key, ()):
                        before = point['before_units'][name]
                        if before['installed']:
                            self.host.restore_unit(name, before)
                v.update(state='rolled_back', enabled=enabled)
                U.atom(self.home / 'state.json', v)
        except Exception as exc:
            v.update(state='rollback_blocked', error=str(exc) if isinstance(exc, ModuleError) else 'module_rollback_failed')
            U.atom(self.home / 'state.json', v)

    def recover(self, manual=False):
        if not (self.home / 'state.json').exists():
            return {'state': 'unconfigured'}
        with U.exclusive(self.home / 'operation.lock'):
            v = self.current()
            if v['state'] == 'applying' or (manual and v['state']=='rollback_blocked'):
                self.rollback(v,manual)
            return self.status()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', default='/srv/p1-agent')
    p.add_argument('action', choices=('catalog', 'status', 'plan', 'apply', 'remove', 'recover','rollback'), default='catalog', nargs='?')
    p.add_argument('--only', help='Comma-separated final selection; dependencies are added')
    p.add_argument('--disable', help='Disable these modules and their dependents')
    p.add_argument('--profile', choices=('chat', 'companion', 'tools', 'full'))
    a = p.parse_args()
    try:
        if a.action == 'catalog':
            result = registry()[0]
        else:
            U.need(os.geteuid() == 0 and sys.platform.startswith('linux'), 'linux_root_required')
            c = Controller(a.root)
            if a.action == 'status':
                result = c.status()
            elif a.action in ('recover','rollback'):
                result = c.recover(a.action=='rollback')
            else:
                current = c.current()['enabled']
                U.need(sum(x is not None for x in (a.only, a.disable, a.profile)) == 1, 'choose_one_module_selection')
                if a.disable:
                    selected = disable_plan(a.disable.split(','), current)['enabled']
                elif a.profile:
                    selected = c.catalog['profiles'][a.profile] + [x for x in current if x in UNITS]
                else:
                    selected = a.only.split(',')
                result = plan(selected, current) if a.action == 'plan' else c.apply(selected, a.action == 'remove')
        print(json.dumps({'ok': True, **result}, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({'ok': False, 'error': str(exc) if isinstance(exc, ModuleError) else 'module_operation_unavailable'}, ensure_ascii=False))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
