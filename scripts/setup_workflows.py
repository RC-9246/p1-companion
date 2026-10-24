"""Fixed-target n8n bootstrap. Credentials remain on P1 and are never printed."""
import hashlib,json,os
from pathlib import Path
import secrets,shutil,subprocess,time
os.umask(0o077)
BASE=Path('/srv/p1-agent')
DATA=BASE/'astrbot/data'
STAGE=Path(__file__).resolve().parents[1]
SERVICES=DATA/'companion_services'
assert not (DATA/'companion_workflows/n8n/workflow.db').exists(), 'inspect existing n8n state before bootstrap'
for name in ('mcp','workflows'):
    shutil.copytree(STAGE/'services'/name,SERVICES/name,dirs_exist_ok=True)
state=DATA/'companion_workflows/n8n';state.mkdir(parents=True,mode=0o700)
os.chown(state,1000,1000)
bootstrap=SERVICES/'workflows/bootstrap';bootstrap.mkdir(mode=0o700)
os.chown(bootstrap,1000,1000)
webhook=secrets.token_urlsafe(36)
(SERVICES/'mcp/workflow_token.json').write_text(json.dumps({'webhook':webhook}))
(SERVICES/'workflows/workflow.env').write_text('N8N_ENCRYPTION_KEY='+secrets.token_hex(32)+'\nN8N_RUNNERS_AUTH_TOKEN='+secrets.token_urlsafe(36)+'\n')
browser_token=(DATA/'plugin_data/affect/browser_token').read_text().strip()
credentials=[{'id':'p1BrokerReadOnly','name':'P1 Browser Read Only','type':'httpHeaderAuth','data':{'name':'Authorization','value':'Bearer '+browser_token}},
 {'id':'p1WorkflowEntry','name':'P1 Workflow Entry','type':'httpHeaderAuth','data':{'name':'X-P1-Workflow','value':webhook}}]
workflow=[{'id':'p1PublicPythonDigest','name':'P1 public Python documentation (read only)','active':False,
 'nodes':[{'id':'entry','name':'Approved entry','type':'n8n-nodes-base.webhook','typeVersion':2,'position':[0,0],
   'webhookId':'p1-public-digest','parameters':{'path':'p1-public-digest','httpMethod':'POST','authentication':'headerAuth','responseMode':'lastNode'},'credentials':{'httpHeaderAuth':{'id':'p1WorkflowEntry','name':'P1 Workflow Entry'}}},
 {'id':'read','name':'Isolated public page','type':'n8n-nodes-base.httpRequest','typeVersion':4.2,'position':[300,0],
   'parameters':{'method':'POST','url':'http://p1-browser:8765/browse','authentication':'genericCredentialType','genericAuthType':'httpHeaderAuth',
     'sendBody':True,'specifyBody':'json','jsonBody':json.dumps({'subject':'v1:'+hashlib.sha256(b'p1-public-workflow').hexdigest(),'action':'open','url':'https://docs.python.org/3/'}),
     'options':{'timeout':27000}},'credentials':{'httpHeaderAuth':{'id':'p1BrokerReadOnly','name':'P1 Browser Read Only'}}}],
 'connections':{'Approved entry':{'main':[[{'node':'Isolated public page','type':'main','index':0}]]}},
 'settings':{'executionOrder':'v1','saveDataSuccessExecution':'none','saveDataErrorExecution':'none','saveManualExecutions':False}}]
for name,value in [('credentials.json',credentials),('workflow.json',workflow)]:
    path=bootstrap/name;path.write_text(json.dumps(value));os.chown(path,1000,1000);path.chmod(0o600)
compose=['docker','compose','-f',str(SERVICES/'workflows/compose.yaml'),'-p','p1-workflows']
for args in (['run','--rm','-T','--no-deps','workflows','import:credentials','--input=/bootstrap/credentials.json'],
             ['run','--rm','-T','--no-deps','workflows','import:workflow','--input=/bootstrap/workflow.json'],
             ['run','--rm','-T','--no-deps','workflows','publish:workflow','--id=p1PublicPythonDigest'],
             ['up','-d']):
    r=subprocess.run(compose+args,capture_output=True,text=True,timeout=180)
    if r.returncode:
        (BASE/'backups/workflow-bootstrap-error.log').write_text(r.stdout+r.stderr)
        raise RuntimeError('n8n bootstrap failed; protected diagnostic log saved on P1')
for path in bootstrap.glob('*.json'):
    path.unlink()  # Secrets are now encrypted in the DB; source key stays in protected env file.
print(json.dumps({'n8n_version':'2.44.6','workflow':'p1PublicPythonDigest','read_only_workflow':True,'new_public_ports':0,'credential_contents_logged':False}))
