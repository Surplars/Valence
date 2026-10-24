#!/usr/bin/env python3
"""One M3 actual CommonA1 CPU model, exact retained full-r1 structural reuse gate."""
import argparse
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
MAIN = 'soc.core.ooo.M3CompletedCanonicalCpuGsimMain'
HOST = common.HERE / 'harness/m3_completed_canonical_cpu.cpp'
BASELINE_SHA = '76d3b7cb6e77dbaf5c14098452abf837d2b9bce28a1c647294d829f58c2cb558'
OLD_HOST_SHA = 'b388eab9448b66ead9a189c38b2563f279c6159682165a31a34bfa11c58ec4cc'
TRACE = common.BUILD / 'm3-hot-store-analysis-20261024-r1'
TRACE_LOG_SHA = 'a3cdb2eb5459df3e97919435b19111f7dd0d79cf4e047094eb8a1d0383e22729'
CASES = ('vm_store_stream', 'vm_dependency', 'vm_alias')
PASS = 'M3_CPU_RETIREMENT_PASS'
SCOPE = {
    'DUT': 'actual full-r1-m3 CommonA1CpuTile, preserved complete RV64GC/VM/PMP and cache/resource geometry',
    'matched': 'two original 49-store VM programs, unchanged independent retirement/memory oracle and external service law',
    'new_functional_only': '72-retirement alias guest, two VA pages independently mapped to same PA line',
    'baseline_reuse': 'fresh default-false full-r1 CHIRRTL must equal retained FIR after removing source annotations and six specifically bound diagnostic source line locations; no generated baseline model rerun',
    'forwarding_observer': 'actual full-token LSU start, source certificate, actual prior physical reply, same-slot complete.fire, independent load bytes, retirement conservation',
    'negative_scope': 'sampled observation mutations, not RTL mutants',
    'limits': ['ordinary serial stores, no broad memory-bandwidth or NEMU/ISA qualification',
               'subword/sign/mask/fault/cancel/tag-reuse handled by separate actual LSU and predicate models',
               'no timing/PPA/300MHz/board qualification; acceptedPrefixValidation remains false'],
}


def inputs():
    found = base.source_inputs()
    for name in ('src/test/scala/platform/CommonA1VmPipelineGsim.scala',
                 'src/test/scala/platform/M3CompletedCanonicalCpuGsim.scala',
                 'simulator/gsim/harness/a1_vm_pipeline.cpp',
                 'simulator/gsim/harness/m3_completed_canonical_cpu.cpp',
                 'simulator/gsim/a1_vm_pipeline.py',
                 'simulator/gsim/m3_completed_canonical_cpu.py',
                 'simulator/gsim/m2_r1_compile_gate.py'):
        found[name] = base.sha(common.ROOT / name)
    return dict(sorted(found.items()))


def parse(log, prefix):
    text = log.read_text(); base.check_log(text)
    if text.splitlines().count(PASS) != 1: raise RuntimeError('missing exact complete M3 CPU PASS marker')
    rows = [base.read_json(line[len(prefix):]) for line in text.splitlines() if line.startswith(prefix)]
    if [r['name'] for r in rows] != list(CASES): raise RuntimeError('not the exact three bounded CPU guests')
    return rows


def normalize_locators(path):
    # FIRRTL source-location syntax only. Whitespace, symbols, ordering,
    # annotations, circuits and all expressions otherwise remain byte-exact.
    return re.sub(rb' @\[[^\]\n]*\]', b'', path.read_bytes())


def normalize_diagnostic_locations(data, current):
    # Approved narrow extension after retaining r1 FAIL: these exact two source
    # assertions moved, and ONLY their Chisel builtin automatic fatal line text
    # changed. Count checks reject every other version/format or broad rewrite.
    changes=[]
    for filename, old, new, count in [('LoadStoreUnit.scala',315,352,5),('IntegerBackend.scala',3406,3454,1)]:
        prefix=b'intrinsic(circt_chisel_ifelsefatal<format = "Assertion failed at '
        oldtext=prefix+f'{filename}:{old}\\n'.encode()
        newtext=prefix+f'{filename}:{new}\\n'.encode()
        needle=newtext if current else oldtext
        if data.count(needle)!=count:raise RuntimeError('diagnostic source-location count/format drift: '+filename)
        if current:data=data.replace(newtext,oldtext)
        changes.append({'source':filename,'old_line':old,'new_line':new,'occurrences':count})
    return data,changes


def reused_gate(path, before, report):
    old=json.loads(path.read_text())
    if old['status']!='FAIL' or 'FRESH_BASELINE_REQUIRED:' not in old.get('failure','') or not old['inputs_unchanged'] or not old['tools_unchanged']:
        raise RuntimeError('reuse requires immutable failed diagnostic-only r1 gate')
    delta={k:[old['inputs_before'].get(k),before.get(k)] for k in set(old['inputs_before'])|set(before)
           if old['inputs_before'].get(k)!=before.get(k)}
    if set(delta)!={'simulator/gsim/m3_completed_canonical_cpu.py'}:
        raise RuntimeError('reuse source drift beyond explicit runner-only gate repair: '+str(delta))
    for name,expected in old['artifacts_sha256'].items():
        if base.sha(path.parent/name)!=expected:raise RuntimeError('r1 retained artifact changed: '+name)
    report['r1_gate_reuse']={'receipt':str(path),'receipt_sha256':base.sha(path),'runner_only_delta':delta,
        'reason':'exact six approved builtin assertion diagnostic source-line locations; no DUT/host/program changes'}
    report['program_gate']=old['program_gate']
    return path.parent/'baseline-structural-gate'


def effective(directory):
    return {kind: base.read_json((directory / name).read_text()) for kind, name in
            [('config','effective-config.json'), ('core','effective-parameters.json')]}


def compare_params(old, new, enabled):
    changes = {}
    for kind in ('config', 'core'):
        added = {k: new[kind][k] for k in new[kind].keys() - old[kind].keys()}
        diff = {k: [old[kind][k], new[kind].get(k)] for k in old[kind] if new[kind].get(k) != old[kind][k]}
        if added != {'completedCanonicalStoreForwarding': str(enabled).lower()} or diff:
            raise RuntimeError(f'unexpected {kind} profile delta: {added}, {diff}')
        changes[kind] = {'added':added, 'changed':diff}
    return changes


def baseline_binding(path, report):
    if base.sha(path) != BASELINE_SHA: raise RuntimeError('historical baseline receipt bytes changed')
    data = json.loads(path.read_text())
    if data['status'] != 'PASS_BOUNDED_M2_R1_ACTUAL_CPU_FOUR_CONTROL': raise RuntimeError('invalid retained CPU baseline')
    bound = {}
    for name, expected in data['artifacts_sha256'].items():
        if name.startswith('full-r1/'):
            source = path.parent / name
            if base.sha(source) != expected: raise RuntimeError('retained baseline artifact changed: ' + name)
            bound[str(source)] = expected
    if base.sha(common.HERE / 'harness/a1_vm_pipeline.cpp') != OLD_HOST_SHA:
        raise RuntimeError('published old VM host changed')
    if base.sha(TRACE/'trace.log') != TRACE_LOG_SHA: raise RuntimeError('passive baseline trace changed')
    manifest = json.loads((TRACE/'manifest.json').read_text())
    if manifest['status'] != 'PASS_TRACE_WITH_EXACT_ORIGINAL_VM_METRICS' or not manifest['unchangedSourceModelAndHistoricalReceipt']:
        raise RuntimeError('baseline traffic trace lacks immutable model/metric binding')
    for name in ('trace.log','trace.cpp','manifest.json','analysis.json','original_host.cpp'):
        bound[str(TRACE/name)] = base.sha(TRACE/name)
    report['baseline_binding'] = {'receipt':str(path),'receipt_sha256':BASELINE_SHA,'artifacts':bound,
                                  'old_host_sha256':OLD_HOST_SHA,'trace_fields_exact':108}
    counts = {n:{'upstream_loads':0,'physical_loads':0,'load_replies':0,'physical_stores':0,'store_replies':0} for n in CASES[:2]}
    for line in (TRACE/'trace.log').read_text().splitlines():
        prefix = line.split(' ',1)[0]
        if prefix not in ('M3_REQUEST','M3_PHYSICAL','M3_REPLY'): continue
        row = dict(x.split('=',1) for x in line.split()[1:]); out = counts[row['guest']]; write = int(row['write'])
        if prefix == 'M3_REQUEST' and not write: out['upstream_loads'] += 1
        if prefix == 'M3_PHYSICAL': out['physical_stores' if write else 'physical_loads'] += 1
        if prefix == 'M3_REPLY': out['store_replies' if write else 'load_replies'] += 1
    for n, loads in zip(CASES[:2], (57,105)):
        if counts[n] != {'upstream_loads':loads,'physical_loads':loads,'load_replies':loads,'physical_stores':49,'store_replies':49}:
            raise RuntimeError('baseline trace traffic conservation changed')
    report['baseline_traffic'] = counts
    return data


def program_gate(out, cxx):
    old = common.HERE / 'harness/a1_vm_pipeline.cpp'
    helper = out/'old-byte-dump.cpp'
    helper.write_text('#define A1_VM_ORACLE_ONLY 1\n#define main original_host_main\n#include '+json.dumps(str(old))+'''\n#undef main
int main(){for(const auto&p:programs())if(p.vm()){
std::cout<<"M3_PROGRAM "<<p.name<<' '<<p.placement<<' '<<p.setupInstructions;
for(auto word:p.code)std::cout<<' '<<std::hex<<std::setw(8)<<std::setfill('0')<<word;
std::cout<<std::dec<<'\\n';}}
''')
    flags=['-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all']
    for source, binary, extra in [(helper,out/'old-byte-dump',[]),(HOST,out/'new-oracle',['-DA1_VM_ORACLE_ONLY=1'])]:
        common.run([cxx,*flags,*extra,source,'-o',binary],log=out/(binary.name+'-compile.log'))
    common.run([out/'old-byte-dump'],env=base.runtime_env(),log=out/'old-programs.log')
    common.run([out/'new-oracle','--dump-programs'],env=base.runtime_env(),log=out/'new-programs.log')
    common.run([out/'new-oracle','--oracle-only'],env=base.runtime_env(),log=out/'oracle.log')
    oldlines=(out/'old-programs.log').read_text().splitlines(); newlines=(out/'new-programs.log').read_text().splitlines()
    if len(oldlines)!=2 or len(newlines)!=3 or oldlines!=newlines[:2]:raise RuntimeError('original two VM program bytes/setup changed')
    return {'exact_original_programs':2,'new_alias_guest_only':1,'published_old_host_sha256':base.sha(old),
            'old_dump_sha256':base.sha(out/'old-programs.log'),'new_dump_sha256':base.sha(out/'new-programs.log')}


def negative(model, flag, marker, diagnostic):
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
    p.add_argument('--baseline',type=Path,default=common.BUILD/'m2-r1-common-vm-20261024-r1/receipt.json')
    p.add_argument('--build-run',action='store_true');p.add_argument('--reuse-baseline-gate',type=Path);args=p.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+',args.tag):p.error('fresh safe tag required')
    before=inputs()
    if not args.build_run:
        print(json.dumps({'status':'PREFLIGHT_ONLY','inputs':len(before),'scope':SCOPE},indent=2));return
    out=common.BUILD/args.tag;out.mkdir(parents=True,exist_ok=False)
    resource.setrlimit(resource.RLIMIT_CORE,(0,0));gate.install()
    tools=base.tool_binding(True);cxx=tools['compiler']['command']
    if args.gsim.resolve()!=Path(tools['gsim']['path']).resolve():raise RuntimeError('pinned GSIM required')
    report={'schema':'m3-actual-cpu-v1','status':'RUNNING','source_revision':base.git(common.ROOT,'rev-parse','HEAD').strip(),
            'inputs_before':before,'tools_before':tools,'scope':SCOPE}
    base.save_receipt(out,report)
    try:
        old=baseline_binding(args.baseline,report)
        if args.reuse_baseline_gate:
            control=reused_gate(args.reuse_baseline_gate,before,report)
        else:
            report['program_gate']=program_gate(out,cxx)
            control=out/'baseline-structural-gate';control.mkdir()
            common.run(['mill','-i','IonSoC.test.runMain','soc.core.ooo.CommonA1VmPipelineGsimMain',control,'full-r1'],log=control/'elaborate.log')
        base.save_receipt(out,report)
        report['baseline_parameters']=compare_params(old['effective_parameters']['full-r1'],effective(control),False)
        a=normalize_locators(args.baseline.parent/'full-r1'/f'{TOP}.fir');b=normalize_locators(control/f'{TOP}.fir')
        a,locators=normalize_diagnostic_locations(a,False);b,_=normalize_diagnostic_locations(b,True)
        report['baseline_fir_gate']={'normalization':'remove @[source locators] plus exactly six approved builtin diagnostic source line locations',
            'diagnostic_source_locations':locators,'raw_fir_equal':False,'control_fir':str(control/f'{TOP}.fir'),'control_fir_sha256':base.sha(control/f'{TOP}.fir'),
            'old_normalized_sha256':hashlib.sha256(a).hexdigest(),'new_normalized_sha256':hashlib.sha256(b).hexdigest(),'exact':a==b}
        base.save_receipt(out,report)
        if a!=b:raise RuntimeError('FRESH_BASELINE_REQUIRED: default-false structural FIR differs beyond source locators')
        if inputs()!=before:raise RuntimeError('source drift before candidate model')
        model=common.test(args.gsim,cxx,args.tag+'/full-r1-m3',MAIN,TOP,HOST.name,defines={},timeout=180)
        report['effective_parameters']=effective(model)
        report['candidate_parameters']=compare_params(old['effective_parameters']['full-r1'],report['effective_parameters'],True)
        report['cases']=parse(model/'test.log','A1_VM_CPU_METRIC ')
        report['stages']=parse(model/'test.log','A1_VM_STAGE_METRIC ')
        report['forwarding']=parse(model/'test.log','M3_CPU_FORWARD_METRIC ')
        report['negative_controls']=[negative(model,*entry) for entry in (
            ('--inject-forward-data','M3_FORWARD_NEGATIVE_REACHED','independent forwarded bytes mismatch'),
            ('--inject-retirement-data','A1_RETIREMENT_NEGATIVE_REACHED','data pc='))]
        oldrows={r['name']:r for r in old['cases']['full-r1']};report['comparison']=[]
        for row,traffic in zip(report['cases'][:2],report['forwarding'][:2]):
            prev=oldrows[row['name']];counts=report['baseline_traffic'][row['name']]
            if row['retired']!=prev['retired'] or row['bootstrap_retired']!=prev['bootstrap_retired']:raise RuntimeError('architectural retirement count changed')
            if not 0<traffic['physical_loads']<counts['physical_loads'] or traffic['forwarded_loads']<=0:raise RuntimeError('no actual forwarding/request reduction')
            report['comparison'].append({'name':row['name'],'baseline_work':prev['work_cycles'],'candidate_work':row['work_cycles'],
                'delta_work':row['work_cycles']-prev['work_cycles'],'baseline_roi':prev['roi_cycles'],'candidate_roi':row['roi_cycles'],
                'delta_roi':row['roi_cycles']-prev['roi_cycles'],'retired':row['retired'],'baseline_physical_loads':counts['physical_loads'],
                'candidate_physical_loads':traffic['physical_loads'],'forwarded_loads':traffic['forwarded_loads'],'physical_stores':traffic['physical_stores']})
        report['status']='PASS_BOUNDED_M3_ACTUAL_CPU_AND_ALIAS'
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
