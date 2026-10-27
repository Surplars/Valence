#!/usr/bin/env python3
"""One actual checked-flow CPU candidate; retain the exact published M3 control."""
import argparse
from collections import Counter, deque
import difflib
import hashlib
import json
from pathlib import Path
import re
import resource
import subprocess
import sys

sys.dont_write_bytecode = True
import run as common
import a1_common_cpu_retirement as base
import m2_r1_compile_gate as gate

TOP = 'CommonA1VmPipelineGsim'
MAIN = 'soc.core.ooo.CombinedCheckedFlowCpuGsimMain'
HOST = common.HERE / 'harness/combined_checked_flow_cpu.cpp'
OLD_HOST = common.HERE / 'harness/m3_completed_canonical_cpu.cpp'
BASELINE_SHA = '045aea52acdd12813b491d6327a7492aa38b83dba9c791001e7458461122d371'
OLD_HOST_SHA = '69f86bee68fa5182e8253cc0310418b4d830283eac64f1cce7f302df5c4fa674'
TRACE = common.BUILD / 'm3-dependency-trace-20261024-r2'
TRACE_MANIFEST_SHA = 'ee54278c8303d9134700831682e58f40d822dbf02ea2e01b4ff5167674cbe3c4'
CASES = ('vm_store_stream', 'vm_dependency')
PASS = 'CHECKED_FLOW_CPU_PASS'
SCOPE = {
    'DUT': 'actual full-r1-m3-checked-flow CommonA1CpuTile; full RV64GC/VM/PMP/cache resources retained',
    'matched': 'exact original two 233-retirement M3 VM guests and fixed legal external service law',
    'baseline_reuse': 'fresh default-false M3 wrapper FIR must match retained M3 FIR after source annotations only',
    'owner_observer': 'actual LSU start full token -> selected actual request slot -> ordered DTA ingress/checked/physical/reply',
    'negative_scope': 'two sampled observation mutations, not RTL mutants',
    'limits': ['serial ordinary stores; no DDR bandwidth or Fmax claim',
               'component actual-DTA A/B covers spill/permission/epoch/ordering separately',
               'no NEMU/SoC/CDC/native/STA/new board qualification; acceptedPrefixValidation remains false'],
}


def inputs():
    found = base.source_inputs()
    for name in ('src/test/scala/platform/CommonA1VmPipelineGsim.scala',
                 'src/test/scala/platform/M3CompletedCanonicalCpuGsim.scala',
                 'src/test/scala/platform/CombinedCheckedFlowCpuGsim.scala',
                 'simulator/gsim/harness/a1_vm_pipeline.cpp',
                 'simulator/gsim/harness/m3_completed_canonical_cpu.cpp',
                 'simulator/gsim/harness/combined_checked_flow_cpu.cpp',
                 'simulator/gsim/combined_checked_flow_cpu.py',
                 'simulator/gsim/m2_r1_compile_gate.py'):
        found[name] = base.sha(common.ROOT / name)
    return dict(sorted(found.items()))


def effective(directory):
    return {kind: base.read_json((directory / name).read_text()) for kind, name in
            [('config', 'effective-config.json'), ('core', 'effective-parameters.json')]}


def compare_params(old, new, enabled):
    result = {}
    for kind in ('config', 'core'):
        added = {k:new[kind][k] for k in new[kind].keys()-old[kind].keys()}
        changed = {k:[v,new[kind].get(k)] for k,v in old[kind].items() if new[kind].get(k)!=v}
        expected = {'precheckedDataRequestFlow':['false','true']} if enabled else {}
        if added != {'combinedCheckedDataFlow':str(enabled).lower()} or changed != expected:
            raise RuntimeError(f'unexpected {kind} profile delta: {added}, {changed}')
        result[kind] = {'added':added,'changed':changed}
    return result


def baseline_binding(path, current_inputs, tools, report):
    if base.sha(path) != BASELINE_SHA: raise RuntimeError('published M3 receipt bytes changed')
    old = json.loads(path.read_text())
    if old['status'] != 'PASS_BOUNDED_M3_ACTUAL_CPU_AND_ALIAS' or not old['inputs_unchanged'] or not old['tools_unchanged']:
        raise RuntimeError('invalid historical M3 baseline')
    if tools != old['tools_after']: raise RuntimeError('historical/current pinned tool identity differs')
    bound = {str(path): BASELINE_SHA}
    for name, expected in old['artifacts_sha256'].items():
        if name.startswith('full-r1-m3/'):
            source = path.parent/name
            if base.sha(source) != expected: raise RuntimeError('retained M3 artifact changed: '+name)
            bound[str(source)] = expected
    for name in ('src/test/scala/platform/CommonA1VmPipelineGsim.scala',
                 'src/test/scala/platform/M3CompletedCanonicalCpuGsim.scala',
                 'simulator/gsim/harness/a1_vm_pipeline.cpp',
                 'simulator/gsim/harness/m3_completed_canonical_cpu.cpp'):
        if current_inputs[name] != old['inputs_before'][name]: raise RuntimeError('immutable baseline fixture/host changed: '+name)
    if base.sha(OLD_HOST) != OLD_HOST_SHA or base.sha(TRACE/'manifest.json') != TRACE_MANIFEST_SHA:
        raise RuntimeError('immutable published host/passive trace changed')
    trace = json.loads((TRACE/'manifest.json').read_text())
    if trace['status'] != 'PASS_TRACE_WITH_EXACT_PUBLISHED_M3_METRICS' or not trace['allOriginalOraclesPassed'] or not trace['unchangedBoundFiles'] or trace['exactMetricFieldsCompared'] != 126:
        raise RuntimeError('historical passive trace missing exact original-oracle binding')
    for name, expected in trace['boundFiles'].items():
        source = common.ROOT/name
        if base.sha(source) != expected: raise RuntimeError('passive trace model/source binding changed: '+name)
        bound[str(source)] = expected
    for name, key in [('trace.log','traceLogSha256'),('trace.cpp','traceHostSha256'),('analysis.json','analysisSha256')]:
        if base.sha(TRACE/name) != trace[key]: raise RuntimeError('passive trace leaf changed: '+name)
        bound[str(TRACE/name)] = trace[key]
    bound[str(TRACE/'manifest.json')] = TRACE_MANIFEST_SHA
    report['baseline_binding'] = {'receipt':str(path),'receipt_sha256':BASELINE_SHA,'artifacts':bound,
        'source_revision':old['source_revision'],'historical_tools_exact':True,'trace_metric_fields_exact':126,
        'historical_current_source_differences':{k:[old['inputs_before'].get(k),current_inputs.get(k)]
            for k in sorted(set(old['inputs_before'])|set(current_inputs)) if old['inputs_before'].get(k)!=current_inputs.get(k)}}
    queues = {n:deque() for n in CASES}; hist = {n:{k:Counter() for k in ('store','raw_load','prechecked')} for n in CASES}
    owners = {n:[] for n in CASES}
    for line in (TRACE/'trace.log').read_text().splitlines():
        if not line.startswith(('M3_REQUEST ','M3_PHYSICAL ')): continue
        row = dict(x.split('=',1) for x in line.split()[1:]); name=row['guest']
        if line.startswith('M3_REQUEST '): queues[name].append(row)
        else:
            if not queues[name]: raise RuntimeError('trace physical owner underflow')
            request=queues[name].popleft()
            if row['write'] != request['write']: raise RuntimeError('trace ordered type mismatch')
            kind='prechecked' if int(request['prechecked']) else ('store' if int(request['write']) else 'raw_load')
            latency=int(row['cycle'])-int(request['cycle']);hist[name][kind][latency]+=1
            owners[name].append({'ordinal':len(owners[name]),'kind':kind,'upstream':int(request['cycle']),
                'physical':int(row['cycle']),'latency':latency,'upstream_address':int(request['va']),'physical_address':int(row['pa'])})
    for name,n in zip(CASES,(7,55)):
        if queues[name] or hist[name] != {'store':Counter({24:1,2:48}),'raw_load':Counter({2:2}),'prechecked':Counter({3:n})}:
            raise RuntimeError('historical per-request stage-latency witness differs')
    report['baseline_latency']={n:{k:dict(v) for k,v in h.items()} for n,h in hist.items()}
    report['baseline_latency_owners']=owners
    return old


def program_gate(out,cxx):
    atext=OLD_HOST.read_text();btext=HOST.read_text()
    # Bind the complete independent ISA/program/PMP/PTE and manager definitions,
    # plus every drive/step/accept/reply action, not only guest instruction bytes.
    if atext.split('class Run {',1)[0]!=btext.split('class Run {',1)[0]:
        raise RuntimeError('immutable independent oracle/service definitions changed')
    for start,end in [('    void drive(', '    bool tick('),('    bool tick(', '\npublic:')]:
        a=atext[atext.index(start):atext.index(end,atext.index(start)+len(start))]
        b=btext[btext.index(start):btext.index(end,btext.index(start)+len(start))]
        b=b.replace('        flowObserve();\n','')
        if a!=b:raise RuntimeError('original CPU external drive/service/retirement flow changed')
    flags=['-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all','-DA1_VM_ORACLE_ONLY=1']
    for source,name in [(OLD_HOST,'old-oracle'),(HOST,'new-oracle')]:
        binary=out/name
        common.run([cxx,*flags,source,'-o',binary],log=out/(name+'-compile.log'))
        common.run([binary,'--dump-programs'],env=base.runtime_env(),log=out/(name+'-programs.log'))
    a=(out/'old-oracle-programs.log').read_bytes();b=(out/'new-oracle-programs.log').read_bytes()
    if a!=b or len(a.splitlines())!=3:raise RuntimeError('published raw program/setup bytes changed')
    common.run([out/'new-oracle','--oracle-only'],env=base.runtime_env(),log=out/'oracle.log')
    return {'oracle_and_external_service_source_exact':True,'published_all_three_generator_bytes_exact':True,'actual_cpu_cases':list(CASES),
            'old_host_sha256':OLD_HOST_SHA,'program_dump_sha256':hashlib.sha256(a).hexdigest()}


def parse(log,prefix):
    text=log.read_text();base.check_log(text)
    if text.splitlines().count(PASS)!=1:raise RuntimeError('missing exact checked-flow CPU PASS')
    rows=[base.read_json(line[len(prefix):]) for line in text.splitlines() if line.startswith(prefix)]
    if [r['name'] for r in rows]!=list(CASES):raise RuntimeError('not exactly two matched bounded CPU guests')
    return rows


def negative(model,flag,marker,diagnostic):
    log=model/(flag[2:]+'.log')
    with log.open('x') as stream:
        result=subprocess.run([str(model/'run'),flag],stdout=stream,stderr=subprocess.STDOUT,timeout=180,env=base.runtime_env())
    text=log.read_text();base.check_log(text)
    if result.returncode!=1 or text.count(marker)!=1 or diagnostic not in text or PASS in text:
        raise RuntimeError('negative missing exact sampled rejection: '+flag)
    return {'flag':flag,'returncode':result.returncode,'marker':marker,'diagnostic':diagnostic,'log_sha256':base.sha(log)}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--tag',required=True);p.add_argument('--gsim',type=Path,required=True)
    p.add_argument('--baseline',type=Path,default=common.BUILD/'m3-common-cpu-20261024-r2/receipt.json')
    p.add_argument('--build-run',action='store_true');args=p.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+',args.tag):p.error('fresh safe tag required')
    before=inputs()
    if not args.build_run:
        print(json.dumps({'status':'PREFLIGHT_ONLY','inputs':len(before),'scope':SCOPE},indent=2));return
    out=common.BUILD/args.tag;out.mkdir(parents=True,exist_ok=False)
    resource.setrlimit(resource.RLIMIT_CORE,(0,0));gate.install()
    tools=base.tool_binding(True);cxx=tools['compiler']['command']
    if args.gsim.resolve()!=Path(tools['gsim']['path']).resolve():raise RuntimeError('pinned GSIM required')
    report={'schema':'combined-checked-flow-cpu-v1','status':'RUNNING',
        'source_revision':base.git(common.ROOT,'rev-parse','HEAD').strip(),'inputs_before':before,'tools_before':tools,'scope':SCOPE}
    base.save_receipt(out,report)
    try:
        old=baseline_binding(args.baseline,before,tools,report)
        report['program_gate']=program_gate(out,cxx)
        control=out/'baseline-structural-gate';control.mkdir()
        common.run(['mill','-i','IonSoC.test.runMain','soc.core.ooo.M3CompletedCanonicalCpuGsimMain',control],log=control/'elaborate.log')
        report['baseline_parameters']=compare_params(old['effective_parameters'],effective(control),False)
        oldfir=args.baseline.parent/'full-r1-m3'/f'{TOP}.fir';newfir=control/f'{TOP}.fir'
        a=re.sub(rb' @\[[^\]\n]*\]',b'',oldfir.read_bytes());b=re.sub(rb' @\[[^\]\n]*\]',b'',newfir.read_bytes())
        (control/'normalized.diff').write_text(''.join(difflib.unified_diff(a.decode().splitlines(True),b.decode().splitlines(True),fromfile=str(oldfir),tofile=str(newfir))))
        report['baseline_fir_gate']={'normalization':'only FIR @[source locator] annotations; no string or logic normalization',
            'old_fir_sha256':base.sha(oldfir),'new_fir_sha256':base.sha(newfir),
            'old_normalized_sha256':hashlib.sha256(a).hexdigest(),'new_normalized_sha256':hashlib.sha256(b).hexdigest(),
            'exact':a==b,'diff_sha256':base.sha(control/'normalized.diff')}
        base.save_receipt(out,report)
        if a!=b:raise RuntimeError('FRESH_BASELINE_REQUIRED: disabled control differs beyond FIR source locator annotations')
        if inputs()!=before:raise RuntimeError('source drift before candidate generation')
        model=common.test(args.gsim,cxx,args.tag+'/full-r1-m3-checked-flow',MAIN,TOP,HOST.name,defines={},timeout=180)
        report['effective_parameters']=effective(model)
        report['candidate_parameters']=compare_params(old['effective_parameters'],report['effective_parameters'],True)
        for field,prefix in [('cases','A1_VM_CPU_METRIC '),('stages','A1_VM_STAGE_METRIC '),
                             ('forwarding','M3_CPU_FORWARD_METRIC '),('flow','CHECKED_FLOW_METRIC ')]:report[field]=parse(model/'test.log',prefix)
        report['negative_controls']=[negative(model,*entry) for entry in (
            ('--inject-prechecked-pa','CHECKED_FLOW_NEGATIVE_REACHED','independent checked-flow PA/permission owner mismatch'),
            ('--inject-retirement-data','A1_RETIREMENT_NEGATIVE_REACHED','data pc='))]
        oldrows={r['name']:r for r in old['cases']};oldforward={r['name']:r for r in old['forwarding']}
        report['comparison']=[]
        for row,traffic,flow in zip(report['cases'],report['forwarding'],report['flow']):
            prev=oldrows[row['name']]
            if traffic!=oldforward[row['name']]:raise RuntimeError('M3 forwarding/actual memory conservation differs')
            if row['retired']!=prev['retired'] or row['bootstrap_retired']!=prev['bootstrap_retired']:raise RuntimeError('architectural retirement count changed')
            report['comparison'].append({'name':row['name'],'baseline_work':prev['work_cycles'],'candidate_work':row['work_cycles'],
                'delta_work':row['work_cycles']-prev['work_cycles'],'baseline_roi':prev['roi_cycles'],'candidate_roi':row['roi_cycles'],
                'delta_roi':row['roi_cycles']-prev['roi_cycles'],'retired':row['retired'],
                'all_cpu_field_differences':{k:[prev[k],v] for k,v in row.items() if prev[k]!=v},'actual_stage_observations':flow})
        report['status']='PASS_BOUNDED_CHECKED_FLOW_ACTUAL_CPU'
    except BaseException as error:
        report.update(status='FAIL',failure=f'{type(error).__name__}: {error}');raise
    finally:
        report['inputs_after']=inputs();report['inputs_unchanged']=report['inputs_after']==before
        report['tools_after']=base.tool_binding(True);report['tools_unchanged']=report['tools_after']==tools
        report['baseline_artifacts_unchanged']=all(Path(k).is_file() and base.sha(k)==v for k,v in report.get('baseline_binding',{}).get('artifacts',{}).items())
        if not report['inputs_unchanged'] or not report['tools_unchanged'] or not report['baseline_artifacts_unchanged']:report['status']='FAIL_INPUT_DRIFT'
        report['artifacts_sha256']={str(f.relative_to(out)):base.sha(f) for f in sorted(out.rglob('*')) if f.is_file() and f.name not in ('receipt.json','receipt.json.tmp')}
        base.save_receipt(out,report)
    if not report['status'].startswith('PASS_'):raise RuntimeError(report['status'])
    print(json.dumps({'status':report['status'],'receipt':str(out/'receipt.json'),'comparison':report['comparison']},indent=2))

if __name__=='__main__':main()
