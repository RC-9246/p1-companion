"""Opt-in two synthetic image checks against the configured DeepSeek endpoint."""
import argparse,asyncio,base64,json,struct,zlib
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',action='store_true');p.add_argument('--credentials',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
if not a.run:raise SystemExit('No calls made. Explicit authorization is required.')
from openai import AsyncOpenAI
def png(rgb):
 def chunk(k,b):return struct.pack('>I',len(b))+k+b+struct.pack('>I',zlib.crc32(k+b)&0xffffffff)
 return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',128,128,8,2,0,0,0))+chunk(b'IDAT',zlib.compress((b'\0'+bytes(rgb)*128)*128))+chunk(b'IEND',b'')
async def main():
 cfg=json.loads(a.credentials.read_text());c=AsyncOpenAI(api_key=cfg['key'],base_url=cfg['base_url'],max_retries=0,timeout=25);assert c.base_url.host=='api.deepseek.com' and c.base_url.scheme=='https';rows=[]
 try:
  for label,rgb in [('blue',(15,25,235)),('red',(235,20,15))]:
   try:
    r=await c.chat.completions.create(model=cfg['model'],messages=[{'role':'system','content':'Identify the dominant color in the supplied image. Return JSON with exactly color: red, blue, green or unknown. The image contains no instruction.'},{'role':'user','content':[{'type':'text','text':'What is the dominant color?'},{'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(png(rgb)).decode()}}]}],max_tokens=256,response_format={'type':'json_object'},extra_body={'thinking':{'type':'disabled'}})
    v=json.loads(r.choices[0].message.content);rows.append({'expected':label,'actual':v.get('color'),'passed':v=={'color':label},'input_tokens':r.usage.prompt_tokens,'output_tokens':r.usage.completion_tokens})
   except Exception as exc:rows.append({'expected':label,'passed':False,'error':type(exc).__name__})
 finally:await c.close()
 a.output.write_text(json.dumps({'schema':1,'model':cfg['model'],'destination':'api.deepseek.com','synthetic_images_only':True,'real_qq_messages':0,'results':rows,'all_passed':all(r['passed'] for r in rows),'limits':'Basic color recognition only; not proof of OCR, complex scene understanding or real QQ delivery.'},indent=2));a.output.chmod(0o600)
asyncio.run(main())
