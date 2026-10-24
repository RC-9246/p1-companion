"""Synthetic transport: stop-on-reply, unknown outcome and shared queue coverage."""
import asyncio,json,os
from pathlib import Path
import sys,tempfile,time
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'release'))
from astrbot_plugin_affect.social_runtime import SocialController
from astrbot_plugin_affect.social import in_quiet
from astrbot_plugin_affect.identity import make_identity_key

async def run():
    with tempfile.TemporaryDirectory() as t:
        data=Path(t);identity=make_identity_key('qq_snowluma','bot','owner')
        (data/'allowed_identities.json').write_text(json.dumps({'version':1,'allowed_identities':[identity]}))
        (data/'social_policy.json').write_text('{"enabled":true}')
        calls=[];delays=[];audits=[]
        async def send(row,message):calls.append(row['umo']);return True
        async def pause(seconds):delays.append(seconds)
        async def fake_decision(row):return {'contact':True,'reason':'follow_up','message':'之前那份汇报，后来顺利吗？'}
        p=SimpleNamespace(reply_gate=asyncio.Lock(),reply_pause=pause,enabled=lambda:True,
            context=SimpleNamespace(),send_social_message=send,store=SimpleNamespace(audit=lambda *args:audits.append(args)))
        c=SocialController(p,data);c.store.migrate()
        now=time.time()
        assert not in_quiet(now),'run these production-runtime synthetic tests during Shanghai daytime'
        c.store.enroll(identity,'qq_snowluma:FriendMessage:owner','owner','bot',now-9*3600)
        decision=await fake_decision(None)
        row=c.store.get(identity)
        result=await c.send(row,decision)
        assert result=='sent' and len(calls)==1 and len(delays)==1 and 2<=delays[0]<=5
        assert c.store.recent_sent(identity,time.time())[0]['content']==decision['message']
        # A reply arriving while waiting cancels the pending send.
        async def reply_during_pause(seconds):
            c.store.observe(identity,row['umo'],'owner','bot','new-message',time.time())
        p.reply_pause=reply_during_pause
        result=await c.send(c.store.get(identity),decision)
        assert result=='cancelled' and len(calls)==1
        # A switch-off during the randomized wait also cancels it.
        async def off_during_pause(seconds):c.store.toggle(identity,False,time.time())
        p.reply_pause=off_during_pause
        result=await c.send(c.store.get(identity),decision)
        assert result=='cancelled' and len(calls)==1
        c.store.toggle(identity,True,time.time())
        p.reply_pause=pause
        async def broken_send(row,message):calls.append(row['umo']);raise RuntimeError('transport outcome uncertain')
        p.send_social_message=broken_send
        try:await c.send(c.store.get(identity),decision)
        except RuntimeError:pass
        else:raise AssertionError('expected synthetic transport error')
        assert len(calls)==2
        with c.store.db() as db:
            statuses=[r[0] for r in db.execute('SELECT state FROM companion_social_outbox')]
        assert statuses==['sent','cancelled','cancelled','unknown'],statuses
        assert c.store.get(identity)['unanswered']==1
        # Revoking the identity before transport never sends.
        (data/'allowed_identities.json').write_text('{"version":1,"allowed_identities":[]}')
        result=await c.send(c.store.get(identity),decision)
        assert result is not None and len(calls)==2
        print(json.dumps({'synthetic_social_transport':True,'random_delay':delays,
            'sent_once':True,'arrival_cancellation':True,'disable_cancellation':True,
            'unknown_not_retried':True,'identity_revocation':True,'real_qq_messages':0}))

asyncio.run(run())
