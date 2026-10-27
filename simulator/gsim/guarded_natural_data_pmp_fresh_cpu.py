#!/usr/bin/env python3
"""Two fresh guarded-PMP CPU models under an explicitly qualified repaired GSIM epoch.
Historical FIR binds disabled hardware provenance only: no old binary execution,
object reuse, or inherited functional PASS. Both fresh models run all four guests.
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
import guarded_natural_pmp_structure as structure
import gsim_initialization_epoch as epoch

common, base, row = raw.common, raw.base, raw.row
need, sha, read = raw.need, raw.sha, raw.read
CONTROL = raw.CONTROL
CANDIDATE = CONTROL + '-guarded-natural-pmp'
MAIN = 'soc.core.ooo.GuardedNaturalDataPmpCpuGsimMain'
REFERENCE = common.BUILD / 'registered-raw-certified-cpu-20261025-r1/receipt.json'
REFERENCE_SHA = '870131f244a4796d2c3caac3bbbb055fe8bff18426ff0b1d5989356043a29377'
SELF = Path(__file__).resolve()
WRAPPER = common.ROOT / 'src/test/scala/platform/GuardedNaturalDataPmpCpuGsim.scala'
METRICS = (*raw.VM_PREFIXES, 'latency_owners', 'owner_stage_histograms', 'load_cases', 'proof_metrics')


def inputs():
    return {**raw.inputs(), str(Path(epoch.__file__).relative_to(common.ROOT)): sha(Path(epoch.__file__)), str(SELF.relative_to(common.ROOT)): sha(SELF),
            str(WRAPPER.relative_to(common.ROOT)): sha(WRAPPER),
            'simulator/gsim/gsim_initialization_setup.py': sha(common.HERE / 'gsim_initialization_setup.py'),
            'simulator/gsim/test_gsim_initialization_setup.py': sha(common.HERE / 'test_gsim_initialization_setup.py'),
            str(Path(structure.__file__).relative_to(common.ROOT)): sha(Path(structure.__file__)),
            'simulator/gsim/test_guarded_natural_pmp_structure.py':
                sha(common.HERE / 'test_guarded_natural_pmp_structure.py'),
            'simulator/gsim/registered_raw_certified_cones.py':
                sha(common.HERE / 'registered_raw_certified_cones.py')}


def bind_history():
    need(sha(REFERENCE) == REFERENCE_SHA, 'historical receipt changed')
    prior = read(REFERENCE)
    record = prior['models'][CONTROL]
    model = REFERENCE.parent / CONTROL
    fir = model / (raw.TOP + '.fir')
    expected = prior.get('artifacts_sha256', {}).get(str(fir.relative_to(REFERENCE.parent)))
    need(expected is not None and sha(fir) == expected, 'historical FIR binding failed')
    return model, record, {'receipt': str(REFERENCE), 'sha256': REFERENCE_SHA,
                         'artifacts': {str(REFERENCE): REFERENCE_SHA, str(fir): sha(fir)},
                         'scope': 'hardware provenance only; no runtime reuse'}


def parameter_gate(control, candidate, sealed):
    for kind in ('config', 'core'):
        a, b, old = control[kind], candidate[kind], sealed[kind]
        need(set(a) == set(old) | {'factoredDataPmpRange', 'guardedNaturalDataPmp'} and
             a['factoredDataPmpRange'] == a['guardedNaturalDataPmp'] == 'false' and
             all(a[k] == v for k, v in old.items()), 'disabled control parameter/resource drift: ' + kind)
        need(row.differences(a, b) == {'guardedNaturalDataPmp': ['false', 'true']},
             'candidate is not the exact one-flag guarded comparator change: ' + kind)
    return {'only_delta': 'guardedNaturalDataPmp false->true', 'all_capacities_and_stages_unchanged': True}




def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--gsim', type=Path, required=True)
    parser.add_argument('--compile-receipt', type=Path)
    parser.add_argument('--component-receipt', type=Path)
    parser.add_argument('--build-run', action='store_true')
    parser.add_argument('--tool-receipt', type=Path, required=True)
    args = parser.parse_args()
    need(re.fullmatch(r'[A-Za-z0-9_-]+', args.tag), 'safe fresh tag required')
    before, source_gate = inputs(), raw.host_source_gate()
    tools = epoch.tool_binding(args.tool_receipt)
    control_model, sealed, control_binding = bind_history()
    if not args.build_run:
        print(json.dumps({'status': 'PREFLIGHT_ONLY', 'source_gate': source_gate,
                          'historical_FIR_only_verified': True, 'new_DUT_builds': 0}, indent=2))
        return
    need(args.compile_receipt is not None and args.component_receipt is not None,
         'current Scala and guarded-natural-PMP component receipts required')
    component = read(args.component_receipt)
    need(component.get('schema') == 'valence-guarded-natural-dta-v1' and
         component.get('status') == 'PASS_GUARDED_NATURAL_DTA', 'complete guarded-natural-PMP component gate required')
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
    report = {'schema': 'guarded-natural-data-pmp-fresh-pair-cpu-v1', 'status': 'RUNNING',
              'source_revision': base.git(common.ROOT, 'rev-parse', 'HEAD').strip(),
              'inputs_before': before, 'tools_before': tools, 'history_binding': control_binding, 'models': {},
              'tool_receipt_binding': {'artifacts': {str(args.tool_receipt): sha(args.tool_receipt)}},
              'source_gate': source_gate, 'new_DUT_builds': 0, 'hardware_guest_runs': 0,
              'component_binding': {'artifacts': {str(args.component_receipt): sha(args.component_receipt)}},
              'limits': 'No PPA/STA/board/SoC/NEMU; two fresh models, four immutable legal guests each; no old runtime reuse. New standalone raw-misaligned rejection is component scope, not arbitrary-input equality or full-CPU misalignment coverage.'}
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
        need(report['structure_gate']['status'] == 'PASS_GUARDED_NATURAL_PMP_STRUCTURE',
             'complete guarded natural main DTA checker structure gate required')
        raw.gate.install()
        for profile in (CONTROL, CANDIDATE):
            model, cxx = out / profile, tools['compiler']['command']
            record = {'effective_parameters': row.effective(model),
                      'first_build': raw.build_model(model, args.gsim, cxx)}
            report['models'][profile] = record
            report['new_DUT_builds'] += 1
            base.save_receipt(out, report)
            common.run([model / 'run'], env=base.runtime_env(), log=model / 'test.log', timeout=180)
            record.update(raw.vm_metrics(model, False))
            record['second_host'], record['load_cases'], record['proof_metrics'] = raw.second_host(model, cxx, record['first_build'])
            report['hardware_guest_runs'] += 4
            record['execution_artifacts'] = {'artifacts': {str(p): sha(p) for p in (
                model / 'test.log', model / 'load-host/test.log')}}
            base.save_receipt(out, report)
        control, candidate = report['models'][CONTROL], report['models'][CANDIDATE]
        for key in METRICS:
            need(candidate[key] == control[key], 'fresh-pair exact metric/owner mismatch: ' + key)
            need(json.loads(json.dumps(control[key])) == sealed[key], 'fresh control historical metric mismatch: ' + key)
        for log in ('test.log', 'load-host/test.log'):
            need((out / CANDIDATE / log).read_bytes() == (out / CONTROL / log).read_bytes(),
                 'fresh-pair full log differs: ' + log)
        candidate['negative'] = raw.negative(out / CANDIDATE)
        candidate['execution_artifacts']['artifacts'][candidate['negative']['log']] = sha(Path(candidate['negative']['log']))
        report['status'] = 'PASS_EXACT_GUARDED_NATURAL_PMP_FRESH_PAIR_CPU'
    except BaseException as error:
        report.update(status='FAIL', failure=f'{type(error).__name__}: {error}')
        raise
    finally:
        report['inputs_unchanged'] = inputs() == before
        report['tools_unchanged'] = epoch.tool_binding(args.tool_receipt) == tools
        checks = [report['inputs_unchanged'], report['tools_unchanged']]
        for key in ('history_binding', 'tool_receipt_binding', 'component_binding', 'scala_compile_receipt'):
            report[key + '_unchanged'] = row.unchanged_artifacts(report.get(key, {}))
            checks.append(report[key + '_unchanged'])
        for record in report['models'].values():
            for key in ('first_build', 'second_host', 'execution_artifacts'):
                checks.append(row.unchanged_artifacts(record.get(key, {})))
        if not all(checks):
            report['status'] = 'FAIL_SOURCE_TOOL_OR_ARTIFACT_DRIFT'
        report['artifacts_sha256'] = {str(p.relative_to(out)): sha(p) for p in out.rglob('*') if p.is_file() and
                                     p.name not in ('receipt.json', 'receipt.json.tmp')}
        base.save_receipt(out, report)
    need(report['status'] == 'PASS_EXACT_GUARDED_NATURAL_PMP_FRESH_PAIR_CPU', report['status'])
    print(json.dumps({'status': report['status'], 'receipt': str(out / 'receipt.json'),
                      'new_DUT_builds': 2, 'all_four_guests_exact': True}, indent=2))


if __name__ == '__main__':
    main()
