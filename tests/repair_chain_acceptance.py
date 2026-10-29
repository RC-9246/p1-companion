"""Root/Linux lab: real systemd, real file faults and SIGKILL, no production mounts.

Only uniquely prefixed lab units are mutated. An injected uptime offset advances
rate-limit windows; OS time is unchanged. Production container state is read only.
"""
import fcntl,hashlib,importlib.util,json,os,shutil,signal,stat,subprocess,sys,tempfile,time
from pathlib import Path
R=Path(__file__).resolve().parents[1]
def load():
 spec=importlib.util.spec_from_file_location('watchdog_lab',R/'services/maintenance/p1-companion-watchdog.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
PREFIX='p1-repair-chain-lab-'
PROD=('astrbot','snowluma','p1-browser','p1-browser-egress','p1-leisure','p1-leisure-egress','p1-workbench','p1-n8n')
def production():
 p=subprocess.run(['docker','inspect','--format','{{.Name}} {{.State.StartedAt}} {{.RestartCount}}',*PROD],capture_output=True,text=True,timeout=20);assert p.returncode==0;return p.stdout

def checked_systemctl(args,timeout=20):
 assert args[0]=='systemctl'
 if args[1]!='daemon-reload':
  names=[a for a in args[2:] if a.endswith(('.timer','.service'))]
  assert names and all(a.startswith(PREFIX) and '/' not in a for a in names),args
 return subprocess.run(args,capture_output=True,text=True,timeout=timeout)

def context(m,cfg):
 m.SERVICE=cfg['service'];m.TIMERS=tuple(cfg['timers'])
 clock=lambda:(time.time(),float(Path('/proc/uptime').read_text().split()[0])+cfg['offset'],'lab-boot')
 return m.Context(Path(cfg['checkpoint']),Path(cfg['data']),{k:Path(v) for k,v in cfg['files'].items()},0,0,checked_systemctl,clock)
def child(path,phase):
 cfg=json.loads(Path(path).read_text());m=load();ctx=context(m,cfg)
 if phase=='before_files':
  original=m.atomic_bytes
  def fault(p,*args):
   if p==ctx.files['maintain']:os.kill(os.getpid(),signal.SIGKILL)
   return original(p,*args)
  m.atomic_bytes=fault
 else:
  def fault(args,timeout=20):
   result=checked_systemctl(args,timeout)
   if args[1]=='start':os.kill(os.getpid(),signal.SIGKILL)
   return result
  ctx.runner=fault
 m.recover(ctx);raise AssertionError('crash injection not reached')

def main():
 assert os.geteuid()==0 and sys.platform=='linux';os.umask(0o077);before=production();m=load();records=[];installed=[]
 def item(name,ok):records.append({'case':name,'passed':bool(ok)});assert ok,name
 with tempfile.TemporaryDirectory(prefix=PREFIX) as temp:
  sandbox=Path(temp);base=sandbox/'agent';data=base/'astrbot/data/plugin_data/affect';data.mkdir(mode=0o700,parents=True);cp=sandbox/'checkpoint';(cp/'fixed').mkdir(parents=True,mode=0o700);cp.chmod(0o700)
  name=PREFIX+str(os.getpid());service=name+'-engine.service';timer=name+'-engine.timer';watch_service=name+'-watch.service';watch_timer=name+'-watch.timer'
  engine=sandbox/'engine.py'
  body=('#!/usr/bin/env python3\nfrom pathlib import Path\nimport json,time,sys\ndata=Path('+repr(str(data))+')\nif (data/"fail").exists():sys.exit(17)\np=data/"runs"\np.write_text(str(int(p.read_text())+1 if p.exists() else 1))\nv={"at":time.time(),"disabled":False,"ttl_sweep":True,"services":{"lab":True},"databases":{}}\nq=data/"maintenance_health.json"\nq.write_text(json.dumps(v))\n').encode()
  files={};manifest={};metadata={}
  unit_names={'unit_p1-companion-maintain_service':service,'unit_p1-companion-maintain_timer':timer,'unit_p1-companion-watchdog_service':watch_service,'unit_p1-companion-watchdog_timer':watch_timer}
  for key,target in m.FILES.items():
   if key in unit_names:
    p=Path('/etc/systemd/system')/unit_names[key];assert not p.exists(),str(p)
    if p.suffix=='.service':
     cmd='/usr/bin/python3 '+str(engine) if key.endswith('maintain_service') else '/usr/bin/true'
     raw=('[Unit]\nDescription=Isolated repair-chain acceptance\n[Service]\nType=oneshot\nExecStart='+cmd+'\nTimeoutStartSec=15\nNoNewPrivileges=yes\nPrivateNetwork=yes\nProtectSystem=strict\nProtectHome=yes\nReadWritePaths='+str(data)+'\n').encode()
    else:
     unit=service if key.endswith('maintain_timer') else watch_service
     raw=('[Unit]\nDescription=Isolated repair-chain lab timer\n[Timer]\nOnActiveSec=1h\nUnit='+unit+'\n[Install]\nWantedBy=timers.target\n').encode()
    installed.append(p)
   else:
    p=engine if key=='maintain' else sandbox/(key+'.py');raw=body if key=='maintain' else b'#!/usr/bin/env python3\nvalue=1\n'
   files[key]=p;mode=0o644 if key.startswith('unit_') else 0o700
   p.write_bytes(raw);p.chmod(mode);source=cp/'fixed'/key;source.write_bytes(raw);source.chmod(0o600)
   manifest[key]=m.digest(raw);metadata[key]={'uid':0,'gid':0,'mode':mode}
  for file,value in [('fixed-manifest.json',manifest),('fixed-metadata.json',metadata)]:
   p=cp/file;p.write_text(json.dumps(value));p.chmod(0o600)
  cfg={'service':service,'timers':[timer,watch_timer],'checkpoint':str(cp),'data':str(data),'files':{k:str(v) for k,v in files.items()},'offset':0}
  def fresh():
   cfg['offset']+=86401
   return context(m,cfg)
  def runs():return int((data/'runs').read_text()) if (data/'runs').exists() else 0
  try:
   assert checked_systemctl(['systemctl','daemon-reload']).returncode==0
   assert checked_systemctl(['systemctl','enable','--now',timer,watch_timer]).returncode==0
   assert checked_systemctl(['systemctl','start',service]).returncode==0
   for key,target in files.items():
    target.unlink();result=m.recover(fresh())
    item('real_missing_'+key,result['status']=='repair_succeeded' and m.digest(target.read_bytes())==manifest[key] and stat.S_IMODE(target.stat().st_mode)==metadata[key]['mode'])
   engine.chmod(0o600);item('real_permission_only_drift',m.recover(fresh())['status']=='repair_succeeded' and stat.S_IMODE(engine.stat().st_mode)==0o700)
   assert checked_systemctl(['systemctl','disable','--now',timer]).returncode==0
   item('real_disabled_timer_reenabled',m.recover(fresh())['status']=='repair_succeeded')
   (data/'fail').touch();assert checked_systemctl(['systemctl','start',service]).returncode!=0
   ctx=fresh();result=m.recover(ctx);item('real_failed_oneshot_not_claimed_success',result['status']=='repair_failed' and result['pending'])
   (data/'fail').unlink();item('real_failed_engine_resumes_once',m.recover(ctx)['status']=='repair_succeeded')
   engine.unlink();ctx=fresh();config=sandbox/'child.json';config.write_text(json.dumps(cfg))
   p=subprocess.run([sys.executable,__file__,'--child',str(config),'before_files'],capture_output=True,text=True,timeout=30)
   assert p.returncode==-signal.SIGKILL
   item('sigkill_before_file_write_resumed',m.recover(ctx)['status']=='repair_succeeded')
   engine.unlink();ctx=fresh();config.write_text(json.dumps(cfg))
   p=subprocess.run([sys.executable,__file__,'--child',str(config),'after_engine'],capture_output=True,text=True,timeout=30)
   assert p.returncode==-signal.SIGKILL;count=runs();result=m.recover(ctx)
   item('sigkill_after_engine_no_duplicate_start',result['status']=='pending_recovery_verified' and runs()==count)
   count=runs();journal=m.Journal(data,0,0);attempts=len(journal.load()['attempts']);(data/'.watchdog-journal-a.json').write_text('{bad')
   result=m.recover(context(m,cfg));item('single_journal_slot_recovers_without_reset',result['status']=='healthy' and len(m.Journal(data,0,0).load()['attempts'])==attempts and runs()==count)
   saved={p:p.read_bytes() for p in m.Journal(data,0,0).paths}
   for p in saved:p.write_text('{bad')
   item('double_journal_corruption_stops_actions',m.recover(context(m,cfg))['status']=='journal_corrupt' and runs()==count)
   for p,raw in saved.items():p.write_bytes(raw);p.chmod(0o600)
   engine.write_text('bad syntax !!!');(data/'maintenance.disabled').touch();count=runs();item('operator_pause_respected',m.recover(fresh())['status']=='paused' and runs()==count);(data/'maintenance.disabled').unlink()
   with (data/'maintenance.lock').open('a') as lock:
    fcntl.flock(lock,fcntl.LOCK_EX);item('real_shared_lock_defers_repair',m.recover(context(m,cfg))['status']=='busy' and runs()==count)
   assert m.recover(context(m,cfg))['status']=='repair_succeeded'
   engine.write_text('bad syntax !!!');source=cp/'fixed/maintain';raw=source.read_bytes();source.write_text('poison');count=runs()
   item('poisoned_checkpoint_rejected_without_partial_repair',m.recover(fresh())['status']=='checkpoint_rejected' and engine.read_text()=='bad syntax !!!' and runs()==count)
   source.write_bytes(raw);source.chmod(0o600);assert m.recover(context(m,cfg))['status']=='repair_succeeded'
   # Rehearse the actual upgrade coordinator against the same isolated targets.
   # The on-disk copy and its persisted rollback helper share only this lab namespace.
   project=sandbox/'upgrade-project';(project/'scripts').mkdir(parents=True);(project/'services/maintenance').mkdir(parents=True)
   namespace='\nFILES='+repr({k:str(v) for k,v in files.items()})+'\nFILES={k:Path(v) for k,v in FILES.items()}\nSERVICE='+repr(service)+'\nTIMERS='+repr((timer,watch_timer))+'\nROOT=Path('+repr(str(cp))+')\nDATA=Path('+repr(str(data))+')\n'
   watchdog_source=(R/'services/maintenance/p1-companion-watchdog.py').read_text()
   watchdog_source=watchdog_source.replace("if __name__=='__main__':raise SystemExit(main())",namespace+"if __name__=='__main__':raise SystemExit(main())")
   (project/'services/maintenance/p1-companion-watchdog.py').write_text(watchdog_source)
   upgrader_source=(R/'scripts/upgrade_repair_chain.py' if (R/'scripts/upgrade_repair_chain.py').is_file() else R/'tools/upgrade_repair_chain.py').read_text()
   upgrader_source=upgrader_source.replace("CURRENT=Path('/var/lib/p1-companion/recovery/current')",'CURRENT=Path('+repr(str(cp))+')').replace("LIVE=Path('/usr/local/sbin/p1-companion-watchdog.py')",'LIVE=Path('+repr(str(files['watchdog']))+')')
   upgrader_source=upgrader_source.replace("TIMERS=('p1-companion-maintain.timer','p1-companion-watchdog.timer')",'TIMERS='+repr((timer,watch_timer))).replace("UNITS=('p1-companion-maintain.service','p1-companion-watchdog.service')",'UNITS='+repr((service,watch_service)))
   upgrade_file=project/'scripts/upgrade_repair_chain.py';upgrade_file.write_text(upgrader_source)
   spec=importlib.util.spec_from_file_location('isolated_upgrader',upgrade_file);up=importlib.util.module_from_spec(spec);spec.loader.exec_module(up)
   for target in up.sources(base)[1:]:target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(files['watchdog'].read_bytes());target.chmod(0o700)
   baseline=up.tree_hashes(cp);before_files={str(p):p.read_bytes() for p in up.sources(base)}
   report=up.apply(base);point=Path(report['recovery_point'])
   item('actual_upgrade_commits_without_container_restart',report['changed'] and report['checkpoint_verified'] and not report['bot_restarted'])
   up.restore(point,base,manual=True)
   item('actual_upgrade_manual_rollback_preserves_original_checkpoint',up.tree_hashes(cp)==baseline and all(p.read_bytes()==before_files[str(p)] for p in up.sources(base)))
   original_candidate=up.candidate
   def reject_after(raw):
    module=original_candidate(raw);module.inspect=lambda ctx:{'ok':False};return module
   up.candidate=reject_after
   try:up.apply(base);raise AssertionError('postcheck fault not reached')
   except up.UpgradeError:pass
   finally:up.candidate=original_candidate
   item('actual_failed_upgrade_automatically_rolled_back',up.tree_hashes(cp)==baseline and all(p.read_bytes()==before_files[str(p)] for p in up.sources(base)))
   crash=sandbox/'upgrade-crash.py';crash.write_text('import importlib.util,os,signal,sys\nfrom pathlib import Path\ns=importlib.util.spec_from_file_location("upgrade",sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)\noriginal=m.atom\ndef kill_after(p,*args,**kwargs):\n r=original(p,*args,**kwargs)\n if p==m.LIVE:os.kill(os.getpid(),signal.SIGKILL)\n return r\nm.atom=kill_after\nm.apply(Path(sys.argv[2]))\n')
   previous={p.name for p in (base/'backups').glob('recovery-chain-*')}
   child_run=subprocess.run([sys.executable,str(crash),str(upgrade_file),str(base)],capture_output=True,text=True,timeout=90);assert child_run.returncode==-signal.SIGKILL
   interrupted=next(p for p in (base/'backups').glob('recovery-chain-*') if p.name not in previous)
   recovered=subprocess.run([sys.executable,str(interrupted/'rollback-helper.py'),'--root',str(base),'--recover',str(interrupted)],capture_output=True,text=True,timeout=90)
   # OnBootSec may launch the persisted systemd guard immediately on an old
   # boot. It can win the lock after SIGKILL; wait for its real receipt before
   # testing the same helper's idempotent entry point again.
   deadline=time.monotonic()+30
   while recovered.returncode!=0 and time.monotonic()<deadline:
    time.sleep(.5)
    recovered=subprocess.run([sys.executable,str(interrupted/'rollback-helper.py'),'--root',str(base),'--recover',str(interrupted)],capture_output=True,text=True,timeout=90)
   if recovered.returncode:print(json.dumps({'guard_exit':recovered.returncode,'output':(recovered.stdout+recovered.stderr)[-1500:]}))
   item('killed_upgrade_recovers_via_persisted_guard_entry',recovered.returncode==0 and (interrupted/'rolled_back').exists() and up.tree_hashes(cp)==baseline and all(p.read_bytes()==before_files[str(p)] for p in up.sources(base)))
  finally:
   checked_systemctl(['systemctl','stop',timer,watch_timer]);checked_systemctl(['systemctl','disable',timer,watch_timer]);checked_systemctl(['systemctl','stop',service,watch_service])
   for p in installed:
    assert p.name.startswith(PREFIX);p.unlink(missing_ok=True)
   checked_systemctl(['systemctl','daemon-reload']);checked_systemctl(['systemctl','reset-failed',service,watch_service])
 item('production_containers_unchanged',before==production())
 summary={'all_passed':all(r['passed'] for r in records),'cases':records,'real_systemd_units':True,'real_sigkill':True,'production_mounts_into_lab':False,'rate_limit_clock':'injected uptime offset; OS clock unchanged','production_before_after_equal':True,'real_qq_messages':0,'model_calls':0}
 Path(os.environ.get('P1_ACCEPTANCE_OUTPUT',str(R/'evidence/repair-chain-isolated.json'))).write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n');print(json.dumps(summary,ensure_ascii=False))
if __name__=='__main__':
 if len(sys.argv)>1 and sys.argv[1]=='--child':child(sys.argv[2],sys.argv[3])
 else:main()
