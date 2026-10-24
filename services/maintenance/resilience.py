"""Deterministic recovery primitives, independently testable with copied data.

No model output is accepted as a command/path/image. A known snapshot is the only
source of executable files. Corrupt originals are quarantined, never discarded.
"""
from contextlib import closing
import hashlib,json,os,re,shutil,sqlite3,time,stat
from pathlib import Path
MODULES=('astrbot_plugin_affect','astrbot_plugin_memoria','astrbot_plugin_p1_reflection','astrbot_plugin_p1_stickers','astrbot_plugin_p1_group_memory','astrbot_plugin_p1_group_affect','astrbot_plugin_p1_qq_style','astrbot_plugin_p1_learning')
SERVICES=('astrbot','snowluma','p1-n8n','p1-browser','p1-browser-egress','p1-workbench','p1-leisure','p1-leisure-egress')
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
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
  tmp=target.with_name(target.name+'.repair-next');shutil.copyfile(source,tmp);tmp.chmod(0o600);os.replace(tmp,target);repaired.append(rel)
 return repaired

def restore_database(path,snapshot,quarantine,required=(),now=None):
 """Caller must stop the owning service. No source rollback or write on a bad backup."""
 path=Path(path);snapshot=Path(snapshot);quarantine=Path(quarantine);now=time.time() if now is None else now
 if valid_db(path,required):return {'state':'healthy','restored':False}
 if not valid_db(snapshot,required):return {'state':'backup_rejected','restored':False}
 quarantine.mkdir(mode=0o700,parents=True,exist_ok=True);stamp=str(time.time_ns())
 candidate=path.with_name(path.name+'.verified-restore');snapshot_database(snapshot,candidate)
 # A restored outbox must not replay stale/unknown work. Permissions remain in
 # current human-managed files, and proactive contact waits a full day.
 with closing(sqlite3.connect(candidate)) as c,c:
  names={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
  if 'p1_qq_actions' in names:c.execute("UPDATE p1_qq_actions SET state='unknown' WHERE state='reserved'")
  if 'p1_qq_targets' in names:c.execute('UPDATE p1_qq_targets SET next_at=?,unanswered=MAX(unanswered,2)',(now+86400,))
  if 'companion_social_outbox' in names:c.execute("UPDATE companion_social_outbox SET state='unknown' WHERE state='reserved'")
  if 'memoria_records' in names:
   c.execute("UPDATE memoria_records SET status='candidate',confidence=MIN(confidence,.65) WHERE status='active'")
  for table in ('p1_private_turns','p1_learning_turns','p1_learning_evidence','p1_learning_checks','p1_reflection','group_messages','group_notes'):
   if table in names:c.execute('DELETE FROM '+table)
  if 'p1_learning_items' in names:c.execute("UPDATE p1_learning_items SET status='pending' WHERE status='active'")
  if 'group_meta' in names:c.execute('UPDATE group_meta SET hydrated=1,epoch=epoch+1')
  if 'task' in names:
   # An old snapshot cannot establish whether a newer forget/cancel occurred.
   if 'scope' in names:c.execute('UPDATE scope SET paused=1,epoch=epoch+1')
   c.execute("UPDATE task SET status='abandoned',notes='恢复快照无法确认后续取消，不自动补发' WHERE kind='reminder' AND status IN ('queued','active')")
   c.execute("UPDATE task SET status='paused',lease=0 WHERE kind!='reminder' AND status IN ('queued','active')")
   for table in ('event','document','artifact','feedback','topic'):
    if table in names:c.execute('DELETE FROM '+table)
   if 'interest' in names:c.execute("UPDATE interest SET score=.5,evidence=''")
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
 p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_name(p.name+'.closed-next');tmp.write_text(json.dumps(defaults[kind]));tmp.chmod(0o600);os.replace(tmp,p);return True

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
  target.parent.mkdir(parents=True,exist_ok=True);tmp=target.with_name(target.name+'.repair-next');shutil.copyfile(source,tmp)
  s=tmp.stat()
  if (s.st_uid,s.st_gid)!=(wanted['uid'],wanted['gid']):os.chown(tmp,wanted['uid'],wanted['gid'])
  tmp.chmod(wanted['mode']);os.replace(tmp,target);fixed.append(key)
 return fixed
