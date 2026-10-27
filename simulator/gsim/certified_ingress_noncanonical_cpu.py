#!/usr/bin/env python3
"""Host-only canonical-address gate on existing candidate/control CPU DUT objects.

No Scala elaboration, GSIM generation, global compiler override or DUT build.
Four fixed Sv39 guests require exact cause/tval/mepc, handler retirement, no
noncanonical certificate and exactly sixteen authorized physical reads.
"""
from pathlib import Path
import argparse
import subprocess
import re
import sys
sys.dont_write_bytecode = True
import buffered_return_flow_cpu as cpu

HOST=cpu.common.HERE/'harness/certified_ingress_noncanonical_cpu.cpp'
BASE=HOST.parent/'registered_raw_certified_cpu.cpp'
BASE_SHA='e818bb97bd18bea2c4b4bf4458f8e352dc3182f81723f0dc6fc0fe65f1dfd903'

def inputs(models):
    cpu.need(cpu.sha(BASE)==BASE_SHA,'sealed raw CPU host drift')
    pending=[HOST,BASE,Path(__file__).resolve()]; result={}
    while pending:
        p=pending.pop().resolve()
        if str(p) in result: continue
        result[str(p)]=cpu.sha(p)
        if p.suffix not in ('.h','.cpp'): continue
        for name in re.findall(r'^\s*#include\s+"([^"]+)"',p.read_text(),re.M):
            if name==cpu.raw.TOP+'.h': continue
            child=(p.parent/name).resolve()
            cpu.need(child.is_file() and child.is_relative_to(HOST.parent.resolve()),'unexpected include closure')
            pending.append(child)
    for model in models.values():
        for suffix in ('.h','.fir'):
            p=Path(model['path'])/(cpu.raw.TOP+suffix);result[str(p)]=cpu.sha(p)
    return result

def run(models,tools,out):
    cpu.need(set(models)=={'control','candidate'},'exact cached control/candidate CPU pair required')
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    before=inputs(models)
    report={'schema':'valence-certified-ingress-noncanonical-cpu-v1','status':'RUNNING',
        'new_DUT_compilations':0,'new_host_compilations':0,'inputs':before,'models':{}}
    def save():cpu.save(out/'receipt.json',report)
    save()
    try:
        for label,record in models.items():
            first=record['first_build'];model=Path(record['path']);target=out/label;target.mkdir()
            cpu.need(cpu.row.unchanged_artifacts(first),'cached DUT changed')
            flags=['-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all',
                '-I'+str(model),'-I'+str(HOST.parent)]
            cxx=tools['compiler']['command'];obj=target/'host.o';binary=target/'run'
            cpu.common.run([cxx,*flags,'-fsyntax-only',HOST],log=target/'syntax.log',timeout=180)
            cpu.common.run([cxx,*flags,'-c',HOST,'-o',obj],log=target/'compile.log',timeout=600)
            cpu.common.run([cxx,*flags,*first['DUT_objects'],obj,'-ldl','-o',binary],log=target/'link.log',timeout=600)
            report['new_host_compilations']+=1;save()
            cpu.common.run([binary,'--oracle-only'],env=cpu.base.runtime_env(),log=target/'oracle.log',timeout=30)
            cpu.need('CERTIFIED_INGRESS_NONCANONICAL_ORACLE cases=4' in (target/'oracle.log').read_text(),'fixed oracle missing')
            cpu.common.run([binary],env=cpu.base.runtime_env(),log=target/'run.log',timeout=180)
            log=(target/'run.log').read_text();cpu.base.check_log(log)
            rows=[dict(x.split('=',1) for x in line.split()[1:]) for line in log.splitlines()
                if line.startswith('CERTIFIED_INGRESS_NONCANONICAL_CPU_PASS ')]
            cpu.need(len(rows)==4,'four canonical-address guests missing')
            cpu.need({(r['superpage'],r['high_bit']) for r in rows}=={('0','38'),('0','39'),('1','38'),('1','39')},'guest set differs')
            negative=subprocess.run([str(binary),'--negative-result'],env=cpu.base.runtime_env(),stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,text=True,timeout=180)
            (target/'negative-result.log').write_text(negative.stdout)
            cpu.need(negative.returncode==1 and 'SMOKE_RETIREMENT_RESULT_OBSERVATION_MUTANT_REACHED' in negative.stdout and
                'SMOKE_INDEPENDENT_RESULT' in negative.stdout and 'AddressSanitizer' not in negative.stdout,
                'mcause independent observation mutant not rejected')
            report['models'][label]={'cases':rows,'negative':'EXPECTED_MCAUSE_OBSERVATION_REJECTION',
                'binary_sha256':cpu.sha(binary),'host_object_sha256':cpu.sha(obj)};save()
        report['status']='PASS_CERTIFIED_INGRESS_NONCANONICAL_CPU'
    except BaseException as error:
        report.update(status='FAIL',error=f'{type(error).__name__}: {error}');raise
    finally:
        report['inputs_unchanged']=inputs(models)==before
        report['DUT_artifacts_unchanged']=all(cpu.row.unchanged_artifacts(r['first_build']) for r in models.values())
        if not report['inputs_unchanged'] or not report['DUT_artifacts_unchanged']:report['status']='FAIL_INPUT_OR_DUT_DRIFT'
        report['artifacts']={str(p.relative_to(out)):cpu.sha(p) for p in out.rglob('*') if p.is_file() and p!=out/'receipt.json'}
        save()
    cpu.need(report['status'].startswith('PASS_'),report['status']);return report

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--models-plan',type=Path,required=True)
    ap.add_argument('--tool-receipt',type=Path,required=True);ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--build-run',action='store_true');args=ap.parse_args()
    plan=cpu.read(args.models_plan);tools=cpu.epoch.tool_binding(args.tool_receipt)
    cpu.need(plan['tools']==tools,'model/tool epoch mismatch');inputs(plan['models'])
    if not args.build_run:print('SOURCE_PREFLIGHT_ONLY_NO_BUILD_OR_RUN');return
    print(run(plan['models'],tools,args.output)['status'])
if __name__=='__main__':main()
