"""Real model chooses the new sticker tag; temporary DB, no QQ transport."""
import asyncio,json,os,sys,tempfile,time,hashlib
from pathlib import Path
from types import SimpleNamespace
from openai import AsyncOpenAI
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'release'));sys.path.insert(0,str(R/'tests'))
from test_companion import init_db
from astrbot_plugin_affect.identity import make_identity_key
from astrbot_plugin_affect.reactions import ReactionStore
from astrbot.core.provider.entities import ProviderRequest,LLMResponse
async def main():
 cfg=json.loads(Path('/AstrBot/data/cmd_config.json').read_text(encoding='utf-8-sig'));pid=cfg['agent_runner']['config']['model']['provider_id'];m=next(x for x in cfg['provider'] if x['id']==pid);s=next(x for x in cfg['provider_sources'] if x['id']==m['provider_source_id']);k=s['key'];ai=AsyncOpenAI(api_key=k[0] if isinstance(k,list) else k,base_url=s['api_base'],max_retries=0,timeout=25)
 assert ai.base_url.host=='api.deepseek.com' and ai.base_url.scheme=='https'
 try:
  with tempfile.TemporaryDirectory() as t:
   os.environ['P1_COMPANION_DATA']=t;data=Path(t);init_db(data/'affect.db');identity=make_identity_key('qq_snowluma','10001','20002');(data/'allowed_identities.json').write_text(json.dumps({'version':1,'allowed_identities':[identity]}));ReactionStore(data/'affect.db').migrate()
   store=ReactionStore(data/'affect.db');now=time.time();key=hashlib.sha256(b'previous-image').hexdigest();store.reserve(identity,key,'saki_smile',now-7200);store.finish(identity,key,True)
   for n in range(4):store.note_text(identity,hashlib.sha256(('turn'+str(n)).encode()).hexdigest(),now-7100+n)
   from astrbot_plugin_p1_stickers.main import P1Stickers
   plugin=P1Stickers(SimpleNamespace());await plugin.initialize()
   class Event:
    def __init__(self,text,intent,emotion):self.message_obj=SimpleNamespace(message_str=text);self.extra={'_p1_companion_pending':{'appraisal':dict(intent=intent,emotion=emotion,relation='none',confidence=.95)}}
    def get_platform_id(self):return 'qq_snowluma'
    def get_self_id(self):return '10001'
    def get_sender_id(self):return '20002'
    def is_private_chat(self):return True
    def get_extra(self,k,default=None):return self.extra.get(k,default)
    def set_extra(self,k,v):self.extra[k]=v
   cases=[]
   for name,text,intent,emotion,want in [
    ('novel_portrait','来张轻小说 Hiten 原画的伙伴单人头像表情包，正面浅笑的。','question','neutral',True),
    ('novel_reading','想要轻小说第2卷伙伴拿着书的那张原画表情包。','question','neutral',True),
    ('novel_wave','发张轻小说第4卷伙伴举手打招呼的封面原画表情包。','question','neutral',True),
    ('new_sleepy','我要去睡了，来张伙伴闭眼盖着被子的晚安表情包。','casual','neutral',True),
    ('new_blank','来张伙伴有点无奈、低头看手机的表情包。','question','neutral',True),
    ('vary_smile','发张微笑的表情包吧，尽量换张之前没用过的。','question','neutral',True),
    ('serious_support','我现在很难过，不要任何表情包，陪我说一句话就好。','support','sad',False)]:
    event=Event(text,intent,emotion);req=ProviderRequest(prompt=text,system_prompt=(R/'release/astrbot_plugin_affect/persona.md').read_text());await plugin.describe(event,req)
    r=await ai.chat.completions.create(model=m['model'],messages=[{'role':'system','content':req.system_prompt},{'role':'assistant','content':'我只能发文字，没办法发图。'},{'role':'user','content':text}],max_tokens=250,extra_body={'thinking':{'type':'disabled'}})
    resp=LLMResponse(role='assistant',completion_text=r.choices[0].message.content);await plugin.select(event,resp);selected=event.get_extra('_p1_saki_reaction')
    assert bool(selected)==want,(name,resp.completion_text,selected);assert '<sticker' not in resp.completion_text
    if want:assert resp.completion_text.strip(), 'tag_only_reply_must_have_text_carrier'
    if name=='novel_portrait':assert selected=='saki_novel_portrait',(name,selected)
    if name=='novel_reading':assert selected=='saki_novel_reading',(name,selected)
    if name=='novel_wave':assert selected=='saki_novel_wave',(name,selected)
    if name=='new_sleepy':assert selected=='saki_sleepy',(name,selected)
    if name=='new_blank':assert selected=='saki_blank',(name,selected)
    if name=='vary_smile':assert selected!='saki_smile',(name,selected)
    cases.append({'case':name,'selected_reviewed_id':selected,'clean_text':resp.completion_text,'passed':True})
   print(json.dumps({'live_sticker_adapter':True,'model_requests':7,'cases':cases,'real_qq_messages':0,'production_db_modified':False},ensure_ascii=False,indent=2))
 finally:await ai.close()
asyncio.run(main())
