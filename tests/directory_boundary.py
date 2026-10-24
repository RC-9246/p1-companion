"""A newly authorized target must remain reachable behind many nonadmitted entries."""
import argparse,asyncio,json,sys
from pathlib import Path
R=Path(__file__).resolve().parents[1];sys.path[:0]=[str(R/'release'),str(R/'tests')]
from test_qq_actions import QQActions
async def run(out):
 t=QQActions('test_actual_receipt_and_delay_are_required');await t.asyncSetUp()
 try:
  original=t.api.call_action
  async def directory(action,**kw):
   if action=='get_friend_list':return [{'user_id':20002,'nickname':'主人'}]+[{'user_id':40000+n,'nickname':'未加白好友'} for n in range(205)]+[{'user_id':20003,'nickname':'新增获准好友'}]
   if action=='get_group_list':return [{'group_id':50000+n,'group_name':'未开启群'} for n in range(25)]+[{'group_id':30003,'group_name':'新增开启群'}]
   return await original(action,**kw)
  t.api.call_action=directory;await t.q.refresh(True)
  r=await t.q.directory(t.a);refs={x['target_ref'] for x in r['targets']}
  report={'new_private_at_end_registered':t.q.event_ref(t.b) in refs,'new_group_at_end_registered':t.q.event_ref(t.g) in refs,'unadmitted_entries_excluded':len(refs)<=3,'synthetic_only':True,'actual_qq_messages':0,'production_database_modified':False}
  report['passed']=all(report[x] for x in ('new_private_at_end_registered','new_group_at_end_registered','unadmitted_entries_excluded'))
  Path(out).write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2));assert report['passed']
 finally:await t.asyncTearDown()
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--out',required=True);a=p.parse_args();asyncio.run(run(a.out))
