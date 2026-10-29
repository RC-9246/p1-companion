"""Generated pixel fixtures, independent of private or licensed character art."""
import hashlib,json,struct,zlib
from pathlib import Path

def catalog(folder):
    folder=Path(folder);(folder/'reaction_assets').mkdir(parents=True,exist_ok=True)
    def chunk(kind,body):return struct.pack('>I',len(body))+kind+body+struct.pack('>I',zlib.crc32(kind+body)&0xffffffff)
    raw=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',1,1,8,2,0,0,0))+chunk(b'tEXt',b'fixture\0'+b'generated synthetic test pixel '*45)+chunk(b'IDAT',zlib.compress(b'\x00\x40\x80\xc0'))+chunk(b'IEND',b'')
    ident='saki_fixture_portrait';(folder/'reaction_assets'/(ident+'.png')).write_bytes(raw)
    row={'id':ident,'file':ident+'.png','bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'reviewed':True,'source':'local-human-review','medium':'user_reviewed','label':'synthetic pixel','tags':['合成'],'category':'其他'}
    (folder/'reactions.json').write_text(json.dumps({'version':1,'credit':'Generated test pixel, no third-party art','assets':[row]}))
    return folder

def expanded(folder):
    """46 generated pixels exercise large catalogs and source metadata policies.

    Publisher URLs below are policy fixtures only, not claims about the pixels.
    No official art is downloaded or distributed by these tests.
    """
    folder=Path(folder);catalog(folder);template=json.loads((folder/'reactions.json').read_text())['assets'][0]
    seed=(folder/'reaction_assets'/template['file']).read_bytes();(folder/'reaction_assets'/template['file']).unlink()
    rows=[];base='https://promo.kadokawa.co.jp/mfbunkoj/special/gimaiseikatsu/'
    profiles=[('saki_novel_portrait','character_img02'),('saki_novel_key_visual','kv_key_visual')]+[('saki_novel_cover_'+chr(97+i),'book_cover_%02d'%(i+2)) for i in range(12)]
    for ident,url in profiles:
        rows.append({**template,'id':ident,'file':ident+'.png','medium':'light_novel_art','illustrator':'Hiten','source':base,'url':base+'img/'+url+'.png','label':'Synthetic source-policy pixel','category':'温和','tags':['轻小说','原画','Hiten']})
    names=[('smile',['微笑']),('soft_smile',['微笑']),('sleepy',['睡觉']),('tired',['疲惫']),('listening',['好奇'])]+[('fixture_'+(chr(97+i) if i<26 else 'aa'),['合成'+(chr(97+i) if i<26 else 'aa')]) for i in range(27)]
    cats=['轻松','温和','疑惑','思考','无奈','含蓄','困倦','日常']
    for i,(name,tags) in enumerate(names):rows.append({**template,'id':'saki_'+name,'file':'saki_'+name+'.png','label':'Synthetic '+name,'tags':tags,'category':cats[i%8]})
    def chunk(kind,body):return struct.pack('>I',len(body))+kind+body+struct.pack('>I',zlib.crc32(kind+body)&0xffffffff)
    for i,row in enumerate(rows):
        raw=seed[:-12]+chunk(b'tEXt',('unique\0fixture'+str(i)).encode())+seed[-12:];(folder/'reaction_assets'/row['file']).write_bytes(raw);row.update(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
    (folder/'reactions.json').write_text(json.dumps({'version':1,'credit':'Generated source-policy fixtures; no official art','assets':rows}))
    return folder
