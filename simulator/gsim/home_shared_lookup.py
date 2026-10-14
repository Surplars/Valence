#!/usr/bin/env python3
"""Run the paired exact-overlap home fixture from its freshly generated GSIM model.
Emit: mill -i IonSoC.test.runMain ooo.HomeSharedLookupGsimMain OUT 0 4 1 1 1 4 2
Generate OUT/HomeSharedLookupGsim.fir with the pinned GSIM tool, then run this script.
"""
import argparse, hashlib, json, os, re, subprocess
from pathlib import Path

def main():
 p=argparse.ArgumentParser(allow_abbrev=False);p.add_argument('--model',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--cxx',required=True);p.add_argument('--harness-root',type=Path);a=p.parse_args();m=a.model.resolve();o=a.output.resolve();o.mkdir(parents=True,exist_ok=False)
 root=Path(__file__).resolve().parent;top='HomeSharedLookupGsim';f=(m/(top+'.fir')).read_text();header=(m/(top+'.h')).read_text();mod=f.split('  module MixedCoherentLineHome :',1)[1].split('\n  module ',1)[0]
 regs=set(re.findall(r'^    reg(?:reset)? (\w+)\s*:',mod,re.M));members=set(re.findall(r'^.+? (home\$[\w$]+)(?:\[[^;]+\])?;',header,re.M));paired=[]
 for n in sorted(members):
  suffix=n[5:]
  if suffix.split('$')[0] in regs and not suffix.endswith('$NEXT') and re.search(r'\breferenceHome\$'+re.escape(suffix)+r'(?:\[|;)',header):paired.append(suffix)
 if len(paired)<30:raise RuntimeError('missing retained state binding')
 selected=re.findall(r'^    connect selectLine, (\w+)\s',mod,re.M)
 if len(selected)!=1 or ('home$'+selected[0]) not in header:raise RuntimeError('missing unique final selected-line binding')
 obs='#include <type_traits>\ntemplate<class T> static bool sameValue(const T&a,const T&b){if constexpr(std::is_array_v<T>){for(unsigned i=0;i<std::extent_v<T>;++i)if(!sameValue(a[i],b[i]))return false;return true;}else return a==b;}\nstatic uint64_t observedCycles=0,savedSelected=0,dmaSelected=0,upstreamSelected=0,releaseAcquire=0;\nstatic void homeObserve(SHomeSharedLookupGsim&d){\n'
 for n in paired:obs+=f'check(sameValue(d.home${n},d.referenceHome${n}),"HOME_RETAINED_STATE {n}");\n'
 obs+='++observedCycles; if(d.home$maintenance==1||d.home$maintenance==12)++savedSelected; else if(d.home$'+selected[0]+')++dmaSelected;else ++upstreamSelected;\nif((d.home$phase[0]||d.home$phase[1])&&(d.home$releasePhases[0]||d.home$releasePhases[1]))++releaseAcquire;\n}\n';(o/'home_observer.h').write_text(obs)
 units=sorted(m.glob(top+'[0-9]*.cpp'))
 if not units:raise RuntimeError('missing generated model')
 cmd=[a.cxx,'-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all','-DDMA_LINE_ENABLED=1','-DDMA_LINE_ENTRIES=4','-I'+str(m),'-I'+str(o),'-I'+str(a.harness_root.resolve() if a.harness_root else root/'harness'),*map(str,units),str(root/'harness/home_shared_lookup.cpp'),'-ldl','-o',str(o/'run')]
 with (o/'compile.log').open('w') as log:subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,check=True)
 with (o/'protocol.log').open('w') as log:subprocess.run([str(o/'run'),'--protocol-only'],stdout=log,stderr=subprocess.STDOUT,check=True,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'},timeout=180)
 text=(o/'protocol.log').read_text()
 for marker in ['HOME_RELEASE_ACQUIRE_REACHED','HOME_STATE_PASS','DMA_PIPELINE_PROTOCOL_PASS']:
  if marker not in text:raise RuntimeError('missing '+marker)
 sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
 (o/'receipt.json').write_text(json.dumps({'status':'PASS','paired_retained_members':paired,'fir_sha256':sha(m/(top+'.fir')),'header_sha256':sha(m/(top+'.h')),'host_sha256':sha(root/'harness/home_shared_lookup.cpp'),'log_sha256':sha(o/'protocol.log'),'physical_result':'UNMEASURED'},indent=2)+'\n')
 print('HOME_SHARED_LOOKUP_PASS',len(paired))
if __name__=='__main__':main()
