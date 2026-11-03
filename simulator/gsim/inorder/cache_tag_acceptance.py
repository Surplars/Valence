#!/usr/bin/env python3
"""Affected raw-cache window/tag gates; reuse unchanged IF/BP/bare evidence, not a full regression."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import run as common
ROOT = Path(__file__).resolve().parents[3]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--parent',type=Path,required=True)
    parser.add_argument('--raw-only',action='store_true',help='Reuse unchanged parent CPU/CoreMark; expand raw-cache checks only')
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or not output.is_relative_to(ROOT/'build') or os.environ.get('VALENCE_WORK_ROOT')!=str(ROOT):
        parser.error('source local env; fresh repository build/ output required')
    parent = json.loads(args.parent.read_text())
    if parent['status']!='PASS_I1_CORE300_SHORT_FUNCTIONAL_ONLY':
        raise RuntimeError('missing parent gate')
    changed = {'src/main/scala/core/inorder/FiveStageWordCache.scala','src/test/scala/inorder/I1VivadoMain.scala',
               'src/test/scala/inorder/I1Core300Main.scala','src/test/scala/inorder/FiveStageMain.scala'}
    for name,digest in parent['source_sha256'].items():
        if (name not in changed or args.raw_only and name.startswith('src/main/')) and sha(ROOT/name)!=digest:
            raise RuntimeError('unchanged parent evidence invalidated: '+name)
    sources = [ROOT/name for name in parent['source_sha256']]
    sources += [ROOT/'simulator/gsim/harness/five_stage_cache.cpp',Path(__file__).resolve()]
    frozen = {str(path.relative_to(ROOT)):sha(path) for path in sources}
    receipt = copy.deepcopy(parent)
    receipt.update(status='RUNNING',source_sha256=frozen,commands=[],cache_components={},
        parent_gate=dict(path=str(args.parent),sha256=sha(args.parent),
            reused='unchanged IF queue, predictor, bare ISA/performance and reference CoreMark'),
        scope='affected raw-cache tag/window byte oracle plus cached CoreMark; no full regression or board claim')
    receipt['cpu_coremark_retested']=not args.raw_only
    if args.raw_only:
        receipt['scope']='expanded raw-cache oracle only; unchanged CPU and CoreMark reused by exact production source hashes'
    receipt.pop('rtl_sha256',None);receipt.pop('rtl_root',None)
    output.mkdir(parents=True)
    gsim,cxx=common.setup(False)
    values=json.loads((ROOT/'out/OrbitalI1/test/runClasspath.json').read_text())['value']
    runtime=os.pathsep.join(str(p) for p in [Path(v.split(':',3)[3]) for v in values] if p.exists())
    def save():
        (output/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    def run(cmd,folder,log,negative=None):
        cmd=list(map(str,cmd));receipt['commands'].append(dict(argv=cmd,log=str(folder/log)));save()
        with (folder/log).open('w') as stream:
            result=subprocess.run(cmd,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,
                                  env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'})
        text=(folder/log).read_text()
        if negative:
            if result.returncode==0 or negative not in text:
                raise RuntimeError('negative not rejected: '+str(folder/log))
        elif result.returncode:
            raise RuntimeError('failed: '+str(folder/log))
        return text
    def model(name,entry,top,flags,driver,defines):
        folder=output/name;folder.mkdir()
        run(['java','-cp',runtime,'inorder.'+entry,folder,*flags],folder,'emit.log')
        run([gsim,'--threads=1','--dir='+str(folder),folder/(top+'.fir')],folder,'generate.log')
        cpp=sorted(folder.glob(top+'[0-9]*.cpp'))
        if not cpp:raise RuntimeError('missing GSIM units')
        run([cxx,'-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all',
             *defines,'-I'+str(folder),*cpp,ROOT/'simulator/gsim/harness'/driver,'-o',folder/'run'],folder,'compile.log')
        return folder
    try:
        cases=[('rv64-32k',64,32768,0x80000000,0x10000000,False),
               ('rv64-flow',64,512,0x80000000,0x10000000,True),
               ('rv64-flow-32k',64,32768,0x80000000,0x10000000,True),
               ('rv32',32,512,0x80000000,0x10000000,False),
               ('minimum-128',64,128,0x80000000,0x10000000,False),
               ('maximum-64k',64,65536,0x80000000,0x10000000,False),
               ('constant-tag',64,512,0x4000,0x40,False),
               ('offset-prefix',64,512,0x80000040,0x1800,False),
               ('cross-32-bit',64,512,0xffffffc0,0x180,False)]
        for name,width,size,base,window,flow in cases:
            flags=[width,'--pipeline=fpga8','--timing-cuts','--dcache='+str(size),
                   '--cache-base='+hex(base),'--cache-window='+hex(window)]
            defines=['-DDUT_XLEN='+str(width),'-DCACHE_BYTES='+str(size),
                     '-DCACHE_BASE='+hex(base)+'ULL','-DCACHE_WINDOW='+hex(window)+'ULL']
            if flow:flags+=['--flow-hits'];defines+=['-DCACHE_FLOW=1']
            folder=model(name,'I1CacheTagMain','FiveStageWordCache',flags,'five_stage_cache.cpp',defines)
            text=run([folder/'run'],folder,'positive.log')
            if 'FIVE_STAGE_CACHE_PASS' not in text:raise RuntimeError('missing cache gate')
            run([folder/'run','--inject'],folder,'negative.log','independent byte-memory oracle mismatch')
            receipt['cache_components'][name]=dict(summary=text.strip(),negative_rejected=True)
            print(text.strip(),flush=True)
        payload=Path(parent['coremark_reference']['path']).parent/'payload/coremark.bin'
        if sha(payload)!=parent['payload']['binary_sha256']:raise RuntimeError('payload drift')
        symbols=parent['payload']['symbols']
        for role in ([] if args.raw_only else ['candidate','candidate-hashed']):
            flags=[64,'--pipeline=fpga8','--timing-cuts','--dsp-tiled','--predictor=128',
                   '--icache=32768','--dcache=32768']
            if role=='candidate-hashed':flags+=['--hashed-branch-index']
            folder=model(role+'-cached','I1PerformanceCachedMain','I1PerformanceCachedCore',flags,
                         'five_stage_coremark.cpp',['-DI1_COREMARK_PREDICTION=1'])
            for latency in [1,12]:
                cmd=[folder/'run',payload,symbols['coremark_validation_errors'],symbols['coremark_elapsed_ticks'],
                     symbols['coremark_crcs'],latency]
                text=run(cmd,folder,'coremark-l'+str(latency)+'.log')
                actual=json.loads(re.search(r'MATCHED_COREMARK_PASS (.+)',text)[1])
                actual.update(json.loads(re.search(r'I1_COREMARK_PREDICTION (.+)',text)[1]))
                expected=next(row for row in parent['profiles'][role]['coremark'] if row['memory_latency']==latency)
                for key,value in actual.items():
                    if value!=expected[key]:raise RuntimeError('tag rewrite changed CPU/service '+role+' '+key)
                run([*cmd,'--inject'],folder,'negative-register-l'+str(latency)+'.log','independent register oracle mismatch')
                print(role,'latency',latency,'ROI',actual['roi_ticks'],'unchanged',flush=True)
        for name,digest in frozen.items():
            if sha(ROOT/name)!=digest:raise RuntimeError('source drift: '+name)
        receipt['status']='PASS_I1_CORE300_SHORT_FUNCTIONAL_ONLY'
        receipt['cache_tag_contract']=('independent raw-cache latency/II/ownership; CPU metrics inherited by exact source hashes'
            if args.raw_only else 'identical synchronous latency, II, capacity, window admission and CoreMark metrics')
    except BaseException as error:
        receipt.update(status='FAIL',error=repr(error));raise
    finally:save()
    print(json.dumps(dict(status=receipt['status'],receipt=str(output/'receipt.json'))))


if __name__=='__main__':main()
