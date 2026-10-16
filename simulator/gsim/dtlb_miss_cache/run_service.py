#!/usr/bin/env python3
"""Reproduce one bounded actual-service GSIM contract; never constructs a full CPU."""
from pathlib import Path
import argparse,subprocess,os,json,hashlib
if not __debug__:raise RuntimeError('Run checks without Python -O')
P=Path(__file__).resolve().parent;ROOT=P.parents[2]
a=argparse.ArgumentParser(description=__doc__);a.add_argument('--repo-root',type=Path,default=ROOT);a.add_argument('--entries',type=int,choices=[0,32,64,128],required=True);a.add_argument('--output',type=Path,required=True);a.add_argument('--gsim',required=True);a.add_argument('--cxx',default=os.environ.get('CXX','clang++'));a.add_argument('--mill',default='mill');a=a.parse_args()
ROOT=a.repo_root.resolve();out=a.output.resolve();assert not out.exists(),'fresh output directory required';out.mkdir(parents=True);steps=[]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def command(name,argv,expected=0,anchor=None):
 log=out/(name+'.log')
 with log.open('w') as f:p=subprocess.run(list(map(str,argv)),cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,timeout=600,env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0'))
 assert p.returncode==expected,(name,p.returncode)
 if anchor:assert anchor in log.read_text(),name
 steps.append({'name':name,'argv':list(map(str,argv)),'exit':p.returncode,'log_sha256':sha(log)})
 (out/'receipt.json').write_text(json.dumps({'status':'RUNNING','entries':a.entries,'steps':steps},indent=2)+'\n')
command('emit',[a.mill,'-i','IonSoC.test.runMain','ooo.DataTlbMissCacheGsimMain',out,a.entries])
command('generate',[a.gsim,'--threads=1','--dir='+str(out),out/'VirtualLoadPrecheckGsim.fir'])
units=sorted(out.glob('VirtualLoadPrecheckGsim[0-9]*.cpp'));assert units
h=ROOT/'simulator/gsim/harness'/('mmu_l2_contracts.cpp' if a.entries else 'mmu_capacity.cpp')
command('compile',[a.cxx,'-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all','-DDTLB_ENTRIES=16','-DDTLB_WRITE_READ_REUSE=1','-DMISS_CACHE_ENTRIES='+str(a.entries),'-I'+str(out),*units,h,'-ldl','-o',out/'run'])
command('normal',[out/'run'],anchor='MMU_L2_PERMISSION_CONTEXT_FLUSH_CONFLICT_PASS' if a.entries else 'MMU_SERVICE_CAPACITY_PASS')
if a.entries:
 command('negative-address',[out/'run','--mutate-address'],1,'DTLB independent physical operation mismatch')
 command('negative-permission',[out/'run','--mutate-permission'],1,'DTLB independent ordered permission/fault mismatch')
(out/'receipt.json').write_text(json.dumps({'status':'PASS_SERVICE_CONTRACTS','entries':a.entries,'steps':steps,'FIR_sha256':sha(out/'VirtualLoadPrecheckGsim.fir'),'host_sha256':sha(h),'scope':'D16 service plus adapter/PMP fixture; not fullCPU or physical timing'},indent=2)+'\n');print('PASS_SERVICE_CONTRACTS',a.entries)
