#!/usr/bin/env python3
"""Bounded host-only ROI/case6/parser/profile controls, no Board header or DUT."""
import argparse,resource
from contract import *
from model import execute

def run(out):
 out=Path(out).resolve();require(not out.exists(),'fresh light-control namespace');out.mkdir();limit=5*1024**2
 r=dict(schema='memory-proof-frontier-light-host-v1',status='RUNNING',source=source(),guest=guest(),tool_receipt_sha256=TOOL_SHA,tools=tools(),steps=[],DUT_executed=False,Board_header_used=False,full_host_preflight=False,ASAN_OPTIONS='detect_leaks=0',artifact_limit_bytes=limit)
 before={p.name:sha(p)for p in HERE.iterdir()if p.is_file()and p.suffix in ('.py','.hpp','.h','.cpp')};old_limit=resource.getrlimit(resource.RLIMIT_FSIZE)
 try:
  resource.setrlimit(resource.RLIMIT_FSIZE,(limit,old_limit[1]))
  cc=r['tools']['files']['clang']['path'];cmd=[cc,*FLAGS,*geometry('off'),'-DPREFETCH_CANDIDATE_CYCLES=1',str(HERE/'test_roi.cpp'),'-o',str(out/'test_roi')]
  r['steps'].append(execute(cmd,out/'build.log',120,cwd=HERE));require((out/'test_roi').stat().st_size<=limit,'native helper too large')
  r['steps'].append(execute([str(out/'test_roi')],out/'roi.log',30,cwd=HERE));require('cases=0,6,18,19,21'in(out/'roi.log').read_text(),'case6 ROI coverage absent')
  for name in ('test_parser','test_profile'):r['steps'].append(execute([sys.executable,'-B',str(HERE/(name+'.py'))],out/(name+'.log'),60,cwd=HERE))
  require(exact(before,{p.name:sha(p)for p in HERE.iterdir()if p.is_file()and p.suffix in ('.py','.hpp','.h','.cpp')}),'host source changed')
  require(exact(r['source'],source()),'selected source changed');r['status']='PASS_LIGHT_HOST_ROI_CASE6_PARSER_PROFILE_ONLY'
 except BaseException as e:r['status']='FAIL';r['error']=str(e);raise
 finally:
  resource.setrlimit(resource.RLIMIT_FSIZE,old_limit);r['host_inputs']=before;r['artifacts']={p.name:sha(p)for p in out.iterdir()if p.is_file()and p.name!='receipt.json'};save(out/'receipt.json',r)
 require(sum(p.stat().st_size for p in out.iterdir()if p.is_file())<=limit,'light artifact total exceeds 5MiB')
 return dict(status=r['status'],receipt=str(out/'receipt.json'),sha256=sha(out/'receipt.json'),bytes=sum(p.stat().st_size for p in out.iterdir()if p.is_file()),DUT_executed=False,full_host_preflight=False)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);a=p.parse_args();print(json.dumps(run(a.out),indent=2))
