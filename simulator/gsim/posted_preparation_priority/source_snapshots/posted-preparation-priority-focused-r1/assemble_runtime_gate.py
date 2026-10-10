#!/usr/bin/env python3
"""Assemble only executed immutable inputs, then require strict final verification."""
from pathlib import Path
import argparse,hashlib,json
import focused_verify_r3 as v
HERE=Path(__file__).resolve().parent

def ref(p):
 p=Path(p).resolve();assert p.is_file(),p
 return {'path':str(p),'sha256':v.sha(p)}

def record(side,attempt,name,negative=None):
 prefix=f'run-{side}-{attempt}-{name}'+(f'-negative-{negative}'if negative else'')
 step=HERE/(prefix+'.receipt.json');r=json.loads(step.read_text())
 out={'name':negative if negative else name,'step':ref(step),'log':ref(r['log']),'trace':ref(HERE/(prefix+'.jsonl')),'exit_code':r['exit_code'],'guard':r['guard']}
 if not negative:
  rows=[x for x in Path(r['log']).read_text().splitlines()if x.startswith('POSTED_PREPARATION_CASE ')]
  assert len(rows)==1,rows
  parts=dict(x.split('=',1)for x in rows[0].split()[1:]);assert parts.pop('name')==name
  out['metrics']={k:int(x)for k,x in parts.items()}
 return out

def main():
 p=argparse.ArgumentParser();p.add_argument('--off-attempt',required=True);p.add_argument('--on-attempt',required=True);p.add_argument('--structural',required=True);p.add_argument('--output',required=True);a=p.parse_args()
 manifest=json.loads((HERE/'source-freeze-r4.json').read_text());production=manifest['production_head'];tool=v.sha(HERE.parent/'toolchain/tool-receipt.json')
 for name,digest in manifest['files'].items():assert v.sha(HERE/name)==digest,(name,'frozen source drift')
 r={'schema':'posted-preparation-priority-focused-v1','status':v.STATUS,'production_head':production,'tool_receipt_sha256':tool,'DUT_executed':True,'raw_instruction_decode':True,'real_backend_cache':True,'checks':dict.fromkeys(v.CHECKS,'PASS'),'generic_off':ref(a.structural),'sides':{}}
 for side,attempt in [('off',a.off_attempt),('on',a.on_attempt)]:
  m=HERE/f'model-{side}-r1';r['sides'][side]={'profile':ref(m/'profile.json'),'binary':ref(m/f'host-{attempt}'),'host_source':ref(HERE/'posted_preparation_priority.cpp'),'model_artifacts':[ref(x)for x in sorted(m.glob('*.cpp'))]+[ref(x)for x in sorted(m.glob('*.h'))],'cases':{n:record(side,attempt,n)for n in v.CASES},'negative_controls':[record(side,attempt,'main',n)for n in ['data','token','timing']]}
 output=Path(a.output).resolve();assert not output.exists(),'fresh aggregate required'
 staging=output.with_suffix('.unverified.json');staging.write_text(json.dumps(r,indent=2)+'\n')
 checked=v.verify(staging,v.sha(staging),production_head=production,tool_receipt_sha256=tool)
 staging.rename(output);print(json.dumps({'aggregate':ref(output),'verification':checked}))
if __name__=='__main__':main()
