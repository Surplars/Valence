#!/usr/bin/env python3
"""Bounded two-phase, one-new-DUT buffered return-flow/index CPU comparison.

--emit creates and seals only the two actual FIR exports. --build-run requires
the resulting source/compile/component seal and a separate reviewed structure
receipt. Historical 7daf119 runtime objects are immutable controls, not rebuilt.
Original hosts are immutable; candidate adapters add passive observations only.
"""
import argparse
from collections import Counter
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
import registered_raw_certified_cpu as raw
import buffered_third_rank_cpu as donor
import gsim_initialization_epoch as epoch

common, base, row = raw.common, raw.base, raw.row
need, sha, read = raw.need, raw.sha, raw.read
CONTROL = donor.CANDIDATE
CANDIDATE = CONTROL + '-return-flow-index'
MAIN = 'soc.core.ooo.BufferedReturnFlowCpuGsimMain'
REFERENCE = common.BUILD / 'buffered-third-rank-cpu-20261025-r3-host-recovery/receipt.json'
REFERENCE_SHA = '98ef619db33d8ea546802c4fa3480b492bf9cf2e9ec1469b8052998419608c05'
COMMIT = '7daf1190db48b37214f73a2fdd68a9fd0dbff3aa'
COMMIT_BINDING = common.ROOT / 'build/buffered-third-rank-final-20261025-r1/commit-binding.json'
EPOCH_SHA = '128c4853a6584cd1181cff863fc727a824fe132ad3c60f3ba323d46ea3b135fa'
OBSERVER = common.HERE / 'harness/buffered_source_lifetime_observer.h'
OBSERVER_UNIT = common.ROOT / 'build/buffered-source-lifetime-observer-20261025-r1/receipt.json'
EMIT_SCHEMA = 'buffered-return-flow-frozen-cpu-emission-v1'
RESULT_SCHEMA = 'buffered-return-flow-one-new-cpu-v1'
SOURCE = common.ROOT / 'src/test/scala/platform/BufferedReturnFlowCpuGsim.scala'
RETURN_OBSERVER = common.HERE / 'harness/buffered_return_flow_observer.h'
RETURN_OBSERVER_UNIT = common.ROOT / 'build/buffered-return-flow-observer-20261025-r2-slot-events/receipt.json'
ALLOW_CHANGED = {'IntegerBackend', 'IntegerCore', 'MachineCore', 'MappedMachineCore',
                 'CommonA1CpuTile', raw.TOP, 'DataResponseBuffer_1', 'TwoEntryRegisterQueue_4',
                 'DataTranslationAdapter', 'ParallelLoadStoreUnit', 'LoadStoreUnit',
                 'LoadStoreUnit_1', 'LoadStoreUnit_2', 'LoadStoreUnit_3'}
ALLOW_REMOVED = set()
ALLOW_ADDED = set()


def save(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def inputs():
    files = list((common.ROOT / 'src/main/scala').rglob('*.scala')) + [
        Path(__file__), Path(epoch.__file__), Path(donor.__file__), SOURCE, OBSERVER, RETURN_OBSERVER,
        common.HERE / 'test_buffered_return_flow_cpu.py',
        common.HERE / 'harness/isa_model.h', common.HERE / 'harness/gsim_model_storage.h']
    return {**raw.inputs(), **{str(p.relative_to(common.ROOT)): sha(p) for p in files}}


def bind_history(tools):
    need(sha(REFERENCE) == REFERENCE_SHA, 'sealed 7daf119 CPU receipt changed')
    prior = read(REFERENCE)
    need(prior['status'] == 'PASS_FOCUSED_BUFFERED_SUPPLY_WITH_HOT_GAIN' and
         prior['tools_before'] == tools and tools['gsim']['epoch_receipt_sha256'] == EPOCH_SHA,
         'qualified 7daf119 runtime and identical corrected GSIM epoch required')
    model, record = REFERENCE.parent / CONTROL, prior['models'][CONTROL]
    artifacts = {str(REFERENCE): REFERENCE_SHA, str(COMMIT_BINDING): sha(COMMIT_BINDING)}
    for name, digest in prior['artifacts_sha256'].items():
        if name.startswith(CONTROL + '/'):
            artifacts[str(REFERENCE.parent / name)] = digest
    binding = read(COMMIT_BINDING)
    need(binding['status'] == 'PASS_PRECOMMIT_VALIDATION_TO_FINAL_SOURCE_EQUALITY' and
         binding['final_commit'] == COMMIT, 'historical source-to-commit qualification missing')
    compile_path = common.ROOT / binding['compile_receipt']
    need(sha(compile_path) == binding['compile_receipt_sha256'], 'historical compile receipt changed')
    artifacts[str(compile_path)] = sha(compile_path)
    compiled = read(compile_path)
    historical = {**binding['changed_inputs'], **{
        str(Path(p).relative_to(common.ROOT)): d for p, d in compiled['sourceInputs'].items()}}
    for name, digest in historical.items():
        blob = subprocess.check_output(['git', 'show', COMMIT + ':' + name], cwd=common.ROOT)
        need(hashlib.sha256(blob).hexdigest() == digest, 'historical committed source mismatch: ' + name)
    need(row.unchanged_artifacts({'artifacts': artifacts}), 'sealed control artifacts changed')
    need(donor.verify_build(model, tools['compiler']['command'], Path(record['first_build']['host'])) == record['first_build'],
         'sealed control content-key/header/host binding changed')
    need(row.unchanged_artifacts(record['second_host']), 'sealed load-host objects/binary changed')
    need([x['work_cycles'] for x in record['cases']] == [677, 967] and
         [x['roi_work_cycles'] for x in record['load_cases']] == [402, 360], 'baseline cycle contract changed')
    return model, record, {'artifacts': artifacts, 'qualified_commit': COMMIT,
                          'historical_compile_identity_preserved': True,
                          'scope': 'sealed corrected-epoch control objects and replay, not fresh control rebuild'}


def component_gate(path, compile_path, tools):
    r = read(path)
    need(r.get('schema') == 'valence-buffered-return-flow-components-v1' and
         r.get('status') == 'PASS_BUFFERED_RETURN_FLOW_COMPONENTS', 'qualified actual components required')
    need(r.get('inputs_unchanged') is True and r['inputs'] and
         all(sha(common.ROOT / p) == d for p, d in r['inputs'].items()), 'component current source drift')
    need(r['compile_receipt_sha256'] == sha(compile_path) and r['tool_epoch'] == tools,
         'component compile/tool epoch mismatch')
    need(set(r['tests']) >= {'local_off', 'local_on', 'chain_off', 'chain_on'} and
         all(r['tests'][k]['status'] == 'PASS' for k in ('local_off', 'local_on', 'chain_off', 'chain_on')),
         'actual local queue and composed return-chain tests incomplete')
    need(r['negatives'] and all(x['status'] == 'EXPECTED_REJECTION' for x in r['negatives'].values()),
         'independent negative controls incomplete')
    artifacts = {str(path): sha(path), **{str(path.parent / p): d for p, d in r['artifacts'].items()}}
    contract = r['model_contract']
    need(contract['sha256'] == 'd73c7c4ec39434260ae5550de534d97b4cbb9e1541edb2c790b651748bebd430',
         'reviewed independent model receipt required')
    artifacts.update(contract['artifacts'])
    need(any(p.endswith('/REVIEW-ADDENDUM.md') and d ==
             '6463484a5264dcede858bea1e299ca8686bc59f9f555f34d1b9aa972fd9c3730'
             for p, d in artifacts.items()), 'reviewed model limitation addendum missing')
    need(r['artifacts'] and row.unchanged_artifacts({'artifacts': artifacts}), 'component artifact drift')
    return {'artifacts': artifacts, 'actual_return_components_pass': True}


def observer_unit_gate():
    r = read(OBSERVER_UNIT)
    need(r.get('schema') == 'valence-buffered-source-shadow-unit-v1' and
         r.get('status') == 'PASS_SYNTHETIC_SHADOW_ONLY' and r['negative_count'] >= 8 and
         r['header']['path'] == str(OBSERVER.relative_to(common.ROOT)) and
         r['header']['sha256'] == sha(OBSERVER), 'source-lifetime observer synthetic coverage/header drift')
    artifacts = {str(OBSERVER_UNIT): sha(OBSERVER_UNIT), str(OBSERVER): sha(OBSERVER),
                 **{str(OBSERVER_UNIT.parent / p): d for p, d in r['artifacts'].items()}}
    need(row.unchanged_artifacts({'artifacts': artifacts}), 'source observer unit artifacts drift')
    return {'artifacts': artifacts, 'scope': 'retained synthetic source observer self-tests; prior actual GSIM phase is historically sealed'}


def return_observer_unit_gate():
    r = read(RETURN_OBSERVER_UNIT)
    need(r.get('schema') == 'valence-buffered-return-flow-observer-v1' and
         r.get('status') == 'PASS_SYNTHETIC_OBSERVER_ONLY' and
         r['header']['path'] == str(RETURN_OBSERVER.relative_to(common.ROOT)) and
         r['header']['sha256'] == sha(RETURN_OBSERVER), 'return observer header/unit binding drift')
    need(r['negatives'] and all(x['status'] == 'EXPECTED_REJECTION' for x in r['negatives'].values()),
         'return observer negative calibrations missing')
    artifacts = {str(RETURN_OBSERVER_UNIT): sha(RETURN_OBSERVER_UNIT),
                 str(RETURN_OBSERVER): sha(RETURN_OBSERVER),
                 **{str(RETURN_OBSERVER_UNIT.parent / p): d for p, d in r['artifacts'].items()}}
    need(row.unchanged_artifacts({'artifacts': artifacts}), 'return observer unit artifacts drift')
    return {'artifacts': artifacts, 'scope': 'synthetic observer calibration, not DUT proof'}


def initial_index_gate():
    path = common.ROOT / 'build/buffered-index-initial-state-20261025-r2-exact-traces/receipt.json'
    need(sha(path) == '8b47198e5984878c62a522503071d34a18852f1ec4cf449ede6a1cb1a72af140',
         'qualified initial-index receipt drift')
    r = read(path)
    need(r['status'] == 'PASS_BOUNDED_INITIAL_INDEX_NONINTERFERENCE' and
         r['cycle_trace_bytes_exact'] is True and r['new_DUT_compilations'] == 0,
         'bounded exact-trace initial-index gate missing')
    artifacts = {str(path): sha(path), **{str(path.parent / p): d for p, d in r['artifacts'].items()}}
    binding_path = RETURN_OBSERVER_UNIT.parent / 'prior-source-binding.json'
    binding = read(binding_path)
    need(binding['original_path'] == str(RETURN_OBSERVER.relative_to(common.ROOT)) and
         binding['original_sha256'] == 'aef11dbc4a3ae0be541c5d013cad37af013c0015b9ea75d3a695fea2c475f3f4' and
         binding['snapshot_sha256'] == binding['original_sha256'] and
         binding['current_header_sha256'] == sha(RETURN_OBSERVER), 'historical observer preimage binding drift')
    snapshot = common.ROOT / binding['snapshot']
    artifacts[str(snapshot)] = binding['snapshot_sha256']
    artifacts[str(binding_path)] = sha(binding_path)
    plan = read(path.parent / 'plan.json')
    for source, digest in plan['inputs'].items():
        if Path(source).resolve() == RETURN_OBSERVER.resolve():
            need(digest == binding['original_sha256'], 'historical source snapshot does not match executed plan')
        else:
            artifacts[source] = digest
    need(row.unchanged_artifacts({'artifacts': artifacts}), 'index trace/source/artifact drift')
    return {'artifacts': artifacts, 'scope': plan['scope'], 'exact_scalar_fields_per_cycle': 477,
            'historical_header_snapshot': str(snapshot), 'no_universal_noninterference_claim': True}


def dta_latency_contract():
    paths = [common.ROOT / 'src/main/scala/core/ooo/mmu/DataTranslationAdapter.scala']
    queues = list((common.ROOT / 'src/main/scala').rglob('TwoEntryRegisterQueue.scala'))
    need(len(queues) == 1, 'one actual registered queue source required')
    paths += queues
    for p in paths:
        old = subprocess.check_output(['git', 'show', COMMIT + ':' + str(p.relative_to(common.ROOT))], cwd=common.ROOT)
        need(p.read_bytes() == old, 'DTA/registered queue changed from qualified baseline')
    return {'source_inputs': {str(p.relative_to(common.ROOT)): sha(p) for p in paths},
            'minimum_cycles': 2, 'route': 'certified DTA upstream acceptance -> physical acceptance',
            'boundary_1': 'DataTranslationAdapter193-213 registered non-flow virtualRequests ingress',
            'boundary_2': 'DataTranslationAdapter485-506 non-flow checked capture; certified shortcut skips translated only',
            'waiting': 'DataTranslationAdapter695-700 orderedAllowed, response-owner credit and physical READY may hold checked head',
            'queue_law': 'registered headValid, no empty bypass and no full-queue pop credit',
            'dynamic_check': 'each full owner enforces upstream < checked < physical; all latency histograms recomputed from owner timestamps',
            'separate_quantity': 'advisory query -> LSU issue is independently checked by immutable load host with minimum2'}


def parameter_gate(control, candidate, sealed):
    expected = {name: ['false', 'true'] for name in
                ('bufferedReturnFlow', 'translatedResponseEmptyFlow', 'reconstructIssueTokenIndex')}
    for kind in ('config', 'core'):
        a, b, old = control[kind], candidate[kind], sealed[kind]
        need(set(a) == set(old) | {'bufferedReturnFlow'} and
             a['bufferedReturnFlow'] == 'false' and all(a[k] == v for k, v in old.items()),
             'disabled baseline parameter/resource drift: ' + kind)
        need(row.differences(a, b) == expected, 'candidate must be exact three-flag recipe: ' + kind)
    return {'only_delta': expected, 'all_execution_capacities_unchanged': True}


def modules(path):
    data = row.normalize_fir(path.read_bytes())
    declarations = list(re.finditer(rb'^  (?:public )?(?:module|extmodule|intmodule) (\S+) :[^\n]*$', data, re.M))
    need(declarations, 'no FIR modules')
    result = {}
    for i, declaration in enumerate(declarations):
        name = declaration[1].decode()
        need(name not in result, 'duplicate FIR module: ' + name)
        end = declarations[i + 1].start() if i + 1 < len(declarations) else len(data)
        block = data[declaration.start():end]
        need(len(re.findall(rb'^  \S', block, re.M)) == 1, 'unparsed circuit declaration: ' + name)
        result[name] = block
    return data[:declarations[0].start()], result


def module_gate(control, candidate):
    pa, a = modules(control)
    pb, b = modules(candidate)
    def annotation_parts(data):
        text = data.decode()
        need(text.count('%[') == 1, 'exact one FIR annotation block required')
        start = text.index('%[') + 2
        annotations, length = json.JSONDecoder().raw_decode(text[start:])
        need(isinstance(annotations, list), 'FIR annotations must be a list')
        return text[:start], annotations, text[start + length:]
    prefix_a, annotations_a, suffix_a = annotation_parts(pa)
    prefix_b, annotations_b, suffix_b = annotation_parts(pb)
    need(prefix_a == prefix_b and suffix_a == suffix_b, 'non-annotation circuit preamble changed')
    annotation = lambda name: {'class': 'firrtl.transforms.DedupGroupAnnotation',
                               'target': '~|' + name, 'group': name}
    def without_expected(records, names):
        result = records.copy()
        for name in names:
            expected = annotation(name)
            need(result.count(expected) == 1, 'missing/duplicate exact expected dedup annotation: ' + name)
            result.remove(expected)
        return result
    need(without_expected(annotations_a, ALLOW_REMOVED) == without_expected(annotations_b, ALLOW_ADDED),
         'annotation delta exceeds exact return-flow module identities')
    added, removed = set(b) - set(a), set(a) - set(b)
    need(added == ALLOW_ADDED and removed == ALLOW_REMOVED,
         'unexpected added/removed modules: ' + repr((added, removed)))
    changed, port_changes = [], {}
    for name in sorted(set(a) & set(b)):
        need(a[name].splitlines()[0] == b[name].splitlines()[0], 'module kind/visibility changed: ' + name)
        if a[name] == b[name]:
            continue
        need(name in ALLOW_CHANGED, 'unrelated module changed: ' + name)
        changed.append(name)
        ports = lambda text: [p.decode() for p in re.findall(rb'^    (?:input|output) .*$', text, re.M)]
        before, after = ports(a[name]), ports(b[name])
        if before != after:
            port_changes[name] = {'control': before, 'candidate': after}
    need({'IntegerBackend', 'DataResponseBuffer_1', raw.TOP} <= set(changed),
         'expected fixed-row reconstruction/return buffer/observer changes missing')
    # The proof supply, issue-payload RAM and PRF must be byte-identical; this
    # treatment does not acquire a new read port, row, slot or proof capacity.
    for name in ('OwnerBankedPhysicalRegisterFile', 'BankedIssuePayload',
                 'BufferedVirtualRamLoadPreparation', 'ThirdMemoryPreparationRank'):
        need(a[name] == b[name], 'unrelated storage/supply module changed: ' + name)
    return {'changed_modules': changed, 'added_modules': sorted(added), 'removed_modules': sorted(removed),
            'annotation_delta': {'removed_exact_dedup_groups': sorted(ALLOW_REMOVED),
                                 'added_exact_dedup_groups': sorted(ALLOW_ADDED),
                                 'all_other_annotations_and_preamble_exact': True},
            'port_changes_for_independent_review': port_changes,
            'module_hashes': {name: hashlib.sha256(text).hexdigest() for name, text in b.items()},
            'limits': 'bounded delta inventory, not independent functional/feedback-cone proof'}


def emit(args, tools, history_model, sealed, history):
    need(args.compile_receipt is not None and args.component_receipt is not None,
         'current compile and component receipts required for emission')
    component = component_gate(args.component_receipt, args.compile_receipt, tools)
    out = common.BUILD / args.tag
    out.mkdir(parents=True, exist_ok=False)
    before = inputs()
    compiled = row.scala.verify_receipt(args.compile_receipt, common.ROOT)
    report = {'schema': EMIT_SCHEMA, 'status': 'RUNNING', 'inputs': before, 'tools': tools,
              'history_binding': history, 'component_binding': component,
              'observer_unit_binding': observer_unit_gate(),
              'return_observer_unit_binding': return_observer_unit_gate(),
              'initial_index_binding': initial_index_gate(),
              'dta_latency_contract': dta_latency_contract(),
              'compile_receipt': str(args.compile_receipt), 'compile_sha256': sha(args.compile_receipt)}
    save(out / 'emit-receipt.json', report)
    try:
        for profile in (CONTROL, CANDIDATE):
            target = out / profile
            target.mkdir()
            common.run(['java', '-cp', os.pathsep.join(compiled['runClasspathEntries']), MAIN, target, profile],
                       log=target / 'elaborate.log')
            row.scala.verify_receipt(args.compile_receipt, common.ROOT)
        a = row.normalize_fir((history_model / (raw.TOP + '.fir')).read_bytes())
        b = row.normalize_fir((out / CONTROL / (raw.TOP + '.fir')).read_bytes())
        delta = out / 'disabled-control.diff'
        delta.write_text('' if a == b else ''.join(difflib.unified_diff(a.decode().splitlines(True), b.decode().splitlines(True))))
        need(a == b, 'FRESH_CONTROL_REQUIRED: disabled FIR differs beyond source annotations')
        report['disabled_control_gate'] = {'source_only_exact': True, 'diff_sha256': sha(delta)}
        report['parameter_gate'] = parameter_gate(row.effective(out / CONTROL), row.effective(out / CANDIDATE), sealed['effective_parameters'])
        report['cache_gate'] = raw.cache_gate(out / CONTROL, out / CANDIDATE)
        report['module_gate'] = module_gate(out / CONTROL / (raw.TOP + '.fir'), out / CANDIDATE / (raw.TOP + '.fir'))
        report['status'] = 'PASS_FROZEN_FIR_AWAIT_INDEPENDENT_STRUCTURE_REVIEW'
    except BaseException as error:
        report.update(status='FAIL', failure=f'{type(error).__name__}: {error}')
        raise
    finally:
        report['inputs_unchanged'] = inputs() == before
        need(report['inputs_unchanged'], 'source drift during CPU emission')
        report['artifacts'] = {str(p.relative_to(out)): sha(p) for p in out.rglob('*')
                               if p.is_file() and p.name != 'emit-receipt.json'}
        save(out / 'emit-receipt.json', report)
    return report


def reviewed_emission(args, tools):
    out = common.BUILD / args.tag
    path = out / 'emit-receipt.json'
    r = read(path)
    need(r['schema'] == EMIT_SCHEMA and r['status'] == 'PASS_FROZEN_FIR_AWAIT_INDEPENDENT_STRUCTURE_REVIEW' and
         r['inputs_unchanged'] is True and r['inputs'] == inputs() and r['tools'] == tools,
         'unchanged successful bounded emission required')
    compile_path = Path(r['compile_receipt'])
    need(sha(compile_path) == r['compile_sha256'], 'emission compile receipt changed')
    row.scala.verify_receipt(compile_path, common.ROOT)
    artifacts = {str(path): sha(path), str(compile_path): sha(compile_path),
                 **{str(out / p): d for p, d in r['artifacts'].items()}}
    need(row.unchanged_artifacts({'artifacts': artifacts}), 'sealed emission changed')
    review = read(args.structure_receipt)
    need(review.get('schema') == 'valence-buffered-return-flow-structure-v1' and
         review.get('status') == 'PASS_BUFFERED_RETURN_FLOW_SOURCE_AND_STRUCTURE' and
         review['emit_receipt_sha256'] == sha(path) and review['compile_receipt_sha256'] == sha(compile_path),
         'exact independent source/emitted structure approval required')
    required_gates = {'fullchain_scc', 'no_live_reply_to_completion',
                      'no_consumer_ready_to_physical_ready', 'index_all_consumers'}
    need(isinstance(review.get('gates'), dict) and required_gates <= set(review['gates']) and
         all(review['gates'][key] == 'PASS' for key in required_gates),
         'independent full-chain structural gates incomplete')
    need(review.get('inputs') and all(sha(common.ROOT / p) == d for p, d in review['inputs'].items()),
         'independent structure source inputs drift')
    artifacts[str(args.structure_receipt)] = sha(args.structure_receipt)
    artifacts.update({str(args.structure_receipt.parent / p): d for p, d in review['artifacts'].items()})
    need(row.unchanged_artifacts({'artifacts': artifacts}), 'independent structure artifacts drift')
    for key in ('history_binding', 'component_binding', 'observer_unit_binding', 'return_observer_unit_binding', 'initial_index_binding'):
        need(row.unchanged_artifacts(r[key]), key + ' changed after emission')
        artifacts.update(r[key]['artifacts'])
    return out, r, {'artifacts': artifacts, 'independent_structure_pass': True}


def load_owners(log):
    result = {name: [] for name in raw.LOAD_CASES}
    seen = {name: set() for name in raw.LOAD_CASES}
    for line in log.read_text().splitlines():
        if not line.startswith('LOAD_OWNER '):
            continue
        r = json.loads(line[len('LOAD_OWNER '):])
        need(r['guest'] in result, 'unknown load owner guest')
        token = (r['index'], r['tag'])
        need(token not in seen[r['guest']], 'duplicate full-token load owner')
        seen[r['guest']].add(token)
        result[r['guest']].append(r)
    for name, owners in result.items():
        need(owners and all(not (x['retired'] and x['cancelled']) and
                            (not x['retired'] or x['architectural_PC_occurrence'] > 0) for x in owners),
             'invalid retired/cancelled architectural occurrence: ' + name)
        result[name] = sorted(owners, key=lambda x: x['start'])
    return result


def comparisons(control, candidate):
    report = raw.comparisons(control, candidate, control)
    for name in raw.VM_CASES:
        a, b = control['latency_owners'][name], candidate['latency_owners'][name]
        need(len(a) == len(b) and all(all(x[k] == y[k] for k in ('pc', 'va', 'pa', 'write'))
                                    for x, y in zip(a, b)), 'VM ordered architectural traffic changed: ' + name)
    report['load_owner_comparisons'] = {}
    for name in raw.LOAD_CASES:
        a, b = control['load_owners'][name], candidate['load_owners'][name]
        def committed(owners):
            result = {}
            for owner in owners:
                if not owner['retired']:
                    continue
                key = (owner['pc'], owner['architectural_PC_occurrence'])
                need(key not in result, 'duplicate independent committed load occurrence')
                result[key] = owner
            return result
        ca, cb = committed(a), committed(b)
        need(ca.keys() == cb.keys() and all(all(ca[k][f] == cb[k][f] for f in ('va', 'roi')) for k in ca),
             'independent committed load PC/occurrence/VA/ROI changed: ' + name)
        report['load_owner_comparisons'][name] = {
            'committed_occurrences': len(ca),
            'committed_differences': [{'pc': k[0], 'architectural_PC_occurrence': k[1],
                                      'differences': row.differences(ca[k], cb[k])} for k in ca if ca[k] != cb[k]],
            'control_nonretired': [x for x in a if not x['retired']],
            'candidate_nonretired': [x for x in b if not x['retired']],
            'control_all_owners': a, 'candidate_all_owners': b,
            'scope': 'numeric ROB/tag/start ordinals may differ; full-token ownership remains checked within each DUT'}
        roi = [x for x in b if x['retired'] and x['roi']]
        gaps = dict(Counter(str(y['start'] - x['start']) for x, y in zip(roi, roi[1:])))
        case = next(x for x in candidate['load_cases'] if x['name'] == name)
        need(case['roi_owner_start_gaps'] == gaps and len(roi) == case['measured_loads'],
             'load full-owner gap/ROI conservation failed')
    a, b = control['load_cases'][0], candidate['load_cases'][0]
    report['hot_improved'] = b['roi_work_cycles'] < a['roi_work_cycles']
    report['hot_gap2_count_reduced'] = b['roi_owner_start_gaps'].get('2', 0) < a['roi_owner_start_gaps'].get('2', 0)
    report['cycle_regressions'] = [r['name'] for r in report['VM'] + report['loads'] if r['delta_work'] > 0 or r['delta_roi'] > 0]
    return report


def host_adapters(model):
    """Every allowed edit is reversible, unique and passive; original bytes stay sealed."""
    raw.host_source_gate()
    include = '#include "buffered_source_lifetime_observer.h"\n#include "buffered_return_flow_observer.h"\n'
    member = '    buffered_source_lifetime::Observer sourceObserver;\n    buffered_return_flow::Observer returnObserver;\n'
    occupancy = ('unsigned(bool(dut.get_proof$$descriptorOwner$$valid()))+'
                 'unsigned(bool(dut.get_proof$$translatedOwner$$valid()))+'
                 'unsigned(bool(dut.get_proof$$preparedOwner$$valid()))')
    specs = {
        'vm': (raw.HOST, [
            ('#include "gsim_model_storage.h"\n', '#include "gsim_model_storage.h"\n' + include),
            ('class Run {\n', 'class Run {\n' + member),
            ('        dut.step();\n', '        dut.step();\n        sourceObserver.observe(dut);returnObserver.observe(dut);\n'),
            ('        std::cout << "A1_VM_STAGE_METRIC ',
             '        sourceObserver.report(std::cout, program.name);returnObserver.report(std::cout, program.name);\n        std::cout << "A1_VM_STAGE_METRIC ')]),
        'load': (raw.LOAD_HOST, [
            ('#include "gsim_model_storage.h"\n', '#include "gsim_model_storage.h"\n' + include),
            ('class Run {\n', 'class Run {\n' + member),
            ('dut.step();Sample s;', 'dut.step();sourceObserver.observe(dut);returnObserver.observe(dut);Sample s;'),
            ('report();proofReport();}', 'report();proofReport();sourceObserver.report(std::cout,program.name);returnObserver.report(std::cout,program.name);}'),
            (occupancy, 'unsigned(dut.get_bufferedProof$$occupancy())')])}
    records = {}
    for kind, (original, edits) in specs.items():
        before = original.read_text()
        after = before
        for old, new in edits:
            need(after.count(old) == 1 and new not in after, 'adapter unique edit precondition: ' + kind)
            after = after.replace(old, new, 1)
        restored = after
        for old, new in reversed(edits):
            need(restored.count(new) == 1, 'adapter inverse edit precondition: ' + kind)
            restored = restored.replace(new, old, 1)
        need(restored == before, 'adapter changed original functional logic: ' + kind)
        target = model / (original.stem + '_buffered_return.cpp')
        target.write_text(after)
        diff = target.with_suffix('.diff')
        diff.write_text(''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                                   fromfile=str(original), tofile=str(target))))
        records[kind] = {'source': str(original), 'source_sha256': sha(original),
                         'adapter': str(target), 'adapter_sha256': sha(target), 'diff_sha256': sha(diff),
                         'allowed_exact_edits': len(edits), 'inverse_original_bytes_exact': True}
    headers = {}
    pending = [OBSERVER, RETURN_OBSERVER, common.HERE / 'harness/isa_model.h', common.HERE / 'harness/gsim_model_storage.h']
    while pending:
        source = pending.pop(0)
        if str(source) in headers:
            continue
        need(source.is_file() and source.resolve().is_relative_to((common.HERE / 'harness').resolve()),
             'quoted host header outside immutable harness closure')
        target = model / source.name
        need(not target.exists(), 'candidate header destination already exists')
        shutil.copyfile(source, target)
        need(sha(target) == sha(source), 'copied immutable header drift')
        headers[str(source)] = sha(source)
        for name in re.findall(r'^\s*#include\s+"([^"]+)"', source.read_text(), re.M):
            pending.append(source.parent / name)
    records['headers'] = headers
    return records


def verify_build(model, cxx, host):
    path = model / 'run-compile-receipt.json'
    r = read(path)
    generated = {str(p) for p in model.glob(raw.TOP + '[0-9]*.cpp')}
    flags = ['-std=c++20', '-O1', '-g', '-fsanitize=address,undefined',
             '-fno-sanitize-recover=all', '-I' + str(model)]
    headers = {str(p): sha(p) for p in sorted(model.glob('*.h'))}
    need(r['schema'] == 'real-gsim-header-gate-v1' and r['syntax_pass'] is True and
         r['host'] == str(host) and r['host_sha256'] == sha(host) and r['flags'] == flags and
         r['compiler'] == str(Path(cxx).resolve()) and r['headers'] == headers,
         'candidate real-header/compiler/host binding mismatch')
    entries = r['objects']
    need(generated and len(entries) == len(generated) + 1 and
         {x['source'] for x in entries} == generated | {str(host)}, 'candidate DUT/host object set mismatch')
    bound = {str(path): sha(path), **headers}
    objects = []
    for entry in entries:
        source, obj = Path(entry['source']), Path(entry['object'])
        key = hashlib.sha256(json.dumps({'source': sha(source), 'headers': headers,
              'flags': flags, 'compiler': sha(cxx)}, sort_keys=True).encode()).hexdigest()
        need(entry['reused'] is False and entry['source_sha256'] == sha(source) and
             entry['key'] == key and obj == model / (source.stem + '-' + key[:16] + '.o') and
             entry['object_sha256'] == sha(obj), 'fresh candidate object content key mismatch')
        bound[str(source)], bound[str(obj)] = sha(source), sha(obj)
        if str(source) in generated:
            objects.append(str(obj))
    need(r['binary_sha256'] == sha(model / 'run'), 'candidate binary mismatch')
    bound[str(model / 'run')] = sha(model / 'run')
    return {'artifacts': bound, 'DUT_objects': objects, 'ordered_flags': flags,
            'all_DUT_objects_fresh': True, 'host': str(host)}


def candidate_abi_gate(model):
    """Exact ON+ROB16 observation layout, never a missing-field fallback."""
    parameters = row.effective(model)
    for kind in ('config', 'core'):
        p = parameters[kind]
        need(all(p.get(k) == 'true' for k in
                 ('bufferedReturnFlow', 'translatedResponseEmptyFlow', 'reconstructIssueTokenIndex',
                  'bufferedThirdRankLoadProof')), 'observer requires exact combined ON identity: ' + kind)
    p = parameters['core']
    need(p['robEntries'] == '16' and p['tagBits'] == '64' and p['memoryEntries'] == '4',
         'observer only qualified for ROB16/full64/LSU4')
    header = model / (raw.TOP + '.h')
    data = header.read_text()
    for field, ctype in (('token$$tag', 'uint64_t'), ('source1', 'uint8_t'),
                         ('source2', 'uint8_t'), ('destination', 'uint8_t'), ('writesRd', 'uint8_t')):
        name = 'tile$core$core$core$backend$queue$$renamed$$' + field
        need(re.search(r'^' + ctype + ' ' + re.escape(name) + r'\[16\];', data, re.M),
             'exact full-tag/source row ABI missing: ' + field)
    for field in ('rawIndices', 'viewIndices'):
        need('get_returnFlow$$' + field + '(' in data, 'explicit candidate index observation missing: ' + field)
    return {'header_sha256': sha(header), 'rob_entries': 16, 'tag_bits': 64,
            'raw_index': 'explicit packed rawIndices observation, not consumer token',
            'consumer_index': 'explicit packed viewIndices; static slot checked against allocation ledger',
            'missing_field_fallback': False}


def build_candidate(model, tools, adapters):
    need(not (model / 'run').exists() and not list(model.glob('*.o')) and
         not list(model.glob(raw.TOP + '[0-9]*.cpp')), 'candidate DUT already built/generated')
    gsim, cxx = tools['gsim']['path'], tools['compiler']['command']
    common.run([gsim, '--threads=1', '--dir=' + str(model), model / (raw.TOP + '.fir')],
               log=model / 'generate.log')
    sources = sorted(model.glob(raw.TOP + '[0-9]*.cpp'))
    need(sources, 'no actual GSIM translation units')
    abi = candidate_abi_gate(model)
    save(model / 'return-observer-abi.json', abi)
    host = Path(adapters['vm']['adapter'])
    raw.gate.install()
    common.run([cxx, '-std=c++20', '-O1', '-g', '-fsanitize=address,undefined',
                '-fno-sanitize-recover=all', '-I' + str(model), *sources, host, '-ldl', '-o', model / 'run'],
               log=model / 'compile.log', timeout=600)
    return verify_build(model, cxx, host)


def load_host(model, tools, first, adapter):
    need(row.unchanged_artifacts(first), 'candidate objects drift before load link')
    target = model / 'load-host'
    target.mkdir(exist_ok=False)
    cxx, flags = tools['compiler']['command'], first['ordered_flags']
    host = Path(adapter['adapter'])
    need(sha(host) == adapter['adapter_sha256'], 'candidate load adapter drift')
    obj, binary = target / 'load-host.o', target / 'run'
    common.run([cxx, *flags, '-fsyntax-only', host], log=target / 'syntax.log', timeout=180)
    common.run([cxx, *flags, '-c', host, '-o', obj], log=target / 'compile.log', timeout=600)
    common.run([cxx, *flags, *first['DUT_objects'], obj, '-ldl', '-o', binary],
               log=target / 'link.log', timeout=600)
    need(row.unchanged_artifacts(first), 'candidate DUT changed during host-only link')
    return {'artifacts': {str(host): sha(host), str(obj): sha(obj), str(binary): sha(binary)},
            'new_DUT_compilations': 0, 'new_host_compilations': 1}


def observer_metrics(log, names):
    prefix = 'BUFFERED_SOURCE_LIFETIME_PASS '
    records = []
    for line in log.read_text().splitlines():
        if not line.startswith(prefix):
            continue
        r = base.unique_object([x.split('=', 1) for x in line[len(prefix):].split()])
        need(r.pop('scope') == 'accepted_allocation_source_lifetime_not_ISA_or_rename', 'observer scope drift')
        guest = r.pop('guest')
        need(all(re.fullmatch(r'[0-9]+', v) for v in r.values()), 'observer nonnumeric counter')
        records.append({'name': guest, **{k: int(v) for k, v in r.items()}})
    need([x['name'] for x in records] == list(names), 'missing/duplicate source-lifetime observer guest')
    need(all(x['cycles'] > 0 and x['allocations'] > 0 and x['candidate_checks'] > 0 for x in records),
         'empty source-lifetime observer')
    return records


def return_observer_metrics(log, names):
    prefix = 'BUFFERED_RETURN_FLOW '
    fields = {'cycles', 'allocations', 'live_checks', 'accepted', 'consumed', 'bypass',
              'captures', 'queued_pops', 'full_pop', 'faults', 'fp', 'slot_starts', 'slot_reply_accepts',
              'slot_completions', 'slot_released_without_completion'}
    result = []
    for line in log.read_text().splitlines():
        if not line.startswith(prefix):
            continue
        r = base.unique_object([x.split('=', 1) for x in line[len(prefix):].split()])
        name = r.pop('name')
        need(set(r) == fields and all(re.fullmatch(r'[0-9]+', v) for v in r.values()),
             'return/index observer schema or counter drift')
        result.append({'name': name, **{k: int(v) for k, v in r.items()}})
    need([x['name'] for x in result] == list(names), 'missing/duplicate return/index observer guest')
    need(all(x['cycles'] > 0 and x['allocations'] > 0 and x['live_checks'] > 0 and
             x['accepted'] > 0 and x['accepted'] == x['consumed'] and
             x['consumed'] == x['bypass'] + x['queued_pops'] and
             x['accepted'] == x['bypass'] + x['captures'] for x in result),
         'return/index observer empty coverage or final transaction conservation failed')
    for record in result:
        events = []
        for line in log.read_text().splitlines():
            if not line.startswith('BUFFERED_LSU_SLOT_REPLY '):
                continue
            event = base.unique_object([x.split('=', 1) for x in line.split()[1:]])
            if event.pop('name') != record['name']:
                continue
            need(set(event) == {'cycle', 'slot', 'token_index', 'token_tag', 'start_cycle',
                               'outer_reply_same_cycle', 'any_complete_same_cycle'} and
                 all(re.fullmatch(r'[0-9]+', v) for v in event.values()), 'slot reply event schema')
            event = {k: int(v) for k, v in event.items()}
            need(event['slot'] < 4 and event['token_index'] < 16 and event['token_tag'] < 2**64 and
                 event['cycle'] >= event['start_cycle'], 'slot reply event identity/time bounds')
            events.append(event)
        need(len(events) == record['slot_reply_accepts'] > 0, 'slot reply event coverage/count missing')
        need(record['slot_starts'] == record['slot_completions'] + record['slot_released_without_completion'],
             'slot start-to-terminal conservation')
        record['slot_reply_events'] = events
    return result


def candidate_vm_metrics(model):
    """Candidate DTA waits may exceed two; owner/register/conservation gates remain.

    This is DTA upstream->physical latency, not advisory query->LSU-issue latency.
    The immutable C++ host's first-attempt exact flow guards are NOT rewritten.
    """
    log = model / 'test.log'
    r = {field: raw.parse(log, prefix, raw.VM_CASES, row.PASS) for field, prefix in raw.VM_PREFIXES.items()}
    need('CHECKED_FLOW_METRIC ' not in log.read_text(), 'obsolete scalar flow report')
    r['latency_owners'], r['owner_stage_histograms'] = raw.read_owners(log)
    for n, name in enumerate(raw.VM_CASES):
        case, stage, traffic, flow = (r[k][n] for k in ('cases', 'stages', 'forwarding', 'flow'))
        need(case['retired'] == 233 and case['bootstrap_retired'] == 32 and case['roi_retired'] == 201 and
             case['placement'] == 'rom' and case['work_cycles'] == case['bootstrap_cycles'] + case['roi_cycles'],
             'original VM guest/retirement/cycle accounting changed')
        need(all(traffic[k] == 49 for k in ('architectural_stores', 'physical_stores', 'store_replies', 'store_completions')) and
             traffic['forwarded_loads'] == traffic['forwarded_retired'] == 48 and traffic['alias_forwards'] == 0 and
             traffic['architectural_loads'] == (57 if n == 0 else 105) and
             traffic['upstream_loads'] == traffic['physical_loads'] == traffic['load_replies'] == traffic['architectural_loads'] - 48,
             'original architectural/forward/actual traffic conservation failed')
        row.check_prepared(r['prepared_store'][n], traffic)
        need(stage['registered_translation'] == 0 and stage['accepted_prefix_validation'] is False and
             stage['circular_payload'] == 1, 'unexpected active VM profile')
        need(set(flow) == raw.FLOW_FIELDS and all(type(v) is int and v >= 0 for k, v in flow.items()
                                                if k != 'name' and k not in raw.FLOW_HISTOGRAMS), 'flow metric schema changed')
        hist = {k: raw.histogram(flow[k]) for k in raw.FLOW_HISTOGRAMS}
        owners = r['latency_owners'][name]
        need(flow['registered'] == 0 and flow['requests'] == flow['replies'] == len(owners) == 49 + traffic['physical_loads'] and
             flow['prechecked_samples'] == stage['prechecked_loads'] > 0 and
             flow['prechecked_passes'] + flow['certified_spills'] == flow['prechecked_samples'],
             'full-token sample/pass/spill conservation failed')
        need(all(hist[k] == r['owner_stage_histograms'][name][k]['upstream_physical'] for k in raw.FLOW_HISTOGRAMS),
             'flow histogram disagrees with actual full-owner timestamps')
        need(hist['raw_store_latency'] == {2: 48} and hist['raw_load_latency'] == {2: 2} and
             hist['cold_store_latency'] == {24: 1} and flow['raw_passes'] == 50,
             'original exact raw-route count/latency guards changed; requires separate review')
        need(min(hist['prechecked_latency']) >= 2 and sum(hist['prechecked_latency'].values()) == flow['prechecked_samples'],
             'certified DTA permission/physical register minimum or conservation violated')
    return r


def build_run(args, tools, history_model, sealed, history):
    out, emission, approval = reviewed_emission(args, tools)
    need(not (out / 'receipt.json').exists(), 'fresh bounded build-run only; prior attempt preserved')
    before = inputs()
    report = {'schema': RESULT_SCHEMA, 'status': 'RUNNING', 'inputs_before': before,
              'tools_before': tools, 'history_binding': history, 'emission_review_binding': approval,
              'models': {}, 'new_DUT_builds': 0, 'hardware_guest_runs': 0,
              'limits': 'focused CPU and source-lifetime checks; no whole-CPU formal/STA/Fmax/board claim'}
    base.save_receipt(out, report)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    try:
        replay = out / CONTROL
        (replay / 'load-host').mkdir()
        for name, binary, flags in [('test.log', history_model / 'run', []),
                                    ('load-host/test.log', history_model / 'load-host/run', ['--trace'])]:
            common.run([binary, *flags], env=base.runtime_env(), log=replay / name, timeout=180)
            need((replay / name).read_bytes() == (history_model / name).read_bytes(), 'sealed control replay differs: ' + name)
        control = donor.candidate_vm_metrics(replay)
        control['load_cases'] = raw.parse(replay / 'load-host/test.log', 'LOAD_SUPPLY_METRIC ', raw.LOAD_CASES, 'LOAD_SUPPLY_PASS')
        control['proof_metrics'] = raw.parse(replay / 'load-host/test.log', 'ELASTIC_PROOF_METRIC ', raw.LOAD_CASES, 'LOAD_SUPPLY_PASS')
        control['load_owners'] = load_owners(replay / 'load-host/test.log')
        for key in (*raw.VM_PREFIXES, 'latency_owners', 'owner_stage_histograms', 'load_cases', 'proof_metrics'):
            need(json.loads(json.dumps(control[key])) == sealed[key], 'historical baseline metric drift: ' + key)
        report['models'][CONTROL] = control
        report['hardware_guest_runs'] += 4
        model = out / CANDIDATE
        adapters = host_adapters(model)
        report['host_adapters'] = adapters
        candidate = {'effective_parameters': row.effective(model)}
        report['models'][CANDIDATE] = candidate
        candidate['first_build'] = build_candidate(model, tools, adapters)
        report['new_DUT_builds'] = 1
        base.save_receipt(out, report)
        common.run([model / 'run'], env=base.runtime_env(), log=model / 'test.log', timeout=180)
        candidate.update(candidate_vm_metrics(model))
        candidate['vm_source_lifetime'] = observer_metrics(model / 'test.log', raw.VM_CASES)
        candidate['vm_return_index'] = return_observer_metrics(model / 'test.log', raw.VM_CASES)
        candidate['second_host'] = load_host(model, tools, candidate['first_build'], adapters['load'])
        common.run([model / 'load-host/run', '--trace'], env=base.runtime_env(), log=model / 'load-host/test.log', timeout=180)
        candidate['load_cases'] = raw.parse(model / 'load-host/test.log', 'LOAD_SUPPLY_METRIC ', raw.LOAD_CASES, 'LOAD_SUPPLY_PASS')
        candidate['proof_metrics'] = raw.parse(model / 'load-host/test.log', 'ELASTIC_PROOF_METRIC ', raw.LOAD_CASES, 'LOAD_SUPPLY_PASS')
        candidate['load_owners'] = load_owners(model / 'load-host/test.log')
        candidate['load_source_lifetime'] = observer_metrics(model / 'load-host/test.log', raw.LOAD_CASES)
        candidate['load_return_index'] = return_observer_metrics(model / 'load-host/test.log', raw.LOAD_CASES)
        all_observers = candidate['vm_source_lifetime'] + candidate['load_source_lifetime']
        need(all(sum(x[k] for x in all_observers) > 0 for k in
                 ('rank3_checks', 'rank3_captures', 'protected_checks', 'producer_before_capture', 'live_owner_checks')),
             'required actual third-rank/source-lifetime coverage missing')
        report['hardware_guest_runs'] += 4
        report['comparisons'] = comparisons(control, candidate)
        candidate['negative'] = raw.negative(model)
        report['status'] = ('PASS_FOCUSED_BUFFERED_RETURN_FLOW_WITH_HOT_GAIN'
                            if report['comparisons']['hot_improved'] and report['comparisons']['hot_gap2_count_reduced']
                            else 'PASS_FUNCTIONAL_NO_HOT_GAIN_NOT_PROMOTABLE')
    except BaseException as error:
        report.update(status='FAIL', failure=f'{type(error).__name__}: {error}')
        raise
    finally:
        report['inputs_unchanged'] = inputs() == before
        report['tools_unchanged'] = epoch.tool_binding(args.tool_receipt) == tools
        checks = [report['inputs_unchanged'], report['tools_unchanged']]
        for key in ('history_binding', 'emission_review_binding'):
            report[key + '_unchanged'] = row.unchanged_artifacts(report[key])
            checks.append(report[key + '_unchanged'])
        for model in report['models'].values():
            for key in ('first_build', 'second_host'):
                checks.append(row.unchanged_artifacts(model.get(key, {})))
        if not all(checks):
            report['status'] = 'FAIL_SOURCE_TOOL_OR_ARTIFACT_DRIFT'
        report['artifacts_sha256'] = {str(p.relative_to(out)): sha(p) for p in out.rglob('*')
                                     if p.is_file() and p.name not in ('receipt.json', 'receipt.json.tmp')}
        base.save_receipt(out, report)
    need(report['status'].startswith('PASS_'), report['status'])
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--tool-receipt', type=Path, required=True)
    parser.add_argument('--compile-receipt', type=Path)
    parser.add_argument('--component-receipt', type=Path)
    parser.add_argument('--structure-receipt', type=Path)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--emit', action='store_true')
    modes.add_argument('--build-run', action='store_true')
    args = parser.parse_args()
    need(re.fullmatch(r'[A-Za-z0-9_-]+', args.tag), 'safe fresh tag required')
    tools = epoch.tool_binding(args.tool_receipt)
    history_model, sealed, history = bind_history(tools)
    source_gate = raw.host_source_gate()
    if args.emit:
        result = emit(args, tools, history_model, sealed, history)
    elif args.build_run:
        need(args.structure_receipt is not None, 'independent structure receipt required')
        result = build_run(args, tools, history_model, sealed, history)
    else:
        result = {'status': 'PREFLIGHT_ONLY', 'sealed_7daf119_control_verified': True,
                  'source_gate': source_gate, 'new_DUT_builds': 0}
    print(json.dumps({'status': result['status'], 'new_DUT_builds': result.get('new_DUT_builds', 0)}, indent=2))


if __name__ == '__main__':
    main()
