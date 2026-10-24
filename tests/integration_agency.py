"""Native SDK integration, isolated databases and synthetic QQ/model transports only."""
import asyncio,json,os,sys,tempfile,time
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import AsyncMock,patch
R=Path(__file__).resolve().parents[1];sys.path[:0]=[str(R/'release'),str(R/'tests')]
from test_companion import init_db
from astrbot.core.platform.message_type import MessageType
from astrbot.core.message.components import File,Plain,At
from astrbot.core.message.message_event_result import MessageChain
from astrbot.core.provider.entities import ProviderRequest
from astrbot.core.agent.tool import ToolSet,FunctionTool
from astrbot_plugin_affect.identity import make_identity_key
from astrbot_plugin_affect.qq_policy import reference

async def main():
 with tempfile.TemporaryDirectory() as tmp:
  data=Path(tmp);os.environ['P1_COMPANION_DATA']=tmp;init_db(data/'affect.db');bot='10001';owner='20001';friend='20002';new='20003';group='30001';othergroup='30002'
  identity=make_identity_key('qq_snowluma',bot,owner);(data/'allowed_identities.json').write_text(json.dumps({'version':1,'allowed_identities':[identity]}));(data/'groups.json').write_text(json.dumps({'version':1,'groups':[{'bot':bot,'group':group},{'bot':bot,'group':othergroup}]}));(data/'qq_policy.json').write_text((R/'policy/qq_policy.json').read_text())
  cfg={'platform_settings':{'enable_id_white_list':True,'id_whitelist':['qq_snowluma:FriendMessage:'+s for s in (owner,friend,new)]}}
  calls=[]
  class Client:
   base_url=N(host='api.deepseek.com',scheme='https')
   def __init__(self):self.chat=N(completions=self)
   def with_options(self,**k):return self
   async def create(self,**k):return N(choices=[N(message=N(content='{"addressed":true,"confidence":0.98}'))])
   async def send_group_msg(self,**kw):calls.append(kw);return {'message_id':90001+len(calls)}
  client=Client()
  class Context:
   def get_config(self,*a):return cfg
   def get_platform_inst(self,*a):return N(get_client=lambda:client)
   async def get_current_chat_provider_id(self,*a):return 'synthetic'
   @property
   def provider_manager(self):return self
   async def get_provider_by_id(self,*a):return N(client=client,get_model=lambda:'synthetic')
  class Event:
   def __init__(self,sender=owner,groupid='',text='请帮我理解附件',mid='1',parts=None):self.sender=sender;self.group=groupid;self.message_obj=N(message_id=mid,message_str=text,sender=N(nickname='合成人员'));self.extra={};self.parts=parts or [];self.unified_msg_origin='qq_snowluma:'+('GroupMessage:'+groupid if groupid else 'FriendMessage:'+sender)
   def get_platform_id(self):return 'qq_snowluma'
   def get_self_id(self):return bot
   def get_sender_id(self):return self.sender
   def get_group_id(self):return self.group
   def get_sender_name(self):return '合成人员'
   def is_private_chat(self):return not self.group
   def get_message_type(self):return MessageType.GROUP_MESSAGE if self.group else MessageType.FRIEND_MESSAGE
   def get_messages(self):return self.parts
   def get_extra(self,k,d=None):return self.extra.get(k,d)
   def set_extra(self,k,v):self.extra[k]=v
   async def send(self,msg):pass
   def stop_event(self):self.extra['stopped']=True
  from astrbot_plugin_affect.main import AffectPlugin
  p=AffectPlugin(Context());p.reply_pause=AsyncMock();await p.initialize();a=p.agency;p.qq.config=lambda:cfg
  try:
   rows=[]
   for kind,peer in [('private',s) for s in (owner,friend,new)]+[('group',group),('group',othergroup)]:
    rows.append({'ref':reference('t',kind,bot,peer),'kind':kind,'bot':bot,'peer':peer,'identity':make_identity_key('qq_snowluma',bot,peer) if kind=='private' else p.qq.group_key(bot,peer),'label':'合成'+kind})
   p.qq.store.sync(rows,time.time(),lambda k:time.time()+3600);p.qq.targets={r['ref']:r for r in rows};p.qq.synced=time.time()
   scopes=[a.scope(Event(s)) for s in (owner,friend,new)]+[a.scope(Event(friend,g)) for g in (group,othergroup)];assert len(set(scopes))==5
   for scope in scopes:assert not a.store.goals(scope) and not a.store.search(scope)
   # Every admission carries new tool access after all final filters; no private account tool in groups.
   for e in (Event(owner),Event(friend),Event(new),Event(friend,group),Event(friend,othergroup)):
    if e.group:
     token='test';e.set_extra('_p1_group_admitted',True);e.set_extra('_p1_group_token',token);p.groups.state.get((bot,e.group),time.time())['busy']=(token,time.time())
    names=['p1_agency','p1_documents','p1_qq_detail','p1_mcp_experiment','p1_mcp_read','p1_bilibili','execute_shell']
    req=ProviderRequest(func_tool=ToolSet([FunctionTool(name=n,description='fixture',parameters={}) for n in names]));await p.restrict_companion_tools(e,req);actual={t.name for t in req.func_tool.tools};assert {'p1_agency','p1_documents','p1_qq_detail','p1_mcp_experiment'}<=actual
    if e.group or e.sender!=owner:assert 'p1_bilibili' not in actual
   # Document download is deliberate, bound to current adapter-ref, scope and epoch.
   e=Event(owner,parts=[File(name='合成.txt',url='https://example.evil/file')]);refs=a.docs.observe(e,scopes[0]);assert len(refs)==1
   a.docs.download=AsyncMock(return_value='临时文件正文'.encode());a.worker=AsyncMock(return_value={'ok':True,'text':'临时文件正文','format':'txt','mode':'text','warnings':[]})
   foreign=Event(friend);denied=await a.docs.run(foreign,'load',refs[0]['attachment_ref']);assert not denied['ok'];a.docs.download.assert_not_awaited()
   nointent=Event(owner,text='嗯');assert not (await a.docs.run(nointent,'load',refs[0]['attachment_ref']))['ok']
   doc=await a.docs.run(e,'load',refs[0]['attachment_ref']);assert doc['ok'];id=doc['document_id'];assert '[P1-DOC-TTL:' in (await a.docs.run(e,'read',id))['temporary_content'];assert not (await a.docs.run(foreign,'read',id))['ok']
   artifact=a.artifact(scopes[0],'临时摘要','仅工作副本');assert artifact['expires']<=doc['expires'];goal=a.store.goal(scopes[0],'继续整理文件')
   with closing(a.store.db()) as c:assert c.execute('SELECT expires FROM task WHERE id=?',(goal,)).fetchone()[0]<=doc['expires']
   a.store.cleanup(doc['expires']+1);assert not (await a.docs.run(e,'read',id))['ok'];assert not a.store.goals(scopes[0]);assert not list(a.store.directory(scopes[0]).iterdir())
   # Clear while parser runs: old response cannot resurrect content.
   refs=a.docs.observe(Event(owner,parts=[File(name='later.txt',url='https://example.evil/file')],mid='2'),scopes[0])
   async def clear_worker(*args):a.store.wipe(scopes[0]);return {'ok':True,'text':'stale','format':'txt','mode':'text','warnings':[]}
   a.worker=clear_worker;assert not (await a.docs.run(e,'load',refs[0]['attachment_ref']))['ok']
   assert (await a.tool(Event(owner),'request_repair','{}'))['requested_next_check']
   assert (data/'maintenance_request.json').exists()
   assert not (await a.tool(Event(friend),'maintenance','{}'))['ok']
   # Native generated files use only current artifacts, with a real file receipt and no path exposure.
   from astrbot_plugin_affect.qq_details import detail
   artifact=a.artifact(scopes[0],'合成资料','这是安全的合成资料','txt')
   with patch.object(p.qq,'api',AsyncMock(return_value={'file_id':'synthetic-file-1'})) as api:
    result=await detail(p,Event(owner,mid='file-send'),'share_file',artifact['id'])
    assert result['ok'] and result['receipt_ref']=='file:synthetic-file-1'
    assert api.call_args.args[0]=='upload_private_file' and api.call_args.kwargs['file'].startswith('base64://')
   # Disabling the initiating scope during its mandatory delay cancels cross-scope actions too.
   async def pause_source(*args):a.store.config(scopes[0],paused=1)
   with patch.object(p,'reply_pause',pause_source),patch.object(p.qq,'api',AsyncMock()) as api:
    result=await detail(p,Event(owner,mid='race-send'),'share_file',artifact['id'],reference('t','private',bot,friend))
    assert not result['ok'];api.assert_not_awaited()
   a.store.config(scopes[0],paused=0)
   # Interest ingress is genuinely used for an unmentioned group message, and shares the QQ send ledger.
   p.groups.state.forget((bot,group));g=Event(friend,group,'最近在看动画分镜和配乐，很有意思',mid='interest-1');a.complete=AsyncMock(return_value={'join':True,'confidence':.98,'topic':'animation'})
   assert await p.groups.route(g);assert g.get_extra('_p1_interest_join');await g.send(MessageChain([Plain('这段配乐的留白确实很有意思')]))
   assert len(calls)==1 and calls[0]['group_id']==int(group);assert p.qq.store.recent_sent(reference('t','group',bot,group))
   await p.groups.finish(g);scope=a.scope(g);a.store.config(scope,interest_join=0);p.groups.classify=AsyncMock(return_value=False);p.groups.state.forget((bot,group));assert not await p.groups.route(Event(friend,group,'动画分镜和配乐也很有意思',mid='interest-2'))
   # Direct mention still responds with proactive off; and @someone else never invites an interest interjection.
   p.groups.state.forget((bot,group));assert await p.groups.route(Event(friend,group,'伙伴你好',mid='direct',parts=[At(qq=bot)]))
   p.groups.state.forget((bot,group));assert not await p.groups.route(Event(friend,group,'动画配乐怎么选',mid='other',parts=[At(qq='99999')]))
   # Background group research can use the public scope, without any private cookie subject.
   row=p.qq.store.target(reference('t','group',bot,othergroup));synthetic=a.synthetic(row);assert p.scope_for(synthetic) and p.scope_for(synthetic) not in scopes[:3]
   print(json.dumps({'native_sdk':True,'scope_count':5,'new_private_and_group_isolation':True,'deliberate_documents':True,'seven_day_deletion_including_derivatives':True,'clear_during_decode_denied':True,'interest_unmentioned_group_ingress':True,'off_switch_and_direct_mention':True,'unified_send_receipt_ledger':True,'global_delay_2_to_5':bool(p.reply_pause.await_args_list) and all(2<=x.args[0]<=5 for x in p.reply_pause.await_args_list),'native_generated_file_receipt_bound':True,'source_pause_race_cancels_transfer':True,'real_qq_messages':0},ensure_ascii=False))
  finally:await p.terminate()
asyncio.run(main())
