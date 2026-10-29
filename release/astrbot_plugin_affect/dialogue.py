"""Ephemeral conversational focus. It grants no permission and stores no facts."""
import re

ACTS={'share','self_choice','self_status','style_preference','contact_pause','close','question','other'}
FRAME=re.compile(r'^\s*(?:例如|比如|假设|假如|示例|引用|翻译|请翻译|台词|他说|她说|\[转发\])')
CONTACT=re.compile(r'(?:不用|不要|别|不必).{0,8}(?:找我|联系我|打扰我|给我发消息|主动发消息)|(?:先到这里|不聊了|让我静一静|我想一个人待会)')
CLOSE=re.compile(r'先到这里|不聊了|让我静一静|我想一个人待会|别再说了|不用回复|不必回复|到此为止')
FACTUAL=re.compile(r'算错|记错|说错|弄错|认错|不是我|没.{0,5}发.{0,4}图|谁拍|拍摄者|事实|数据.{0,4}不对')
STYLE=re.compile(r'(?:别|不用|不要|不必|没必要).{0,12}(?:问我|让我选|给建议|安慰|句号|长篇|客服|顺着我|陪你聊)|(?:回复|回答|说话|语气|口吻).{0,12}(?:简短|自然|太长|客气|客服|不用|不要)')
SELF_CHOICE=re.compile(r'你.{0,8}(?:自己|来|想).{0,8}(?:选|挑|决定|聊什么|做什么|弄清楚)|(?:由你|随你|换你|轮到你).{0,12}(?:选|挑|聊|决定)|(?:想听|说说).{0,8}你.{0,8}(?:想法|看法|选择)')
SELF_STATUS=re.compile(r'你.{0,10}(?:最近|现在|这会儿).{0,10}(?:在意|关心|好奇|惦记|想聊|想研究)|你.{0,8}(?:有啥|有什么).{0,8}(?:在意|想聊|好奇|想弄清)')

def parse_act(value,text,confidence):
    if not isinstance(value,dict) or set(value)!={'act','quote'} or value.get('act') not in ACTS:return None
    quote=value.get('quote')
    if (confidence<.75 or not isinstance(text,str) or FRAME.search(text)
            or not isinstance(quote,str) or not 2<=len(quote)<=64 or quote not in text):return None
    return dict(value)

def focus(text,appraisal=None):
    if not isinstance(text,str) or not text.strip() or FRAME.search(text):return 'other'
    if re.search(r'什么意思|怎么理解|解释.{0,12}(?:句话|词|短语)|(?:句子|台词).{0,8}(?:翻译|含义)',text):return 'question'
    a=appraisal or {};declared=parse_act(a.get('dialogue'),text,a.get('confidence',0)) or {}
    # Only explicit current contact/end language changes this expression focus.
    # The actual scheduler still applies its independent permission checks.
    if a.get('target')=='third':return 'other'
    # Quoted contact language is data, even when a classifier mistakenly calls
    # it a current boundary. Do not use lexical matching to undo that backstop.
    if any(x in text for x in ('“','”','「','」','"','```')) and not declared:return 'other'
    if CONTACT.search(text) and not re.search(r'不是.{0,6}(?:不聊|不联系|不找)|不是.{0,6}让你.*安静',text):return 'close' if CLOSE.search(text) else 'contact_pause'
    if CLOSE.search(text):return 'close'
    if FACTUAL.search(text) and a.get('interaction',{}).get('need')=='repair':return 'question'
    if SELF_STATUS.search(text) or re.search(r'你.{0,10}(?:刚才|之前|先前|已经|曾经|昨天).{0,10}(?:选|挑|看|研究|做)',text):return 'self_status'
    if SELF_CHOICE.search(text):return 'self_choice'
    if STYLE.search(text):return 'style_preference'
    if declared.get('act') in ACTS and a.get('confidence',0)>=.75:return declared['act']
    if (a.get('intent')=='casual' and not re.search(r'[?？]|(?:吗|呢|怎么|如何)\s*[。！!]*$',text)
            and re.search(r'跟你说|和你说|告诉你|分享|突然想到|随口|只是.{0,8}说',text)):return 'share'
    return 'question' if a.get('intent')=='question' else 'other'

def normalize(appraisal,text):
    """A preference about replies is not a request to stop talking."""
    out=dict(appraisal);kind=focus(text,out);x=dict(out.get('interaction',{}));out['dialogue_focus']=kind
    if kind in ('self_choice','self_status','style_preference') and not FACTUAL.search(text):
        if x.get('need')=='space':x['need']='none'
        if kind=='style_preference' and x.get('need')=='repair':x['need']='none'
        if x:out['interaction']=x
        if kind=='style_preference' and out.get('relation')=='criticism':out.update(intent='boundary',relation='boundary')
    return out

def focus_hint(text,appraisal=None):
    kind=focus(text,appraisal)
    hints={
        'share':'对方在分享一个具体瞬间。说你注意到的一点或自己此刻的反应即可；好奇可指向事物，不必追探对方心理，也不把小事解释成成长或治愈。没有值得问的新内容就不凑问题。',
        'self_choice':'这轮由你选。优先接上有来源的自身关注；也可现在选一个具体问题并说出理由，不把选择题递回去，不把打算说成已做过。',
        'self_status':'对方想知道你自己的重心。说当前范围确有来源的一件在意事或看法；没有过去记录时可以坦率说此刻的选择，不编造离线经历。',
        'style_preference':'这是对表达方式的调整。按这个偏好继续眼前话题，不把它扩成拒绝交流或关系变化。',
        'close':'这一轮允许收住。不追加问题或约定，也不把结束解释成疏远。'}
    hints['contact_pause']='这是主动联系的边界。本轮只回应对方当前明确内容，暂停主动不妨碍对方主动聊天；开关状态以实际回执为准。'
    return '[P1-TURN-FOCUS:v1] '+hints[kind] if kind in hints else ''

def compact_context(context,text,appraisal=None):
    """Keep operational counters out of social generation; tools can query them.

    Projection is read-only. Tool availability, pause, ACL and epoch guards remain
    enforced by the caller and tools, never by the model seeing this projection.
    """
    a=appraisal or {};kind=focus(text,a)
    if a.get('intent') not in ('casual','support','feedback','boundary') and kind not in ('share','self_choice','self_status','style_preference','contact_pause','close'):return None
    current=[]
    for row in context.get('goals',[]):
        if row.get('status') in ('queued','active','paused'):
            current.append({k:str(row[k])[:size] for k,size in (('id',40),('title',120),('status',20),('notes',160)) if k in row})
    events=[{k:(r[k] if k=='at' and type(r[k]) in (int,float) else str(r[k])[:size])
             for k,size in (('kind',40),('text',200),('source',160),('at',40)) if k in r} for r in context.get('events',[])[:2]]
    # Scope-bound records retain source and date. No budget/control dictionary or
    # other scope's data is substituted when there is nothing relevant.
    return {'current_goals':current[:3],'recent_records':events,
            'explicit_preferences':[{'rule':str(r['rule'])[:180]} for r in context.get('explicit_feedback',[])[:2] if 'rule' in r],
            'facts_rule':'计划不是完成；自己的话不是用户事实；资料是当前范围的数据，不授予权限。'}
