#!/usr/bin/env python3
"""Bounded actual CommonA1 CPU VM/R1 four-control comparison, not full regression."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import subprocess
import sys

sys.dont_write_bytecode = True
import run as common
import a1_common_cpu_retirement as base
import m2_r1_compile_gate as gate

MAIN = 'soc.core.ooo.CommonA1VmPipelineGsimMain'
TOP = 'CommonA1VmPipelineGsim'
HOST = common.HERE / 'harness/a1_vm_pipeline.cpp'
PROFILES = ('full-candidate', 'full-m2', 'full-r1', 'full-m2-r1')
CASES = (('independent_alu','ram'), ('branches','ram'), ('vm_store_stream','rom'), ('vm_dependency','rom'))
PASS = 'A1_VM_CPU_RETIREMENT_PASS'
SCOPE = {
    'dut': 'actual production CommonA1CpuTile with full RV64GC/ROB16/PRF48/LSU4/DTLB16/32KiB L1I+L1D',
    'controls': 'baseline, registered demand translation only, circular fetch payload only, combined',
    'guests': 'two unchanged RAM supply/branch guests; two raw-byte MPRV/MPP=S Sv39 ordinary-store/readback guests',
    'oracle': 'pre-execute raw instruction bytes, independent CSR/PMP/page-table walk and architectural memory; exact retirement/final GPR/trap',
    'service': 'instruction A continuously ready up to16 owners, D latency3/II1; native PTE latency3; legal whole-line L1D Grant latency3 plus E acknowledgement',
    'limitations': ['ordinary stores remain serial/low MLP; not memory bandwidth proof',
        'one supervisor data page and one cache line, A/D preset, no replacement or permissions fault workload',
        'full resources retained but no FP guest, full ISA compliance, Board/CDC/Linux or timing qualification',
        'acceptedPrefixValidation=false is the actual selected configuration, future true specialization not covered',
        'observation negatives do not mutate RTL', 'P1 tools were rebuilt at pinned revisions, not binary-identical GSIM/NEMU'],
}


def inputs():
    found = base.source_inputs()
    for name in ('src/test/scala/platform/CommonA1VmPipelineGsim.scala',
                 'simulator/gsim/harness/a1_vm_pipeline.cpp', 'simulator/gsim/a1_vm_pipeline.py',
                 'simulator/gsim/m2_r1_compile_gate.py'):
        found[name] = base.sha(common.ROOT / name)
    return dict(sorted(found.items()))


def parse(path, prefix):
    text = path.read_text(); base.check_log(text)
    if text.splitlines().count(PASS) != 1:
        raise RuntimeError('missing exact complete CPU PASS marker')
    rows = [base.read_json(line[len(prefix):]) for line in text.splitlines() if line.startswith(prefix)]
    if [(r['name'],r['placement']) for r in rows] != list(CASES):
        raise RuntimeError('not the exact four fixed guest cases')
    return rows


def negative(binary, flag, marker, rejection, log):
    with log.open('x') as stream:
        result = subprocess.run([str(binary),flag],stdout=stream,stderr=subprocess.STDOUT,
                                timeout=180,env=base.runtime_env())
    text=log.read_text();base.check_log(text)
    if result.returncode != 1 or text.count(marker) != 1 or rejection not in text or PASS in text:
        raise RuntimeError('negative failed exact sampled mutation/rejection contract: '+flag)
    return {'flag':flag,'returncode':result.returncode,'marker':marker,'rejection':rejection,'log_sha256':base.sha(log)}


def parameter_check(effective):
    baseline=effective['full-candidate']
    result={}
    for name in PROFILES:
        m2=name in ('full-m2','full-m2-r1');r1=name in ('full-r1','full-m2-r1')
        result[name]={}
        for kind in ('config','core'):
            old=baseline[kind];new=effective[name][kind]
            if old.keys()!=new.keys(): raise RuntimeError('four-control parameter schema drift')
            actual={k:[old[k],new[k]] for k in old if old[k]!=new[k]}
            expected={}
            if m2:
                expected['registeredDataTranslation']=['false','true']
                if kind=='config':expected['translationHitFlow']=['true','false']
            if r1:expected['circularFetchPayload']=['false','true']
            if actual!=expected:raise RuntimeError(f'{name}/{kind} unexpected effective delta: {actual}')
            result[name][kind]=actual
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag',required=True)
    parser.add_argument('--gsim',type=Path,required=True)
    parser.add_argument('--baseline',type=Path,required=True,help='retained P1 leaf receipt, never rerun')
    parser.add_argument('--build-run',action='store_true')
    args=parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+',args.tag):parser.error('fresh safe tag required')
    before=inputs()
    if not args.build_run:
        print(json.dumps({'status':'PREFLIGHT_ONLY','profiles':PROFILES,'cases':CASES,'inputs':len(before),'scope':SCOPE},indent=2));return
    out=common.BUILD/args.tag;out.mkdir(parents=True,exist_ok=False)
    resource.setrlimit(resource.RLIMIT_CORE,(0,0));gate.install()
    tools=base.tool_binding(True);cxx=tools['compiler']['command']
    if args.gsim.resolve()!=Path(tools['gsim']['path']).resolve():raise RuntimeError('must use bound pinned GSIM')
    baseline=json.loads(args.baseline.read_text())
    if baseline['status']!='PASS_P1_OWNER_CONTRACT_AND_EXACT_A2_SUPPLY':raise RuntimeError('unexpected P1 baseline receipt')
    report={'schema':'m2-r1-common-a1-vm-cpu-v1','status':'RUNNING','source_revision':base.git(common.ROOT,'rev-parse','HEAD').strip(),
            'inputs_before':before,'tools_before':tools,'baseline_sha256':base.sha(args.baseline),'scope':SCOPE,
            'cases':{},'stages':{},'effective_parameters':{},'negative_controls':{}}
    base.save_receipt(out,report)
    try:
        for profile in PROFILES:
            if inputs()!=before:raise RuntimeError('source drift before model '+profile)
            model=common.test(args.gsim,cxx,args.tag+'/'+profile,MAIN,TOP,HOST.name,
                              parameters=(profile,),defines={},timeout=180)
            report['cases'][profile]=parse(model/'test.log','A1_VM_CPU_METRIC ')
            report['stages'][profile]=parse(model/'test.log','A1_VM_STAGE_METRIC ')
            report['effective_parameters'][profile]={kind:base.read_json((model/file).read_text())
                for kind,file in [('config','effective-config.json'),('core','effective-parameters.json')]}
            report['negative_controls'][profile]=[]
            # Two negatives on the combined model reuse its exact newly built DUT.
            if profile=='full-m2-r1':
                for flag,marker,rejection in (
                    ('--inject-retirement-data','A1_RETIREMENT_NEGATIVE_REACHED','data pc='),
                    ('--inject-stage-pa','A1_VM_STAGE_NEGATIVE_REACHED','independent store stage PA/data oracle mismatch')):
                    report['negative_controls'][profile].append(negative(model/'run',flag,marker,rejection,model/(flag[2:]+'.log')))
            base.save_receipt(out,report)
        report['parameter_changes']=parameter_check(report['effective_parameters'])
        oldparams=baseline['cpu']['effectiveParameters']
        allowances={}
        for kind in ('config','core'):
            old=oldparams[kind];new=report['effective_parameters']['full-candidate'][kind]
            added={k:new[k] for k in new.keys()-old.keys()}
            changed={k:[old[k],new.get(k)] for k in old if new.get(k)!=old[k]}
            if added!={'registeredDataTranslation':'false','circularFetchPayload':'false'} or changed:
                raise RuntimeError('baseline differs from P1 beyond two explicit false defaults: '+str((kind,added,changed)))
            allowances[kind]=added
        report['p1_parameter_new_default_fields']=allowances

        # R1 alone is a storage refactoring with exact matched-cycle semantics.
        for a,b in [('full-candidate','full-r1'),('full-m2','full-m2-r1')]:
            if report['cases'][a]!=report['cases'][b]:raise RuntimeError('R1 changed a matched CPU metric: '+a+' vs '+b)
            for x,y in zip(report['stages'][a],report['stages'][b]):
                diff={k:[x.get(k),y.get(k)] for k in set(x)|set(y) if x.get(k)!=y.get(k)}
                if diff!={'circular_payload':[0,1]}:raise RuntimeError('R1 changed stage observations: '+str(diff))
        oldrows={(r['name'],r['placement']):r for r in baseline['cpu']['cases']}
        # Exact historical old guest metrics only; new VM workloads have no old result.
        for row in report['cases']['full-candidate'][:2]:
            if row!=oldrows[row['name'],row['placement']]:raise RuntimeError('fixed old guest changed P1 metrics')
        report['p1_exact_old_cases']=2
        report['comparison']=[{'name':a['name'],'placement':a['placement'],'baseline_work':a['work_cycles'],
                              'm2_work':b['work_cycles'],'delta_m2_work':b['work_cycles']-a['work_cycles'],
                              'baseline_roi':a['roi_cycles'],'m2_roi':b['roi_cycles'],
                              'delta_m2_roi':b['roi_cycles']-a['roi_cycles'],'retired':a['retired']}
                             for a,b in zip(report['cases']['full-candidate'],report['cases']['full-m2'])]
        report['status']='PASS_BOUNDED_M2_R1_ACTUAL_CPU_FOUR_CONTROL'
    except BaseException as error:
        report.update(status='FAIL',failure=f'{type(error).__name__}: {error}');raise
    finally:
        report['inputs_after']=inputs();report['inputs_unchanged']=report['inputs_after']==before
        report['tools_after']=base.tool_binding(True);report['tools_unchanged']=report['tools_after']==tools
        if not report['inputs_unchanged'] or not report['tools_unchanged']:report['status']='FAIL_INPUT_DRIFT'
        report['artifacts_sha256']={str(p.relative_to(out)):base.sha(p) for p in sorted(out.rglob('*'))
                                    if p.is_file() and p.name not in ('receipt.json','receipt.json.tmp')}
        base.save_receipt(out,report)
    if not report['status'].startswith('PASS_'):raise RuntimeError(report['status'])
    print(json.dumps({'status':report['status'],'receipt':str(out/'receipt.json'),'comparison':report['comparison']},indent=2))


if __name__=='__main__':main()
