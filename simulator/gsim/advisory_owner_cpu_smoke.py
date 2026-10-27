#!/usr/bin/env python3
"""Host-only AMO/LRSC/FP CPU smoke on the two already-qualified cached DUTs.

No new Scala, GSIM generation or DUT object compilation. The tile has no
AtomicMemory: this validates native atomic transport and CPU ISA/owner/handoff
behavior against a fixed independent host service. Actual subordinate atomic
phases are a separate real-component qualification, never claimed here.
"""
import argparse
from pathlib import Path
import re
import sys
sys.dont_write_bytecode = True
import buffered_return_flow_cpu as cpu

R,need,sha=cpu.common.ROOT,cpu.need,cpu.sha
HOST=R/'simulator/gsim/harness/advisory_owner_cpu_smoke.cpp'
BASE_HOST=HOST.parent/'registered_raw_certified_cpu.cpp'
BASE_HOST_SHA='e818bb97bd18bea2c4b4bf4458f8e352dc3182f81723f0dc6fc0fe65f1dfd903'


def inputs(models):
    need(sha(BASE_HOST)==BASE_HOST_SHA,'immutable raw instruction transport host changed')
    pending=[HOST,BASE_HOST,Path(__file__).resolve()]
    result={}
    while pending:
        p=pending.pop()
        if str(p) in result:continue
        result[str(p)]=sha(p)
        if p.suffix not in ('.h','.cpp'):continue
        for name in re.findall(r'^\s*#include\s+"([^"]+)"',p.read_text(),re.M):
            if name==cpu.raw.TOP+'.h':continue
            child=p.parent/name
            need(child.is_file() and child.resolve().is_relative_to(HOST.parent.resolve()),'unexpected quoted source closure')
            pending.append(child.resolve())
    for record in models.values():
        model=Path(record['path'])
        for suffix in ('.h','.fir'):
            p=model/(cpu.raw.TOP+suffix);result[str(p)]=sha(p)
    return result


def run(models,tools,out):
    need(set(models)=={'owner_only','combined'},'exact two existing candidate models required')
    out=Path(out).resolve();out.mkdir(parents=True,exist_ok=False)
    before=inputs(models)
    report={'schema':'valence-advisory-owner-cpu-native-atomic-fp-smoke-v1','status':'RUNNING',
        'scope':'CPU ISA/ordered owners/native atomic transport/FP handoff; not tile-internal AtomicMemory phases',
        'oracle':'fixed raw encodings and independently calculated register/atomic/FP binary64 expected values, not NEMU',
        'new_DUT_compilations':0,'new_host_compilations':0,'inputs':before,'tools':tools,'models':{}}
    cpu.save(out/'receipt.json',report)
    try:
        for label,record in models.items():
            model=Path(record['path']);first=record['first_build']
            need(cpu.row.unchanged_artifacts(first),'cached DUT binding changed')
            target=out/label;target.mkdir()
            flags=['-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all',
                   '-I'+str(model),'-I'+str(HOST.parent)]
            cxx=tools['compiler']['command'];obj=target/'host.o';binary=target/'run'
            cpu.common.run([cxx,*flags,'-fsyntax-only',HOST],log=target/'syntax.log',timeout=180)
            cpu.common.run([cxx,*flags,'-c',HOST,'-o',obj],log=target/'compile.log',timeout=600)
            cpu.common.run([cxx,*flags,*first['DUT_objects'],obj,'-ldl','-o',binary],log=target/'link.log',timeout=600)
            report['new_host_compilations']+=1
            cpu.common.run([binary,'--oracle-only'],env=cpu.base.runtime_env(),log=target/'oracle.log',timeout=30)
            need('ADVISORY_OWNER_SMOKE_ORACLE' in (target/'oracle.log').read_text(),'pre-DUT fixed oracle construction missing')
            cpu.common.run([binary],env=cpu.base.runtime_env(),log=target/'run.log',timeout=180)
            log=(target/'run.log').read_text();cpu.base.check_log(log)
            rows=[dict(x.split('=',1) for x in line.split()[1:]) for line in log.splitlines()
                  if line.startswith('ADVISORY_OWNER_CPU_SMOKE_PASS ')]
            need(len(rows)==1 and all(v.isdigit() for v in rows[0].values()),'unique CPU smoke result schema')
            metrics={k:int(v) for k,v in rows[0].items()}
            need(metrics['atomics']==metrics['atomic_replies']==11 and metrics['fp_retired']==8 and
                 metrics['integer_starts']==metrics['integer_completes'] and
                 metrics['physical_requests']==metrics['physical_replies'] and metrics['fp_epoch_cycles']>0,
                 'missing atomic/FP/owner complete coverage')
            # Only the first AMO retirement observation is corrupted (not the
            # memory service or DUT response). The architectural
            # checker must reject, not an unrelated sanitizer or protocol crash.
            import subprocess
            negative=subprocess.run([str(binary),'--negative-result'],env=cpu.base.runtime_env(),
                                    stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=180)
            (target/'negative-result.log').write_text(negative.stdout)
            need(negative.returncode==1 and 'SMOKE_RETIREMENT_RESULT_OBSERVATION_MUTANT_REACHED' in negative.stdout and
                 'ADVISORY_OWNER_CPU_SMOKE_FAIL SMOKE_INDEPENDENT_RESULT' in negative.stdout and
                 'AddressSanitizer' not in negative.stdout and 'runtime error:' not in negative.stdout,
                 'independent architectural negative control not reached')
            report['models'][label]={'metrics':metrics,'negative':'EXPECTED_RETIREMENT_OBSERVATION_MUTANT_REJECTION',
                'binary_sha256':sha(binary),'object_sha256':sha(obj),'DUT_artifacts_unchanged':cpu.row.unchanged_artifacts(first)}
            cpu.save(out/'receipt.json',report)
        report['status']='PASS_BOUNDED_CPU_NATIVE_ATOMIC_FP_SMOKE'
    except BaseException as error:
        report.update(status='FAIL',error=f'{type(error).__name__}: {error}');raise
    finally:
        report['inputs_unchanged']=inputs(models)==before
        report['DUT_artifacts_unchanged']=all(cpu.row.unchanged_artifacts(m['first_build']) for m in models.values())
        if not report['inputs_unchanged'] or not report['DUT_artifacts_unchanged']:report['status']='FAIL_INPUT_OR_DUT_DRIFT'
        report['artifacts']={str(p.relative_to(out)):sha(p) for p in out.rglob('*') if p.is_file() and p!=out/'receipt.json'}
        cpu.save(out/'receipt.json',report)
    need(report['status'].startswith('PASS_'),report['status'])
    return report


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--models-plan',type=Path,required=True)
    ap.add_argument('--tool-receipt',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--build-run',action='store_true')
    args=ap.parse_args();plan=cpu.read(args.models_plan);tools=cpu.epoch.tool_binding(args.tool_receipt)
    need(plan['tools']==tools,'model plan tool epoch differs')
    approved=Path(plan['cpu_receipt'])
    need(sha(approved)==plan['cpu_receipt_sha256'] and cpu.read(approved)['status'].startswith('PASS_'),
         'original four guests and mandatory Bare CPU gate must pass first')
    inputs(plan['models'])
    if not args.build_run:print('SMOKE_PREFLIGHT_ONLY_NO_BUILD_OR_RUN');return
    print(run(plan['models'],tools,args.output)['status'])


if __name__=='__main__':main()
