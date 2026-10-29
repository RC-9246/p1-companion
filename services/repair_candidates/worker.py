"""Trusted independent behavior probe. Mounted read-only, outside proposal content."""
import importlib.util,json,random,sys
from pathlib import Path
spec=importlib.util.spec_from_file_location('candidate',sys.argv[1]);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
probes=json.loads(Path(sys.argv[2]).read_text());failures=[];checked=0
for probe in probes:
 checked+=1
 try:actual=getattr(m,probe['function'])(*probe['args'])
 except Exception:failures.append({'probe':probe['id'],'code':'raised'});continue
 if actual!=probe['expected']:failures.append({'probe':probe['id'],'code':'wrong_result'})
# Independent properties, including novel inputs not sent with a proposal.
rng=random.Random(983461)
for i in range(180):
 body=''.join(rng.choice('山雨蓝纸书灯茶鱼') for _ in range(rng.randint(2,35)))
 checked+=1
 if m.casual_tail(body+'。')!=body:failures.append({'probe':'tail-property-'+str(i),'code':'terminal_stop'})
 structured='```text\n'+body+'。\n```';checked+=1
 if m.qq_reply(structured)!=[structured]:failures.append({'probe':'structure-property-'+str(i),'code':'code_changed'})
 parts=m.split_reply(body+'\n\n'+body);checked+=1
 if not 1<=len(parts)<=3 or ''.join(parts)!=body*2:failures.append({'probe':'segmentation-property-'+str(i),'code':'text_loss'})
print(json.dumps({'ok':not failures,'checked':checked,'failures':failures[:12],'trusted_probe':True},ensure_ascii=False));sys.exit(0 if not failures else 1)
