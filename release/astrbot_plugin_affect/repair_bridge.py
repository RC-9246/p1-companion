"""Unprivileged proposal inbox. Root guardian makes every executable decision."""
import ast,hashlib,json,os,re,secrets,time
from pathlib import Path
FUNCTIONS={'casual_tail','qq_reply','split_reply'}
FAULTS={'punctuation_regression','segmentation_regression','formatting_regression'}
def source_view(folder,function):
 if function not in FUNCTIONS:raise ValueError('repair_function_denied')
 path=Path(folder)/'reply_chunks.py'
 if path.is_symlink() or path.stat().st_size>200000:raise ValueError('repair_source_unavailable')
 raw=path.read_text();node=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name==function)
 return {'target':'qq_format','function':function,'base_sha256':hashlib.sha256(raw.encode()).hexdigest(),'source':ast.get_source_segment(raw,node),'scope':'pure_qq_formatting_only','tests_editable':False,'production_modified':False}
def propose(folder,data,proposal,now=None):
 if not isinstance(proposal,dict) or set(proposal)!={'schema','target','function','base_sha256','replacement','fault'} or proposal.get('schema')!=1:raise ValueError('repair_proposal_shape')
 if proposal['target']!='qq_format' or proposal['function'] not in FUNCTIONS or proposal['fault'] not in FAULTS:raise ValueError('repair_target_denied')
 current=source_view(folder,proposal['function'])
 if proposal['base_sha256']!=current['base_sha256']:raise ValueError('repair_base_changed')
 text=proposal['replacement']
 if not isinstance(text,str) or len(text)>10000 or re.search(r'[\x00-\x08]',text):raise ValueError('repair_size')
 # This is a transport check, never the execution/acceptance gate.
 ast.parse(text);now=time.time() if now is None else now;home=Path(data)/'repair_candidates'
 if home.is_symlink():raise ValueError('repair_path_untrusted')
 home.mkdir(mode=0o700,exist_ok=True)
 if sum(1 for p in home.glob('*.json') if now-p.stat().st_mtime<86400)>=2:raise ValueError('repair_proposal_daily_limit')
 path=home/(secrets.token_hex(12)+'.json');fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
 with os.fdopen(fd,'w') as stream:json.dump(proposal,stream,ensure_ascii=False);stream.flush();os.fsync(stream.fileno())
 return {'ok':True,'proposal_id':path.stem,'state':'queued_for_root_guardian','production_modified':False,'acceptance':'reproduced_baseline_fault + sealed_independent_tests + bounded_canary; otherwise rejected'}
