"""Existing internal brokers only; no model calls, public interaction or QQ sends."""
import json,urllib.request,time
from pathlib import Path
R=Path(__file__).resolve().parents[1];D=Path('/AstrBot/data/plugin_data/affect')
def read(url):
 with urllib.request.urlopen(url,timeout=8) as r:return json.load(r)
report={'browser_health':read('http://p1-browser:8765/health'),'leisure_health':read('http://p1-leisure:8766/health'),'actual_qq_messages':0,'public_account_interactions':0,'model_requests':0}
owner=json.loads((D/'leisure_policy/identities.json').read_text())['allowed_identities'][0]
token=(D/'leisure_token').read_text().strip()
def action(name):
 req=urllib.request.Request('http://p1-leisure:8766/action',data=json.dumps({'subject':owner,'action':name}).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
 with urllib.request.urlopen(req,timeout=55) as r:return json.load(r)
quota=action('quota');report['watch_quota']={k:quota.get(k) for k in ('ok','daily_limit_seconds','remaining_seconds')}
try:
 state=action('login_state');report['bilibili_session']={k:state.get(k) for k in ('ok','logged_in','challenge','session_saved')}
except Exception as e:report['bilibili_session']={'ok':False,'code':type(e).__name__}
(R/'evidence/live-services-health.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
assert report['browser_health'].get('ok') and report['leisure_health'].get('ok') and quota.get('daily_limit_seconds')==28800
