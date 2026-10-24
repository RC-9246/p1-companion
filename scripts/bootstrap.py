"""Install neutral Companion into an existing AstrBot tree. Default is a dry run."""
import argparse,hashlib,json,os,re,secrets,shutil,sqlite3,sys,time
from pathlib import Path
R=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=Path('/srv/p1-agent'));p.add_argument('--bot-id',required=True);p.add_argument('--owner-id',required=True);p.add_argument('--friend-id',action='append',default=[]);p.add_argument('--enable-social',action='store_true');p.add_argument('--cross-forward',choices=['confirm','allow'],default='confirm');p.add_argument('--apply',action='store_true');a=p.parse_args()
root=a.root.resolve();assert re.fullmatch(r'/[A-Za-z0-9_./-]+',str(root)) and str(root) not in ('/','/home','/srv')
assert all(re.fullmatch(r'[0-9]{5,20}',x) for x in [a.bot_id,a.owner_id,*a.friend_id]);data=root/'astrbot/data';cfgpath=data/'cmd_config.json';assert cfgpath.is_file(),'Start/configure AstrBot and its DeepSeek + OneBot connection first'
config=json.loads(cfgpath.read_text(encoding='utf-8-sig'));names=sorted(x.name for x in (R/'release').iterdir() if x.is_dir())
print(json.dumps({'dry_run':not a.apply,'plugins':len(names),'data_path':str(data),'autonomous_social_enabled':a.enable_social,'new_public_ports':0,'model_credentials_logged':False}))
if not a.apply:raise SystemExit(0)
assert os.geteuid()==0,'Run with sudo on the target Linux host';os.umask(0o077)
point=root/'backups'/('install-'+time.strftime('%Y%m%d-%H%M%S'));point.mkdir(mode=0o700,parents=True);affect=data/'plugin_data/affect';affect.mkdir(mode=0o700,parents=True,exist_ok=True)
for name in names:
 target=data/'plugins'/name
 if target.exists():shutil.copytree(target,point/'plugins'/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
for name in ('cmd_config.json','mcp_server.json'):
 if (data/name).exists():shutil.copy2(data/name,point/name)
for path in (affect/'affect.db',data/'plugin_data/memoria/memoria.db',data/'plugin_data/p1_groups/groups.db',data/'data_v4.db'):
 if path.exists():
  target=point/'databases'/path.parent.name/path.name;target.parent.mkdir(parents=True,exist_ok=True)
  with sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True) as src,sqlite3.connect(target) as dst:src.backup(dst)
def rewrite(text):return text.replace('/srv/p1-agent',str(root))
def install(src,dest):
 if src.is_dir():
  for source in src.rglob('*'):
   if source.is_file() and '__pycache__' not in source.parts and source.suffix!='.pyc':install(source,dest/source.relative_to(src))
 else:
  dest.parent.mkdir(parents=True,exist_ok=True)
  if src.suffix in ('.py','.yaml','.service','.timer','.json'):dest.write_text(rewrite(src.read_text()))
  else:shutil.copy2(src,dest)
  # Nonroot leisure/egress bind these code files individually. Keep root ownership
  # and grant only the service group read access; secrets are handled separately.
  dest.chmod(0o640);os.chown(dest,0,1001)
for name in names:install(R/'release'/name,data/'plugins'/name)
install(R/'browser',root/'public-browser');install(R/'services',data/'companion_services')
# The isolated rehearsal/checkpoint paths intentionally mirror the production layout.
stage=data/'companion_v020_lab'
for name in ('release','services','browser'):install(R/name,stage/name)
(stage/'tools').mkdir(parents=True,exist_ok=True)
for name in ('checkpoint_recovery.py','deploy_patch.py'):
 source=R/'scripts'/name
 if source.exists():install(source,stage/'tools'/name)
(stage/'evidence').mkdir(exist_ok=True);manifest={str(q.relative_to(data/'plugins')):hashlib.sha256(q.read_bytes()).hexdigest() for name in names for q in (data/'plugins'/name).rglob('*') if q.is_file() and '__pycache__' not in q.parts and q.suffix!='.pyc'};(stage/'evidence/release-manifest.json').write_text(json.dumps(manifest))
def write_new(path,value):
 if not path.exists():path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,ensure_ascii=False,indent=2));path.chmod(0o600)
identity='v1:'+hashlib.sha256(json.dumps(['qq_snowluma',a.bot_id,a.owner_id],ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
write_new(affect/'allowed_identities.json',{'version':1,'allowed_identities':[identity]});write_new(affect/'groups.json',{'version':1,'groups':[]});write_new(affect/'social_policy.json',{'enabled':False})
qq={'version':1,'enabled':a.enable_social,'scope':'whitelist','cross_forward':a.cross_forward,'quiet_start':23,'quiet_end':8,'private_min_minutes':60,'private_max_minutes':180,'group_min_minutes':20,'group_max_minutes':60,'private_daily':4,'group_daily':4,'global_daily':16,'max_unanswered':2,'favorite_daily':12};write_new(affect/'qq_policy.json',qq)
for name in ('browser','leisure','workbench'):
 token=affect/(name+'_token')
 if not token.exists():token.write_text(secrets.token_hex(32))
 token.chmod(0o600);os.chown(token,1001,1001)
policy=affect/'browser_policy';policy.mkdir(exist_ok=True);policy.chmod(0o755)
sys.path.insert(0,str(R/'release'));from astrbot_plugin_affect.browser_policy import DEFAULT_DOMAINS
write_new(policy/'domains.json',DEFAULT_DOMAINS);(policy/'domains.json').chmod(0o644)
policy=affect/'leisure_policy';policy.mkdir(exist_ok=True);policy.chmod(0o755);write_new(policy/'identities.json',{'version':1,'allowed_identities':[identity]});os.chown(policy/'identities.json',1001,1001)
state=affect/'leisure_state';state.mkdir(exist_ok=True,mode=0o700);os.chown(state,1001,1001)
path=affect/'affect.db'
if not path.exists():
 with sqlite3.connect(path) as db:
  db.execute('CREATE TABLE affect_state(identity_key TEXT PRIMARY KEY,mood REAL NOT NULL DEFAULT 0,energy REAL NOT NULL DEFAULT .5,familiarity REAL NOT NULL DEFAULT 0,interaction_count INTEGER NOT NULL DEFAULT 0,last_interaction_at INTEGER NOT NULL DEFAULT 0,updated_at INTEGER NOT NULL DEFAULT 0)');db.execute('CREATE TABLE affect_processed_events(event_key TEXT PRIMARY KEY,identity_key TEXT NOT NULL,processed_at INTEGER NOT NULL)')
 path.chmod(0o600)
settings=config.setdefault('platform_settings',{});settings['enable_id_white_list']=True;settings['id_whitelist']=sorted(set(settings.get('id_whitelist',[])+['qq_snowluma:FriendMessage:'+x for x in [a.owner_id,*a.friend_id]]));cfgpath.write_text(json.dumps(config,ensure_ascii=False,indent=2));cfgpath.chmod(0o600)
mcp_path=data/'mcp_server.json';mcp=json.loads(mcp_path.read_text()) if mcp_path.exists() else {};mcp.setdefault('mcpServers',{})['p1_companion']={'command':'python','args':['/AstrBot/data/companion_services/mcp/server.py'],'active':True};mcp_path.write_text(json.dumps(mcp,indent=2));mcp_path.chmod(0o600)
(point/'receipt.json').write_text(json.dumps({'plugins':names,'data_path':str(data),'databases_are_snapshots_not_auto_restore':True}));print('Sources installed; protected recovery point: '+str(point)+'\nBuild/start the isolated services, configure the max provider if supported, then restart AstrBot and run the native acceptance commands in README. No container was restarted by this installer.')
