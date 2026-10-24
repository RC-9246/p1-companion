"""Seal a healthy neutral installation and install bounded host recovery. No model commands."""
import argparse,hashlib,json,os,re,shutil,subprocess,sys
from pathlib import Path
R=Path(__file__).resolve().parents[1];p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=Path('/srv/p1-agent'));p.add_argument('--apply',action='store_true');a=p.parse_args();root=a.root.resolve();assert re.fullmatch('/[A-Za-z0-9_./-]+',str(root)) and str(root) not in ('/','/srv','/home')
print(json.dumps({'dry_run':not a.apply,'root':str(root),'services':8,'timers':['p1-companion-maintain','p1-companion-watchdog']}))
if not a.apply:raise SystemExit(0)
assert os.geteuid()==0;os.umask(0o077);data=root/'astrbot/data';affect=data/'plugin_data/affect';stage=data/'companion_v020_lab'
def run(args,timeout=40):
 result=subprocess.run(args,capture_output=True,text=True,timeout=timeout)
 if result.returncode:raise RuntimeError('Prerequisite failed: '+args[0]+'; inspect local service health')
 return result
for name in ('astrbot','snowluma','p1-browser','p1-browser-egress','p1-leisure','p1-leisure-egress','p1-n8n','p1-workbench'):
 value=json.loads(run(['docker','inspect',name,'--format','{{json .State}}']).stdout);assert value['Running'] and value.get('Health',{}).get('Status','healthy')=='healthy'
h=json.loads((affect/'companion_health.json').read_text());assert all(h.get(k) for k in ('agency_ready','group_memory_ready','group_affect_ready','learning_ready','qq_plain_ready'))
# The recovery engine uses explicit container projects and Compose paths only.
assert (root/'astrbot/compose.yaml').is_file() and (root/'snowluma/compose.yaml').is_file(),'Keep the original core Compose files at the documented paths'
lib=Path('/usr/local/lib/p1-companion');lib.mkdir(mode=0o700,parents=True,exist_ok=True)
for name,dest in [('resilience.py',lib/'resilience.py'),('p1-companion-maintain.py',Path('/usr/local/sbin/p1-companion-maintain.py')),('p1-companion-watchdog.py',Path('/usr/local/sbin/p1-companion-watchdog.py')),('p1-companion-backup-agency.py',Path('/usr/local/sbin/p1-companion-backup-agency.py'))]:
 dest.write_text((data/'companion_services/maintenance'/name).read_text());dest.chmod(0o700)
health=Path('/usr/local/sbin/p1-healthcheck.py')
if not health.exists():
 health.write_text("#!/usr/bin/env python3\nimport json,subprocess,sys\nnames=['astrbot','snowluma','p1-browser','p1-browser-egress','p1-leisure','p1-leisure-egress','p1-n8n','p1-workbench']\nfor name in names:\n p=subprocess.run(['docker','inspect',name,'--format','{{json .State}}'],capture_output=True,text=True)\n if p.returncode:sys.exit(1)\n s=json.loads(p.stdout)\n if not s['Running'] or s.get('Health',{}).get('Status','healthy')!='healthy':sys.exit(1)\nprint('PASS: container health (verify account login separately)')\n");health.chmod(0o700)
backup=Path('/usr/local/sbin/p1-backup-dbs')
if not backup.exists():
 backup.write_text("#!/usr/bin/env python3\nfrom pathlib import Path\nimport sqlite3,time,os\nfrom contextlib import closing\nos.umask(0o077)\nroot=Path(ROOT_PLACEHOLDER)\nfolder=root/'backups/db-daily';folder.mkdir(parents=True,exist_ok=True)\nfor rel in ['plugin_data/affect/affect.db','plugin_data/memoria/memoria.db','plugin_data/p1_groups/groups.db','data_v4.db','knowledge_base/kb.db']:\n src=root/'astrbot/data'/rel\n if not src.is_file():continue\n target=folder/(src.parent.name+'-'+src.name+'-'+str(int(time.time()))+'.db')\n with closing(sqlite3.connect('file:'+str(src)+'?mode=ro',uri=True)) as a,closing(sqlite3.connect(target)) as b:a.backup(b)\nimport sys\nsys.path.insert(0,str(root/'astrbot/data/plugins'))\nfrom astrbot_plugin_affect.retention import native_database\nfor q in folder.glob('data-data_v4.db-*.db'):native_database(q,all_temporary=True)\nfor q in folder.glob('*.db'):\n if q.name.startswith(('affect-affect.db-','memoria-memoria.db-','p1_groups-groups.db-','data-data_v4.db-','knowledge_base-kb.db-')) and time.time()-q.stat().st_mtime>30*86400:q.unlink()\n".replace("ROOT_PLACEHOLDER",repr(str(root))));backup.chmod(0o700)
# Schedule the generated/supplied DB backup and the attachment-safe agency backup.
backup_service=Path('/etc/systemd/system/p1-companion-snapshot.service');backup_timer=Path('/etc/systemd/system/p1-companion-snapshot.timer')
agency_step='' if 'p1-companion-backup-agency.py' in backup.read_text() else 'ExecStart=/usr/local/sbin/p1-companion-backup-agency.py\n'
backup_service.write_text('[Unit]\nDescription=Private Companion database and permanent-note snapshots\n[Service]\nType=oneshot\nUMask=0077\nExecStart=/usr/local/sbin/p1-backup-dbs\n'+agency_step+'TimeoutStartSec=180\nNice=15\n')
backup_timer.write_text('[Unit]\nDescription=Daily private Companion snapshots\n[Timer]\nOnCalendar=*-*-* 04:30:00\nPersistent=true\n[Install]\nWantedBy=timers.target\n')
for name in ('p1-companion-maintain.service','p1-companion-maintain.timer','p1-companion-watchdog.service','p1-companion-watchdog.timer'):
 target=Path('/etc/systemd/system')/name;target.write_text((data/'companion_services/maintenance'/name).read_text());target.chmod(0o600)
# Snapshot the installed neutral source, not the private production manifest.
manifest={str(p.relative_to(data/'plugins')):hashlib.sha256(p.read_bytes()).hexdigest() for name in (R/'release').iterdir() if name.is_dir() for p in (data/'plugins'/name.name).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc'}
(stage/'evidence').mkdir(exist_ok=True);(stage/'evidence/release-manifest.json').write_text(json.dumps(manifest))
run(['python3',str(stage/'tools/checkpoint_recovery.py')]);run(['systemctl','daemon-reload']);run(['systemctl','enable','--now','p1-companion-maintain.timer','p1-companion-watchdog.timer','p1-companion-snapshot.timer'])
print('Healthy source, fixed paths and image IDs sealed. Recovery timers enabled. Keep off-device backups and validate account login separately.')
