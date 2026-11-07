#!/usr/bin/env python3
"""Bind real APLIC sources to a validated clean OoO core and check ISA retirement.

Requires the core's completed system-build full compile/test and source manifests.
Freezes those verified classes before compiling the new wrapper. It never writes
into the core tree, and does not pretend that wrapper compilation recompiles CPU
sources. All prepared classes, source identities and external dependencies are pinned.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

ROOT=Path(__file__).resolve().parents[2]
FIXTURE='simulator/gsim/fixtures/AiaRetiringCoreGsim.scala'
HARNESS='simulator/gsim/harness/aia_retiring_core.cpp'
SELF='simulator/gsim/aia_retiring_core_acceptance.py'

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def tree(path):return {str(p.relative_to(path)):sha(p) for p in path.rglob('*') if p.is_file()}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--core-root',type=Path,required=True)
    p.add_argument('--gsim',type=Path,required=True)
    p.add_argument('--cxx',type=Path,required=True)
    p.add_argument('--link-permit-file',type=Path,help='optional explicit resource-coordination gate before native linking')
    a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    core=a.core_root.resolve();build=core/'system-build'
    record={'status':'RUNNING','commands':[],'scope':'Bare ROM fetch, actual OoO retirement and actual APLIC/IMSIC interrupt routing',
            'translated_fetch_qualified':False,'guest_os_boot_qualified':False,'physical_timing_qualified':False,
            'inputs':{p:sha(ROOT/p) for p in [FIXTURE,HARNESS,SELF]},'tools':{str(p):sha(p) for p in [a.gsim,a.cxx]}}
    def save():(out/'receipt.json').write_text(json.dumps(record,indent=2)+'\n')
    def run(argv,name,negative=False):
        argv=list(map(str,argv));start=time.monotonic()
        with (out/name).open('w') as f:
            r=subprocess.run(argv,cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,timeout=600,
                             env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0','UBSAN_OPTIONS':'halt_on_error=1'})
        record['commands'].append({'argv':argv,'exit':r.returncode,'seconds':time.monotonic()-start,'log':name});save()
        text=(out/name).read_text()
        if negative:assert r.returncode==1 and 'independent APLIC-to-core MSI destination' in text,text[-6000:]
        else:assert r.returncode==0,text[-10000:]
        return text
    try:
        completed=json.loads((build/'commands.json').read_text())
        assert completed[-1]['name']=='test' and all(x['exit']==0 for x in completed),'prepared core qualification is not complete'
        source_pins=json.loads((build/'sources.json').read_text())
        assert source_pins==json.loads((build/'sources-before.json').read_text()),'prepared compilation source drift'
        assert all(Path(k).is_file() and sha(k)==v for k,v in source_pins.items()),'current source does not match prepared core'
        record['core_source_pins']=source_pins
        record['prepared_core_commands']=completed
        # Require the exact validated AIA production implementation from this tree.
        for name in ['ip/interrupt/Aplic.scala','ip/interrupt/Imsic.scala','platform/CommonInterruptFabric.scala',
                     'core/ooo/system/AiaHartControl.scala','core/ooo/system/HypervisorGuestInterrupts.scala']:
            assert sha(core/'src/main/scala'/name)==sha(ROOT/'src/main/scala'/name),name
        originals=build/'classes';class_pins=tree(originals)
        frozen=out/'prepared-core-classes';shutil.copytree(originals,frozen)
        assert tree(frozen)==class_pins
        assert all(sha(originals/k)==v for k,v in class_pins.items()),'core classes changed while freezing'
        record['prepared_core_class_pins']=class_pins
        compile_argv=completed[0]['argv'];prefix=compile_argv[:compile_argv.index('-d')]
        cp=prefix[prefix.index('-classpath')+1]
        dependencies={}
        for name in cp.split(':'):
            path=Path(name);assert path.exists(),name
            dependencies[name]=sha(path) if path.is_file() else tree(path)
        record['external_classpath_pins']=dependencies
        record['scala_tool_pins']={name:sha(name) for name in prefix[prefix.index('-cp')+1].split(':')}
        plugin=next(x[len('-Xplugin:'):] for x in prefix if x.startswith('-Xplugin:'))
        record['scala_plugin_sha256']=sha(plugin)
        classes=out/'wrapper-classes';classes.mkdir()
        prefix[prefix.index('-classpath')+1]=str(frozen)+':'+cp
        save()
        run([*prefix,'-d',classes,ROOT/FIXTURE],'wrapper-compile.log')
        runtime=str(classes)+':'+str(frozen)+':'+cp
        run([compile_argv[0],'-Xmx2g','-XX:ActiveProcessorCount=2','-cp',runtime,'ooo.AiaRetiringCoreGsimMain',out],'emit.log')
        fir=out/'AiaRetiringCoreGsim.fir'
        if fir.stat().st_size%4096==0:fir.write_bytes(fir.read_bytes()+b'\n')
        run([a.gsim,'--threads=1','--dir='+str(out),fir],'generate.log')
        if a.link_permit_file:
            record['status']='WAITING_LINK_PERMIT';save()
            while not a.link_permit_file.exists():time.sleep(1)
            record['status']='RUNNING';save()
        run([a.cxx,'-std=c++20','-O1','-fbracket-depth=4096','-fsanitize=address,undefined','-fno-sanitize-recover=all',
             '-I'+str(out),*sorted(out.glob('AiaRetiringCoreGsim[0-9]*.cpp')),ROOT/HARNESS,'-ldl','-o',out/'run'],'link.log')
        result=run([out/'run'],'run.log');assert 'AIA_OOO_ALL_CHAINS_PASS scenarios=3' in result;print(result,flush=True)
        run([out/'run','--wrong-destination'],'negative.log',True)
        assert record['inputs']=={p:sha(ROOT/p) for p in record['inputs']},'test inputs changed during qualification'
        assert tree(frozen)==class_pins,'frozen core classes changed'
        for name,digest in dependencies.items():assert (sha(name) if Path(name).is_file() else tree(Path(name)))==digest,name
        record['status']='PASS_FINITE_AIA_OOO_CHAIN'
    except BaseException as e:record['status']='FAIL';record['error']=repr(e);raise
    finally:
        record['artifacts']={str(p.relative_to(out)):sha(p) for p in out.rglob('*') if p.is_file() and p.name!='receipt.json'}
        save()
if __name__=='__main__':main()
