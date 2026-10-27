#!/usr/bin/env python3
"""Bounded real DTA and LSU/StoreBuffer/FP chain, after one frozen public compile.
No operation beyond source derivation unless --build-run. Failures never overwritten.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
sys.dont_write_bytecode=True
import run as common
import gsim_initialization_epoch as epoch
import certified_ingress_dta_host as dta
import certified_ingress_chain_host as chain
import ordered_owner_chain as old_chain
from registered_raw_certified_cpu import need,sha,read

def inputs():
    files=list((common.ROOT/'src/main/scala').rglob('*.scala'))+list((common.ROOT/'src/test/scala').rglob('*.scala'))
    files += list(common.HERE.glob('certified_ingress*.py'))+list((common.HERE/'harness').glob('certified_ingress*'))
    files += [common.HERE/'harness/registered_raw_certified_flow.cpp',common.HERE/'harness/ordered_owner_chain.cpp',
              common.HERE/'guarded_natural_dta_host.py',common.HERE/'harness/guarded_natural_dta_cases.inc',
              common.HERE/'harness/virtual_load_test_memory.h',common.HERE/'m2_data_translation/oracle.h',
              common.HERE/'harness/gsim_model_storage.h',common.HERE/'run.py',common.ROOT/'build.mill']
    return {str(p.relative_to(common.ROOT)):sha(p) for p in sorted(set(files))}

def save(path,value):path.write_text(json.dumps(value,indent=2)+'\n')

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tag',required=True);ap.add_argument('--build-run',action='store_true')
    ap.add_argument('--compile-receipt',type=Path);ap.add_argument('--tool-receipt',type=Path)
    a=ap.parse_args();need(re.fullmatch(r'[A-Za-z0-9_-]+',a.tag),'safe fresh tag')
    hosts={'dta':dta.derive(),'chain':chain.derive()};before=inputs()
    if not a.build_run:print('PASS_CERTIFIED_INGRESS_SOURCE_DERIVATION_ONLY');return
    need(a.compile_receipt and a.tool_receipt,'frozen compile and qualified tool receipts required')
    tools=epoch.tool_binding(a.tool_receipt)
    spec=importlib.util.spec_from_file_location('scala_gate',common.ROOT/'fpga/common/scala_compile_receipt.py')
    gate=importlib.util.module_from_spec(spec);spec.loader.exec_module(gate)
    compiled=gate.verify_receipt(a.compile_receipt,common.ROOT)
    cp=os.pathsep.join(compiled['runClasspathEntries'])
    out=common.BUILD/a.tag;out.mkdir(parents=True,exist_ok=False)
    r={'schema':'valence-certified-ingress-components-v1','status':'RUNNING','inputs':before,'tool_epoch':tools,
       'compile_receipt_sha256':sha(a.compile_receipt),'tests':{},'negative_controls':[],'new_DUT_builds':0}
    def seal():save(out/'receipt.json',r)
    seal()
    try:
        for kind in ('dta','chain'):
            for enabled in (0,1):
                label=kind+'-'+str(enabled);target=out/label;target.mkdir()
                top='CertifiedIngressDtaGsim' if kind=='dta' else 'CertifiedIngressChainGsim'
                arg=('candidate' if enabled else 'control') if kind=='dta' else str(enabled)
                common.run([tools['java']['path'],'-cp',cp,'ooo.'+top+'Main',target,arg],log=target/'elaborate.log',timeout=180)
                common.run([tools['gsim']['path'],'--threads=1','--dir='+str(target),target/(top+'.fir')],log=target/'generate.log',timeout=600)
                host=target/'host.cpp';host.write_text(hosts[kind])
                flags=['-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all',
                       '-I'+str(target),'-I'+str(common.HERE/'harness'),
                       '-DCERTIFIED_LOAD_INGRESS='+str(enabled),'-DCERTIFIED_INGRESS_ENABLED='+str(enabled)]
                cxx=tools['compiler']['command'];sources=sorted(target.glob(top+'[0-9]*.cpp'));need(sources,'actual generated sources absent')
                common.run([cxx,*flags,'-fsyntax-only',host],log=target/'syntax.log',timeout=180)
                objects=[]
                for source in [*sources,host]:
                    obj=target/(source.stem+'.o');common.run([cxx,*flags,'-c',source,'-o',obj],log=target/(source.stem+'-compile.log'),timeout=600);objects.append(obj)
                binary=target/'run';common.run([cxx,*flags,*objects,'-ldl','-o',binary],log=target/'link.log',timeout=600)
                r['new_DUT_builds']+=1;seal()
                common.run([binary],env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'},log=target/'test.log',timeout=180)
                log=(target/'test.log').read_text();marker='CERTIFIED_INGRESS_'+kind.upper()+'_PASS'
                need(marker in log,'missing full component completion '+label)
                negatives=([('--inject-pa','independent physical PA/order mismatch'),('--inject-data','independent ordered response data mismatch'),
                            ('--inject-fault','independent ordered fault classification mismatch'),('--inject-hint','independent captured next-line permission mismatch')]
                           if kind=='dta' else [*old_chain.NEGATIVES.items(),('source','final payload not associated with accepted fast source')])
                for option,diagnostic in negatives:
                    result=subprocess.run([str(binary),option],env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'},stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=180)
                    path=target/('negative-'+option.lstrip('-')+'.log');path.write_text(result.stdout)
                    need(result.returncode==1 and diagnostic in result.stdout and not any(x in result.stdout for x in ('AddressSanitizer','runtime error:')),
                         'negative did not reach intended oracle '+label+option)
                    r['negative_controls'].append({'model':label,'option':option,'diagnostic':diagnostic,'log_sha256':sha(path)})
                if kind=='dta':
                    result=subprocess.run([str(binary),'--force-undrained-flush'],env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'},stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=180)
                    path=target/'negative-undrained-flush.log';path.write_text(result.stdout)
                    need(result.returncode!=0 and 'INJECT REGISTERED_RAW_CERTIFIED_FLOW undrained flush' in result.stdout and
                         'must drain accepted prechecked loads before changing authorization' in result.stdout,
                         'undrained context negative missed actual authorization assertion')
                    r['negative_controls'].append({'model':label,'option':'--force-undrained-flush','log_sha256':sha(path)})
                r['tests'][label]={'status':'PASS','log_sha256':sha(target/'test.log'),'binary_sha256':sha(binary)};seal()
        gate.verify_receipt(a.compile_receipt,common.ROOT)
        r['status']='PASS_CERTIFIED_INGRESS_COMPONENTS'
    except BaseException as error:r.update(status='FAIL',error=f'{type(error).__name__}: {error}');raise
    finally:
        r['inputs_unchanged']=inputs()==before
        if not r['inputs_unchanged']:r['status']='FAIL_SOURCE_DRIFT'
        r['artifacts']={str(p.relative_to(out)):sha(p) for p in out.rglob('*') if p.is_file() and p.name!='receipt.json'};seal()
    print(r['status'])
if __name__=='__main__':main()
