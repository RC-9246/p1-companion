"""Real public search/read service, synthetic isolated subjects; no private content sent."""
import asyncio,hashlib,json,sys
from pathlib import Path
from types import SimpleNamespace as N
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'release'))
from astrbot_plugin_affect.public_research import Research
async def run():
 data=Path('/AstrBot/data/plugin_data/affect');rows=[]
 for kind in ['private','group']:
  scope='v1:'+hashlib.sha256(('p1-v019-synthetic-public-'+kind).encode()).hexdigest();extra={}
  event=N(get_extra=lambda k,d=None:extra.get(k,d),set_extra=lambda k,v:extra.__setitem__(k,v))
  p=N(scope_for=lambda e:scope,enabled=lambda:True,thinking=N(data=data),store=N(take_budget=lambda *a,**k:True,audit=lambda *a,**k:None))
  r=Research(p)
  for action,query,url in [('capabilities','',''),('search','义妹生活 动画 官方',''),('read','','https://gimaiseikatsu-anime.com/chara/02.html')]:
   out=await r.run(event,action,query,url)
   rows.append({'scope_type':kind,'action':action,'ok':out.get('ok',False),'error':out.get('error'),'result_items':len(out.get('items',[])),'has_public_page_text':bool(out.get('text') or out.get('content')),'read_domains':out.get('read_domains') if action=='capabilities' else None})
 report={'real_public_research':True,'synthetic_subjects_only':True,'private_content_sent':False,'account_access':False,'production_database_modified':False,'actual_qq_messages':0,'results':rows}
 (R/'evidence/live-public-research.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False,indent=2));assert all(r['ok'] for r in rows)
asyncio.run(run())
