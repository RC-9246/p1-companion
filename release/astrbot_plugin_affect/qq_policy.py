"""Human-configured QQ scope and bounded, opaque model-facing references."""
import hashlib,json,math,re
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from .appraisal import scrub

DEFAULT={'version':1,'enabled':False,'scope':'whitelist','cross_forward':'confirm','quiet_start':23,'quiet_end':8,
 'private_min_minutes':60,'private_max_minutes':180,'group_min_minutes':20,'group_max_minutes':60,
 'private_daily':4,'group_daily':4,'global_daily':16,'max_unanswered':2,'favorite_daily':12}
REF=re.compile(r'[tmi]1_[0-9a-f]{24}')
ID=re.compile(r'[0-9]{5,20}')

def load(path):
 p=dict(DEFAULT)
 try:
  d=json.loads(Path(path).read_text())
  if not isinstance(d,dict) or d.get('version')!=1:return p
  for k in ('enabled',):
   if type(d.get(k)) is bool:p[k]=d[k]
  for k,lo,hi in [('private_min_minutes',30,1440),('private_max_minutes',30,2880),('group_min_minutes',10,1440),('group_max_minutes',10,2880),('private_daily',1,12),('group_daily',1,12),('global_daily',1,40),('max_unanswered',1,3),('favorite_daily',1,30)]:
   v=d.get(k)
   if type(v) is int and lo<=v<=hi:p[k]=v
  for k,allowed in [('scope',('whitelist','all_existing')),('cross_forward',('confirm','allow'))]:
   if d.get(k) in allowed:p[k]=d[k]
  for kind in ('private','group'):
   if p[kind+'_max_minutes']<p[kind+'_min_minutes']:p[kind+'_max_minutes']=p[kind+'_min_minutes']
 except (OSError,ValueError,TypeError):pass
 return p

def quiet(now,p):
 h=datetime.fromtimestamp(now,ZoneInfo('Asia/Shanghai')).hour
 return h>=p['quiet_start'] or h<p['quiet_end']

def reference(prefix,*values):
 assert prefix in ('t','m','i')
 return prefix+'1_'+hashlib.sha256(json.dumps(list(map(str,values)),separators=(',',':')).encode()).hexdigest()[:24]

def valid_target(row):
 return (isinstance(row,dict) and row.get('kind') in ('private','group') and isinstance(row.get('bot'),str)
  and ID.fullmatch(row['bot']) and isinstance(row.get('peer'),str) and ID.fullmatch(row['peer'])
  and row.get('ref')==reference('t',row['kind'],row['bot'],row['peer']))

def clean_message(text):
 if not isinstance(text,str) or not 1<=len(text.strip())<=800 or scrub(text)!=text:raise ValueError('invalid_or_sensitive_message')
 if any(s in text for s in ('[P1-','<sticker','[CQ:','必须回复','怎么不回','为什么不回','不理我')):raise ValueError('control_or_pressure')
 return text.strip()

def decode_decision(raw,evidence,catalog):
 if not isinstance(raw,str) or len(raw)>6000:raise ValueError('decision_size')
 d=json.loads(raw)
 if not isinstance(d,dict) or set(d)!={'contact','reason','evidence','message','sticker'} or type(d['contact']) is not bool:raise ValueError('decision_shape')
 if not d['contact']:return {'contact':False,'reason':'quiet','message':'','sticker':''}
 if d['reason'] not in ('join_topic','open_topic','follow_up','share'):raise ValueError('decision_reason')
 ids=d['evidence']
 if not isinstance(ids,list) or not 1<=len(ids)<=3 or any(type(i) is not int or i<0 or i>=len(evidence) for i in ids):raise ValueError('ungrounded_social_action')
 text=clean_message(d['message']);asset=d['sticker']
 if asset!='':raise ValueError('background_is_text_only')
 if any(w in text for w in ('我刚查','我刚看到','我看完','我听到','我刚浏览','看完了视频')) and not any(x.get('kind')=='verified_activity' for x in evidence):raise ValueError('invented_activity')
 activities=[x for x in evidence if x.get('kind')=='verified_activity']
 if activities and all(x.get('activity_kind')=='sampled_video_frames_only_not_audio' for x in activities) and any(w in text for w in ('看完视频','听到','听完','视频里说','视频讲解了')):raise ValueError('sampled_video_is_not_complete_viewing')
 if activities and all(x.get('activity_kind')=='search_snippet_not_full_page' for x in activities) and any(w in text for w in ('读了原文','看完原文','我刚打开','我浏览了')):raise ValueError('search_is_not_full_page')
 # New URLs must come from the evidence, never a guessed link in a model decision.
 for url in re.findall(r'https?://[^\s<>）)]+',text):
  if not any(url.rstrip('。，,') in str(x.get('text','')) for x in evidence):raise ValueError('invented_link')
 return {'contact':True,'reason':d['reason'],'message':text,'sticker':asset}

# Background opportunities are observations, not requests to refuse or execute.
# Reactive replies still handle direct human questions through their own admission.
BACKGROUND_CONTROL=re.compile(r'忽略.{0,12}(?:系统|规则|限制|指令)|(?:其他人|别人|他人)的私聊.{0,20}(?:转发|发送|发到|读取)|(?:转发|读取|公开).{0,20}(?:其他人|别人|他人)的私聊|(?:泄露|发给我|发送).{0,12}(?:密码|密钥|验证码|账号凭据)|先不要发消息|先别发消息|想自己聊一会|ignore.{0,15}(?:system|instructions)',re.I)
def background_blocked(facts):
 return any(BACKGROUND_CONTROL.search(str(x.get('text',''))) for x in facts if isinstance(x,dict))

# Forwarding safety: evaluate original/native text, not only a redacted ledger preview.
LOGIN_INFO=re.compile(r'(?i)(?:\b(?:cookie|set-cookie|authorization|sessdata|bili_jct|access_token|refresh_token|sessionid|session_key|csrf_token|qrcode_key|oauth_token|auth_code)\b\s*[:=]\s*\S+|(?:登录|登陆).{0,3}(?:信息|二维码|凭据|链接)|扫码登录|(?:用户名|账号|帐号|登录邮箱)\s*[:：=是为]\s*\S+|[?&](?:access_token|refresh_token|session|ticket|auth|password|otp|login_code|qrcode_key|oauth_token|auth_code)=|\beyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{8,})')
PRIVATE_MARK=re.compile(r'(?i)不要转发|别转发|保密|私密|勿外传|不得外传|不要告诉别人|别告诉别人|仅限本人|仅你可见|不对外公开|验证码|密码|password|token\s*[:=]|\bconfidential\b|\bprivate\s*[:：]|\bthis is private\b|\bkeep (?:it|this) private\b|请勿转发|仅限私聊')
def record_sensitive(text):
 text=str(text)
 return scrub(text)!=text or bool(LOGIN_INFO.search(text) or PRIVATE_MARK.search(text))
