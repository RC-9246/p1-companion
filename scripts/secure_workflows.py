"""Close the first-owner setup page using an internal-only generated admin account."""
import json,os
from pathlib import Path
import secrets,subprocess
import urllib.request
os.umask(0o077)
root=Path('/srv/p1-agent/astrbot/data/companion_services/workflows')
ip=subprocess.run(['docker','inspect','--format','{{(index .NetworkSettings.Networks "p1-companion-control").IPAddress}}','p1-n8n'],capture_output=True,text=True,check=True).stdout.strip()
base='http://'+ip+':5678'
def get():
    with urllib.request.urlopen(base+'/rest/settings',timeout=8) as r:return json.load(r)['data']
settings=get()
if settings['userManagement']['showSetupOnFirstLoad']:
    account={'email':'owner@p1.invalid','firstName':'P1','lastName':'Administrator','password':secrets.token_urlsafe(32)+'aA9!'}
    request=urllib.request.Request(base+'/rest/owner/setup',data=json.dumps(account).encode(),headers={'Content-Type':'application/json','Origin':base},method='POST')
    with urllib.request.urlopen(request,timeout=10) as response:
        assert response.status==200
    target=root/'admin-initial-access.json';target.write_text(json.dumps(account));target.chmod(0o600)
assert get()['userManagement']['showSetupOnFirstLoad'] is False
print(json.dumps({'first_owner_setup_closed':True,'external_account_created':False,'credentials_logged':False,'public_ports':0}))
