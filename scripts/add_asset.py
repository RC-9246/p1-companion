"""Register a reviewed image in a private pack; never modify distributed source."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'deploy'))
from asset_pack import add_image

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('file',type=Path);p.add_argument('--pack',type=Path,default=Path('.private/reviewed-assets'));p.add_argument('--label',required=True);p.add_argument('--tags',required=True);p.add_argument('--category',default='其他');p.add_argument('--reviewed',action='store_true');a=p.parse_args()
 print(json.dumps(add_image(a.pack,a.file.read_bytes(),a.file.suffix.lower(),a.label,a.tags.split(','),a.category,a.reviewed),ensure_ascii=False))
if __name__=='__main__':main()
