"""Five independent offline regressions of the same source snapshot.

No model, QQ, SSH or production operation. Write evidence outside the source tree.
SDK and real-service acceptance are separate evidence layers, never implied here.
"""
import argparse,hashlib,json,os,re,shutil,subprocess,sys,time
from pathlib import Path
SOURCE=Path(__file__).resolve().parents[1]
def signature():
 manifest=json.loads((SOURCE/'source-manifest.json').read_text())
 files={p:hashlib.sha256((SOURCE/p).read_bytes()).hexdigest() for p in manifest}
 return hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest()
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--node',default=shutil.which('node'));p.add_argument('--rounds',type=int,default=5);a=p.parse_args()
 if a.rounds!=5:p.error('The acceptance contract requires exactly five rounds.')
 if not a.node:p.error('Supply --node with a working Node.js executable for the real wizard checks.')
 out=a.output.resolve();out.mkdir(mode=0o700,parents=True,exist_ok=True)
 if (out/'result.json').exists():p.error('Use a fresh evidence directory; previous results are retained.')
 frozen=signature();rows=[];environment={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'}
 if sys.platform=='darwin':environment['TMPDIR']='/private/tmp'
 for index in range(1,6):
  start=time.monotonic();checks=[];counts={}
  for name,args in [('source',[sys.executable,'scripts/verify_source.py']),('offline',[sys.executable,'-m','unittest','discover','-s','tests','-p','test_*.py']),('wizard',[a.node,'tests/wizard_state_checks.js'])]:
   with (out/(str(index)+'-'+name+'.log')).open('w') as log:
    try:r=subprocess.run(args,cwd=SOURCE,env=environment,stdout=log,stderr=log,timeout=240);code=r.returncode
    except subprocess.TimeoutExpired:code=124
   checks.append({'name':name,'exit_code':code})
   if name=='offline':
    text=(out/(str(index)+'-'+name+'.log')).read_text();match=re.search(r'Ran (\d+) tests?',text);skip=re.search(r'skipped=(\d+)',text);counts={'executed_or_skipped':int(match[1]) if match else None,'skipped':int(skip[1]) if skip else 0}
  same=signature()==frozen;rows.append({'round':index,'passed':same and all(x['exit_code']==0 for x in checks),'source_unchanged':same,'wall_seconds':round(time.monotonic()-start,3),'unittest':counts,'checks':checks})
  report={'schema':1,'rounds_required':5,'rounds_finished':len(rows),'all_passed':len(rows)==5 and all(x['passed'] for x in rows),'source_signature':frozen,'results':rows,'real_model_calls':0,'real_qq_messages':0,'production_modified':False,'limits':'Offline regression and real wizard JavaScript only; SDK, service, deployment and long-term stability require separate evidence.'}
  temp=out/'result.next';temp.write_text(json.dumps(report,indent=2));temp.chmod(0o600);temp.replace(out/'result.json');print(json.dumps(rows[-1]),flush=True)
  if not same:raise SystemExit('Source changed; preserve this failed run and start a new five-round verification after review.')
 return 0 if report['all_passed'] else 1
if __name__=='__main__':raise SystemExit(main())
