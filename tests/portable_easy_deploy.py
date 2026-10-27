"""Root-only Linux rehearsal: real bootstrap/permissions/rollback, no Docker writes.

This proves the filesystem integration, not a cold full-stack installation or
real model/account delivery. No runtime secrets or production data are read.
"""
import hashlib,json,os,sqlite3,subprocess,sys,tempfile
from pathlib import Path
import importlib.util
R=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('installer',R/'deploy/install.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
def production_state():
 p=subprocess.run(['docker','inspect','--format','{{.Name}} {{.State.StartedAt}} {{.RestartCount}}','astrbot','snowluma','p1-browser','p1-browser-egress','p1-workbench','p1-leisure','p1-leisure-egress','p1-n8n'],capture_output=True,text=True,timeout=20)
 return p.stdout if p.returncode==0 else None
assert os.geteuid()==0 and sys.platform=='linux','Run with sudo only in a disposable Linux test environment'
os.umask(0o077)
manifest=m.verify_source(R); before=production_state()
with tempfile.TemporaryDirectory(prefix='p1-easy-deploy-lab-') as tmp:
 root=Path(tmp)/'agent'; data=root/'astrbot/data'; data.mkdir(parents=True)
 original={'provider':[{'id':'synthetic/deepseek','enable':True}],'platform':[{'id':'qq_snowluma','enable':False}]}
 m.atomic(data/'cmd_config.json',original)
 with sqlite3.connect(data/'data_v4.db') as db: db.execute('CREATE TABLE lab_history(value TEXT)');db.execute('INSERT INTO lab_history VALUES("before")')
 point=root/'backups/oneclick-lab';point.mkdir(parents=True,mode=0o700)
 m.atomic(point/'state.json',{'schema':1,'root':str(root),'status':'installing','steps':[],'core_project':'lab'})
 job=m.Job(point);m.snapshot(job);m.materialize(R,point/'source',root)
 p=subprocess.run([sys.executable,str(point/'source/scripts/bootstrap.py'),'--root',str(root),'--bot-id','10001','--owner-id','20002','--apply'],capture_output=True,text=True,timeout=30)
 assert p.returncode==0,'real_bootstrap_failed'
 installed=json.loads((data/'companion_v020_lab/evidence/release-manifest.json').read_text())
 for rel,digest in installed.items():assert hashlib.sha256((data/'plugins'/rel).read_bytes()).hexdigest()==digest
 for name in ('browser','leisure','workbench'):
  token=data/'plugin_data/affect'/(name+'_token');assert token.stat().st_mode&0o777==0o600;assert token.stat().st_uid==1001
 assert (data/'companion_services/leisure/server.py').stat().st_mode&0o777==0o640
 assert (data/'companion_services/leisure/server.py').stat().st_gid==1001
 assert str(root) in (root/'public-browser/compose.yaml').read_text()
 assert str(root) in (point/'source/scripts/setup_workflows.py').read_text()
 assert str(root) in (point/'source/scripts/install_monitor.py').read_text()
 assert '/home/p1admin/p1-agent' not in (point/'source/services/monitor/p1-resource-collector.service').read_text()
 with sqlite3.connect(data/'data_v4.db') as db:db.execute('INSERT INTO lab_history VALUES("after")')
 m.restore_paths(job)
 assert m.read(data/'cmd_config.json')==original
 assert not (data/'plugins/astrbot_plugin_affect').exists()
 with sqlite3.connect(data/'data_v4.db') as db:assert db.execute('SELECT value FROM lab_history').fetchall()==[('before',),('after',)]
 assert m.verify_source(R)==manifest
 after=production_state();assert before==after
 report={'real_linux_bootstrap_passed':True,'installed_plugin_files_verified':len(installed),
         'private_staging_root_remapped':True,'token_uid_and_mode_checked':True,'container_code_group_read_checked':True,
         'rollback_restored_original_config_and_sources':True,'new_database_history_preserved':True,
         'original_repository_files_unchanged':True,'production_container_start_times_and_restarts_unchanged':before is not None,
         'docker_mutations':0,'model_calls':0,'qq_messages':0,'cold_full_stack_install_tested':False}
 print(json.dumps(report,indent=2))
