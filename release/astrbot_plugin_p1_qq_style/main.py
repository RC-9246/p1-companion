"""QQ-native text at both decoration and the shared transport boundary."""
import secrets
from astrbot.api import logger
from astrbot.api.star import Star
from astrbot.api.event import filter
from .plain import render,STYLE,parser

class P1QQStyle(Star):
    def __init__(self,context):super().__init__(context);self.context=context
    async def initialize(self):
        parser();self.context._p1_qq_style=self
        p=getattr(self.context,'_p1_companion',None)
        if p:p.health('ready')
        logger.info('[P1 QQ Style] READY plain_ast=true')
    async def terminate(self):
        if getattr(self.context,'_p1_qq_style',None) is self:del self.context._p1_qq_style
    @filter.on_llm_request(priority=-30000)
    async def instruct(self,event,request):
        if event.get_platform_id()!='qq_snowluma':return
        if '[P1-QQ-PLAIN:v1]' not in request.system_prompt:request.system_prompt+='\n'+STYLE
        event.set_extra('enable_reasoning',False);event.set_extra('enable_streaming',False)
    def clean(self,text):return render(text)[0]
    @filter.on_decorating_result(priority=1000)
    async def decorate(self,event):
        if event.get_platform_id()!='qq_snowluma':return
        result=event.get_result()
        if result is None:return
        from astrbot.core.message.components import Plain
        cached=set(event.get_extra('_p1_qq_cleaned',[]));structured=False
        for comp in result.chain:
            if isinstance(comp,Plain) and comp.text not in cached:
                comp.text,is_structured=render(comp.text);structured|=is_structured;cached.add(comp.text)
        event.set_extra('_p1_qq_cleaned',list(cached)[:8])
        if structured:event.set_extra('_p1_qq_structured',True)
        result.use_t2i_=False
    def remember(self,event,pieces):
        cached=set(event.get_extra('_p1_qq_cleaned',[]));cached.update(pieces)
        event.set_extra('_p1_qq_cleaned',list(cached)[:12])
    def final(self,event,message):
        from astrbot.core.message.components import Plain
        cached=event.get_extra('_p1_qq_cleaned',[]);chain=[]
        for comp in getattr(message,'chain',[]):
            if not isinstance(comp,Plain):chain.append(comp);continue
            text=comp.text
            if text not in cached:
                # Protect previously formatted code/body if a native prefix was added.
                protected={};nonce=secrets.token_hex(5)
                for n,part in enumerate(sorted(cached,key=len,reverse=True)):
                    if len(part)>=8 and part in text:
                        key='\ue000'+nonce+str(n)+'\ue001';text=text.replace(part,key);protected[key]=part
                text=render(text)[0]
                for key,part in protected.items():text=text.replace(key,part)
            chain.append(Plain(text))
        return message.derive(chain)
