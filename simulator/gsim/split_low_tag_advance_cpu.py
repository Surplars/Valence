#!/usr/bin/env python3
"""One new split-tag CPU, sealed corrected-epoch guarded-natural control replay.
No baseline mutation or rebuild; four immutable guests, complete logs and owners exact.
"""
import argparse
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import sys
sys.dont_write_bytecode = True
import registered_raw_certified_cpu as raw
import gsim_initialization_epoch as epoch
common, base, row = raw.common, raw.base, raw.row
need, sha, read = raw.need, raw.sha, raw.read
CONTROL = raw.CONTROL + '-guarded-natural-pmp'
CANDIDATE = CONTROL + '-split-tag'
MAIN = 'soc.core.ooo.SplitLowTagAdvanceCpuGsimMain'
REFERENCE = common.BUILD / 'guarded-natural-fresh-cpu-20261025-r1/receipt.json'
REFERENCE_SHA = '8fe91bc51639e0766c9f6cc48b47c90d9d31ec9ecf86459bc67ad758c0a3abeb'
EPOCH_SHA = '128c4853a6584cd1181cff863fc727a824fe132ad3c60f3ba323d46ea3b135fa'
DTA = common.BUILD / 'guarded-natural-dta-20261025-r4/receipt.json'
DTA_SHA = 'b72af2cdb0f81716abbc793419053a74b1579dbd5dde16e5d68c79a2c6d99056'
METRICS = (*raw.VM_PREFIXES, 'latency_owners', 'owner_stage_histograms', 'load_cases', 'proof_metrics')


def inputs():
    paths = list((common.ROOT / 'src/main/scala').rglob('*.scala')) + [
        Path(__file__).resolve(), Path(epoch.__file__),
        common.ROOT / 'src/test/scala/platform/SplitLowTagAdvanceCpuGsim.scala']
    return {**raw.inputs(), **{str(p.relative_to(common.ROOT)): sha(p) for p in paths}}


def bind_history(tools):
    need(sha(REFERENCE) == REFERENCE_SHA and sha(DTA) == DTA_SHA, 'sealed historical receipt changed')
    prior = read(REFERENCE)
    need(prior['status'] == 'PASS_EXACT_GUARDED_NATURAL_PMP_FRESH_PAIR_CPU', 'unqualified baseline')
    need(prior['tools_before'] == tools and tools['gsim']['epoch_receipt_sha256'] == EPOCH_SHA,
         'control and candidate must share exact qualified corrected tool epoch')
    model, record = REFERENCE.parent / CONTROL, prior['models'][CONTROL]
    artifacts = {str(REFERENCE): REFERENCE_SHA, str(DTA): DTA_SHA}
    for name, digest in prior['artifacts_sha256'].items():
        if name.startswith(CONTROL + '/'):
            artifacts[str(REFERENCE.parent / name)] = digest
    need(row.unchanged_artifacts({'artifacts': artifacts}), 'sealed control artifacts changed')
    need(raw.verify_first_build(model, tools['compiler']['command']) == record['first_build'],
         'sealed first build content-key/host binding mismatch')
    for kind in ('second_host', 'execution_artifacts'):
        need(row.unchanged_artifacts(record[kind]), 'sealed host/execution artifact changed')
    need([x['work_cycles'] for x in record['cases']] == [681, 1018] and
         [x['roi_work_cycles'] for x in record['load_cases']] == [531, 360], 'baseline cycle contract changed')
    return model, record, {'artifacts': artifacts, 'scope': 'qualified guarded-natural corrected-epoch runtime and object reuse; DTA receipt historical provenance only'}


def parameter_gate(control, candidate, sealed):
    for kind in ('config', 'core'):
        a, b, old = control[kind], candidate[kind], sealed[kind]
        need(set(a) == set(old) | {'splitLowTagAdvance'} and a['splitLowTagAdvance'] == 'false' and
             all(a[k] == v for k, v in old.items()), 'disabled control parameter/resource drift: ' + kind)
        need(row.differences(a, b) == {'splitLowTagAdvance': ['false', 'true']},
             'candidate not exact one-flag tag change: ' + kind)
    return {'only_delta': 'splitLowTagAdvance false->true', 'all_capacities_and_stages_unchanged': True}


def module_gate(control, candidate):
    def modules(path):
        data = row.normalize_fir(path.read_bytes())
        declarations = list(re.finditer(rb'^  (?:public )?(?:module|extmodule|intmodule) (\S+) :[^\n]*$', data, re.M))
        need(declarations, 'no FIR modules found')
        result = {}
        for i, declaration in enumerate(declarations):
            name = declaration[1]
            need(name not in result, 'duplicate module declaration: ' + name.decode())
            end = declarations[i + 1].start() if i + 1 < len(declarations) else len(data)
            block = data[declaration.start():end]
            need(len(re.findall(rb'^  \S', block, re.M)) == 1,
                 'unsupported/unparsed circuit declaration in module: ' + name.decode())
            result[name] = block
        return data[:declarations[0].start()], result
    preamble_a, a = modules(control)
    preamble_b, b = modules(candidate)
    need(preamble_a == preamble_b, 'circuit declaration/annotations changed')
    need(set(a) == set(b) and a, 'module set changed')
    changed = []
    for name in a:
        need(a[name].splitlines()[0] == b[name].splitlines()[0], 'module declaration kind/visibility changed: ' + name.decode())
        ports = lambda data: re.findall(rb'^    (?:input|output) .*$', data, re.M)
        need(ports(a[name]) == ports(b[name]), 'module ports changed: ' + name.decode())
        if a[name] != b[name]:
            changed.append(name.decode())
    need(changed == ['RenameRob'], 'hardware differs outside actual RenameRob: ' + repr(changed))
    return {'changed_modules': changed, 'all_module_ports_exact': True,
            'all_memory_hardware_source_normalized_exact': True,
            'normalization': 'source annotations only, no name/diagnostic/logic rewriting'}


def component_gate(path, compile_path, tools):
    component = read(path)
    need(component.get('schema') == 'valence-split-low-tag-advance-ledger-v1' and
         component.get('status') == 'PASS_FOCUSED_FULL64_LEDGER', 'actual full64 Ledger component PASS required')
    need(component['inputs'] and all(sha(common.ROOT / p) == d for p, d in component['inputs'].items()),
         'component current source inputs differ')
    need(component['tool_epoch'] == tools and component['compile_receipt_sha256'] == sha(compile_path),
         'component tool/compile binding mismatch')
    need(component['paired_result'] == 'IDENTICAL_POSITIVE_LOGS_AND_PARAMS_EXCEPT_TAG_ADVANCE',
         'paired Ledger exactness gate required')
    artifacts = {str(path): sha(path)}
    need(component.get('artifacts'), 'component artifact manifest missing')
    for name, record in component['artifacts'].items():
        target = path.parent / name
        need(target.is_file() and target.stat().st_size == record['bytes'] and sha(target) == record['sha256'],
             'component artifact changed: ' + name)
        artifacts[str(target)] = record['sha256']
    need(component['cases']['control'] == component['cases']['split'] and
         all(len(component['negatives'][name]) == 13 and
             all(x['status'] == 'EXPECTED_REJECTION' for x in component['negatives'][name].values())
             for name in ('control', 'split')), 'Ledger paired cases/negative controls incomplete')
    return {'artifacts': artifacts, 'actual_full64_ledger_pass': True}


def formal_gate(path, compile_path):
    proof = read(path)
    need(proof.get('schema') == 'valence-actual-tag-helper-formal-v1' and
         proof.get('status') == 'PASS_FULL64_ACTUAL_HELPER_AND_CONDITIONAL_PROJECTION',
         'actual full64 helper formal PASS required')
    need(proof['compile_receipt_sha256'] == sha(compile_path) and proof['source_inputs'] and
         all(sha(common.ROOT / p) == d for p, d in proof['source_inputs'].items()),
         'actual helper formal source/compile binding mismatch')
    need(proof['proofs']['none']['status'] == 'PASS' and
         all(proof['proofs'][name]['status'] == 'EXPECTED_COUNTEREXAMPLE' for name in ('carry', 'exhaustion')),
         'actual helper proof/negative controls incomplete')
    artifacts = {str(path): sha(path), **{str(path.parent / p): d for p, d in proof['artifacts'].items()}}
    need(proof['artifacts'] and row.unchanged_artifacts({'artifacts': artifacts}), 'formal artifact drift')
    return {'artifacts': artifacts, 'actual_full64_helper_formal_pass': True}


def independent_structure_gate(directory):
    artifacts = {}
    expected = {'emitted-structure.json': 'PASS_EXACT_EMITTED_ARITHMETIC_ONLY_DELTA',
                'lowered-rtl-review.json': 'PASS_LOWERED_RTL_SPOT_CHECK_AND_EXACT_REGISTER_MANIFEST'}
    for name, status in expected.items():
        path = directory / name
        receipt = read(path)
        need(receipt.get('status') == status and receipt.get('inputs'), 'independent structure gate incomplete')
        artifacts[str(path)] = sha(path)
        artifacts.update({str(common.ROOT / p): d for p, d in receipt['inputs'].items()})
        if name == 'emitted-structure.json':
            checker = common.HERE / 'split_low_tag_advance_structure.py'
            need(sha(checker) == receipt['checker_sha256'] and receipt['state_delta'] == 0,
                 'independent structure checker/state binding mismatch')
            artifacts[str(checker)] = sha(checker)
        else:
            need(receipt['same_reg_name_width_order'] is True and receipt['nextTag_width'] == 64,
                 'independent lowered register/width gate failed')
    need(row.unchanged_artifacts({'artifacts': artifacts}), 'independent structure artifact drift')
    return {'artifacts': artifacts, 'independent_actual_Ledger_structure_pass': True}


def resource_gate(path, compile_path):
    need(sha(path) == '5427fbf62676efa0e1f629e9bc82ac8ca298ce27babf8d82388d42be29b6e2ea',
         'root-approved sealed resource receipt changed')
    receipt = read(path)
    need(receipt['status'] == 'PASS_MATCHED_UNTAPPED_LEDGER_RESOURCE_AND_CONNECTIVITY_PROXY' and
         set(receipt['policies']) == {'default', 'no-sat-sharing'}, 'matched resource policies incomplete')
    manifest = path.parent / 'manifest.json'
    artifacts = {str(path): sha(path), str(manifest): sha(manifest)}
    artifacts.update({str(path.parent / p): d for p, d in read(manifest).items()})
    artifacts.update({str(common.ROOT / p): d for p, d in receipt['evidence'].items()})
    for policy, result in receipt['policies'].items():
        mapping = path.parent / ('map-' + policy + '-receipt.json')
        depth = path.parent / (policy + '-depth.json')
        need(sha(mapping) == result['mapping_receipt_sha256'] and sha(depth) == result['depth_sha256'] and
             read(mapping)['compile_sha256'] == sha(compile_path), 'resource policy/compile binding drift')
        artifacts[str(mapping)], artifacts[str(depth)] = sha(mapping), sha(depth)
    need(row.unchanged_artifacts({'artifacts': artifacts}), 'sealed resource artifacts changed')
    return {'artifacts': artifacts, 'matched_actual_Ledger_resource_pass': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--gsim', type=Path, required=True)
    parser.add_argument('--compile-receipt', type=Path)
    parser.add_argument('--component-receipt', type=Path)
    parser.add_argument('--formal-receipt', type=Path)
    parser.add_argument('--structure-directory', type=Path)
    parser.add_argument('--resource-receipt', type=Path)
    parser.add_argument('--build-run', action='store_true')
    parser.add_argument('--tool-receipt', type=Path, required=True)
    args = parser.parse_args()
    need(re.fullmatch(r'[A-Za-z0-9_-]+', args.tag), 'safe fresh tag required')
    before, source_gate = inputs(), raw.host_source_gate()
    tools = epoch.tool_binding(args.tool_receipt)
    control_model, sealed, control_binding = bind_history(tools)
    need(args.gsim.resolve() == Path(tools['gsim']['path']).resolve(), 'pinned GSIM path required')
    if not args.build_run:
        print(json.dumps({'status': 'PREFLIGHT_ONLY', 'source_gate': source_gate,
                          'sealed_corrected_control_verified': True, 'new_DUT_builds': 0}, indent=2))
        return
    need(args.compile_receipt is not None and args.component_receipt is not None and args.formal_receipt is not None and args.structure_directory is not None and args.resource_receipt is not None,
         'current Scala, actual Tag helper formal and Ledger receipts required')
    component = component_gate(args.component_receipt, args.compile_receipt, tools)
    formal = formal_gate(args.formal_receipt, args.compile_receipt)
    independent = independent_structure_gate(args.structure_directory)
    resources = resource_gate(args.resource_receipt, args.compile_receipt)
    out = common.BUILD / args.tag
    out.mkdir(parents=True, exist_ok=False)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    report = {'schema': 'split-low-tag-advance-one-new-cpu-v1', 'status': 'RUNNING',
              'source_revision': base.git(common.ROOT, 'rev-parse', 'HEAD').strip(),
              'inputs_before': before, 'tools_before': tools, 'history_binding': control_binding, 'models': {},
              'tool_receipt_binding': {'artifacts': {str(args.tool_receipt): sha(args.tool_receipt)}},
              'source_gate': source_gate, 'new_DUT_builds': 0, 'hardware_guest_runs': 0,
              'component_binding': component, 'formal_binding': formal, 'structure_binding': independent, 'resource_binding': resources,
              'limits': 'No PPA/STA/board/SoC/NEMU; one new model, qualified control replay, four immutable guests each. No performance gain claimed.'}
    base.save_receipt(out, report)
    try:
        row.bind_compile_receipt(args.compile_receipt, report)
        compiled = row.scala.verify_receipt(args.compile_receipt, common.ROOT)
        classpath = os.pathsep.join(compiled['runClasspathEntries'])
        for profile in (CONTROL, CANDIDATE):
            row.scala.verify_receipt(args.compile_receipt, common.ROOT)
            need(inputs() == before, 'source drift before emission')
            target = out / profile
            target.mkdir()
            common.run(['java', '-cp', classpath, MAIN, target, profile], log=target / 'elaborate.log')
            row.scala.verify_receipt(args.compile_receipt, common.ROOT)
        a, b = row.normalize_fir((control_model / (raw.TOP + '.fir')).read_bytes()), row.normalize_fir(
            (out / CONTROL / (raw.TOP + '.fir')).read_bytes())
        delta = out / 'disabled-control.diff'
        delta.write_text('' if a == b else ''.join(difflib.unified_diff(a.decode().splitlines(True), b.decode().splitlines(True))))
        need(a == b, 'FRESH_CONTROL_REQUIRED: disabled FIR differs beyond source annotations')
        report['disabled_control_gate'] = {'exact_source_only': True, 'diff_sha256': sha(delta)}
        report['parameter_gate'] = parameter_gate(row.effective(out / CONTROL), row.effective(out / CANDIDATE), sealed['effective_parameters'])
        report['cache_gate'] = raw.cache_gate(out / CONTROL, out / CANDIDATE)
        report['module_gate'] = module_gate(out / CONTROL / (raw.TOP + '.fir'), out / CANDIDATE / (raw.TOP + '.fir'))
        replay = out / CONTROL
        (replay / 'load-host').mkdir()
        for log, binary, flags in [('test.log', control_model / 'run', []),
                                   ('load-host/test.log', control_model / 'load-host/run', ['--trace'])]:
            common.run([binary, *flags], env=base.runtime_env(), log=replay / log, timeout=180)
            need((replay / log).read_bytes() == (control_model / log).read_bytes(), 'sealed binary replay log differs: ' + log)
        control = raw.vm_metrics(replay, False)
        control['load_cases'] = raw.parse(replay / 'load-host/test.log', 'LOAD_SUPPLY_METRIC ', raw.LOAD_CASES, 'LOAD_SUPPLY_PASS')
        control['proof_metrics'] = raw.parse(replay / 'load-host/test.log', 'ELASTIC_PROOF_METRIC ', raw.LOAD_CASES, 'LOAD_SUPPLY_PASS')
        report['models'][CONTROL] = control
        report['hardware_guest_runs'] += 4
        raw.gate.install()
        model, cxx = out / CANDIDATE, tools['compiler']['command']
        candidate = {'effective_parameters': row.effective(model), 'first_build': raw.build_model(model, args.gsim, cxx)}
        report['models'][CANDIDATE] = candidate
        report['new_DUT_builds'] = 1
        base.save_receipt(out, report)
        common.run([model / 'run'], env=base.runtime_env(), log=model / 'test.log', timeout=180)
        candidate.update(raw.vm_metrics(model, False))
        candidate['second_host'], candidate['load_cases'], candidate['proof_metrics'] = raw.second_host(model, cxx, candidate['first_build'])
        report['hardware_guest_runs'] += 4
        for key in METRICS:
            need(candidate[key] == control[key], 'exact metric/owner mismatch: ' + key)
            need(json.loads(json.dumps(control[key])) == sealed[key], 'control replay historical metric mismatch: ' + key)
        for log in ('test.log', 'load-host/test.log'):
            need((model / log).read_bytes() == (replay / log).read_bytes(), 'paired full log differs: ' + log)
        candidate['negative'] = raw.negative(model)
        report['status'] = 'PASS_EXACT_SPLIT_LOW_TAG_ADVANCE_ONE_NEW_CPU'
    except BaseException as error:
        report.update(status='FAIL', failure=f'{type(error).__name__}: {error}')
        raise
    finally:
        report['inputs_unchanged'] = inputs() == before
        report['tools_unchanged'] = epoch.tool_binding(args.tool_receipt) == tools
        checks = [report['inputs_unchanged'], report['tools_unchanged']]
        for key in ('history_binding', 'tool_receipt_binding', 'component_binding', 'formal_binding', 'structure_binding', 'resource_binding', 'scala_compile_receipt'):
            report[key + '_unchanged'] = row.unchanged_artifacts(report.get(key, {}))
            checks.append(report[key + '_unchanged'])
        for record in report['models'].values():
            for key in ('first_build', 'second_host'):
                checks.append(row.unchanged_artifacts(record.get(key, {})))
        if not all(checks):
            report['status'] = 'FAIL_SOURCE_TOOL_OR_ARTIFACT_DRIFT'
        report['artifacts_sha256'] = {str(p.relative_to(out)): sha(p) for p in out.rglob('*') if p.is_file() and p.name not in ('receipt.json', 'receipt.json.tmp')}
        base.save_receipt(out, report)
    need(report['status'] == 'PASS_EXACT_SPLIT_LOW_TAG_ADVANCE_ONE_NEW_CPU', report['status'])
    print(json.dumps({'status': report['status'], 'receipt': str(out / 'receipt.json'), 'new_DUT_builds': 1, 'all_four_guests_exact': True}, indent=2))


if __name__ == '__main__':
    main()
