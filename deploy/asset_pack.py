"""Private reviewed image packs, separate from the immutable public source tree."""
import hashlib,json,os,secrets,shutil,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'release'))
from astrbot_plugin_affect.reactions import Catalog,valid_image,CATEGORIES

def checked(path):
    path=Path(path).absolute()
    if any(p.is_symlink() for p in (path,*path.parents)):raise ValueError('asset_symlink_denied')
    return path

def add_image(pack,raw,suffix,label,tags,category,reviewed):
    if reviewed is not True:raise ValueError('human_content_and_rights_review_required')
    if suffix not in ('.png','.jpg') or not 1000<=len(raw)<=1000000 or not valid_image(raw,suffix):raise ValueError('asset_format_or_size')
    if not isinstance(label,str) or not 1<=len(label)<=100 or not isinstance(tags,list) or not 1<=len(tags)<=12 or any(not isinstance(t,str) or not 1<=len(t)<=20 for t in tags) or category not in CATEGORIES:raise ValueError('asset_metadata')
    from PIL import Image
    import io
    Image.MAX_IMAGE_PIXELS=20000000
    with Image.open(io.BytesIO(raw)) as im:im.verify()
    pack=checked(pack);pack.mkdir(mode=0o700,parents=True,exist_ok=True)
    p=pack/'reactions.json';v=json.loads(p.read_text()) if p.exists() else {'version':1,'credit':'Privately supplied and human-reviewed; rights remain with their owners.','assets':[]}
    if v['assets']:Catalog(pack)
    digest=hashlib.sha256(raw).hexdigest()
    if any(r['sha256']==digest for r in v['assets']):raise ValueError('duplicate_asset')
    if len(v['assets'])>=64:raise ValueError('asset_count_limit')
    id='saki_'+''.join(chr(97+int(x,16)) for x in digest[:16]);folder=pack/'reaction_assets';folder.mkdir(mode=0o700,exist_ok=True);checked(folder)
    dest=folder/(id+suffix);fd=os.open(dest,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
    with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
    v['assets'].append({'id':id,'file':id+suffix,'sha256':digest,'bytes':len(raw),'reviewed':True,'label':label,'tags':tags,'category':category,'medium':'user_reviewed','source':'local-human-review','url':''})
    tmp=p.with_name('.catalog-'+secrets.token_hex(8));tmp.write_text(json.dumps(v,ensure_ascii=False,indent=2));tmp.chmod(0o600);os.replace(tmp,p)
    Catalog(pack)
    return {'id':id,'images':len(v['assets']),'private_pack':str(pack),'public_source_modified':False}

def install_pack(source,data):
    source=checked(source);catalog=Catalog(source);target=checked(Path(data)/'reviewed_assets')
    if target.exists():raise ValueError('asset_pack_already_installed_use_reviewed_merge')
    stage=target.with_name('.reviewed-assets-'+secrets.token_hex(8));stage.mkdir(mode=0o700,parents=True)
    try:
        (stage/'reaction_assets').mkdir(mode=0o700)
        for id,row in catalog.assets.items():
            p=stage/'reaction_assets'/row['file'];p.write_bytes(catalog.read(id));p.chmod(0o600)
        shutil.copyfile(source/'reactions.json',stage/'reactions.json');(stage/'reactions.json').chmod(0o600)
        Catalog(stage);os.replace(stage,target)
    finally:
        if stage.exists():shutil.rmtree(stage)
    return {'assets_installed':len(catalog.assets),'runtime_restart_required':True,'public_source_modified':False}
