"""Additive migration inside the existing backed-up affect.db. Atomic dedup and projection."""
import json
import math
import re
import sqlite3
import time
from contextlib import closing
from pathlib import Path
try:
    from .emotion_model import seed as emotion_seed, advance as emotion_advance, react as emotion_react, project as emotion_project, TOPICS as EMOTION_TOPICS
except ImportError:  # The existing native MCP process imports this file as a standalone module.
    from emotion_model import seed as emotion_seed, advance as emotion_advance, react as emotion_react, project as emotion_project, TOPICS as EMOTION_TOPICS

BASE={'mood':0.,'energy':.5,'familiarity':0.,'trust':.25,'comfort':.4,'curiosity':.4,'concern':0.,'interaction_count':0,'last_interaction_at':0,'updated_at':0}
LIMITS={'mood':(-1,1),'energy':(0,1),'familiarity':(0,.7),'trust':(0,1),'comfort':(0,1),'curiosity':(0,1),'concern':(0,1)}

def clamp(x,a,b):
    return min(b,max(a,x))

def evolve(previous,now,a=None,interact=False):
    if isinstance(now,bool) or not isinstance(now,(int,float)) or not math.isfinite(now) or now<0:
        raise ValueError('invalid clock')
    s=dict(previous)
    for key,(lo,hi) in LIMITS.items():
        x=s.get(key)
        if isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) or not lo<=x<=hi:
            raise ValueError('invalid state')
    last=s['updated_at']
    dt=max(0,now-last) if last else 0
    for key,baseline,half in [('mood',0,21600),('energy',.5,43200),('curiosity',.4,21600),('concern',0,3600),('comfort',.4,604800)]:
        s[key]=baseline+(s[key]-baseline)*2**(-dt/half)
    if not interact:
        return s
    a=a or {}
    elapsed=max(0,now-s['last_interaction_at'])
    first=s['interaction_count']==0
    weight=1 if first else min(1,elapsed/60)
    slow=1 if first else min(1,elapsed/300)
    relation=a.get('relation') if a.get('target')=='self' and a.get('confidence',0)>=.75 else 'none'
    signal={'thanks':.5,'repair':.2,'criticism':-.25,'boundary':-.1}.get(relation,0)
    s['mood']+=signal*.08*weight
    # Corrections are useful feedback, never treated as hostility or a trust penalty.
    if relation in ('thanks','repair'):
        s['trust']+=.0015*slow*(1-s['trust'])
        s['comfort']+=.003*slow
    if relation=='boundary':
        s['comfort']-=.01*weight
    s['energy']+=.005*weight
    s['familiarity']+=.001*slow*max(0,1-s['familiarity']/.7)
    if a.get('emotion') in ('sad','anxious') and a.get('target')=='user':
        s['concern']+=.12*weight
    if a.get('intent') in ('question','planning'):
        s['curiosity']+=.015*weight
    for key,(lo,hi) in LIMITS.items():
        s[key]=clamp(s[key],lo,hi)
    s['interaction_count']+=1
    s['last_interaction_at']=max(now,s['last_interaction_at'])
    s['updated_at']=max(now,last)
    return s

class CompanionStore:
    def __init__(self,path):
        self.path=Path(path)
        if not self.path.is_file():
            raise FileNotFoundError('existing affect DB required')

    def connect(self):
        conn=sqlite3.connect(self.path,timeout=2)
        conn.row_factory=sqlite3.Row
        conn.execute('PRAGMA busy_timeout=2000')
        return conn

    def migrate(self):
        with closing(self.connect()) as c, c:
            c.execute('BEGIN IMMEDIATE')
            # Legacy tables must exist; refuse to silently create a wrong database.
            assert c.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name IN ('affect_state','affect_processed_events')").fetchone()[0]==2
            c.execute('CREATE TABLE IF NOT EXISTS companion_meta (key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            old=c.execute("SELECT value FROM companion_meta WHERE key='schema'").fetchone()
            if old and old[0]!='1':
                raise ValueError('unsupported schema')
            c.execute("INSERT OR IGNORE INTO companion_meta VALUES ('schema','1')")
            c.execute('''CREATE TABLE IF NOT EXISTS companion_state (
                identity_key TEXT PRIMARY KEY,mood REAL NOT NULL CHECK(mood BETWEEN -1 AND 1),
                energy REAL NOT NULL CHECK(energy BETWEEN 0 AND 1),familiarity REAL NOT NULL CHECK(familiarity BETWEEN 0 AND .7),
                trust REAL NOT NULL CHECK(trust BETWEEN 0 AND 1),comfort REAL NOT NULL CHECK(comfort BETWEEN 0 AND 1),
                curiosity REAL NOT NULL CHECK(curiosity BETWEEN 0 AND 1),concern REAL NOT NULL CHECK(concern BETWEEN 0 AND 1),
                interaction_count INTEGER NOT NULL CHECK(interaction_count>=0),last_interaction_at INTEGER NOT NULL,updated_at INTEGER NOT NULL)''')
            c.execute('''CREATE TABLE IF NOT EXISTS companion_events (event_key TEXT PRIMARY KEY,identity_key TEXT NOT NULL,
                processed_at INTEGER NOT NULL,intent TEXT NOT NULL,emotion TEXT NOT NULL,relation TEXT NOT NULL,source TEXT NOT NULL)''')
            c.execute('CREATE TABLE IF NOT EXISTS companion_budget (day INTEGER PRIMARY KEY,used INTEGER NOT NULL)')
            c.execute('CREATE TABLE IF NOT EXISTS companion_reply_review_budget(day INTEGER PRIMARY KEY,used INTEGER NOT NULL)')
            c.execute('''CREATE TABLE IF NOT EXISTS companion_audit (id INTEGER PRIMARY KEY,at INTEGER NOT NULL,
                action TEXT NOT NULL,status TEXT NOT NULL,host TEXT NOT NULL DEFAULT '')''')
            emotion_version=c.execute("SELECT value FROM companion_meta WHERE key='emotion_schema'").fetchone()
            if emotion_version and emotion_version[0]!='1':raise ValueError('unsupported_emotion_schema')
            c.execute("INSERT OR IGNORE INTO companion_meta VALUES('emotion_schema','1')")
            c.execute('CREATE TABLE IF NOT EXISTS companion_emotion(identity TEXT PRIMARY KEY,state TEXT NOT NULL)')
            c.execute('''CREATE TABLE IF NOT EXISTS companion_emotion_episodes(event TEXT PRIMARY KEY,identity TEXT NOT NULL,
                kind TEXT NOT NULL,topic TEXT NOT NULL,intensity REAL NOT NULL,summary TEXT NOT NULL,at REAL NOT NULL)''')
            for row in c.execute('SELECT identity_key FROM affect_state').fetchall():
                self.validate(row[0])
                c.execute('INSERT OR IGNORE INTO companion_emotion VALUES(?,?)',(row[0],json.dumps(emotion_seed(self._read(c,row[0])),separators=(',',':'))))

    @staticmethod
    def validate(identity,event=None):
        if not isinstance(identity,str) or not re.fullmatch('v1:[0-9a-f]{64}',identity):
            raise ValueError('invalid identity')
        if event is not None and (not isinstance(event,str) or not re.fullmatch('[0-9a-f]{64}',event)):
            raise ValueError('invalid event')

    def _read(self,c,identity):
        r=c.execute('SELECT * FROM companion_state WHERE identity_key=?',(identity,)).fetchone()
        legacy=c.execute('SELECT * FROM affect_state WHERE identity_key=?',(identity,)).fetchone()
        if r:
            s=dict(r); s.pop('identity_key')
            # A temporary v0.6.2 rollback may have accepted additional interactions.
            # Never overwrite that newer legacy projection on the next upgrade.
            if legacy and (legacy['interaction_count']>s['interaction_count'] or legacy['updated_at']>s['updated_at']):
                s=evolve(s,max(s['updated_at'],legacy['updated_at']))
                count=max(s['interaction_count'],legacy['interaction_count'])
                last=max(s['last_interaction_at'],legacy['last_interaction_at'])
                updated=max(s['updated_at'],legacy['updated_at'])
                for key in ('mood','energy','familiarity'):
                    s[key]=legacy[key]
                s.update(interaction_count=count,last_interaction_at=last,updated_at=updated)
                s['familiarity']=min(.7,s['familiarity'])
            return s
        s=dict(BASE)
        r=legacy
        if r:
            for k in s:
                if k in r.keys():
                    s[k]=r[k]
            s['familiarity']=min(.7,s['familiarity'])
        return s

    def ensure_identity(self,identity):
        """Initialize an empty per-contact state without inventing interactions."""
        self.validate(identity)
        with closing(self.connect()) as c:
            if (c.execute('SELECT 1 FROM companion_state WHERE identity_key=?',(identity,)).fetchone()
                    and c.execute('SELECT 1 FROM companion_emotion WHERE identity=?',(identity,)).fetchone()):
                return
        with closing(self.connect()) as c,c:
            c.execute('BEGIN IMMEDIATE');state=self._read(c,identity);cols=list(BASE)
            c.execute('INSERT OR IGNORE INTO companion_state(identity_key,'+','.join(cols)+') VALUES('+','.join('?' for _ in range(len(cols)+1))+')',[identity]+[state[k] for k in cols])
            c.execute('INSERT OR IGNORE INTO companion_emotion VALUES(?,?)',(identity,json.dumps(emotion_seed(state),separators=(',',':'))))

    def read(self,identity,now=None):
        self.validate(identity)
        with closing(self.connect()) as c:
            now=time.time() if now is None else now
            state=evolve(self._read(c,identity),now)
            if c.execute('SELECT 1 FROM companion_emotion WHERE identity=?',(identity,)).fetchone():
                state.update(emotion_project(emotion_advance(self._emotion(c,identity,state),now)))
            return state

    def commit(self,identity,event,a,now=None):
        self.validate(identity,event)
        now=int(time.time() if now is None else now)
        with closing(self.connect()) as c, c:
            c.execute('BEGIN IMMEDIATE')
            previous=c.execute('SELECT identity_key FROM affect_processed_events WHERE event_key=?',(event,)).fetchone()
            if previous:
                if previous[0]!=identity:
                    raise ValueError('ownership mismatch')
                return False
            before=self._read(c,identity)
            s=evolve(before,now,a,True)
            c.execute('INSERT INTO companion_events VALUES (?,?,?,?,?,?,?)',(event,identity,now,a['intent'],a['emotion'],a['relation'],a['source']))
            cols=list(BASE)
            c.execute('INSERT OR REPLACE INTO companion_state (identity_key,'+','.join(cols)+') VALUES ('+','.join('?' for _ in range(len(cols)+1))+')',[identity]+[s[k] for k in cols])
            c.execute('INSERT INTO affect_processed_events VALUES (?,?,?)',(event,identity,now))
            legacy=['mood','energy','familiarity','interaction_count','last_interaction_at','updated_at']
            c.execute('INSERT OR REPLACE INTO affect_state (identity_key,'+','.join(legacy)+') VALUES (?,?,?,?,?,?,?)',[identity]+[s[k] for k in legacy])
            self._commit_emotion(c,identity,event,a,now,before)
            # Compatibility columns are projections, not a second independent emotional system.
            # The transaction still commits only after the existing delivery acknowledgment.
            projection=emotion_project(self._emotion(c,identity))
            c.execute('UPDATE companion_state SET '+','.join(k+'=?' for k in projection)+' WHERE identity_key=?',list(projection.values())+[identity])
            c.execute('UPDATE affect_state SET mood=?,energy=?,familiarity=? WHERE identity_key=?',
                (projection['mood'],projection['energy'],projection['familiarity'],identity))
            return True

    def _emotion(self,c,identity,legacy=None):
        row=c.execute('SELECT state FROM companion_emotion WHERE identity=?',(identity,)).fetchone()
        old=legacy if legacy is not None else self._read(c,identity)
        if not row:return emotion_seed(old)
        state=json.loads(row[0])
        if old['interaction_count']>state['interactions']:
            state['interactions']=old['interaction_count'];state['last_event_at']=max(state['last_event_at'],old['last_interaction_at'])
            state['familiarity']=max(state['familiarity'],min(.7,old['familiarity']))
        return state

    def read_emotion(self,identity,now=None):
        self.validate(identity)
        with closing(self.connect()) as c:return emotion_advance(self._emotion(c,identity),time.time() if now is None else now)

    def preview_emotion(self,identity,a,now=None):
        self.validate(identity)
        with closing(self.connect()) as c:return emotion_react(self._emotion(c,identity),time.time() if now is None else now,a)[0]

    def _commit_emotion(self,c,identity,event,a,now,legacy=None,activity=None):
        previous=c.execute('SELECT identity FROM companion_emotion_episodes WHERE event=?',(event,)).fetchone()
        if previous:
            if previous[0]!=identity:raise ValueError('emotion_ownership_mismatch')
            return False
        state,episode=emotion_react(self._emotion(c,identity,legacy),now,a,activity)
        c.execute('INSERT OR REPLACE INTO companion_emotion VALUES(?,?)',(identity,json.dumps(state,separators=(',',':'))))
        c.execute('INSERT INTO companion_emotion_episodes VALUES(?,?,?,?,?,?,?)',(event,identity,episode['kind'],episode['topic'],episode['intensity'],episode['summary'],now))
        c.execute('DELETE FROM companion_emotion_episodes WHERE at<?',(now-180*86400,))
        return True

    def note_activity(self,identity,event,kind,topic='none',interest=.6,now=None):
        self.validate(identity,event)
        if kind not in ('watch','reflection','rest') or topic not in EMOTION_TOPICS or isinstance(interest,bool) or not isinstance(interest,(int,float)) or not math.isfinite(interest) or not 0<=interest<=1:raise ValueError('invalid_activity')
        with closing(self.connect()) as c,c:
            c.execute('BEGIN IMMEDIATE')
            return self._commit_emotion(c,identity,event,{'confidence':1.},time.time() if now is None else now,
                activity={'kind':kind,'topic':topic,'interest':interest})

    def emotional_episodes(self,identity,now=None,topic='none'):
        self.validate(identity);now=time.time() if now is None else now
        with closing(self.connect()) as c:
            rows=[dict(x) for x in c.execute('SELECT kind,topic,intensity,summary,at FROM companion_emotion_episodes WHERE identity=? ORDER BY at DESC LIMIT 30',(identity,))]
        # Keep the latest change visible; older salient distress cannot crowd out later recovery.
        selected=rows[:1]
        ranked=sorted(rows[1:],key=lambda x:x['intensity']*2**(-max(0,now-x['at'])/(2*86400))+(0.3 if topic!='none' and x['topic']==topic else 0),reverse=True)
        seen={x['kind'] for x in selected}
        for row in ranked:
            if row['kind'] in seen:continue
            selected.append(row);seen.add(row['kind'])
            if len(selected)>=3:break
        return selected

    def take_budget(self,limit=200,now=None,bucket=0):
        if type(bucket) is not int or not 0<=bucket<=9:raise ValueError('budget_bucket_out_of_range')
        day=int(time.time() if now is None else now)//86400*10+bucket
        with closing(self.connect()) as c, c:
            c.execute('BEGIN IMMEDIATE')
            c.execute('INSERT OR IGNORE INTO companion_budget VALUES (?,0)',(day,))
            cur=c.execute('UPDATE companion_budget SET used=used+1 WHERE day=? AND used<?',(day,limit))
            c.execute('DELETE FROM companion_budget WHERE day<?',(day-80,))
            return cur.rowcount==1

    def audit(self,action,status,host=''):
        # Only enumerated codes and a public DNS name, never paths, queries, content or IDs.
        if not re.fullmatch('[a-z_]{1,40}',action) or not re.fullmatch('[a-z_]{1,40}',status) or not re.fullmatch('[a-z0-9.-]{0,253}',host):
            raise ValueError('invalid audit')
        with closing(self.connect()) as c, c:
            c.execute('INSERT INTO companion_audit(at,action,status,host) VALUES (?,?,?,?)',(int(time.time()),action,status,host))
            c.execute('DELETE FROM companion_audit WHERE id < (SELECT MAX(id)-2000 FROM companion_audit)')

    def take_reply_review_budget(self,limit=64,now=None):
        if type(limit) is not int or not 1<=limit<=128:raise ValueError('review_budget_limit')
        now=time.time() if now is None else now
        if isinstance(now,bool) or not isinstance(now,(int,float)) or not math.isfinite(now) or now<0:raise ValueError('review_clock')
        day=int((now+28800)//86400)
        with closing(self.connect()) as c,c:
            c.execute('BEGIN IMMEDIATE');c.execute('INSERT OR IGNORE INTO companion_reply_review_budget VALUES(?,0)',(day,))
            cur=c.execute('UPDATE companion_reply_review_budget SET used=used+1 WHERE day=? AND used<?',(day,limit))
            c.execute('DELETE FROM companion_reply_review_budget WHERE day<?',(day-2,));return cur.rowcount==1
