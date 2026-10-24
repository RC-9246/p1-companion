import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'release'))
from astrbot_plugin_affect.social import SocialStore,POLICY,decide,in_quiet,valid_target
from astrbot_plugin_affect.identity import make_identity_key
from astrbot_plugin_affect.context_style import style_context
from astrbot_plugin_affect.companion_store import BASE

NOW=datetime(2026,10,23,15,tzinfo=ZoneInfo('Asia/Shanghai')).timestamp()

class SocialTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=SocialStore(Path(self.temp.name)/'affect.db');self.store.migrate()
        self.identity=make_identity_key('qq_snowluma','bot','owner')
        self.umo='qq_snowluma:FriendMessage:owner'
        self.allowed={self.identity};self.p=dict(POLICY,enabled=True)
        self.store.enroll(self.identity,self.umo,'owner','bot',NOW-9*3600)
        with self.store.db() as c:c.execute('UPDATE companion_social SET next_at=?',(NOW-1,))
    def row(self):return self.store.get(self.identity)
    def eligible(self,r=None,t=NOW):return self.store.eligible(r or self.row(),t,self.p,self.allowed)
    def decision(self):return {'contact':True,'reason':'follow_up','message':'上次说的汇报，后来顺利吗？'}
    def test_time_window_and_timezone(self):
        self.assertTrue(self.eligible())
        for hour in (0,7,23):
            t=datetime(2026,10,23,hour,tzinfo=ZoneInfo('Asia/Shanghai')).timestamp()
            self.assertTrue(in_quiet(t))
        self.assertFalse(in_quiet(datetime(2026,10,23,8,tzinfo=ZoneInfo('Asia/Shanghai')).timestamp()))
    def test_minimum_interval_not_bypassed_by_due_time(self):
        r=self.row();r['last_inbound']=NOW-179*60
        self.assertFalse(self.eligible(r))
    def test_exact_recipient_binding(self):
        r=self.row();self.assertTrue(valid_target(r,self.allowed))
        for k,v in [('user_id','other'),('umo','qq_snowluma:GroupMessage:owner'),('bot_id','other')]:
            bad=dict(r);bad[k]=v;self.assertFalse(valid_target(bad,self.allowed))
        self.assertFalse(valid_target(r,set()))
    def test_inbound_dedup_and_reset(self):
        self.store.observe(self.identity,self.umo,'owner','bot','same',NOW)
        first=self.row()
        self.store.observe(self.identity,self.umo,'owner','bot','same',NOW+1)
        self.assertEqual(first,self.row())
        self.assertEqual(first['version'],1)
        self.assertEqual(first['unanswered'],0)
        self.assertGreaterEqual(first['next_at'],NOW+180*60)
        self.assertLessEqual(first['next_at'],NOW+480*60)
    def test_single_worker_lease(self):
        r=self.row();self.assertTrue(self.store.claim(r,NOW));self.assertFalse(self.store.claim(r,NOW))
    def test_two_unanswered_pause_and_reply_resume(self):
        for _ in range(2):
            key=self.store.reserve(self.row(),self.decision(),NOW)
            self.store.finish(key,'sent')
        self.assertEqual(self.row()['unanswered'],2)
        self.assertFalse(self.eligible())
        self.store.observe(self.identity,self.umo,'owner','bot','reply',NOW+1)
        self.assertEqual(self.row()['unanswered'],0)
    def test_daily_cap_survives_reply_reset(self):
        for n in range(2):
            key=self.store.reserve(self.row(),self.decision(),NOW-100)
            self.store.finish(key,'sent')
            self.store.observe(self.identity,self.umo,'owner','bot',str(n),NOW-4*3600)
        r=self.row();r['next_at']=NOW-1
        self.assertFalse(self.eligible(r))
    def test_disabled_stays_disabled_after_new_messages(self):
        self.store.toggle(self.identity,False,NOW)
        self.store.observe(self.identity,self.umo,'owner','bot','new',NOW+1)
        self.assertEqual(self.row()['enabled'],0)
        self.assertFalse(self.eligible())
    def test_restarted_reservation_never_replayed(self):
        key=self.store.reserve(self.row(),self.decision(),NOW)
        restarted=SocialStore(self.store.path);restarted.migrate();restarted.defer(self.identity,NOW+121)
        with restarted.db() as c:state=c.execute('SELECT state FROM companion_social_outbox WHERE id=?',(key,)).fetchone()[0]
        self.assertEqual(state,'unknown')
        self.assertEqual(restarted.get(self.identity)['unanswered'],1)
    def test_arrival_invalidates_model_decision(self):
        row=self.row();self.store.observe(self.identity,self.umo,'owner','bot','reply',NOW)
        self.assertIsNone(self.store.reserve(row,self.decision(),NOW))
    def test_concurrent_stale_snapshot_cannot_reserve_twice(self):
        row=self.row()
        self.assertIsNotNone(self.store.reserve(row,self.decision(),NOW))
        self.assertIsNone(self.store.reserve(row,self.decision(),NOW))
    def test_cancelled_is_not_sent_history(self):
        key=self.store.reserve(self.row(),self.decision(),NOW);self.store.finish(key,'cancelled')
        self.assertEqual(self.store.recent_sent(self.identity,NOW),[])
        self.assertEqual(self.row()['unanswered'],0)
    def test_watch_first_snapshot_is_not_a_new_discovery(self):
        url='https://docs.python.org/3/'
        self.store.watch(self.identity,url)
        self.assertFalse(self.store.watched(self.identity,url,'first',NOW))
        self.assertFalse(self.store.watched(self.identity,url,'first',NOW+1))
        self.assertTrue(self.store.watched(self.identity,url,'changed',NOW+2))
    def test_model_can_choose_silence(self):
        d=decide(json.dumps({'contact':False,'reason':'none','evidence':[],'message':''}),[],[])
        self.assertFalse(d['contact'])
    def test_contact_requires_real_evidence(self):
        data=dict(self.decision(),evidence=[0])
        self.assertTrue(decide(json.dumps(data),[{'text':'my presentation'}],[])['contact'])
        for change in ({'evidence':[3]},{'evidence':[True]},{'contact':'yes'},{'reason':'discovery'}, {'message':'我刚查到这个资料'}, {'message':'密码是abcdefgh'}):
            bad=dict(data,**change)
            with self.assertRaises(ValueError):decide(json.dumps(bad),[{'text':'source'}],[])
    def test_malformed_response_means_no_unchecked_send(self):
        for raw in ('{}','[]','not json','{"contact":true}',json.dumps(dict(self.decision(),evidence=[0],new_permission='send_to_everyone'))):
            with self.assertRaises((ValueError,TypeError)):decide(raw,[{}],[])
    def test_unverified_link_rejected(self):
        d=dict(self.decision(),evidence=[0],message='https://unverified.example/')
        with self.assertRaises(ValueError):decide(json.dumps(d),[{}],[])
    def test_ignored_user_does_not_change_emotional_state(self):
        from astrbot_plugin_affect.companion_store import evolve
        previous=dict(BASE,trust=.5,familiarity=.2,updated_at=NOW-86400)
        current=evolve(previous,NOW)
        self.assertEqual(current['trust'],previous['trust'])
        self.assertEqual(current['familiarity'],previous['familiarity'])
    def test_historical_concern_not_a_diagnosis(self):
        text=style_context(dict(BASE,concern=.8),{})
        self.assertIn('不假定对方仍然难过',text)
        self.assertNotIn('concern=',text)

if __name__=='__main__':unittest.main()
