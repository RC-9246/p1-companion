import base64,json,resource,sys
resource.setrlimit(resource.RLIMIT_CPU,(35,36));resource.setrlimit(resource.RLIMIT_AS,(450*1024*1024,450*1024*1024));resource.setrlimit(resource.RLIMIT_FSIZE,(24*1024*1024,24*1024*1024));resource.setrlimit(resource.RLIMIT_NOFILE,(64,64))
sys.path.insert(0,"/opt/workbench")
from decoder import extract
try:
 data=json.load(sys.stdin);answer=extract(data['name'],base64.b64decode(data['data'],validate=True));print(json.dumps(answer,ensure_ascii=False))
except Exception as e:print(json.dumps({'ok':False,'error':type(e).__name__,'reason':str(e)[:100] if isinstance(e,ValueError) else 'decoder_failed'}))
