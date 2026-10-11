#!/usr/bin/env python3
"""Necessary short permission/backpressure checks for translation-hit FIFO bypass.

Real DataTranslationAdapter/Sv39 service; independent ordered PA/value/fault oracle.
Component proof only. The executing CPU is measured by cpu_sv39_bandwidth.py.
"""
import argparse
from contextlib import redirect_stdout
import json
import os
from pathlib import Path
import re
import subprocess
import run as common
from cpu_sv39_bandwidth import inputs as cpu_inputs, sha

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--tag',required=True);args=ap.parse_args()
    if not re.fullmatch('[A-Za-z0-9_-]+',args.tag):ap.error('unsafe tag')
    out=common.BUILD/('translation-hit-flow-'+args.tag);out.mkdir(parents=True,exist_ok=False)
    def inputs():
        files=[Path(__file__),common.HERE/'harness/dtlb_write_read_reuse.cpp',
            common.HERE/'harness/virtual_load_precheck.cpp',common.HERE/'harness/virtual_load_test_memory.h']
        return {**cpu_inputs(),**{str(p.relative_to(common.ROOT)):sha(p) for p in files}}
    frozen=inputs();state={'status':'RUNNING','source_sha256':frozen,'commands':[],'artifacts':{}}
    def save():(out/'receipt.json').write_text(json.dumps(state,indent=2)+'\n')
    save()
    try:
        gsim,cxx=common.setup(False)
        state['toolchain']={**common.LOCK,'compiler':common.compiler()[1],'gsim_sha256':sha(gsim)}
        with (out/'driver.log').open('x') as trace,redirect_stdout(trace):
            model=common.test(gsim,cxx,out.name+'/adapter','ooo.TranslationHitFlowGsimMain',
                'VirtualLoadPrecheckGsim','dtlb_write_read_reuse.cpp',parameters=('1',),
                defines={'DTLB_ENTRIES':8,'DTLB_WRITE_READ_REUSE':1},timeout=120)
        if 'DTLB_WRITE_READ_REUSE_PASS' not in (model/'test.log').read_text():raise RuntimeError('component anchor absent')
        def command(name,cmd,anchor,negative=False):
            print('+ '+' '.join(map(str,cmd)),flush=True)
            r=subprocess.run(list(map(str,cmd)),cwd=common.ROOT,capture_output=True,text=True,timeout=120,
                env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'})
            text=r.stdout+r.stderr;(out/(name+'.log')).write_text(text)
            state['commands'].append({'name':name,'argv':list(map(str,cmd)),'exit':r.returncode,
                'anchor':anchor,'log_sha256':sha(out/(name+'.log'))});save()
            if (r.returncode==0)==negative or anchor not in text:raise RuntimeError(name+'\n'+text[-3000:])
        command('peek-link',[cxx,'-std=c++20','-O1','-g','-fsanitize=address,undefined',
            '-fno-sanitize-recover=all','-DPRECHECK_ENABLED=1','-DDTLB_ENTRIES=8','-I'+str(model),
            *sorted(model.glob('VirtualLoadPrecheckGsim[0-9]*.cpp')),
            common.HERE/'harness/virtual_load_precheck.cpp','-o',model/'peek-run'],'')
        command('peek-run',[model/'peek-run'],'VIRTUAL_LOAD_PRECHECK_PASS')
        for name,anchor in [('mutate-address','DTLB independent physical operation mismatch'),
                            ('mutate-permission','DTLB independent ordered permission/fault mismatch')]:
            command('negative-'+name,[model/'run','--'+name],anchor,True)
        if inputs()!=frozen:raise RuntimeError('source changed during short permission gate')
        state['artifacts']={str(p.relative_to(out)):sha(p) for p in out.rglob('*') if p.is_file() and p.name!='receipt.json'}
        state['status']='PASS_TRANSLATION_HIT_FLOW_BOUNDARIES';save();print(state['status'])
    except Exception as e:
        state['status']='FAIL';state['error']=str(e);save();raise

if __name__=='__main__':main()
