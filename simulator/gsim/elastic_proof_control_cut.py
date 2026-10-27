#!/usr/bin/env python3
"""Opt-in cleanup: one fresh CPU DUT, four unchanged guests, exact all-field comparison.

Old executed DUTs are immutable evidence only. The disabled-control FIR gate
removes source annotations, not diagnostic strings. A changed diagnostic must
first fail and receive a separately pinned, reviewed amendment. No generic model
resume, baseline rerun, synthesis or frequency qualification is performed.
"""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import re
import resource
import shutil
import sys
import tarfile

sys.dont_write_bytecode = True
import elastic_load_proof_cpu as previous
import prepared_head_store_cpu as row
import a1_common_cpu_retirement as base
import run as common
import m2_r1_compile_gate as gate

need, sha, read = row.need, base.sha, previous.read
PROFILE, TOP = previous.PROFILE, previous.TOP
SELF = 'simulator/gsim/elastic_proof_control_cut.py'
OWNED = (
    'src/main/scala/core/ooo/lsu/ElasticVirtualRamLoadPreparation.scala',
    'src/main/scala/core/ooo/integration/IntegerBackend.scala',
    'simulator/gsim/harness/elastic_load_proof.cpp',
    'simulator/gsim/elastic_load_proof.py',
    'docs/a1-elastic-proof-query-control-cut.md', SELF,
)
OLD = common.BUILD / 'elastic-load-proof-cpu-20261024-r3/receipt.json'
OLD_SHA = 'c72263ca5bc5df808a7575ff76ce833aaff7d016fe05f782cd915ce782c87421'
CHECKPOINT = common.ROOT / 'build/elastic-load-proof-20261024-r2/checkpoint-receipt.json'
CHECKPOINT_SHA = 'dfaa8b1e92929f102c0567769b2c9e87f9365a51b15d930621eeac93ebaf08e6'
MANIFEST = CHECKPOINT.parent / 'final-source-manifest.json'
MANIFEST_SHA = 'd8ab0326e0e8b103a8107e0bcf3618ca6c422c5594bdbfedab8f57c29d34d0c7'
OLD_MODEL = common.BUILD / 'elastic-load-proof-cpu-20261024-r2' / PROFILE
CONTROL = common.BUILD / 'elastic-load-proof-cpu-20261024-r2/baseline-structural-gate'
PREFIXES = {'cases': 'A1_VM_CPU_METRIC ', 'stages': 'A1_VM_STAGE_METRIC ',
            'forwarding': 'M3_CPU_FORWARD_METRIC ', 'flow': 'CHECKED_FLOW_METRIC ',
            'prepared_store': 'PREPARED_STORE_METRIC '}
SCOPE = {
    'delta': 'Remove live-lookahead descriptor conflict from registered-D query selection; retain cancellation and add assertions; no new flag/state/profile.',
    'DUT': 'One fresh full-resource actual CommonA1CpuTile with the same elastic-proof profile and two immutable hosts.',
    'comparison': 'Every four-guest metric/proof/service/local histogram field exact against sealed elastic execution; no required speedup.',
    'disabled_control': 'Same disabled-elastic profile, strict FIR structure modulo source annotations; diagnostic changes fail first. Not active-DUT equivalence.',
    'negative_scope': 'Prior unchanged-host CPU observation negatives referenced, not re-executed or counted as new coverage; fresh adversarial checks belong to the tiny module.',
    'limits': 'Fixed original service; no new CPU arbitrary backpressure, alias, NEMU/SoC/DDR/CDC/native/PPA/Fmax/board evidence.',
}


def inputs():
    result = previous.inputs()
    for name in OWNED:
        result[name] = sha(common.ROOT / name)
    return dict(sorted(result.items()))


def bind_baseline(report):
    need(sha(OLD) == OLD_SHA and sha(CHECKPOINT) == CHECKPOINT_SHA and sha(MANIFEST) == MANIFEST_SHA,
         'sealed baseline receipt/checkpoint/source manifest changed')
    old = read(OLD)
    need(old['status'] == 'PASS_BOUNDED_ELASTIC_LOAD_PROOF_ACTUAL_CPU' and
         old['execution_artifacts_unchanged'] and old['finalizer_inputs_unchanged'], 'baseline not sealed successful evidence')
    need(old['tools_after'] == report['tools_before'], 'baseline/current exact tool identity mismatch')
    bound = {str(OLD): OLD_SHA, str(CHECKPOINT): CHECKPOINT_SHA, str(MANIFEST): MANIFEST_SHA,
             **old['execution_artifacts']}
    for field in ('baseline_binding', 'scala_compile_receipt', 'control_reuse'):
        bound.update(old[field]['artifacts'])
    for name, digest in read(CHECKPOINT)['leaves_sha256'].items():
        bound[str(common.ROOT / name)] = digest
    frozen = read(MANIFEST)['complete_inputs']
    # The checkpoint also names live source paths. Approved new sources cannot
    # equal their old bytes; verify those historical bytes from the sealed tar,
    # never silently drop an artifact check or substitute current source.
    archive = MANIFEST.parent / 'final-frozen-inputs.tar.gz'
    need(sha(archive) == '90c932bf4f48ad65fe2c4cee6cf90d8550dae9e89bb7f001be9ca0127f742a03',
         'sealed old source archive changed')
    archived_sources = {}
    with tarfile.open(archive, 'r:gz') as tar:
        for name in OWNED:
            path = str(common.ROOT / name)
            if path not in bound:
                continue
            need(name in frozen and frozen[name] == bound[path], 'old source leaf not bound by final source manifest')
            data = tar.extractfile(name).read()
            need(hashlib.sha256(data).hexdigest() == bound[path], 'historical source archive member changed: ' + name)
            archived_sources[name] = bound.pop(path)
    bound[str(archive)] = sha(archive)
    need(row.unchanged_artifacts({'artifacts': bound}), 'sealed baseline artifact changed')
    changed = {name: [digest, sha(common.ROOT / name)] for name, digest in frozen.items()
               if sha(common.ROOT / name) != digest}
    need(set(changed) <= set(OWNED), 'unapproved baseline source difference: ' + repr(set(changed) - set(OWNED)))
    for name in previous.NEW_FILES + ('simulator/gsim/harness/prepared_head_store_cpu.cpp',):
        need(sha(common.ROOT / name) == frozen[name], 'immutable CPU wrapper/host/runner changed: ' + name)
    need([case['work_cycles'] for case in old['cases']] == [681, 1018] and
         [case['roi_work_cycles'] for case in old['load_cases']] == [531, 360], 'wrong historical functional baseline')
    previous.host_source_gate()
    report['baseline_binding'] = {'artifacts': bound, 'source_differences': changed,
        'receipt': str(OLD), 'new_baseline_runs': 0, 'tools_exact': True,
        'historical_source_archive': str(archive), 'verified_archive_members': archived_sources,
        'historical_negative_controls': old['negative_controls']}
    return old


def bind_control_reuse(path, report):
    path = path.resolve(strict=True)
    need(path == common.BUILD / 'elastic-proof-control-cut-cpu-20261024-r1/receipt.json' and
         sha(path) == '74e2a3eb1f69cbe6d8894f1bf378f8d635474e9bfeff17e95c8a9216aa916a58',
         'only exact failed r1 control may be reused')
    failed = read(path)
    need(failed['status'] == 'FAIL' and failed['failure'].startswith('RuntimeError: FRESH_BASELINE_REQUIRED:') and
         all(failed[k] for k in ('inputs_unchanged', 'tools_unchanged', 'baseline_binding_unchanged', 'scala_compile_receipt_unchanged')),
         'r1 must be unchanged structural-only rejection')
    delta = row.differences(failed['inputs_after'], report['inputs_before'])
    need(set(delta) == {SELF} and delta[SELF][0] == '2b8ab065eaa79b4d1e4c8b385d1cdfeee5003cc073b62d019148ddbfb0d276d1',
         'only approved runner diagnostic mapping may change after r1')
    need(failed['tools_after'] == report['tools_before'] and
         failed['scala_compile_receipt']['sha256'] == report['scala_compile_receipt']['sha256'],
         'r1 control tools/compile changed')
    bound = {str(path): sha(path)}
    for name, digest in failed['artifacts_sha256'].items():
        source = (path.parent / name).resolve()
        need(path.parent in source.parents and sha(source) == digest, 'r1 control artifact changed: ' + name)
        bound[str(source)] = digest
    report['control_reuse'] = {'receipt': str(path), 'artifacts': bound, 'input_differences': delta,
        'scope': 'only existing control elaboration, never candidate execution or a functional PASS'}


def structural_gate(out, report):
    control = out / 'baseline-structural-gate'
    control.mkdir()
    reuse = report.get('control_reuse')
    if reuse:
        original = Path(reuse['receipt']).parent / 'baseline-structural-gate'
        for source in original.iterdir():
            need(source.is_file() and str(source) in reuse['artifacts'], 'unexpected control artifact')
            destination = control / ('r1-source-normalized.diff' if source.name == 'source-normalized.diff' else source.name)
            shutil.copyfile(source, destination)
            need(sha(destination) == reuse['artifacts'][str(source)], 'control copy mismatch')
    else:
        common.run(['mill', '-i', 'IonSoC.test.runMain', row.MAIN, control], log=control / 'elaborate.log')
    need(row.effective(control) == row.effective(CONTROL), 'disabled control effective parameters changed')
    oldfir, newfir = CONTROL / (TOP + '.fir'), control / (TOP + '.fir')
    a, b = row.normalize_fir(oldfir.read_bytes()), row.normalize_fir(newfir.read_bytes())
    mapped, mapping = a, None
    if reuse:
        need(sha(oldfir) == 'dbd4b91f15cc1f1781d4063e44a9b62295fbeedd5574b308fc6674dce3337a00' and
             sha(newfir) == 'adc18d3416a285e01501dc484d2e109cc81fbdf65c090cf015320ad4e1a7e637',
             'exact reviewed old/new raw control FIR required')
        old_text = b'"Assertion failed at IntegerBackend.scala:3520\\n"'
        new_text = b'"Assertion failed: dispatch reservations must not exceed issue width\\n"'
        need(a.count(old_text) == b.count(new_text) == 1 and not a.count(new_text) and not b.count(old_text),
             'complete approved diagnostic must occur exactly once on each side')
        mapped = a.replace(old_text, new_text)
        mapping = {'old': old_text.decode(), 'new': new_text.decode(), 'old_count': 1, 'new_count': 1,
            'approval': 'Root directly reviewed unchanged PopCount/reserve predicate, clock/_T_1330/_T_1332/label; one complete stable diagnostic substitution only.'}
    diff = control / 'source-normalized.diff'
    diff.write_text(''.join(difflib.unified_diff(a.decode().splitlines(True), b.decode().splitlines(True),
                                               fromfile=str(oldfir), tofile=str(newfir))))
    mapped_diff = control / 'mapped.diff'
    mapped_diff.write_text(''.join(difflib.unified_diff(mapped.decode().splitlines(True), b.decode().splitlines(True))))
    report['baseline_fir_gate'] = {'old_fir_sha256': sha(oldfir), 'new_fir_sha256': sha(newfir),
        'raw_exact': oldfir.read_bytes() == newfir.read_bytes(),
        'old_source_normalized_sha256': hashlib.sha256(a).hexdigest(),
        'new_source_normalized_sha256': hashlib.sha256(b).hexdigest(), 'source_only_exact': a == b,
        'normalization': 'source annotations; only exact pinned r1 reuse permits the approved complete diagnostic substitution count1',
        'diagnostic_mapping': mapping, 'mapped_old_sha256': hashlib.sha256(mapped).hexdigest(),
        'mapped_new_sha256': hashlib.sha256(b).hexdigest(),
        'diff': str(diff), 'diff_sha256': sha(diff), 'mapped_diff_sha256': sha(mapped_diff), 'exact': mapped == b,
        'scope': 'disabled-elastic control only; active query-control RTL intentionally differs'}
    base.save_receipt(out, report)
    need(mapped == b, 'FRESH_BASELINE_REQUIRED: disabled control differs beyond source annotations; see ' + str(diff))


def cache_gate(model, out, report):
    def module(path):
        matches = re.findall(rb'^  module NonBlockingCoherentLineCache :[^\n]*\n.*?(?=^  (?:module|extmodule|intmodule) |\Z)',
                             row.normalize_fir(path.read_bytes()), re.M | re.S)
        need(len(matches) == 1, 'one cache module required for unchanged private observer')
        return matches[0]
    a, b = module(OLD_MODEL / (TOP + '.fir')), module(model / (TOP + '.fir'))
    report['cache_observation_gate'] = {'old_sha256': hashlib.sha256(a).hexdigest(),
        'new_sha256': hashlib.sha256(b).hexdigest(), 'exact_after_source_annotations': a == b}
    base.save_receipt(out, report)
    need(a == b, 'cache private observer structure changed')


def compare(old, report, fields):
    # Round-trip keys so integer histogram bins compare with saved JSON strings.
    def canonical(value):
        return json.loads(json.dumps(value))
    differences = {}
    for field in fields:
        a, b = canonical(old[field]), canonical(report[field])
        if a != b:
            differences[field] = {'baseline': a, 'candidate': b}
    report.setdefault('exact_comparison', {}).update({field: field not in differences for field in fields})
    report.setdefault('metric_differences', {}).update(differences)
    need(not differences, 'exact four-guest metric/owner comparison failed: ' + repr(list(differences)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--gsim', required=True, type=Path)
    parser.add_argument('--compile-receipt', type=Path)
    parser.add_argument('--reuse-control', type=Path, help='only exact failed r1 with approved diagnostic mapping')
    parser.add_argument('--build-run', action='store_true')
    args = parser.parse_args()
    need(re.fullmatch(r'[A-Za-z0-9_-]+', args.tag), 'safe fresh tag required')
    before = inputs()
    if not args.build_run:
        print(json.dumps({'status': 'PREFLIGHT_ONLY', 'inputs': len(before), 'scope': SCOPE,
                          'host_source_gate': previous.host_source_gate()}, indent=2))
        return
    need(args.compile_receipt is not None, 'current complete Scala compile receipt required')
    out = common.BUILD / args.tag
    out.mkdir(parents=True, exist_ok=False)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    tools = base.tool_binding(True)
    cxx = tools['compiler']['command']
    need(args.gsim.resolve() == Path(tools['gsim']['path']).resolve(), 'pinned GSIM required')
    report = {'schema': 'elastic-proof-control-cut-cpu-v1', 'status': 'RUNNING', 'scope': SCOPE,
        'source_revision': base.git(common.ROOT, 'rev-parse', 'HEAD').strip(),
        'inputs_before': before, 'tools_before': tools}
    base.save_receipt(out, report)
    try:
        row.bind_compile_receipt(args.compile_receipt, report)
        old = bind_baseline(report)
        if args.reuse_control:
            bind_control_reuse(args.reuse_control, report)
        structural_gate(out, report)
        need(inputs() == before, 'source drift before fresh candidate emission')
        gate.install()
        gated_run = common.run
        def with_cache_gate(command, **kwargs):
            if str(command[0]) == str(args.gsim):
                cache_gate(out / PROFILE, out, report)
            return gated_run(command, **kwargs)
        common.run = with_cache_gate
        model = common.test(args.gsim, cxx, args.tag + '/' + PROFILE, previous.MAIN, TOP,
                            row.HOST.name, defines={}, timeout=180)
        report['candidate_fresh_build'] = row.fresh_build_gate(model)
        report['effective_parameters'] = row.effective(model)
        need(report['effective_parameters'] == old['effective_parameters'], 'active effective profile changed')
        for field, prefix in PREFIXES.items():
            report[field] = row.parse(model / 'test.log', prefix)
        report['latency_owners'], report['latency'] = row.read_owners(model / 'test.log')
        compare(old, report, [*PREFIXES, 'latency_owners', 'latency'])
        base.save_receipt(out, report)
        target = previous.second_host(model, out, cxx, report)
        report['load_cases'] = previous.load_metrics(target / 'test.log', 'LOAD_SUPPLY_METRIC ')
        report['proof_metrics'] = previous.load_metrics(target / 'test.log', 'ELASTIC_PROOF_METRIC ')
        compare(old, report, ['load_cases', 'proof_metrics'])
        old_owners = [line for line in (OLD_MODEL.parent / 'load-host/test.log').read_text().splitlines() if line.startswith('LOAD_OWNER ')]
        new_owners = [line for line in (target / 'test.log').read_text().splitlines() if line.startswith('LOAD_OWNER ')]
        need(len(old_owners) > 0 and old_owners == new_owners, 'load owner trace changed')
        report['load_owner_trace_exact'] = {'rows': len(new_owners), 'exact': True}
        report['new_hardware_guest_runs'] = 4
        report['new_CPU_negative_runs'] = 0
        report['status'] = 'PASS_BOUNDED_ELASTIC_PROOF_CONTROL_CUT_EXACT_CPU'
    except BaseException as error:
        report.update(status='FAIL', failure=f'{type(error).__name__}: {error}')
        raise
    finally:
        report['inputs_after'] = inputs()
        report['inputs_unchanged'] = before == report['inputs_after']
        report['source_input_drift'] = row.differences(before, report['inputs_after'])
        report['tools_after'] = base.tool_binding(True)
        report['tools_unchanged'] = tools == report['tools_after']
        for name in ('baseline_binding', 'scala_compile_receipt', 'control_reuse'):
            report[name + '_unchanged'] = row.unchanged_artifacts(report.get(name, {}))
        if not all(report[k] for k in ('inputs_unchanged', 'tools_unchanged', 'baseline_binding_unchanged', 'scala_compile_receipt_unchanged', 'control_reuse_unchanged')):
            report['status'] = 'FAIL_INPUT_DRIFT'
        report['artifacts_sha256'] = {str(p.relative_to(out)): sha(p) for p in sorted(out.rglob('*'))
            if p.is_file() and p.name not in ('receipt.json', 'receipt.json.tmp')}
        base.save_receipt(out, report)
    need(report['status'].startswith('PASS_'), report['status'])
    print(json.dumps({'status': report['status'], 'receipt': str(out / 'receipt.json'),
                      'exact_comparison': report['exact_comparison']}, indent=2))


if __name__ == '__main__':
    main()
