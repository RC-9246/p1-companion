"""Model-neutral, read-only engineering CLI. No SSH, shell, accounts or DB reads."""
from __future__ import annotations
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

SOURCE = Path(__file__).resolve().parents[1]
MODULES = ('group_memory_ready','group_affect_ready','learning_ready','qq_plain_ready',
           'agency_ready','qq_actions_ready','private_access_commands_ready')
SERVICES = ('astrbot','snowluma','p1-browser','p1-browser-egress','p1-leisure','p1-leisure-egress','p1-workbench','p1-n8n')
DATABASES = ('affect','memoria','groups','agency','astrbot','knowledge')
REPAIR_STATES = frozenset(('healthy','paused','busy','checkpoint_rejected','journal_corrupt','clock_guard',
    'repair_succeeded','repair_failed','cooldown','daily_budget_exhausted','pending_recovery_verified',
    'pending_recovery_failed','generation_changed','unit_query_failed','deferred_verification','state_unavailable'))

class AccessError(Exception):
    pass

def root_path(value):
    p = Path(value)
    if not p.is_absolute() or not re.fullmatch(r'/[A-Za-z0-9_./-]+', str(p)) or '..' in p.parts or len(p.parts)<3:
        raise AccessError('invalid_root')
    if any(q.is_symlink() for q in (p,*p.parents)) or p != p.resolve():
        raise AccessError('symlink_root_denied')
    return p

def bounded_bytes(path, base, limit=262144):
    """Fixed-path reads only. Never follow a final symlink or emit parse errors."""
    path, base = Path(path), Path(base).resolve()
    relative = path.relative_to(base)
    for n in range(1,len(relative.parts)+1):
        if base.joinpath(*relative.parts[:n]).is_symlink(): raise AccessError('symlink_denied')
    if not path.resolve().is_relative_to(base): raise AccessError('path_denied')
    fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
    with os.fdopen(fd,'rb') as f:
        raw=f.read(limit+1)
    if len(raw)>limit: raise AccessError('file_too_large')
    return raw

def bounded_text(path, base, limit=16000):
    return bounded_bytes(path,base,limit).decode('utf-8-sig')

def bounded_json(path, base, limit=262144):
    value=json.loads(bounded_bytes(path,base,limit))
    if not isinstance(value,dict): raise AccessError('invalid_object')
    return value

def describe(source=SOURCE):
    return {'ok':True,'kind':'public_project_context','project':bounded_json(source/'ai/PROJECT.json',source),
            'live_runtime_checked':False,'network_calls':0,'writes':False}

def verify(source=SOURCE):
    source=Path(source).resolve(); failures=[]; checked=0
    try:
        path=source/'source-manifest.json'; raw=bounded_bytes(path,source,1048576); manifest=json.loads(raw)
        if not isinstance(manifest,dict) or not manifest: raise AccessError('empty_manifest')
        if not {'AGENTS.md','ai/PROJECT.json','ai/companion.py','ai/mcp_server.py'}.issubset(manifest):
            raise AccessError('ai_entries_missing_from_manifest')
        for rel,digest in manifest.items():
            p=source/rel
            if (not isinstance(rel,str) or Path(rel).is_absolute() or '..' in Path(rel).parts or
                    not isinstance(digest,str) or not re.fullmatch('[a-f0-9]{64}',digest)):
                raise AccessError('invalid_manifest_entry')
            if any(q.is_symlink() for q in (p,*p.parents) if q!=source and q.is_relative_to(source)) or not p.resolve().is_relative_to(source):
                raise AccessError('source_symlink_or_escape')
            if not p.is_file() or p.stat().st_size>4*1024**2: raise AccessError('source_missing_or_oversized')
            if hashlib.sha256(bounded_bytes(p,source,4*1024**2)).hexdigest()!=digest: failures.append('source_hash_mismatch')
            checked+=1
        identity=hashlib.sha256(raw).hexdigest()
    except (OSError,ValueError,TypeError,AccessError):
        failures.append('source_verification_failed'); identity=None
    return {'ok':not failures,'source_files_checked':checked,'source_manifest_sha256':identity,
            'errors':sorted(set(failures)),'publisher_authenticity_verified':False,'network_calls':0,'writes':False}

def plan(root='/srv/p1-agent',mode='fresh_host'):
    root=str(root_path(root))
    if mode not in ('fresh_host','existing_core','existing_companion'):raise AccessError('invalid_install_mode')
    steps=[{'id':'source','argv':['python3','ai/companion.py','verify'],'writes':False}]
    if mode=='fresh_host':
        steps += [{'id':'host_wizard','argv':['sudo','python3','deploy/wizard.py'],'windows_launcher':'开始安装.cmd','writes':True,'actual_user_authorization_required':True,'interactive_inputs':['installation_root','bot_QQ','owner_QQ','DeepSeek_API','QQ_scan','real_chat_acceptance']}]
    elif mode=='existing_core':
        steps += [{'id':'preflight','argv':['sudo','bash','deploy.sh','--root',root,'--check'],'writes':False},
                  {'id':'integrate_only','argv':['sudo','bash','deploy.sh','--root',root,'--apply'],'writes':True,'actual_user_authorization_required':True,'interactive_inputs':['bot_QQ','owner_QQ']}]
    else:
        steps += [{'id':'health','argv':['python3','ai/companion.py','status','--root',root],'writes':False},
                  {'id':'manage_existing','argv':['sudo','python3','deploy/wizard.py','--manage-root',root],'writes':True,'actual_user_authorization_required':True,'never_reinstall':True}]
    return {'ok':True,'kind':'plan_not_execution','mode':mode,'root':root,'steps':steps,
        'stop_on_preflight_errors':True,'existing_companion':'use_reviewed_patch_or_component_upgrade_not_first_install',
        'manual_acceptance':['QQ_login_and_real_delivery','Bilibili_QR_if_used','host_repair_after_acceptance'],
        'executed':False,'network_calls':0,'writes':False}

def handoff(source=SOURCE):
    checked=verify(source)
    return {'schema_version':1,'objective':'','phase':'not_started',
            'source_manifest_sha256':checked['source_manifest_sha256'],'observations':[],
            'tests':[],'pending':[],'limits':['Source integrity is not runtime acceptance or publisher authentication.',
            'Keep private recovery locations and runtime data out of public handoffs.'],'private_runtime_data_included':False}

def mcp_config(root=None, source=SOURCE):
    args=[str(source/'ai/mcp_server.py')]
    if root is not None: args+=['--live-root',str(root_path(root))]
    return {'mcpServers':{'p1_companion_engineering':{'command':sys.executable,'args':args}}}

def age(at, now):
    if type(at) not in (int,float) or not (0<at<=now+300): return None
    return max(0,int(now-at))

def report(path, root):
    try: return bounded_json(path,root)
    except (OSError,ValueError,AccessError): return {}

def flags(value, names):
    value=value if isinstance(value,dict) else {}
    return {k:value[k] if type(value.get(k)) is bool else None for k in names}

def recovery_summary(value, now):
    elapsed=age(value.get('at'),now)
    fresh=elapsed is not None and elapsed<=1200 and type(value.get('schema')) is int and value['schema']==1
    def count(name,maximum):
        v=value.get(name)
        return v if fresh and type(v) is int and 0<=v<=maximum else None
    state=value.get('status')
    return {'age_seconds':elapsed,'fresh':fresh,
            'status':state if fresh and isinstance(state,str) and state in REPAIR_STATES else None,
            'pending':value.get('pending') if fresh and type(value.get('pending')) is bool else None,
            'engine_verified':value.get('engine_verified') if fresh and type(value.get('engine_verified')) is bool else None,
            'restored_files':count('restored_files',10),'rolling_24h_attempts':count('rolling_24h_attempts',2)}

def health(root, now=None):
    root=root_path(str(root)); now=time.time() if now is None else now
    data=root/'astrbot/data/plugin_data/affect'
    start=report(data/'companion_health.json',root); maintenance=report(data/'maintenance_health.json',root)
    watchdog=report(data/'repair_watchdog_health.json',root)
    elapsed=age(maintenance.get('at'),now); fresh=elapsed is not None and elapsed<=900
    services=flags(maintenance.get('services'),SERVICES)
    dbs=flags(maintenance.get('databases'),DATABASES)
    if not fresh: services=dict.fromkeys(SERVICES); dbs=dict.fromkeys(DATABASES)
    repairs=maintenance.get('repairs'); count=min(len(repairs),10000) if isinstance(repairs,list) else None
    return {'ok':bool(start or maintenance or watchdog),'source':'closed_local_status_files','writes':False,'network_calls':0,
            'startup_report':{'age_seconds':age(start.get('at'),now),'modules':flags(start,MODULES),
                              'continuous_runtime_probe':False},
            'maintenance':{'age_seconds':elapsed,'fresh':fresh,'services':services,'databases':dbs,
                           'disabled':maintenance.get('disabled') if type(maintenance.get('disabled')) is bool else None,
                           'last_repair_count':count},
            'recovery_chain':recovery_summary(watchdog,now),
            'account_login_verified':False,'conversation_store_or_credential_files_read':False,
            'limits':['Startup flags are historical readiness, not continuous health.',
                      'Maintenance states become unknown after 15 minutes or invalid timestamps.',
                      'Recovery-chain states become unknown after 20 minutes; they do not prove every application is healthy.',
                      'Container health does not prove QQ/Bilibili login or message delivery.']}

def doctor(root, source=SOURCE):
    root=root_path(str(root)); integrity=verify(source)
    if not integrity['ok']: return {'ok':False,'errors':['verify_source_first'],'writes':False}
    command=[sys.executable,str(source/'deploy/install.py'),'--root',str(root),'--check']
    try:
        # Only source-declared diagnostic labels may reach a model. In particular,
        # do not treat an arbitrary alphanumeric token as a harmless error code.
        tree=ast.parse((source/'deploy/install.py').read_text())
        routine=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='doctor')
        allowed={n.value for n in ast.walk(routine) if isinstance(n,ast.Constant) and
                 isinstance(n.value,str) and re.fullmatch('[A-Za-z0-9_]{1,100}',n.value)}
        result=subprocess.run(command,cwd=source,stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=60)
        data,_=json.JSONDecoder().raw_decode(result.stdout.lstrip())
        if not isinstance(data,dict) or data.get('read_only') is not True: raise ValueError()
        def codes(key):
            values=data.get(key,[])
            if not isinstance(values,list): return ['invalid_preflight_report']
            output=[]
            for v in values[:50]:
                if isinstance(v,str) and v in allowed: output.append(v)
                elif key=='errors': output.append('unrecognized_preflight_code')
            return list(dict.fromkeys(output))
        errors=codes('errors')
        return {'ok':data.get('ok') is True and result.returncode==0 and not errors,'errors':errors,
                'warnings':codes('warnings'),'read_only':True,'writes':False,'account_login_verified':False}
    except (OSError,ValueError,SyntaxError,StopIteration,subprocess.SubprocessError):
        return {'ok':False,'errors':['doctor_unavailable_or_timeout'],'read_only':True,'writes':False}

def main():
    p=argparse.ArgumentParser(description='AI engineering context; JSON only, no deployment or shell tools')
    sub=p.add_subparsers(dest='action',required=True)
    for name in ('describe','verify','handoff'): sub.add_parser(name)
    q=sub.add_parser('plan');q.add_argument('--root',default='/srv/p1-agent');q.add_argument('--mode',choices=('fresh_host','existing_core','existing_companion'),default='fresh_host')
    q=sub.add_parser('mcp-config');q.add_argument('--live-root')
    for name in ('doctor','status'):
        q=sub.add_parser(name);q.add_argument('--root',required=True)
    a=p.parse_args()
    try:
        if a.action=='describe': value=describe()
        elif a.action=='verify': value=verify()
        elif a.action=='plan': value=plan(a.root,a.mode)
        elif a.action=='handoff': value=handoff()
        elif a.action=='mcp-config': value=mcp_config(a.live_root)
        elif a.action=='doctor': value=doctor(a.root)
        else: value=health(a.root)
        print(json.dumps(value,ensure_ascii=False,indent=2))
        return 1 if value.get('ok') is False else 0
    except (OSError,ValueError,AccessError):
        print(json.dumps({'ok':False,'error':'unavailable_or_invalid_input','writes':False}));return 1

if __name__=='__main__': raise SystemExit(main())
