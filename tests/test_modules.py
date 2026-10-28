"""Dependency, lifecycle, data retention and runtime gate contract tests."""
import copy, hashlib, importlib.util, json, os, sqlite3, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from test_core_updater import FakeDocker, OLD
R = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('module_manager_tests', R/'services/modules/manager.py')
M = importlib.util.module_from_spec(spec);spec.loader.exec_module(M)
spec = importlib.util.spec_from_file_location('runtime_module_policy', R/'release/astrbot_plugin_affect/module_policy.py')
P = importlib.util.module_from_spec(spec);spec.loader.exec_module(P)


class Docker(FakeDocker):
    def __init__(self, root):
        super().__init__(root)
        self.items.update(FakeDocker(root, 'snowluma').items)
        self.fail_stop = None
        for name in M.ALL_SERVICES:
            row = copy.deepcopy(self.original)
            row.update(Name='/'+name, Id=hashlib.sha256(name.encode()).hexdigest())
            row['Config']['Labels'].update({'com.docker.compose.service':name,
                'com.docker.compose.project.config_files':str(root/'services'/name/'compose.yaml')})
            data=root/'service-data'/name;data.mkdir(parents=True)
            (data/'session.txt').write_text('synthetic-session')
            row['Mounts']=[{'Type':'bind','Source':str(data),'Destination':'/state','RW':True}]
            row['HostConfig'].update(Binds=[str(data)+':/state'],RestartPolicy={'Name':'unless-stopped'})
            self.items[name]=row
    def restart_policy(self,name,value):self.items[name]['HostConfig']['RestartPolicy']=value
    def stop(self,name):
        if self.fail_stop==name:self.fail_stop=None;raise M.ModuleError('injected_stop_failure')
        super().stop(name)
    def create(self,name,spec):
        super().create(name,spec)
        if spec['HostConfig'].get('Binds'):
            self.items[name]['Mounts']=[{'Type':'bind','Source':v.split(':')[0],'Destination':v.split(':')[1],'RW':True} for v in spec['HostConfig']['Binds']]


class Host:
    def __init__(self):self.rows={n:{'installed':False,'active':False,'enabled':False} for names in M.UNITS.values() for n in names};self.armed=False
    def unit(self,name):return dict(self.rows[name])
    def arm(self):self.armed=True
    def set_unit(self,name,enabled,before=None):
        M.U.need(not enabled or self.rows[name]['installed'],'module_requires_setup')
        self.rows[name].update(active=enabled,enabled=enabled)
    def restore_unit(self,name,before):self.rows[name]=dict(before)


class CompositionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve()/'agent';data=self.root/'astrbot/data/plugin_data/affect';data.mkdir(parents=True)
        (data/'companion_health.json').write_text('{"module_policy_schema":1}')
        self.d=Docker(self.root);self.h=Host()
        for k,v in [('HOME',self.root/'control'),('MAINTAIN',self.root/'maintain.py')]:
            p=patch.object(M,k,v);p.start();self.addCleanup(p.stop)
        p=patch.object(M.U,'ROOT_STATE',self.root/'updates');p.start();self.addCleanup(p.stop)
        self.c=M.Controller(self.root,self.d,self.h);self.c.poll=.0001;self.c.wait_seconds=.005
    def test_catalog_has_15_registered_units_and_four_profiles(self):
        v,rows,order=M.registry();self.assertEqual(len(rows),15);self.assertEqual(len(v['profiles']),4);self.assertEqual(set(rows),set(order))
    def test_dependencies_added_and_dependents_removed(self):
        v=M.plan(['core','reflection','proactive'],[])
        self.assertEqual(set(v['dependencies_added']),{'learning','autonomy'})
        v=M.disable_plan(['autonomy'],v['enabled']);self.assertNotIn('proactive',v['enabled'])
    def test_required_core_and_unknown_ids_are_rejected(self):
        with self.assertRaises(M.ModuleError):M.disable_plan(['core'],['core'])
        with self.assertRaises(M.ModuleError):M.plan(['arbitrary_shell'],[])
    def test_missing_adapter_and_cycle_are_rejected(self):
        p=self.root/'catalog.json';v=copy.deepcopy(M.registry()[0]);v['modules'].append({'id':'unreviewed','requires':[]});p.write_text(json.dumps(v))
        with self.assertRaises(M.ModuleError):M.registry(p)
        v=M.registry()[0];v['modules'][0]['requires']=['learning'];p.write_text(json.dumps(v))
        with self.assertRaises(M.ModuleError):M.registry(p)
    def test_chat_profile_stops_optional_services_and_keeps_sessions(self):
        result=self.c.apply(['core','learning','stickers'])
        self.assertEqual(result['state'],'ready');self.assertTrue(self.h.armed)
        for name in M.ALL_SERVICES:
            self.assertFalse(self.d.items[name]['State']['Running']);self.assertEqual(self.d.items[name]['HostConfig']['RestartPolicy'],{'Name':'no'})
            self.assertEqual((self.root/'service-data'/name/'session.txt').read_text(),'synthetic-session')
        self.assertTrue(self.d.items['astrbot']['State']['Running']);self.assertTrue(self.d.items['snowluma']['State']['Running'])
        self.assertFalse(P.enabled(self.c.mirror.parent,'public_web'));self.assertTrue(P.enabled(self.c.mirror.parent,'learning'))
    def test_remove_and_reenable_recreates_same_data_without_pull(self):
        self.c.apply(['core'],remove=True)
        self.assertFalse(M.ALL_SERVICES & set(self.d.items))
        result=self.c.apply(['core','public_web','workflows'])
        self.assertEqual(result['state'],'ready')
        for name in (*M.SERVICES['public_web'],*M.SERVICES['workflows']):
            self.assertTrue(self.d.items[name]['State']['Running']);self.assertEqual(self.d.items[name]['Mounts'][0]['Source'],str(self.root/'service-data'/name))
    def test_already_disabled_services_can_be_removed(self):
        self.c.apply(['core']);self.c.apply(['core'],remove=True)
        self.assertFalse(M.ALL_SERVICES & set(self.d.items))
    def test_partial_failure_restores_prior_services_and_flags(self):
        self.d.fail_stop='p1-workbench';result=self.c.apply(['core'])
        self.assertEqual(result['state'],'rolled_back')
        for name in M.ALL_SERVICES:self.assertTrue(self.d.items[name]['State']['Running'])
        self.assertTrue(P.enabled(self.c.mirror.parent,'public_web'))
    def test_recover_interrupted_operation_uses_durable_before_state(self):
        self.c.apply(['core','learning'])
        v=M.U.read(self.c.home/'state.json');v.update(state='applying',target=['core'])
        M.U.atom(self.c.home/'state.json',v)
        self.c.publish(['core'],v['generation'])
        self.assertEqual(self.c.recover()['state'],'rolled_back')
        self.assertTrue(P.enabled(self.c.mirror.parent,'public_web'))
    def test_foreign_image_change_stops_adoption(self):
        self.c.apply(['core']);self.d.items['p1-workbench']['Image']='sha256:'+'f'*64
        with self.assertRaisesRegex(M.ModuleError,'module_binding_changed'):self.c.apply(['core','workbench'])
    def test_unprepared_service_requires_setup(self):
        del self.d.items['p1-workbench']
        with self.assertRaisesRegex(M.ModuleError,'module_requires_setup'):self.c.apply(['core','workbench'])
    def test_host_modules_cannot_install_unreviewed_programs(self):
        with self.assertRaisesRegex(M.ModuleError,'module_requires_setup'):self.c.apply(['core','monitor'])
    def test_installed_host_units_enable_disable(self):
        for n in M.UNITS['monitor']:self.h.rows[n]['installed']=True
        self.c.apply(['core','monitor']);self.assertTrue(all(self.h.unit(n)['active'] for n in M.UNITS['monitor']))
        self.c.apply(['core']);self.assertFalse(any(self.h.unit(n)['active'] for n in M.UNITS['monitor']))
    def test_old_runtime_is_not_given_a_nonfunctional_switch(self):
        self.c.mirror.with_name('companion_health.json').write_text('{}')
        with self.assertRaisesRegex(M.ModuleError,'runtime_module_upgrade_required'):self.c.apply(['core'])
    def test_active_core_upgrade_blocks_module_changes(self):
        M.U.atom(M.U.ROOT_STATE/self.c.home.name/'active.json',{'state':'observing'})
        with self.assertRaisesRegex(M.ModuleError,'core_upgrade_in_progress'):self.c.apply(['core'])
    def test_public_status_contains_no_private_bindings(self):
        self.c.apply(['core']);text=json.dumps(self.c.status())
        self.assertNotIn('do-not-print',text);self.assertNotIn('synthetic-session',text);self.assertNotIn(str(self.root),text)
    def test_partial_legacy_service_is_reconciled_to_off(self):
        self.d.items['p1-browser-egress']['State']['Running']=False
        self.assertEqual(self.c.apply(['core'])['state'],'ready')
        self.assertFalse(self.d.items['p1-browser']['State']['Running'])
    def test_busy_maintenance_does_not_change_services(self):
        with M.U.exclusive(self.c.mirror.parent/'maintenance.lock'):
            self.assertEqual(self.c.apply(['core'])['state'],'rolled_back')
        self.assertTrue(all(self.d.items[n]['State']['Running'] for n in M.ALL_SERVICES))
        self.assertFalse(self.c.mirror.exists())
    def test_recovery_limit_requires_explicit_manual_retry(self):
        self.c.apply(['core']);v=M.U.read(self.c.home/'state.json');v.update(state='applying',recovery_attempts=2);M.U.atom(self.c.home/'state.json',v)
        self.assertEqual(self.c.recover()['state'],'rollback_blocked')
        self.assertEqual(self.c.recover(True)['state'],'rolled_back')


class RuntimePolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.p=Path(self.tmp.name).resolve()
    def test_absent_config_preserves_existing_behavior(self):
        self.assertTrue(all(P.enabled(self.p,k) for k in P.FEATURES));self.assertFalse(P.enabled(self.p,'unknown'))
    def test_disabled_tools_cannot_consume_budget_or_reach_transport(self):
        (self.p/'modules_enabled.json').write_text('{"schema":1,"enabled":["core"]}')
        for tool in P.TOOL_MODULES:self.assertFalse(P.tool_enabled(self.p,tool),tool)
        self.assertFalse(P.tool_enabled(self.p,'p1_mcp_capabilities'));self.assertTrue(P.tool_enabled(self.p,'search_memory'))
    def test_corruption_disables_optional_but_never_privacy_core(self):
        (self.p/'modules_enabled.json').write_text('{broken')
        self.assertTrue(P.enabled(self.p,'core'));self.assertFalse(P.enabled(self.p,'public_web'))
    def test_toggle_is_seen_without_plugin_reload(self):
        p=self.p/'modules_enabled.json';M.U.atom(p,{'schema':1,'enabled':['core','learning']});self.assertTrue(P.enabled(self.p,'learning'))
        M.U.atom(p,{'schema':1,'enabled':['core']});self.assertFalse(P.enabled(self.p,'learning'))
    def test_symlink_policy_is_not_followed(self):
        (self.p/'other').write_text('{"schema":1,"enabled":["core","learning"]}')
        (self.p/'modules_enabled.json').symlink_to(self.p/'other');self.assertFalse(P.enabled(self.p,'learning'))
    def test_static_gate_is_wired_to_native_mcp_and_schedulers(self):
        checks={'release/astrbot_plugin_affect/main.py':['module_tool_enabled(DATA,t.name)','module_policy_schema'],
                'services/mcp/server.py':['module_tool_enabled(DATA,'],
                'release/astrbot_plugin_affect/agency_runtime.py':["module_on(self.data,'autonomy')","module_on(self.data,'workbench')"],
                'release/astrbot_plugin_affect/social_runtime.py':["module_on(self.data,'proactive')"]}
        for rel,needles in checks.items():
            text=(R/rel).read_text()
            for s in needles:self.assertIn(s,text)


if __name__=='__main__':unittest.main()
