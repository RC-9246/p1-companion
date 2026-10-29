"""Deterministic recovery primitives, independently testable with copied data.

No model output is accepted as a command/path/image. A known snapshot is the only
source of executable files. Corrupt originals are quarantined, never discarded.
"""
from contextlib import closing
import hashlib,json,math,os,re,shutil,sqlite3,time,stat,secrets
from pathlib import Path
MODULES=('astrbot_plugin_affect','astrbot_plugin_memoria','astrbot_plugin_p1_reflection','astrbot_plugin_p1_stickers','astrbot_plugin_p1_group_memory','astrbot_plugin_p1_group_affect','astrbot_plugin_p1_qq_style','astrbot_plugin_p1_learning')
SERVICES=('astrbot','snowluma','p1-n8n','p1-browser','p1-browser-egress','p1-workbench','p1-leisure','p1-leisure-egress')
def candidate_fixed(root):
 base=Path('/usr/local/lib/p1-companion/candidates');home=Path('/var/lib/p1-companion-candidates')/hashlib.sha256(str(root).encode()).hexdigest()[:16]
 return {**{'candidate_'+n:base/f for n,f in {'manager':'manager.py','worker':'worker.py','probes':'probes.json','updater':'updater.py','resilience':'resilience.py'}.items()},**{'candidate_kit_'+n:home/'kit'/f for n,f in {'worker':'worker.py','probes':'probes.json'}.items()},**{'unit_p1-companion-candidates_'+n:Path('/etc/systemd/system')/('p1-companion-candidates.'+n) for n in ('service','timer')}}
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def atomic_bytes(path,raw,mode=0o600,uid=None,gid=None):
 """Replace through held directory descriptors; never follow a parent/temp link."""
 path=Path(path).absolute()
 if '..' in path.parts:raise ValueError('unsafe_target_parent')
 flags=os.O_RDONLY|getattr(os,'O_DIRECTORY',0)|getattr(os,'O_NOFOLLOW',0)
 fd=os.open(path.anchor,flags);tmp='.'+path.name+'.'+secrets.token_hex(12)+'.next'
 try:
  for part in path.parts[1:-1]:
   try:os.mkdir(part,0o700,dir_fd=fd)
   except FileExistsError:pass
   nxt=os.open(part,flags,dir_fd=fd);os.close(fd);fd=nxt
  f=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),mode,dir_fd=fd)
  with os.fdopen(f,'wb') as stream:
   stream.write(raw);stream.flush()
   if uid is not None and gid is not None:os.fchown(stream.fileno(),uid,gid)
   os.fchmod(stream.fileno(),mode);os.fsync(stream.fileno())
  os.replace(tmp,path.name,src_dir_fd=fd,dst_dir_fd=fd);os.fsync(fd)
 finally:
  try:os.unlink(tmp,dir_fd=fd)
  except FileNotFoundError:pass
  os.close(fd)
def valid_db(path,required=()):
 try:
  with closing(sqlite3.connect('file:'+str(Path(path))+'?mode=ro',uri=True,timeout=2)) as c:
   if c.execute('PRAGMA quick_check').fetchone()[0]!='ok':return False
   names={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
   return set(required)<=names
 except (sqlite3.Error,OSError):return False

def snapshot_database(source,target):
 source=Path(source);target=Path(target);target.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
 with closing(sqlite3.connect('file:'+str(source)+'?mode=ro',uri=True,timeout=3)) as src,closing(sqlite3.connect(target)) as dst:src.backup(dst)
 target.chmod(0o600)
 if not valid_db(target):raise ValueError('snapshot_invalid')

def restore_sources(root,checkpoint,manifest):
 root=Path(root).resolve();checkpoint=Path(checkpoint).resolve();repaired=[]
 for rel,expected in manifest.items():
  p=Path(rel)
  if p.is_absolute() or '..' in p.parts or len(p.parts)<2 or p.parts[0] not in MODULES or not re.fullmatch('[0-9a-f]{64}',expected):raise ValueError('unsafe_manifest')
  source=checkpoint/p;target=root/p
  if source.is_symlink() or not source.is_file() or not source.resolve().is_relative_to(checkpoint) or digest(source)!=expected:raise ValueError('untrusted_recovery_source')
  if target.is_file() and not target.is_symlink() and digest(target)==expected:continue
  target.parent.mkdir(parents=True,exist_ok=True)
  if not target.parent.resolve().is_relative_to(root):raise ValueError('unsafe_target_parent')
  atomic_bytes(target,source.read_bytes());repaired.append(rel)
 return repaired

def candidate_source_exclusions(root,manifest,now=None,home=None,trusted_uid=0):
 """Honor only a root-verified, bounded code canary; never a runtime marker."""
 root=Path(root);now=time.time() if now is None else now
 home=Path(home) if home else Path('/var/lib/p1-companion-candidates')/hashlib.sha256(str(root).encode()).hexdigest()[:16]
 rel='astrbot_plugin_affect/reply_chunks.py'
 def read_trusted(path):
  p=Path(path)
  if any(q.is_symlink() for q in (p,*p.parents)) or not p.is_file():raise ValueError('untrusted_canary')
  s=p.stat()
  if s.st_uid!=trusted_uid or s.st_mode&0o022 or s.st_size>1048576:raise ValueError('untrusted_canary')
  return json.loads(p.read_text())
 try:
  state=read_trusted(home/'state.json');policy=read_trusted(home/'policy.json')
  if state.get('state')!='observing' or policy.get('root')!=str(root) or policy.get('auto_pure') is not True:return set()
  started=state['published_at'];end=state['watch_until']
  if not all(type(t) in (int,float) and math.isfinite(t) for t in (started,end)) or not (started<=now<=end+120 and started<end<=started+1800):return set()
  job=state['job']
  if not isinstance(job,str) or not re.fullmatch('[0-9a-f]{24}',job) or job!=state['id']:return set()
  proof=read_trusted(home/'jobs'/job/'verification.json')
  if proof.get('baseline',{}).get('ok') or proof.get('candidate',{}).get('ok') is not True or proof['candidate'].get('exit_code')!=0 or proof['candidate'].get('checked',0)<500:return set()
  if manifest.get(rel)!=state['base_sha256']:return set()
  candidate=home/'jobs'/job/'candidate.py';target=root/'astrbot/data/plugins'/rel
  if candidate.is_symlink() or not candidate.is_file() or candidate.stat().st_uid!=trusted_uid or digest(candidate)!=state['candidate_sha256'] or target.is_symlink() or digest(target)!=state['candidate_sha256']:return set()
  return {rel}
 except (ValueError,OSError,KeyError,TypeError):return set()

def restore_database(path,snapshot,quarantine,required=(),now=None):
 """Caller must stop the owning service. No source rollback or write on a bad backup."""
 path=Path(path);snapshot=Path(snapshot);quarantine=Path(quarantine);now=time.time() if now is None else now
 if valid_db(path,required):return {'state':'healthy','restored':False}
 if not valid_db(snapshot,required):return {'state':'backup_rejected','restored':False}
 quarantine.mkdir(mode=0o700,parents=True,exist_ok=True);stamp=str(time.time_ns())
 candidate=path.with_name('.'+path.name+'.'+secrets.token_hex(10)+'.verified-restore');snapshot_database(snapshot,candidate)
 # A restored outbox must not replay stale/unknown work. Permissions remain in
 # current human-managed files, and proactive contact waits a full day.
 with closing(sqlite3.connect(candidate)) as c,c:
  names={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
  if 'p1_qq_actions' in names:c.execute("UPDATE p1_qq_actions SET state='unknown' WHERE state='reserved'")
  if 'p1_qq_targets' in names:c.execute('UPDATE p1_qq_targets SET next_at=?,unanswered=MAX(unanswered,2)',(now+86400,))
  if 'companion_social_outbox' in names:c.execute("UPDATE companion_social_outbox SET state='unknown' WHERE state='reserved'")
  if 'memoria_records' in names:
   ledger=path.with_name('clear-epochs.json')
   if ledger.exists():
    if ledger.is_symlink() or ledger.stat().st_size>1048576:raise ValueError('forget_ledger_untrusted')
    v=json.loads(ledger.read_text());epochs=v.get('epochs') if isinstance(v,dict) and v.get('schema')==1 else None
    if not isinstance(epochs,dict) or any(not isinstance(k,str) or type(e) is not int or e<1 for k,e in epochs.items()):raise ValueError('forget_ledger_untrusted')
    c.execute('CREATE TABLE IF NOT EXISTS memoria_scope_epochs(scope TEXT PRIMARY KEY,epoch INTEGER NOT NULL,cleared_at INTEGER NOT NULL)')
    for owner,epoch in epochs.items():
     old=c.execute('SELECT epoch FROM memoria_scope_epochs WHERE scope=?',(owner,)).fetchone()
     if not old or old[0]<epoch:
      c.execute('DELETE FROM memoria_records WHERE user_id=?',(owner,));c.execute('INSERT INTO memoria_scope_epochs VALUES(?,?,?) ON CONFLICT(scope) DO UPDATE SET epoch=excluded.epoch,cleared_at=excluded.cleared_at',(owner,epoch,int(now)))
   c.execute("UPDATE memoria_records SET status='candidate',confidence=MIN(confidence,.65) WHERE status='active'")
  for table in ('p1_private_turns','p1_learning_turns','p1_learning_evidence','p1_learning_checks','p1_learning_temporary','p1_reflection','group_messages','group_notes','companion_video_notes','leisure_observations','companion_watches','memoria_follow_up','memoria_suppression','memoria_activity'):
   if table in names:c.execute('DELETE FROM '+table)
  if 'companion_idle_runs' in names:c.execute("UPDATE companion_idle_runs SET details='{}'")
  if 'companion_social_outbox' in names:c.execute("UPDATE companion_social_outbox SET content=''")
  if 'companion_social' in names:c.execute('UPDATE companion_social SET version=version+1')
  if 'p1_learning_items' in names:c.execute("UPDATE p1_learning_items SET status='pending' WHERE status='active'")
  if 'group_meta' in names:c.execute('UPDATE group_meta SET hydrated=1,epoch=epoch+1')
  if 'task' in names:
   # An old snapshot cannot establish whether a newer forget/cancel occurred.
   if 'scope' in names:c.execute('UPDATE scope SET paused=1,epoch=epoch+1')
   c.execute("UPDATE task SET status='abandoned',notes='恢复快照无法确认后续取消，不自动补发' WHERE kind='reminder' AND status IN ('queued','active')")
   c.execute("UPDATE task SET status='paused',lease=0 WHERE kind!='reminder' AND status IN ('queued','active')")
   for table in ('event','document','artifact','feedback','topic','cognitive_item','cognitive_seen','interest_evidence','document_coverage','task_control'):
    if table in names:c.execute('DELETE FROM '+table)
   if 'interest' in names:c.execute('UPDATE interest SET score=.5,evidence=0')
  if 'action' in names:c.execute("UPDATE action SET state='unknown' WHERE state='reserved'")
 for suffix in ('','-wal','-shm'):
  old=Path(str(path)+suffix)
  if old.exists():os.replace(old,quarantine/(path.name+'.'+stamp+suffix))
 os.replace(candidate,path);path.chmod(0o600)
 return {'state':'restored','restored':True,'quarantined':True,'stale_outbox_not_replayed':True,'integrity_ok':valid_db(path,required)}

def repair_policy_file(path,kind):
 """Malformed admission policy is recovered to closed access, never to old grants."""
 p=Path(path)
 try:
  value=json.loads(p.read_text(encoding='utf-8-sig'))
  if not isinstance(value,dict) or value.get('version')!=1:raise ValueError('invalid_policy')
  if kind=='groups' and (not isinstance(value.get('groups'),list) or len(value['groups'])>20 or any(not isinstance(r,dict) or set(r)!={'bot','group'} or any(not isinstance(r[k],str) or not re.fullmatch('[0-9]{5,20}',r[k]) for k in ('bot','group')) for r in value['groups'])):raise ValueError('invalid_groups')
  if kind=='identities' and (not isinstance(value.get('allowed_identities'),list) or any(not isinstance(k,str) or not re.fullmatch('v1:[0-9a-f]{64}',k) for k in value['allowed_identities'])):raise ValueError('invalid_identities')
  if kind=='qq' and (type(value.get('enabled')) is not bool or value.get('scope') not in ('whitelist','all_existing')):raise ValueError('invalid_qq_policy')
  return False
 except (OSError,ValueError):pass
 defaults={'groups':{'version':1,'groups':[]},'qq':{'version':1,'enabled':False,'scope':'whitelist','cross_forward':'confirm'},'identities':{'version':1,'allowed_identities':[]}}
 if kind not in defaults:raise ValueError('policy_not_repairable')
 atomic_bytes(p,json.dumps(defaults[kind]).encode());return True

def maintenance_plan(available_mb,disk_free_mb,temperature,clock_skew=0):
 """Resource faults lower optional activity, never delete user data or punish contacts."""
 return {'pause_optional':available_mb<450 or disk_free_mb<512 or temperature>=78 or abs(clock_skew)>300,
  'reason':'memory' if available_mb<450 else 'disk' if disk_free_mb<512 else 'thermal' if temperature>=78 else 'clock' if abs(clock_skew)>300 else 'none',
  'keep_chat_if_possible':True,'delete_user_files':False}

def fixed_permissions(key,target,metadata=None):
 """Root-sealed original ownership/mode, with conservative legacy role defaults."""
 if metadata is not None:
  if not isinstance(metadata,dict) or set(metadata)!={'uid','gid','mode'} or any(type(metadata[k]) is not int for k in metadata):raise ValueError('fixed_metadata_shape')
  if not 0<=metadata['uid']<2**31 or not 0<=metadata['gid']<2**31 or not 0<metadata['mode']<=0o777 or metadata['mode']&0o022:raise ValueError('unsafe_fixed_metadata')
  return metadata
 if key.startswith('internal_'):return {'uid':1001,'gid':1001,'mode':0o600}
 if key.startswith('leisure_'):return {'uid':0,'gid':1001,'mode':0o640}
 return {'uid':os.geteuid(),'gid':os.getegid(),'mode':0o700 if target.suffix=='.py' or key in ('backup_dbs','backup_agency','core_health') else 0o600}

def fixed_dependents(keys):
 """Only enumerated services; no model-supplied name or command."""
 keys=set(keys);services=set()
 if keys & {'leisure_server','leisure_policy','leisure_quota','leisure_private_api','internal_leisure_token'}:services.add('p1-leisure')
 if keys & {'leisure_egress','leisure_policy'}:services.add('p1-leisure-egress')
 if 'internal_browser_token' in keys:services.add('p1-browser')
 if 'internal_workbench_token' in keys:services.add('p1-workbench')
 if 'mcp_server' in keys or any(k.startswith('internal_') for k in keys):services.add('astrbot')
 return [x for x in SERVICES if x in services]

def restore_fixed(files,checkpoint,manifest,metadata=None):
 """Restore fixed, caller-enumerated ancillary files; paths never come from the model."""
 if metadata is not None and not isinstance(metadata,dict):raise ValueError('fixed_metadata_mapping')
 fixed=[];checkpoint=Path(checkpoint);metadata=metadata or {}
 if set(manifest)-set(files):raise ValueError('unknown_fixed_file')
 if set(metadata)-set(files):raise ValueError('unknown_fixed_metadata')
 for key,expected in manifest.items():
  if not re.fullmatch('[a-z0-9_-]{1,60}',key):raise ValueError('unsafe_fixed_key')
  source=checkpoint/key;target=Path(files[key])
  if source.is_symlink() or not source.is_file() or digest(source)!=expected:raise ValueError('untrusted_fixed_snapshot')
  wanted=fixed_permissions(key,target,metadata.get(key))
  if target.is_file() and not target.is_symlink() and digest(target)==expected:
   s=target.stat()
   if (s.st_uid,s.st_gid,stat.S_IMODE(s.st_mode))==(wanted['uid'],wanted['gid'],wanted['mode']):continue
  atomic_bytes(target,source.read_bytes(),wanted['mode'],wanted['uid'],wanted['gid']);fixed.append(key)
 return fixed
