#!/usr/bin/env python3
"""One fresh factored-PMP CPU with an exactly bound same-tool existing control.

Emit only a structural disabled control, never recompile its DUT. Rerun its
verified binaries and require byte-exact original logs, then build one fresh
candidate using immutable existing VM/load hosts. All metrics and owner traces
must be exactly equal. Component and current Scala gates precede execution.
"""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import re
import resource
import sys

sys.dont_write_bytecode = True
import registered_raw_certified_cpu as raw
import factored_pmp_structure as structure

common, base, row = raw.common, raw.base, raw.row
need, sha, read = raw.need, raw.sha, raw.read
CONTROL = raw.CONTROL
CANDIDATE = CONTROL + '-factored-pmp'
MAIN = 'soc.core.ooo.FactoredDataPmpCpuGsimMain'
REFERENCE = common.BUILD / 'registered-raw-certified-cpu-20261025-r1/receipt.json'
REFERENCE_SHA = '870131f244a4796d2c3caac3bbbb055fe8bff18426ff0b1d5989356043a29377'
SELF = Path(__file__).resolve()
WRAPPER = common.ROOT / 'src/test/scala/platform/FactoredDataPmpCpuGsim.scala'
METRICS = (*raw.VM_PREFIXES, 'latency_owners', 'owner_stage_histograms', 'load_cases', 'proof_metrics')


def inputs():
    return {**raw.inputs(), str(SELF.relative_to(common.ROOT)): sha(SELF),
            str(WRAPPER.relative_to(common.ROOT)): sha(WRAPPER),
            str(Path(structure.__file__).relative_to(common.ROOT)): sha(Path(structure.__file__)),
            'simulator/gsim/registered_raw_certified_cones.py':
                sha(common.HERE / 'registered_raw_certified_cones.py')}


def bind_control(tools):
    need(sha(REFERENCE) == REFERENCE_SHA, 'sealed same-tool control receipt changed')
    prior = read(REFERENCE)
    need(prior['status'] == 'PASS_BOUNDED_REGISTERED_RAW_CERTIFIED_ACTUAL_CPU' and
         prior['tools_before'] == prior['tools_after'] == tools,
         'previous control is not a passed identical-tool run')
    record = prior['models'][CONTROL]
    model = REFERENCE.parent / CONTROL
    for key in ('first_build', 'second_host', 'execution_artifacts'):
        need(row.unchanged_artifacts(record[key]), 'control artifact mismatch: ' + key)
    need(raw.verify_first_build(model, tools['compiler']['command']) == record['first_build'],
         'control generated objects/content keys differ from sealed receipt')
    artifacts = {str(REFERENCE): REFERENCE_SHA}
    for key in ('first_build', 'second_host', 'execution_artifacts'):
        artifacts.update(record[key]['artifacts'])
    return model, record, {'receipt': str(REFERENCE), 'sha256': REFERENCE_SHA, 'artifacts': artifacts,
                          'same_tool_epoch': True, 'new_control_DUT_compilations': 0}


def parameter_gate(control, candidate, sealed):
    for kind in ('config', 'core'):
        a, b, old = control[kind], candidate[kind], sealed[kind]
        need(set(a) == set(old) | {'factoredDataPmpRange'} and a['factoredDataPmpRange'] == 'false' and
             all(a[k] == v for k, v in old.items()), 'disabled control parameter/resource drift: ' + kind)
        need(row.differences(a, b) == {'factoredDataPmpRange': ['false', 'true']},
             'candidate is not the exact one-flag comparator change: ' + kind)
    return {'only_delta': 'factoredDataPmpRange false->true', 'all_capacities_and_stages_unchanged': True}


def replay_control(model, out, sealed):
    out.mkdir()
    common.run([model / 'run'], env=base.runtime_env(), log=out / 'test.log', timeout=180)
    need((out / 'test.log').read_bytes() == (model / 'test.log').read_bytes(),
         'replayed control VM log differs from sealed same-tool result')
    record = raw.vm_metrics(out, False)
    common.run([model / 'load-host/run', '--trace'], env=base.runtime_env(), log=out / 'load.log', timeout=180)
    need((out / 'load.log').read_bytes() == (model / 'load-host/test.log').read_bytes(),
         'replayed control load trace differs from sealed same-tool result')
    record['load_cases'] = raw.parse(out / 'load.log', 'LOAD_SUPPLY_METRIC ', raw.LOAD_CASES, 'LOAD_SUPPLY_PASS')
    record['proof_metrics'] = raw.parse(out / 'load.log', 'ELASTIC_PROOF_METRIC ', raw.LOAD_CASES, 'LOAD_SUPPLY_PASS')
    for key in METRICS:
        # JSON roundtrip normalizes histogram integer keys in the stored receipt.
        need(json.loads(json.dumps(record[key])) == sealed[key], 'replayed sealed metric mismatch: ' + key)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--gsim', type=Path, required=True)
    parser.add_argument('--compile-receipt', type=Path)
    parser.add_argument('--component-receipt', type=Path)
    parser.add_argument('--build-run', action='store_true')
    args = parser.parse_args()
    need(re.fullmatch(r'[A-Za-z0-9_-]+', args.tag), 'safe fresh tag required')
    before, source_gate = inputs(), raw.host_source_gate()
    tools = base.tool_binding(True)
    control_model, sealed, control_binding = bind_control(tools)
    if not args.build_run:
        print(json.dumps({'status': 'PREFLIGHT_ONLY', 'source_gate': source_gate,
                          'same_tool_control_verified': True, 'new_DUT_builds': 0}, indent=2))
        return
    need(args.compile_receipt is not None and args.component_receipt is not None,
         'current Scala and factored-PMP component receipts required')
    component = read(args.component_receipt)
    need(component.get('schema') == 'valence-generic-pmp-equivalence-v1' and
         component.get('status') == 'PASS_GENERIC_PMP_EQUIVALENCE', 'complete factored-PMP component gate required')
    need(isinstance(component.get('sources'), dict) and component['sources'] and
         all(sha(common.ROOT / path) == digest for path, digest in component['sources'].items()),
         'component frozen source inputs differ from current candidate')
    need(component['gsim_sha256'] == tools['gsim']['sha256'] and
         component['compiler_sha256'] == tools['compiler']['sha256'] and
         component['compile_receipt_sha256'] == sha(args.compile_receipt),
         'component tool/compiled-source identity mismatch')
    need(args.gsim.resolve() == Path(tools['gsim']['path']).resolve(), 'pinned GSIM path required')
    out = common.BUILD / args.tag
    out.mkdir(parents=True, exist_ok=False)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    report = {'schema': 'factored-data-pmp-single-new-cpu-v1', 'status': 'RUNNING',
              'source_revision': base.git(common.ROOT, 'rev-parse', 'HEAD').strip(),
              'inputs_before': before, 'tools_before': tools, 'control_binding': control_binding,
              'source_gate': source_gate, 'new_DUT_builds': 0, 'hardware_guest_runs': 0,
              'component_binding': {'artifacts': {str(args.component_receipt): sha(args.component_receipt)}},
              'limits': 'No PPA/STA/board/SoC/NEMU; one candidate, four immutable guests, exact same-tool control reuse.'}
    base.save_receipt(out, report)
    try:
        row.bind_compile_receipt(args.compile_receipt, report)
        for profile in (CONTROL, CANDIDATE):
            row.scala.verify_receipt(args.compile_receipt, common.ROOT)
            need(inputs() == before, 'source drift before emission')
            target = out / profile
            target.mkdir()
            common.run(['mill', '-i', 'IonSoC.test.runMain', MAIN, target, profile], log=target / 'elaborate.log')
            row.scala.verify_receipt(args.compile_receipt, common.ROOT)
        a, b = row.normalize_fir((control_model / (raw.TOP + '.fir')).read_bytes()), row.normalize_fir(
            (out / CONTROL / (raw.TOP + '.fir')).read_bytes())
        delta = out / 'disabled-control.diff'
        delta.write_text('' if a == b else ''.join(difflib.unified_diff(
            a.decode().splitlines(True), b.decode().splitlines(True))))
        need(a == b, 'FRESH_CONTROL_REQUIRED: disabled FIR differs beyond source annotations')
        report['disabled_control_gate'] = {'exact_source_only': True, 'diff_sha256': sha(delta)}
        report['parameter_gate'] = parameter_gate(row.effective(out / CONTROL), row.effective(out / CANDIDATE),
                                                  sealed['effective_parameters'])
        report['cache_gate'] = raw.cache_gate(out / CONTROL, out / CANDIDATE)
        report['structure_gate'] = structure.review(out / CANDIDATE / (raw.TOP + '.fir'))
        instances = report['structure_gate']['instances']
        need(len(instances) == 1 and '.legacyPmp.' in instances[0]['path'],
             'factored comparator must occur exactly once in the main legacy DTA PMP')
        report['replayed_control'] = replay_control(control_model, out / 'replayed-control', sealed)
        report['hardware_guest_runs'] += 4
        need(row.unchanged_artifacts(control_binding), 'control changed during replay')
        raw.gate.install()
        model, cxx = out / CANDIDATE, tools['compiler']['command']
        record = {'first_build': raw.build_model(model, args.gsim, cxx)}
        report['candidate'] = record
        report['new_DUT_builds'] += 1
        base.save_receipt(out, report)
        common.run([model / 'run'], env=base.runtime_env(), log=model / 'test.log', timeout=180)
        record.update(raw.vm_metrics(model, False))
        record['second_host'], record['load_cases'], record['proof_metrics'] = raw.second_host(model, cxx, record['first_build'])
        report['hardware_guest_runs'] += 4
        for key in METRICS:
            need(record[key] == report['replayed_control'][key], 'candidate exact metric/owner mismatch: ' + key)
        need((model / 'test.log').read_bytes() == (out / 'replayed-control/test.log').read_bytes(),
             'candidate VM full trace differs')
        need((model / 'load-host/test.log').read_bytes() == (out / 'replayed-control/load.log').read_bytes(),
             'candidate full load trace differs')
        record['negative'] = raw.negative(model)
        record['execution_artifacts'] = {'artifacts': {str(p): sha(p) for p in (
            model / 'test.log', model / 'load-host/test.log', Path(record['negative']['log']))}}
        report['status'] = 'PASS_EXACT_FACTORED_PMP_ACTUAL_CPU'
    except BaseException as error:
        report.update(status='FAIL', failure=f'{type(error).__name__}: {error}')
        raise
    finally:
        report['inputs_unchanged'] = inputs() == before
        report['tools_unchanged'] = base.tool_binding(True) == tools
        checks = [report['inputs_unchanged'], report['tools_unchanged']]
        for key in ('control_binding', 'component_binding', 'scala_compile_receipt'):
            report[key + '_unchanged'] = row.unchanged_artifacts(report.get(key, {}))
            checks.append(report[key + '_unchanged'])
        for key in ('first_build', 'second_host', 'execution_artifacts'):
            checks.append(row.unchanged_artifacts(report.get('candidate', {}).get(key, {})))
        if not all(checks):
            report['status'] = 'FAIL_SOURCE_TOOL_OR_ARTIFACT_DRIFT'
        report['artifacts_sha256'] = {str(p.relative_to(out)): sha(p) for p in out.rglob('*') if p.is_file() and
                                     p.name not in ('receipt.json', 'receipt.json.tmp')}
        base.save_receipt(out, report)
    need(report['status'] == 'PASS_EXACT_FACTORED_PMP_ACTUAL_CPU', report['status'])
    print(json.dumps({'status': report['status'], 'receipt': str(out / 'receipt.json'),
                      'new_DUT_builds': 1, 'all_four_guests_exact': True}, indent=2))


if __name__ == '__main__':
    main()
