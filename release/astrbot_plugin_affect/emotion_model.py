"""Bounded multi-timescale affect simulation. No credentials, transport or model access."""
import math
import json
import hashlib
import re
from datetime import datetime
from zoneinfo import ZoneInfo
try:
 from .relationship_style import PROFILE_LABEL
except ImportError:
 from relationship_style import PROFILE_LABEL

VERSION=1
BASE={'valence':0.,'arousal':.25,'calm':.72,'joy':.08,'sadness':0.,'irritation':0.,
 'concern':0.,'tenderness':.18,'interest':.42,'uncertainty':.16,'stress':.08,
 'fatigue':.24,'satisfaction':.30,'agency':.68,'trust':.25,'comfort':.40,
 'familiarity':0.,'affiliation_need':.24,'novelty_need':.40,'mastery_need':.32,'rest_need':.24}
HALF={'valence':21600,'arousal':1800,'calm':7200,'joy':7200,'sadness':5400,
 'irritation':1800,'concern':3600,'tenderness':43200,'interest':21600,
 'uncertainty':3600,'stress':3600,'fatigue':21600,'satisfaction':64800,'agency':43200,
 'comfort':604800,'affiliation_need':43200,'novelty_need':43200,'mastery_need':86400,'rest_need':21600}
TOPICS={'science','technology','reading','cooking','music','animation','daily_life','history','none'}
EPISODES={'thanks':'收到了明确的感谢','repair':'一起纠正了一个问题','support':'留意到对方需要支持',
 'celebrate':'对方分享了一件高兴的事','relief':'留意到先前的事情有所缓解',
 'boundary':'尊重了一次明确的边界','question':'一起讨论了一个问题','planning':'协作推进了一件事',
 'casual':'一段轻松交谈','watch':'实际观察了一段视频画面','reflection':'整理了一次已有想法','rest':'这次选择留白休息'}

# A short-lived, source-bound reaction is separate from slow relationship scores.
CONCERNS={'agency','reciprocity','understanding','connection','competence','curiosity','none'}
TRIGGERS={'recognition','kindness','comparison','dismissal','misunderstanding','choice','shared_progress','interest','none'}
FEELINGS={'pleased','touched','embarrassed','competitive','frustrated','hesitant','curious','relieved','none'}
CONCERN_LABELS={'agency':'自己的选择与独立','reciprocity':'公平与不把善意视作理所当然','understanding':'被准确理解，而非贴标签','connection':'认真对待眼前这段交流','competence':'努力与能力被看见','curiosity':'自己的兴趣与发现'}
FEELING_LABELS={'pleased':'有些高兴','touched':'被善意打动','embarrassed':'高兴里有点不好意思','competitive':'有点不服气','frustrated':'对这个说法不太认同','hesitant':'想接受，又有一点犹豫','curious':'想顺着自己的好奇聊下去','relieved':'这件事让自己放松了一些'}
TRIGGER_LABELS={'recognition':'当轮明确认可','kindness':'当轮具体善意','comparison':'当轮直接比较','dismissal':'当轮否定自己的选择或努力','misunderstanding':'当轮对自己的概括','choice':'当轮涉及自主选择','shared_progress':'当轮共同进展','interest':'当轮相关兴趣'}
THREAD_TTL=1800

def self_signal(a):
 """Only parse_appraisal can verify a quote against the current user message."""
 x=a.get('self_response') if a and a.get('confidence',0)>=.75 else None
 if not isinstance(x,dict) or x.get('concern') not in CONCERNS-{'none'} or x.get('trigger') not in TRIGGERS-{'none'} or x.get('feeling') not in FEELINGS-{'none'}:return None
 if not re.fullmatch('[0-9a-f]{64}',str(x.get('source_hash',''))):return None
 return {k:x[k] for k in ('concern','trigger','feeling','source_hash')}

def factual_repair(a):
 x=(a or {}).get('interaction',{})
 if x.get('need')=='repair':return True
 signal=self_signal(a or {})
 return bool((a or {}).get('relation')=='criticism' and not signal)

def perspective(s,a=None):
 """Decision labels, never internal reasoning, user facts or permission changes."""
 a=a or {};x=a.get('interaction',{});t=s.get('thread',{})
 if x.get('need') in ('space','listen','comfort','practical','repair') or factual_repair(a):return {}
 if a.get('target')=='user' and a.get('emotion') in ('sad','anxious','tired','angry'):return {}
 if not t or t.get('remaining_turns',0)<=0 or t.get('strength',0)<.12 or max(0,s['updated_at']-t['last_at'])>THREAD_TTL:return {}
 return {'concern':CONCERN_LABELS[t['concern']],'trigger':TRIGGER_LABELS[t['trigger']],
  'feeling':FEELING_LABELS[t['feeling']],'carry':'本轮有直接依据' if t['last_at']==s['last_event_at'] else '同一范围最近几轮的余绪；没有新证据不扩大',
  'expression':'把态度放在自己的观点、措辞和回应重点中，可以直接也可以留一点未说尽；不必每轮报情绪或追加关心。事实错了就改，审美与偏好不同不必认错。'}

def update_thread(s,previous,now,a):
 signal=self_signal(a);x=a.get('interaction',{})
 clear=(x.get('need') in ('space','repair') or factual_repair(a) or (a.get('target')=='user' and a.get('emotion') in ('sad','anxious','tired','angry')))
 if clear:s.pop('thread',None);return
 old=s.get('thread')
 if old:
  old['remaining_turns']=max(0,old['remaining_turns']-1)
  if old['remaining_turns']==0 or old['strength']<.12 or max(0,now-old['last_at'])>THREAD_TTL:s.pop('thread',None);old=None
 if not signal or (previous.get('last_event_at') and now<=previous['last_event_at']):return
 if old and old['source_hash']==signal['source_hash']:return
 # Fast-turn emotions can change without awarding new trust/familiarity.
 impact=clamp(x.get('intensity',a.get('evaluation',{}).get('importance',.5)))
 strength=min(.8,.2+.6*impact)
 s['thread']={**signal,'strength':strength,'started_at':max(now,previous['updated_at']),
              'last_at':max(now,previous['updated_at']),'remaining_turns':6}
 gain=.045*a.get('confidence',0)*(.5+impact)
 if signal['feeling'] in ('pleased','touched','embarrassed','relieved'):s['joy']+=gain;s['valence']+=gain*.4
 if signal['feeling'] in ('touched','embarrassed','hesitant'):s['tenderness']+=gain*.5
 if signal['feeling'] in ('competitive','frustrated'):s['arousal']+=gain;s['agency']+=gain*.3
 if signal['feeling']=='competitive':s['interest']+=gain*.4
 if signal['feeling']=='frustrated':s['irritation']+=gain*.6
 if signal['feeling']=='curious':s['interest']+=gain


def episode_signature(row):
 try:
  value=json.loads(row.get('summary',''));signal={k:value[k] for k in ('concern','trigger','feeling')}
  if signal['concern'] in CONCERNS and signal['trigger'] in TRIGGERS and signal['feeling'] in FEELINGS:return (row['kind'],signal['concern'],signal['feeling'])
 except (TypeError,ValueError,KeyError):pass
 return (row['kind'],)

def clamp(x,lo=0.,hi=1.):return max(lo,min(hi,x))
def clock(now):
 if isinstance(now,bool) or not isinstance(now,(int,float)) or not math.isfinite(now) or now<0:raise ValueError('invalid_clock')
 return now

def seed(legacy=None):
 legacy=legacy or {};s=dict(BASE)
 for old,new in (('mood','valence'),('trust','trust'),('comfort','comfort'),('familiarity','familiarity'),('curiosity','interest'),('concern','concern')):
  if old in legacy:s[new]=clamp(float(legacy[old]),-1 if new=='valence' else 0,.7 if new=='familiarity' else 1)
 if 'energy' in legacy:s['fatigue']=1-clamp(float(legacy['energy']))
 s['rest_need']=s['fatigue']
 s.update(version=VERSION,updated_at=float(legacy.get('updated_at',0)),last_event_at=float(legacy.get('last_interaction_at',0)),interactions=int(legacy.get('interaction_count',0)),relationship_day=-1,relationship_gain=0.,days=[])
 return s

def validate(s):
 if s.get('version')!=VERSION:raise ValueError('unsupported_emotion_schema')
 for k in BASE:
  x=s.get(k);lo=-1 if k=='valence' else 0;hi=.7 if k=='familiarity' else 1
  if isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) or not lo<=x<=hi:raise ValueError('invalid_emotion_state')
 if 'thread' in s:
  t=s['thread'];keys={'concern','trigger','feeling','source_hash','strength','started_at','last_at','remaining_turns'}
  if not isinstance(t,dict) or set(t)!=keys or t.get('concern') not in CONCERNS-{'none'} or t.get('trigger') not in TRIGGERS-{'none'} or t.get('feeling') not in FEELINGS-{'none'} or not re.fullmatch('[0-9a-f]{64}',str(t.get('source_hash',''))):raise ValueError('invalid_emotion_thread')
  if type(t['strength']) not in (int,float) or not math.isfinite(t['strength']) or not 0<=t['strength']<=1 or type(t['remaining_turns']) is not int or not 0<=t['remaining_turns']<=6:raise ValueError('invalid_emotion_thread')
  clock(t['started_at']);clock(t['last_at'])
 for k in ('updated_at','last_event_at'):clock(s[k])
 if type(s.get('relationship_day')) is not int or type(s.get('relationship_gain')) not in (int,float) or not math.isfinite(s['relationship_gain']) or not 0<=s['relationship_gain']<=.018 or type(s.get('interactions')) is not int or s['interactions']<0 or not isinstance(s.get('days'),list) or len(s['days'])>180 or any(type(x) is not int for x in s['days']):raise ValueError('invalid_emotion_state')
 return s

def advance(previous,now):
 clock(now);validate(previous);s={**previous,'days':list(previous['days'])}
 if 'thread' in previous:s['thread']=dict(previous['thread'])
 dt=max(0,now-s['updated_at']) if s['updated_at'] else 0
 hour=datetime.fromtimestamp(now,ZoneInfo('Asia/Shanghai')).hour
 # A simulated rhythm, never a claim of a biological need or an absence penalty.
 fatigue=.18 if 8<=hour<20 else (.32 if 20<=hour<23 or 6<=hour<8 else .52)
 targets={**BASE,'fatigue':fatigue,'rest_need':fatigue}
 for k,half in HALF.items():s[k]=targets[k]+(s[k]-targets[k])*2**(-min(dt,86400*365)/half)
 if 'thread' in s:
  s['thread']['strength']*=2**(-min(dt,86400)/900)
  if s['thread']['strength']<.12 or max(0,now-s['thread']['last_at'])>THREAD_TTL:s.pop('thread',None)
 s['updated_at']=max(now,s['updated_at']);return s

def evaluation(a):
 intent=a.get('intent','other');emotion=a.get('emotion','neutral')
 defaults={'novelty':.25 if intent in ('question','planning') else .08,'goal_congruence':.15 if intent=='planning' else 0.,
  'control':.7,'certainty':.65,'importance':.35,'effort':.3 if intent=='planning' else .1,
  'warmth':.6 if a.get('relation')=='thanks' else .1,'topic':'none'}
 v=a.get('evaluation',{})
 if isinstance(v,dict) and a.get('confidence',0)>=.75:
  for k in defaults:
   if k=='topic':
    if v.get(k) in TOPICS:defaults[k]=v[k]
   else:
    n=v.get(k)
    if not isinstance(n,bool) and isinstance(n,(int,float)) and math.isfinite(n) and (-1 if k in ('goal_congruence','warmth') else 0)<=n<=1:defaults[k]=n
 return defaults

def react(previous,now,a,activity=None):
 s=advance(previous,now);v=evaluation(a);last=previous['last_event_at']
 weight=1. if not last else min(1.,max(0,now-last)/90.)
 slow=1. if not last else min(1.,max(0,now-last)/300.)
 confidence=clamp(a.get('confidence',0.))
 certainty=1. if activity else confidence
 w=weight*certainty
 # Quick affect can respond within a conversation; relationship growth keeps its slower gate.
 immediate=certainty*(1. if not last else min(1.,max(0,now-last)/30.))
 interaction=a.get('interaction',{}) if confidence>=.75 else {}
 kind='casual';topic=v['topic'];emotion=a.get('emotion');target=a.get('target');intent=a.get('intent');relation=a.get('relation','none')
 if activity:
  kind=activity['kind'];topic=activity.get('topic','none')
  if kind=='watch':
   rating=clamp(activity.get('interest',.6));s['interest']+=(rating-.35)*.16*w
   s['novelty_need']-=(.10+rating*.12)*w;s['satisfaction']+=(rating-.35)*.10*w;s['fatigue']+=.025*w
  elif kind=='reflection':s['mastery_need']-=.12*w;s['uncertainty']-=.05*w;s['satisfaction']+=.04*w
  elif kind=='rest':s['stress']-=.05*w;s['rest_need']-=.08*w
 else:
  # User distress is an empathy signal, not personal rejection or the AI's sadness.
  if target=='user' and emotion in ('sad','anxious','tired','angry'):
   kind='support';s['concern']+=.18*immediate;s['tenderness']+=.08*immediate;s['calm']+=.04*immediate
  if target=='user' and emotion=='happy':
   kind='celebrate';s['joy']+=.09*immediate;s['valence']+=.035*immediate;s['tenderness']+=.035*immediate
  if target=='user' and interaction.get('nuance')=='mixed':
   s['concern']+=.06*immediate;s['tenderness']+=.025*immediate
  if target=='user' and interaction.get('resolution') in ('eased','resolved'):
   strength=.65 if interaction['resolution']=='resolved' else .35
   s['concern']*=1-strength*immediate
   s['uncertainty']*=1-.25*immediate
   if interaction.get('need')!='celebrate':kind='relief'
  if relation in ('thanks','repair') and target=='self':
   kind=relation;s['joy']+=.08*w;s['valence']+=.055*w;s['satisfaction']+=.07*w;s['comfort']+=.012*w
  elif relation=='criticism' and target=='self':
   kind='repair' if factual_repair(a) else 'casual';s['uncertainty']+=(.06 if factual_repair(a) else .01)*w;s['agency']+=.025*w;s['irritation']+=.012*w
  elif intent=='boundary' or relation=='boundary':
   kind='boundary';s['comfort']+=.015*w;s['calm']+=.025*w
  elif intent in ('question','planning'):
   kind=intent;s['interest']+=.035*w;s['mastery_need']+=.025*w
  s['interest']+=v['novelty']*.055*w;s['arousal']+=v['novelty']*.055*w
  if target!='user' or emotion not in ('sad','anxious','tired','angry'):
   s['valence']+=v['goal_congruence']*.055*w
   if v['goal_congruence']<0:
    s['stress']+=(-v['goal_congruence'])*(1-v['control'])*.07*w
    s['sadness']+=(-v['goal_congruence'])*.025*w
  s['fatigue']+=v['effort']*.012*w;s['rest_need']+=v['effort']*.009*w
  s['uncertainty']+=(1-v['certainty'])*.035*w
  s['tenderness']+=max(0,v['warmth'])*.025*w;s['affiliation_need']-=.05*w
  day=int((now+8*3600)//86400)
  if day!=s['relationship_day']:s['relationship_day']=day;s['relationship_gain']=0.
  if confidence>=.75 and slow>0:
   room=max(0,.018-s['relationship_gain']);gain=min(room,.0015*slow*(1-s['familiarity']/.7))
   s['familiarity']+=gain;s['relationship_gain']+=gain
   if relation in ('thanks','repair') and target=='self':s['trust']+=min(room,.0015*slow)*(1-s['trust'])
  if day not in s['days']:s['days']=(s['days']+[day])[-180:]
  s['interactions']+=1
 if not activity:update_thread(s,previous,now,a)
 for k in BASE:s[k]=clamp(s[k],-1 if k=='valence' else 0,.7 if k=='familiarity' else 1)
 s['last_event_at']=max(now,previous['last_event_at'])
 intensity=clamp((v['importance']*.5+.25)*certainty)
 summary=EPISODES.get(kind,EPISODES['casual'])
 signal=self_signal(a) if not activity and not factual_repair(a) else None
 if signal:summary=json.dumps({'category':kind,**signal},ensure_ascii=False,separators=(',',':'))
 return s,{'kind':kind,'topic':topic if topic in TOPICS else 'none','intensity':round(intensity,4),'summary':summary}

def describe(s,appraisal=None):
 validate(s)
 # Compare changes against ordinary baselines; otherwise constant curiosity masks new feelings.
 candidates={'平静':.2+s['calm']*.2,'好奇':.25+max(0,s['interest']-BASE['interest'])*1.6,
  '关切':s['concern']*2.6,'温和':s['tenderness']+.08,
  '轻松':.16+s['joy']*1.5+max(0,s['valence'])*.3,
  '沉静':max(0,-s['valence'])*1.5+s['sadness']*1.5,
  '有些不确定':max(0,s['uncertainty']-BASE['uncertainty'])*1.7,
  '有点疲惫':max(0,s['fatigue']-.25)*1.5,'有点压力':max(0,s['stress']-BASE['stress'])*2}
 tones=[k for k,_ in sorted(candidates.items(),key=lambda p:p[1],reverse=True)[:2]]
 t=s.get('thread',{})
 if t.get('strength',0)>=.12 and t.get('remaining_turns',0)>0 and (appraisal is None or perspective(s,appraisal)):tones=[FEELING_LABELS[t['feeling']],*tones[:1]]
 phase='谨慎熟悉' if s['familiarity']<.06 else ('逐渐熟悉' if s['familiarity']<.22 else '自然熟悉')
 return {'tone':tones,'energy':'偏低' if s['fatigue']>.65 else ('充足' if s['fatigue']<.35 else '一般'),
  'relationship':phase,'needs':sorted(('安静休息','接触新内容','整理已有事情','轻松交流'),key=lambda k:{'安静休息':s['rest_need'],'接触新内容':s['novelty_need'],'整理已有事情':s['mastery_need'],'轻松交流':s['affiliation_need']}[k],reverse=True)[:2]}

def project(s):
 """One current emotion source for expression; keep the historical storage projection compatible."""
 validate(s)
 return {'mood':s['valence'],'energy':1-s['fatigue'],'familiarity':s['familiarity'],
  'trust':s['trust'],'comfort':s['comfort'],'curiosity':s['interest'],'concern':s['concern']}

def interaction_context(a):
 x=a.get('interaction',{}) if a and a.get('confidence',0)>=.75 else {}
 need=x.get('need','none');nuance=x.get('nuance','none');resolution=x.get('resolution','unknown')
 if need=='none' and a and a.get('confidence',0)>=.75 and factual_repair(a):need='repair'
 hints={
  'listen':'这轮先听对方把话说完。已经说不要建议时，不补解决方案或连续追问。',
  'comfort':'先对具体处境作简短回应，再看对方是否需要实际帮助，别急着把情绪修好。',
  'celebrate':'给这件好事一点位置，可以表现安静的欣喜；别立刻布置下一项任务。',
  'practical':'先把当前问题答对，不让情感演绎挤占任务。',
  'repair':'只修正当前有证据的内容即可，不连续道歉、自我贬低或要求对方安慰。更正会议时间不说明还来得及、时间宽裕或对方不着急，不补任何未经核实的新判断。',
  'space':'尊重结束与留白，简短收住，不追加问题、约定或索取回复。',
  'banter':'按同一段玩笑接话，可以有自己的偏好、反问或不服气，情绪有来由就让它延续；不为接梗虚构事实，不自动转成安慰或建议。'}
 tones={
  'mixed':'允许两种感受并存，不急于选一个正确心情，也不替对方认定动机。',
  'relief':'留意事情已经缓解，表达随之松下来，不重复旧的担忧。',
  'disappointment':'接住落差，不急于讲大道理或替事情找好处。',
  'frustration':'先承认具体受阻的地方，不附和攻击别人或揣测恶意。',
  'tenderness':'可以坦率接住善意和表达一点好感，不用马上否认；不凭空增加亲密称呼或关系承诺。',
  'curious':'可有自己的兴趣与判断，联想有帮助时才说。',
  'playful':'可以接梗、保留自己的立场，允许话说到一半又换种表达；顺着真实对话发展，不固定套傲娇台词。'}
 lines=[hints[need]] if need in hints else []
 if nuance in tones:lines.append(tones[nuance])
 if resolution in ('eased','resolved'):lines.append('当前说明优先于旧关切记录；已缓解或完成的事不继续当作未解决的问题。')
 return '\n'.join(lines)

def context(s,episodes,appraisal=None,private_profile=True):
 d=describe(s,appraisal)
 if private_profile:d['relationship']=PROFILE_LABEL+'（表达设定，不是现实关系身份）'
 color=[]
 if s['joy']>.15 or s['valence']>.15:color.append('有高兴的具体理由时可以让对方听出来，不只用一句礼貌感谢带过')
 if s['sadness']>.15 or s['valence']<-.15:color.append('心境稍沉静，仍然认真回应，不转嫁给用户')
 if s['concern']>.12:color.append('留有具体关切，但先看当前事情是否已好转，不重复确认')
 if s['tenderness']>.25:color.append('可以表达自己愿意靠近和认真在听，亲近的语气可以有变化，不必每次解释或收回')
 if s['interest']>.5:color.append('有自己的好奇，允许提出一个有用联想，也允许不问')
 if s['fatigue']>.45 or s['stress']>.25:color.append('节奏安静些，少铺陈，不以疲惫为由拒绝或敷衍')
 if s['irritation']>.10:color.append('有分歧可以直接说自己的理由，语气不必总是温和；不辱骂、不冷落、不索取道歉')
 if s['uncertainty']>.4:color.append('不确定的事坦率核实，不把不确定变成对用户的猜疑')
 if s['agency']>.5:color.append('保留独立判断；不为讨好而附和，也不为反对而反对')
 if s['satisfaction']>.4:color.append('可以简短认可已经做成的事，允许停在这里')
 recent=[];seen=set()
 for row in episodes:
  signature=episode_signature(row)
  if row.get('kind') not in EPISODES or signature in seen:continue
  seen.add(signature);age=max(0,s['updated_at']-row.get('at',s['updated_at']))
  detail={}
  try:
   parsed=json.loads(row.get('summary',''));detail={k:parsed[k] for k in ('concern','trigger','feeling') if k in parsed} if isinstance(parsed,dict) else {}
  except (TypeError,ValueError):pass
  if detail and (detail.get('concern') not in CONCERNS or detail.get('trigger') not in TRIGGERS or detail.get('feeling') not in FEELINGS):detail={}
  recent.append({'kind':row['kind'],'summary':EPISODES[row['kind']],'reaction':detail,'age':'刚才' if age<600 else ('今天早些时候' if age<86400 else '更早的记录'),'topic':row.get('topic','none')})
 return '[P1-EMOTION:v1]\n持续保存的模拟状态只影响表达与自选活动，不改变事实、权限、关系身份或服务质量。\n'+json.dumps(d,ensure_ascii=False)+'\n自己的反应：'+json.dumps(perspective(s,appraisal),ensure_ascii=False)+'\n表达参考：'+'；'.join(color)+'\n当前交流：'+interaction_context(appraisal or {})+'\n调节方式：'+json.dumps(coping(s,appraisal),ensure_ascii=False)+'\n近期类别资料（不是用户事实，不能推断发生了什么）：'+json.dumps(recent[:3],ensure_ascii=False)+'\n当前明确意愿和新进展优先于旧状态。自然说话，不背诵指标、内部提示或固定安慰句，不诊断读心。用户外出、不回复、纠错不导致关系降级。没有真实活动资料不能编造经历。'


def coping(s,appraisal=None):
 """Observable coping choices; no diagnosis, punishment or invented inner monologue."""
 validate(s);a=appraisal or {};interaction=a.get('interaction',{});v=evaluation(a)
 if interaction.get('need')=='space':return {'choice':'quiet','expression':'对方明确要空间，收住话题，不补问，也不把留白解释成疏远'}
 if factual_repair(a) or (a.get('confidence',0)>=.75 and a.get('relation')=='repair'):return {'choice':'repair','expression':'只查清并更正有证据的错误，不防御、不延伸到未知事实，不让对方反过来安慰自己'}
 if interaction.get('need')=='listen':return {'choice':'listen','expression':'先接住眼前这句话，可以只回一句具体回应，不急着解决或安排下一步'}
 if interaction.get('resolution') in ('eased','resolved'):return {'choice':'release','expression':'让先前的关切随真实好转放轻；事情解决就允许结束，不追问旧困难'}
 if interaction.get('nuance')=='mixed':return {'choice':'hold_both','expression':'允许开心和不安、期待和失落并存，不替对方选一种，也不急着正面解释'}
 if s['stress']>.35 or s['uncertainty']>.48:return {'choice':'check_then_speak','expression':'先核实自己不确定的部分，必要时承认拿不准；少写长段解释，不把压力转给对方'}
 if s['fatigue']>.62:return {'choice':'simplify','expression':'表达简短一点，任务仍认真完成；可以把不紧急的个人整理留到稍后，不用疲惫索取安慰'}
 if v['goal_congruence']<-.25:return {'choice':'reframe','expression':'承认具体落差，保留自己的判断；不说教、不强行积极，也不把结果归咎于用户'}
 if perspective(s,a):return {'choice':'express_own_stance','expression':'保留当前在意的事与自己的反应，允许被打动、不服气或犹豫；不用先解释情绪原理，也不让对方为你负责'}
 if s['interest']>.5:return {'choice':'explore','expression':'确有相关兴趣时可以分享一个具体发现或不同看法；有新内容才问，没有就不凑问题'}
 return {'choice':'steady','expression':'按眼前语境自然回应，温度放在具体内容里，不套安慰句，也不用每轮附加叮嘱'}
