"""Restore installer source/config snapshots; preserve databases and all rejected files."""
import argparse,fcntl,json,os,shutil,subprocess,time
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('point',type=Path);p.add_argument('--apply',action='store_true');a=p.parse_args();point=a.point.resolve();receipt=json.loads((point/'receipt.json').read_text());data=Path(receipt['data_path']).resolve();root=data.parents[1]
assert data.name=='data' and data.parent.name=='astrbot' and point.parent==root/'backups' and point.name.startswith('install-')
expected={'astrbot_plugin_affect','astrbot_plugin_memoria','astrbot_plugin_p1_reflection','astrbot_plugin_p1_stickers','astrbot_plugin_p1_group_memory','astrbot_plugin_p1_group_affect','astrbot_plugin_p1_qq_style','astrbot_plugin_p1_learning'};assert set(receipt['plugins'])==expected
print(json.dumps({'dry_run':not a.apply,'point':str(point),'database_restore':False,'rejected_files_preserved':True}))
if not a.apply:raise SystemExit(0)
assert os.geteuid()==0 and point.stat().st_uid==0 and not point.stat().st_mode&0o022
subprocess.run(['systemctl','stop','p1-companion-maintain.timer','p1-companion-watchdog.timer'],capture_output=True)
( data/'plugin_data/affect/maintenance.disabled').touch(mode=0o600)
with (data/'plugin_data/affect/maintenance.lock').open('a') as lock:
 fcntl.flock(lock,fcntl.LOCK_EX)
 rejected=point/('rejected-'+str(time.time_ns()));rejected.mkdir(mode=0o700)
 for name in expected:
  target=data/'plugins'/name;assert not target.is_symlink() and target.parent.resolve().is_relative_to(data)
  if target.exists():os.replace(target,rejected/name)
  if (point/'plugins'/name).is_dir():shutil.copytree(point/'plugins'/name,target)
 for name in ('cmd_config.json','mcp_server.json'):
  target=data/name
  if (point/name).is_file():shutil.copy2(point/name,target)
  elif name=='mcp_server.json' and target.exists():
   current=json.loads(target.read_text());current.get('mcpServers',{}).pop('p1_companion',None);target.write_text(json.dumps(current));target.chmod(0o600)
 r=subprocess.run(['docker','restart','--time','10','astrbot'],capture_output=True,timeout=60);assert r.returncode==0
print('Source/config snapshot restored. Databases preserved; automatic recovery remains disabled until the restored version is verified and resealed.')
