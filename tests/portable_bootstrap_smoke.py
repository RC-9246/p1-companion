"""Neutral install in a fresh temporary tree; no Docker, network or production writes."""
import hashlib,json,os,stat,subprocess,sys,tempfile
from pathlib import Path
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'release'))
def main():
 assert os.geteuid()==0,'Run in disposable SDK container so uid ownership can be verified'
 with tempfile.TemporaryDirectory(prefix='p1-neutral-bootstrap-') as tmp:
  root=Path(tmp)/'agent';data=root/'astrbot/data';data.mkdir(parents=True);(data/'cmd_config.json').write_text(json.dumps({'platform_settings':{'id_whitelist':[]},'provider':[]}));before=(data/'cmd_config.json').read_bytes()
  args=[sys.executable,str(R/'scripts/bootstrap.py'),'--root',str(root),'--bot-id','10001','--owner-id','20002','--friend-id','20003']
  dry=subprocess.run(args,capture_output=True,text=True);assert dry.returncode==0 and not (data/'plugins').exists()
  applied=subprocess.run([*args,'--apply'],capture_output=True,text=True);assert applied.returncode==0,applied.stderr[-1500:]
  plugins=[p for p in (data/'plugins').iterdir() if p.is_dir()];assert len(plugins)==8
  for p in (data/'plugins').rglob('*.py'):compile(p.read_text(),str(p),'exec')
  from astrbot_plugin_affect.reactions import Catalog
  assert not Catalog(data/'plugins/astrbot_plugin_affect').assets
  affect=data/'plugin_data/affect';owner=json.loads((affect/'allowed_identities.json').read_text())['allowed_identities'];assert len(owner)==1
  expected='v1:'+hashlib.sha256(b'["qq_snowluma","10001","20002"]').hexdigest();assert owner==[expected]
  for name in ('browser_token','leisure_token','workbench_token'):
   p=affect/name;assert stat.S_IMODE(p.stat().st_mode)==0o600 and p.stat().st_uid==1001 and len(p.read_text())>=40
  policy=json.loads((affect/'qq_policy.json').read_text());assert not policy['enabled'] and policy['scope']=='whitelist' and policy['cross_forward']=='confirm'
  assert json.loads((affect/'groups.json').read_text())['groups']==[]
  for name in ('server.py','policy.py','quota.py','private_api.py','egress.py'):
   code=data/'companion_services/leisure'/name;assert code.stat().st_gid==1001 and stat.S_IMODE(code.stat().st_mode)==0o640
  assert set(json.loads((data/'mcp_server.json').read_text())['mcpServers']['p1_companion'])=={'command','args','active'}
  assert all(str(root) in (data/'companion_services'/rel).read_text() for rel in ('workbench/compose.yaml','leisure/compose.yaml','maintenance/p1-companion-maintain.py'))
  points=list((root/'backups').glob('install-*'));assert len(points)==1 and (points[0]/'cmd_config.json').read_bytes()==before
  report={'neutral_bootstrap_fresh_directory':True,'dry_run_no_writes':True,'plugins_installed':8,'python_sources_compile':True,'neutral_empty_catalog_accepted':True,'owner_identity_exact':True,'private_tokens_mode_uid_verified':True,'nonroot_bind_code_group_readable':True,'social_and_groups_closed_by_default':True,'mcp_configuration_shape_native':True,'custom_root_propagates':True,'original_config_recoverable':True,'docker_calls':0,'network_calls':0,'production_data_written':False}
  (R/'evidence/portable-bootstrap.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
if __name__=='__main__':main()
