import asyncio
import json
from pathlib import Path
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'release'))
from astrbot_plugin_affect.main import AffectPlugin

class Event:
    def __init__(self): self.extra={};self.sent=[]
    def get_platform_id(self): return 'qq_snowluma'
    def get_extra(self,k,default=None): return self.extra.get(k,default)
    def set_extra(self,k,v): self.extra[k]=v
    async def send(self,message): self.sent.append(time.monotonic())

async def run():
    p=AffectPlugin(object())
    requested=[]
    async def pause(delay):
        requested.append(delay)
        await asyncio.sleep(delay)
    p.reply_pause=pause
    first,second=Event(),Event()
    p.install_reply_delay(first);p.install_reply_delay(second)
    p.install_reply_delay(first)
    started=time.monotonic()
    await asyncio.gather(first.send('synthetic'),second.send('synthetic'))
    first_wait=first.sent[0]-started
    spacing=second.sent[0]-first.sent[0]
    assert len(requested)==2 and all(2<=x<=5 for x in requested)
    assert first_wait>=requested[0]-.05 and spacing>=requested[1]-.05
    print(json.dumps({'reply_delay_runtime_passed':True,'requested_seconds':[round(x,3) for x in requested],
        'observed_first_delay':round(first_wait,3),'observed_send_spacing':round(spacing,3),
        'qq_messages_sent':0,'transport':'synthetic'},ensure_ascii=False))

asyncio.run(run())
