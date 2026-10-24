"""Actual isolated worker, synthetic document bodies only. No user files or QQ sends."""
import base64,io,json,sys,time,urllib.request,urllib.error,zipfile
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
R=Path(__file__).resolve().parents[1];D=Path('/AstrBot/data/plugin_data/affect');token=(D/'workbench_token').read_text().strip();cases=[]
def request(path,value):
 req=urllib.request.Request('http://p1-workbench:8767/'+path,data=json.dumps(value).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
 try:
  with urllib.request.urlopen(req,timeout=58) as r:return json.load(r)
 except urllib.error.HTTPError as e:return json.load(e)
def archive(files):
 b=io.BytesIO()
 with zipfile.ZipFile(b,'w') as z:
  for key,value in files.items():z.writestr(key,value)
 return b.getvalue()
def run(name,raw,needle):
 started=time.monotonic();result=request('decode',{'name':name,'data':base64.b64encode(raw).decode()});ok=result.get('ok') is True and needle.lower() in result.get('text','').lower();cases.append({'name':name,'passed':ok,'mode':result.get('mode'),'seconds':round(time.monotonic()-started,3),'error':result.get('error'),'reason':result.get('reason')});assert ok,cases[-1]
for name,data,needle in [('sample.txt','你好，临时文件'.encode('gb18030'),'临时文件'),('data.csv',b'name,value\np1,42','42'),('data.json',b'{"device":"P1"}','P1'),('source.py',b'print("read_only_code")','read_only_code'),('subtitle.srt',b'1\n00:00:01,000 --> 00:00:03,000\nhello p1','hello'),('mail.eml',b'Subject: synthetic\nContent-Type: text/plain; charset=utf-8\n\nCompanion synthetic mail','Companion'),('page.html',b'<html><main>Hello P1</main><script>do_not_run()</script></html>','Hello P1')]:run(name,data,needle)
for name,files,needle in [('sample.docx',{'word/document.xml':'<document><p>Companion DOCX</p></document>'},'Companion DOCX'),('sample.pptx',{'ppt/slides/slide1.xml':'<slide><text>Companion PPTX</text></slide>'},'Companion PPTX'),('sample.xlsx',{'xl/sharedStrings.xml':'<sst><si><t>Companion XLSX</t></si></sst>','xl/worksheets/sheet1.xml':'<worksheet><sheetData><row><c r="A1" t="s"><v>0</v></c><c r="B1"><v>42</v></c></row></sheetData></worksheet>'},'Companion XLSX'),('sample.odt',{'content.xml':'<doc><p>Companion ODT</p></doc>'},'Companion ODT'),('sample.epub',{'book/ch1.xhtml':'<html><body>Companion EPUB</body></html>'},'Companion EPUB'),('sample.zip',{'notes.txt':'Companion archive'},'Companion archive')]:run(name,archive(files),needle)
stream=b'BT /F1 18 Tf 50 740 Td (Companion PDF synthetic) Tj ET';objects=[b'<< /Type /Catalog /Pages 2 0 R >>',b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 800] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',b'<< /Length '+str(len(stream)).encode()+b' >>\nstream\n'+stream+b'\nendstream']
pdf=b'%PDF-1.4\n';offsets=[0]
for n,obj in enumerate(objects,1):offsets.append(len(pdf));pdf+=str(n).encode()+b' 0 obj\n'+obj+b'\nendobj\n'
start=len(pdf);pdf+=b'xref\n0 6\n0000000000 65535 f \n'+b''.join(('%010d 00000 n \n'%offset).encode() for offset in offsets[1:])+b'trailer\n<< /Root 1 0 R /Size 6 >>\nstartxref\n'+str(start).encode()+b'\n%%EOF';run('sample.pdf',pdf,'Companion PDF')
image=Image.new('RGB',(1000,180),'white');draw=ImageDraw.Draw(image)
font=next((str(x) for x in Path('/usr/share/fonts/truetype').rglob('*.ttf')),None);face=ImageFont.truetype(font,48) if font else ImageFont.load_default(size=48);draw.text((35,40),'COMPANION 2026',font=face,fill='black');buf=io.BytesIO();image.save(buf,'PNG');run('sample.png',buf.getvalue(),'COMPANION')
run('sample.rtf',b'{\\rtf1\\ansi Companion RTF synthetic}', 'Companion RTF')
blocked=[]
for name,data in [('evil.zip',archive({'../escape':'unsafe'})),('entity.docx',archive({'word/document.xml':'<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><x>&e;</x>'})),('program.exe',b'MZ synthetic'),('mismatch.pdf',b'not pdf')]:
 result=request('decode',{'name':name,'data':base64.b64encode(data).decode()});blocked.append({'name':name,'denied':result.get('ok') is False});assert blocked[-1]['denied']
experiment=request('experiment',{'code':'import math\nprint(sum(x*x for x in range(10)))\nprint(math.sqrt(81))'});assert experiment.get('ok') and '285' in experiment['output']
for code in ['import os\nprint(os.listdir("/"))','open("/run/secrets/workbench_token")','print((1).__class__)']:
 result=request('experiment',{'code':code});assert not result.get('ok')
report={'synthetic_formats_verified':len(cases),'formats':cases,'security_cases':blocked,'math_experiment_executed':True,'forbidden_code_denied':True,'user_files_processed':0,'real_qq_messages':0};(R/'evidence/live-workbench.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False))
