"""Create an optional local quick alias of an existing approved DeepSeek model.

Default is read-only; credentials never leave this host or appear in output.
"""
import argparse,copy,hashlib,json,os,secrets,shutil,time
from pathlib import Path
from urllib.parse import urlsplit
ALIAS='deepseek-quick/deepseek-flash'
def configure(data,source_id=None,apply=False):
 path=Path(data)/'cmd_config.json';before=path.read_bytes();cfg=json.loads(before.decode('utf-8-sig'))
 source_id=source_id or cfg.get('agent_runner',{}).get('config',{}).get('model',{}).get('provider_id')
 model=next(x for x in cfg['provider'] if x['id']==source_id)
 assert model.get('enable') is True and model.get('model')=='deepseek-flash','enabled_deepseek_flash_source_required'
 source=next(x for x in cfg['provider_sources'] if x['id']==model['provider_source_id']);u=urlsplit(source['api_base'])
 assert u.scheme=='https' and u.hostname=='api.deepseek.com' and not u.username and not u.password and u.port in (None,443) and not u.query and not u.fragment,'approved_existing_destination_required'
 new=copy.deepcopy(model);new.update(id=ALIAS,enable=True,custom_extra_body={'thinking':{'type':'disabled'},'max_tokens':2048})
 existing=next((x for x in cfg['provider'] if x.get('id')==ALIAS),None)
 if existing:
  assert existing==new,'quick_alias_already_exists_with_different_settings'
  return {'changed':False,'alias':ALIAS,'destination':'api.deepseek.com'}
 report={'changed':False,'dry_run':not apply,'alias':ALIAS,'destination':'api.deepseek.com','new_external_account':False,'default_provider_unchanged':True}
 if not apply:return report
 point=path.parents[2]/'backups'/('quick-provider-'+time.strftime('%Y%m%d-%H%M%S'));point.mkdir(parents=True,mode=0o700)
 shutil.copy2(path,point/'cmd_config-before.json');(point/'cmd_config-before.json').chmod(0o600)
 cfg['provider'].append(new);after=(json.dumps(cfg,ensure_ascii=False,indent=2)+'\n').encode();s=path.stat();tmp=path.with_name('.quick-provider-'+secrets.token_hex(4)+'.tmp')
 try:
  with tmp.open('xb') as f:f.write(after);f.flush();os.fsync(f.fileno())
  os.chmod(tmp,s.st_mode&0o777)
  if os.geteuid()==0:os.chown(tmp,s.st_uid,s.st_gid)
  assert path.read_bytes()==before,'configuration_changed_during_setup'
  os.replace(tmp,path)
 finally:tmp.unlink(missing_ok=True)
 report.update(changed=True,private_backup=str(point),before_sha256=hashlib.sha256(before).hexdigest(),after_sha256=hashlib.sha256(after).hexdigest());return report
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--data',type=Path,required=True);p.add_argument('--source-provider');p.add_argument('--apply',action='store_true');a=p.parse_args()
 print(json.dumps(configure(a.data,a.source_provider,a.apply)))
