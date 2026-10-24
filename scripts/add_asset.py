"""Register one explicitly human-reviewed local image, never a model-supplied path."""
import argparse,hashlib,json,re,shutil,sys
from pathlib import Path
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'release'))
from astrbot_plugin_affect.reactions import valid_image,CATEGORIES
p=argparse.ArgumentParser();p.add_argument('file',type=Path);p.add_argument('--label',required=True);p.add_argument('--tags',required=True);p.add_argument('--category',choices=sorted(CATEGORIES),default='其他');p.add_argument('--reviewed',action='store_true');a=p.parse_args()
assert a.reviewed,'Review content, source rights and personal data first; then pass --reviewed'
src=a.file.resolve();data=src.read_bytes();suffix=src.suffix.lower();assert 1000<=len(data)<=1000000 and suffix in ('.jpg','.png') and valid_image(data,suffix)
assert 1<=len(a.label)<=100;tags=a.tags.split(',');assert 1<=len(tags)<=12 and all(1<=len(x)<=20 for x in tags)
folder=R/'release/astrbot_plugin_affect';catalog=json.loads((folder/'reactions.json').read_text());digest=hashlib.sha256(data).hexdigest();assert len(catalog['assets'])<64 and not any(x['sha256']==digest for x in catalog['assets']);id='saki_'+''.join(chr(97+int(x,16)) for x in digest[:16]);(folder/'reaction_assets').mkdir(exist_ok=True);shutil.copyfile(src,folder/'reaction_assets'/(id+suffix))
catalog['assets'].append({'id':id,'file':id+suffix,'sha256':digest,'bytes':len(data),'reviewed':True,'label':a.label,'tags':tags,'category':a.category,'medium':'user_reviewed','source':'local-human-review','url':''});(folder/'reactions.json').write_text(json.dumps(catalog,ensure_ascii=False,indent=2));print('Reviewed local image registered. Install/upgrade plugins after reviewing the catalog.')
