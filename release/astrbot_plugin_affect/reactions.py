"""Reviewed local reaction images; the model never supplies paths or download URLs."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import sqlite3

IDENTITY=re.compile(r'v1:[0-9a-f]{64}')
EVENT=re.compile(r'[0-9a-f]{64}')
CATEGORIES={'轻松','温和','疑惑','思考','无奈','含蓄','困倦','日常','其他'}
MAX_ASSETS=64
MAX_IMAGE_BYTES=1000000
REACTION_COOLDOWN_SECONDS=600
REACTION_MIN_TURNS=3
SEARCH_LIMIT=12
SERIOUS=re.compile(r'自杀|自残|急救|过世|去世|病危|葬礼|抑郁|不要.*(?:图|表情)|别.*(?:图|表情)|不用.*(?:图|表情)|严肃|serious|suicid|self.harm',re.I)

def eligible_context(appraisal,text):
    return (isinstance(text,str) and not text.lstrip().startswith('/') and not SERIOUS.search(text)
        and appraisal.get('confidence',0)>=.75
        and (appraisal.get('intent') in ('casual','feedback') or (appraisal.get('intent')=='question' and re.search(r'表情包|发.{0,8}(?:表情|图片)|来张.{0,5}图',text)))
        and appraisal.get('emotion') in ('neutral','happy')
        and appraisal.get('relation') not in ('criticism','repair','boundary'))

def approved_source(row):
    """Only the reviewed official stills and fixed publisher art paths are accepted."""
    if row.get('medium')=='user_reviewed':return row.get('source')=='local-human-review' and row.get('file') in (row.get('id','')+'.png',row.get('id','')+'.jpg')
    url=row.get('url','');source=row.get('source','')
    if not isinstance(url,str) or not isinstance(source,str):return False
    if row.get('medium','anime_still')=='anime_still':
        return bool(re.fullmatch(r'https://gimaiseikatsu-anime\.com/core_sys/images/contents/[0-9]+/block/[0-9]+/[0-9]+\.jpg',url)
            and re.fullmatch(r'https://gimaiseikatsu-anime\.com/story/(?:0[1-9]|1[0-2])\.html',source)
            and row.get('file')==row.get('id','')+'.jpg')
    base='https://promo.kadokawa.co.jp/mfbunkoj/special/gimaiseikatsu/'
    return (row.get('medium')=='light_novel_art' and row.get('illustrator')=='Hiten'
        and source==base and row.get('file')==row.get('id','')+'.png'
        and url in {base+'img/'+x+'.png' for x in ('character_img02','kv_key_visual',*('book_cover_%02d'%n for n in range(2,14)))})

def valid_image(data,suffix):
    if suffix=='.jpg':return data.startswith(b'\xff\xd8\xff') and data.endswith(b'\xff\xd9')
    if suffix=='.png' and len(data)>=33:
        width=int.from_bytes(data[16:20],'big');height=int.from_bytes(data[20:24],'big')
        return (data.startswith(b'\x89PNG\r\n\x1a\n') and data[12:16]==b'IHDR'
            and data.endswith(b'\x00\x00\x00\x00IEND\xaeB`\x82') and 1<=width<=4096 and 1<=height<=4096)
    return False

class Catalog:
    def __init__(self,folder):
        self.folder=Path(folder).resolve()
        manifest=json.loads((self.folder/'reactions.json').read_text())
        assert manifest.get('version')==1 and 0<=len(manifest['assets'])<=MAX_ASSETS
        self.credit=manifest['credit'];self.assets={};digests=set()
        for row in manifest['assets']:
            id=row['id']
            assert re.fullmatch(r'saki_[a-z_]{1,30}',id) and id not in self.assets
            assert row['reviewed'] is True and approved_source(row)
            assert isinstance(row['label'],str) and 1<=len(row['label'])<=100
            assert isinstance(row['tags'],list) and 1<=len(row['tags'])<=12 and all(isinstance(x,str) and 1<=len(x)<=20 for x in row['tags'])
            assert row.get('category','其他') in CATEGORIES
            assert row['sha256'] not in digests,'duplicate_image_digest'
            digests.add(row['sha256']);self.assets[id]={**row,'category':row.get('category','其他')}
            self.read(id)

    def read(self,id):
        row=self.assets[id];root=self.folder/'reaction_assets';p=root/row['file']
        if p.is_symlink() or root.is_symlink() or p.resolve().parent!=root.resolve():
            raise ValueError('invalid_asset_path')
        if not p.is_file() or not 1000<=p.stat().st_size<=MAX_IMAGE_BYTES:
            raise ValueError('invalid_asset_size')
        data=p.read_bytes()
        if len(data)!=row['bytes'] or hashlib.sha256(data).hexdigest()!=row['sha256'] or not valid_image(data,p.suffix):
            raise ValueError('invalid_asset_digest')
        return data

    def search(self,query='',recent=()):
        if not isinstance(query,str) or len(query)>80:raise ValueError('invalid_query')
        recent=set(recent)
        def score(row):
            return (sum(word in query for word in row['tags'])+(1 if query and query in row['label'] else 0),row['id'] not in recent)
        ranked=sorted(self.assets.values(),key=score,reverse=True)
        return [{'id':r['id'],'description':r['label'],'category':r['category'],'tags':r['tags'],'source':r['source'],'medium':r.get('medium','anime_still')} for r in ranked[:SEARCH_LIMIT]]

    def categories(self):
        from collections import Counter
        return dict(Counter(r['category'] for r in self.assets.values()))

class ReactionStore:
    def __init__(self,path):self.path=Path(path)
    def connect(self):
        db=sqlite3.connect(self.path,timeout=3);db.row_factory=sqlite3.Row;return db
    def migrate(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with closing(self.connect()) as db,db:
            db.execute('CREATE TABLE IF NOT EXISTS reaction_preferences(identity TEXT PRIMARY KEY, enabled INTEGER NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS reaction_text(identity TEXT, event TEXT, at REAL, PRIMARY KEY(identity,event))')
            db.execute('CREATE TABLE IF NOT EXISTS reaction_outbox(identity TEXT, event TEXT, asset TEXT, at REAL, state TEXT, PRIMARY KEY(identity,event))')
        self.path.chmod(0o600)
    def validate(self,identity,event=None):
        if not isinstance(identity,str) or not IDENTITY.fullmatch(identity) or (event is not None and (not isinstance(event,str) or not EVENT.fullmatch(event))):
            raise ValueError('invalid_identity_or_event')
    def enabled(self,identity):
        self.validate(identity)
        with closing(self.connect()) as db:
            row=db.execute('SELECT enabled FROM reaction_preferences WHERE identity=?',(identity,)).fetchone()
        return row is None or row[0]==1
    def toggle(self,identity,enabled):
        self.validate(identity)
        with closing(self.connect()) as db,db:
            db.execute('INSERT OR REPLACE INTO reaction_preferences VALUES(?,?)',(identity,int(bool(enabled))))
    def note_text(self,identity,event,now):
        self.validate(identity,event)
        with closing(self.connect()) as db,db:
            db.execute('INSERT OR IGNORE INTO reaction_text VALUES(?,?,?)',(identity,event,now))
            db.execute('DELETE FROM reaction_text WHERE at<?',(now-86400*30,))
            db.execute('DELETE FROM reaction_outbox WHERE at<?',(now-86400*30,))
    def recent(self,identity,limit=4):
        self.validate(identity)
        if type(limit) is not int or not 1<=limit<=8:raise ValueError('invalid_recent_limit')
        with closing(self.connect()) as db:
            return [r[0] for r in db.execute("SELECT asset FROM reaction_outbox WHERE identity=? AND state IN ('sent','reserved','unknown') ORDER BY at DESC LIMIT ?",(identity,limit))]
    def available(self,db,identity,now):
        pref=db.execute('SELECT enabled FROM reaction_preferences WHERE identity=?',(identity,)).fetchone()
        if pref is not None and pref[0]!=1:return False
        count=db.execute('SELECT COUNT(*) FROM reaction_outbox WHERE identity=? AND at>?',(identity,now-86400)).fetchone()[0]
        if count>=6:return False
        last=db.execute('SELECT at FROM reaction_outbox WHERE identity=? ORDER BY at DESC LIMIT 1',(identity,)).fetchone()
        if last:
            if now-last[0]<REACTION_COOLDOWN_SECONDS:return False
            turns=db.execute('SELECT COUNT(*) FROM reaction_text WHERE identity=? AND at>?',(identity,last[0])).fetchone()[0]
            if turns<REACTION_MIN_TURNS:return False
        return True
    def can_use(self,identity,now):
        self.validate(identity)
        with closing(self.connect()) as db:return self.available(db,identity,now)
    def reserve(self,identity,event,asset,now):
        self.validate(identity,event)
        if not isinstance(asset,str) or not re.fullmatch(r'saki_[a-z_]{1,30}',asset):raise ValueError('invalid_asset')
        with closing(self.connect()) as db,db:
            db.execute('BEGIN IMMEDIATE')
            if not self.available(db,identity,now):return False
            return db.execute('INSERT OR IGNORE INTO reaction_outbox VALUES(?,?,?,?,?)',(identity,event,asset,now,'reserved')).rowcount==1
    def finish(self,identity,event,success):
        self.validate(identity,event)
        with closing(self.connect()) as db,db:
            db.execute('UPDATE reaction_outbox SET state=? WHERE identity=? AND event=? AND state=?',('sent' if success else 'unknown',identity,event,'reserved'))
        # An uncertain network result remains consumed. It is never replayed.
