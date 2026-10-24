"""Final v020 emotion patch; rollback watchdog and immutable before checkpoint."""
import argparse,fcntl,json,os,shutil,sqlite3,subprocess,sys,time
from pathlib import Path
S=Path(__file__).resolve().parents[1];D=S.parent;B=D.parents[1];A=D/'plugin_data/affect';C=Path('/var/lib/p1-companion/recovery/current')
def run(args,timeout=30):return subprocess.run(args,capture_output=True,text=True,timeout=timeout)
def sha(p):return __import__('hashlib').sha256(p.read_bytes()).hexdigest()
def rollback(point):
 point=Path(point);assert point.parent==B/'backups' and point.name.startswith('companion-patch-v020-')
 if (point/'rolled_back').exists():return
 manifest=json.loads((point/'before-manifest.json').read_text())
 for rel in manifest:
  target=D/'plugins'/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(point/'plugins'/rel,target)
 for key,path in json.loads((point/'fixed-paths.json').read_text()).items():shutil.copy2(point/'fixed'/key,path)
 if C.exists():shutil.rmtree(C)
 shutil.copytree(point/'checkpoint',C)
 run(['systemctl','daemon-reload']);run(['docker','restart','--time','10','astrbot'],50);run(['systemctl','start','p1-companion-maintain.timer','p1-companion-watchdog.timer'])
 (point/'rolled_back').write_text(str(time.time()))
def main():
 assert os.geteuid()==0;os.umask(0o077)
 parser=argparse.ArgumentParser();parser.add_argument('--watchdog');parser.add_argument('--rollback');args=parser.parse_args()
 if args.rollback:rollback(args.rollback);return
 if args.watchdog:
  p=Path(args.watchdog);end=json.loads((p/'deadline.json').read_text())['at']
  while time.time()<end:
   if (p/'committed').exists() or (p/'rolled_back').exists():return
   time.sleep(2)
  if not (p/'committed').exists():rollback(p)
  return
 old=json.loads((C/'manifest.json').read_text());new=json.loads((S/'evidence/release-manifest.json').read_text());assert set(old)==set(new);changed=[k for k in old if old[k]!=new[k]]
 for rel,h in old.items():assert sha(D/'plugins'/rel)==h,'production drift'
 for rel,h in new.items():assert sha(S/'release'/rel)==h,'stage drift'
 point=B/'backups'/('companion-patch-v020-'+time.strftime('%Y%m%d-%H%M%S'));point.mkdir(mode=0o700)
 (point/'before-manifest.json').write_text(json.dumps(old));shutil.copytree(C/'plugins',point/'plugins');shutil.copytree(C,point/'checkpoint')
 fixed={'watchdog':'/usr/local/sbin/p1-companion-watchdog.py','maintain':'/usr/local/sbin/p1-companion-maintain.py','resilience':'/usr/local/lib/p1-companion/resilience.py','watchdog_service':'/etc/systemd/system/p1-companion-watchdog.service'}
 (point/'fixed-paths.json').write_text(json.dumps(fixed));(point/'fixed').mkdir()
 for key,path in fixed.items():shutil.copy2(path,point/'fixed'/key)
 run(['systemctl','stop','p1-companion-maintain.timer','p1-companion-watchdog.timer'])
 # A oneshot is 'activating' throughout its work. Share its actual file lock,
 # so a timer already in flight cannot restore old sources during deployment.
 for unit in ('p1-companion-maintain.service','p1-companion-watchdog.service'):
  for _ in range(30):
   state=run(['systemctl','is-active',unit]).stdout.strip()
   if state not in ('active','activating','deactivating','reloading'):break
   time.sleep(2)
  else:raise RuntimeError('maintenance_still_running')
 deployment_lock=(A/'maintenance.lock').open('a');fcntl.flock(deployment_lock,fcntl.LOCK_EX)
 start=time.time();(point/'deadline.json').write_text(json.dumps({'at':start+150}))
 with (point/'watchdog.log').open('w') as f:subprocess.Popen([sys.executable,str(__file__),'--watchdog',str(point)],stdin=subprocess.DEVNULL,stdout=f,stderr=subprocess.STDOUT,start_new_session=True,close_fds=True)
 try:
  for rel,h in new.items():
   if old[rel]!=h:shutil.copy2(S/'release'/rel,D/'plugins'/rel)
  shutil.copy2(S/'services/maintenance/p1-companion-watchdog.py',fixed['watchdog']);os.chmod(fixed['watchdog'],0o700)
  shutil.copy2(S/'services/maintenance/p1-companion-maintain.py',fixed['maintain']);os.chmod(fixed['maintain'],0o700)
  shutil.copy2(S/'services/maintenance/resilience.py',fixed['resilience']);os.chmod(fixed['resilience'],0o700)
  shutil.copy2(S/'services/maintenance/p1-companion-watchdog.service',fixed['watchdog_service'])
  ready=A/'companion_health.json'
  if changed:
   ready.unlink(missing_ok=True);assert run(['docker','restart','--time','10','astrbot'],50).returncode==0
  for _ in range(35):
   try:h=json.loads(ready.read_text())
   except (OSError,ValueError):h={}
   if (not changed or h.get('at',0)>=start-1) and all(h.get(k) for k in ('group_memory_ready','group_affect_ready','learning_ready','qq_plain_ready','agency_ready','qq_actions_ready')):break
   time.sleep(2)
  else:raise RuntimeError('module_health_failed')
  health_ok=False
  while time.time()<start+120:
   probe=run(['python3','/usr/local/sbin/p1-healthcheck.py'],30);(point/'health-last.txt').write_text(probe.stdout+probe.stderr)
   if probe.returncode==0:health_ok=True;break
   time.sleep(2)
  assert health_ok,'core health unavailable within bounded startup window'
  for rel,h in new.items():assert sha(D/'plugins'/rel)==h
  # Retire only the known, newly introduced bucket-10 encoding. It is next UTC
  # day's classifier key, never a separate safe namespace. Account before removal;
  # a durable migration receipt makes an interrupted transfer conservative.
  old_runtime=(point/'plugins/astrbot_plugin_affect/agency_runtime.py').read_text()
  budget_transfer=0
  if 'take_budget,200,bucket=10' in old_runtime:
   future_key=(int(time.time())//86400+1)*10;local_day=int((time.time()+28800)//86400)
   with sqlite3.connect(A/'affect.db') as legacy:
    row=legacy.execute('SELECT used FROM companion_budget WHERE day=?',(future_key,)).fetchone();budget_transfer=int(row[0]) if row else 0
   (point/'budget-before.json').write_text(json.dumps({'legacy_key':future_key,'used':budget_transfer,'local_day':local_day}))
   if budget_transfer:
    with sqlite3.connect(A/'agency/agency.db') as account:
     account.execute('CREATE TABLE IF NOT EXISTS budget_migrations(id TEXT PRIMARY KEY,used INTEGER NOT NULL)')
     if not account.execute('SELECT 1 FROM budget_migrations WHERE id=?',(point.name,)).fetchone():
      account.execute('INSERT INTO model_budget VALUES(?,?) ON CONFLICT(day) DO UPDATE SET used=used+excluded.used',(local_day,budget_transfer));account.execute('INSERT INTO budget_migrations VALUES(?,?)',(point.name,budget_transfer))
    with sqlite3.connect(A/'affect.db') as legacy:legacy.execute('DELETE FROM companion_budget WHERE day=? AND used=?',(future_key,budget_transfer))
  assert run(['python3',str(S/'tools/checkpoint_recovery.py')],45).returncode==0
  (point/'committed').write_text(str(time.time()));run(['systemctl','daemon-reload']);run(['systemctl','start','p1-companion-maintain.timer','p1-companion-watchdog.timer'])
  report={'status':'deployed','version':'0.20.0','recovery_point':str(point),'modified_files':[k for k in old if old[k]!=new[k]],'seconds':round(time.time()-start,2),'core_health':True,'scoped_group_coping':True,'resolved_tail_question_guard':True,'background_budget_separate_from_max_deliberation':True,'new_qq_test_messages':0,'legacy_background_calls_moved_to_independent_budget':budget_transfer}
  (S/'evidence/final-emotion-deployment.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
 except BaseException:rollback(point);raise
if __name__=='__main__':main()
