#!/usr/bin/env python3
"""One fresh prepared-head-store CPU candidate against the sealed checked-flow run.

Default mode only hashes inputs and checks the immutable host source contract.
--build-run requires a successful full Scala compile receipt, emits only the old
structural control FIR, and builds one fresh candidate for two original VM guests
and two sampled-observation negatives. No cached-model/resume helper is used.
--reuse-control permits only the pinned failed r1 control and its one explicitly
approved complete diagnostic-line mapping; it never reuses a candidate model.
"""
import argparse
from collections import Counter
import difflib
import hashlib
import json
from pathlib import Path
import re
import resource
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
import run as common
import a1_common_cpu_retirement as base
import m2_r1_compile_gate as gate

sys.path.insert(0, str(common.ROOT / 'fpga/common'))
import scala_compile_receipt as scala

TOP = 'CommonA1VmPipelineGsim'
MAIN = 'soc.core.ooo.PreparedHeadStoreCpuGsimMain'
CONTROL_MAIN = 'soc.core.ooo.CombinedCheckedFlowCpuGsimMain'
PROFILE = 'full-r1-m3-checked-flow-store-row'
OLD_PROFILE = 'full-r1-m3-checked-flow'
HOST = common.HERE / 'harness/prepared_head_store_cpu.cpp'
OLD_HOST = common.HERE / 'harness/combined_checked_flow_cpu.cpp'
BASELINE_SHA = 'd8af8798c93ca437131233af06655c54008aa137f793c05c28ebe9b520485bb8'
OLD_HOST_SHA = '914d643fdcddefec36fc846083dd8a09d86d653b9fa817fd3f6a34abd2ca7d87'
REUSE_RECEIPT_SHA = '7046a44d6ba6bdc2a20b7d303bc742b9e8fd4397593f6b882759cb9016b62e37'
REUSE_RUNNER_SHA = '4896d91a23e02d6e0da202eff909255c8533c57db1f77c60b1876efeda1615e5'
REUSE_DIFF_SHA = '6be019ac730e16c6a9c699164a11b225488a1ee53d015727383a3106e7271adb'
REUSE_OLD_FIR_SHA = '74e54ce8879bdc028f51aa482ed7bb65248a01f28411d014049ebe94817cabd9'
REUSE_NEW_FIR_SHA = '4a03d472102e69cd184a2468e494b8a29f7d35064c550777d6954313b993532d'
CASES = ('vm_store_stream', 'vm_dependency')
PASS = 'PREPARED_HEAD_STORE_CPU_PASS'
ROW_FIELDS = {'name', 'starts', 'prepared_starts', 'fallback_starts', 'requests',
              'replies', 'completions', 'normal_load_starts', 'normal_memory_issued',
              'captures', 'valid_cycles', 'choice_cycles', 'eligible_cycles', 'flushes',
              'fallback_without_prepared', 'fallback_different_owner'}
IMMUTABLE = (
    'src/test/scala/platform/CommonA1VmPipelineGsim.scala',
    'src/test/scala/platform/M3CompletedCanonicalCpuGsim.scala',
    'src/test/scala/platform/CombinedCheckedFlowCpuGsim.scala',
    'simulator/gsim/harness/a1_vm_pipeline.cpp',
    'simulator/gsim/harness/m3_completed_canonical_cpu.cpp',
    'simulator/gsim/harness/combined_checked_flow_cpu.cpp',
    'simulator/gsim/combined_checked_flow_cpu.py',
    'simulator/gsim/a1_common_cpu_retirement.py',
    'simulator/gsim/run.py',
    'simulator/gsim/m2_r1_compile_gate.py',
)
SCOPE = {
    'DUT': 'actual full-r1-m3-checked-flow-store-row CommonA1CpuTile; full RV64GC/VM/PMP/cache resources retained',
    'matched': 'exact original two 233-retirement VM guests and fixed legal external service law',
    'baseline_reuse': 'sealed checked-flow receipt/model/tools; disabled control FIR matches after source annotations, with only the pinned opt-in r1 diagnostic mapping permitted',
    'candidate_delta': 'only newly added preparedHeadStoreOperands=true; disabled structural control adds false',
    'owner_observer': 'independent registered-row lifecycle and raw-ISA payload -> actual LSU full token -> ordered DTA stages',
    'negative_scope': 'two sampled observation mutations, not RTL mutants',
    'model_build': 'one new candidate, all fresh generated-DUT/host objects; no resume helper',
    'limits': ['serial ordinary stores under the original no-backpressure CPU service',
               'no alias rerun or CPU backpressure qualification',
               'no NEMU/SoC/CDC/native/STA/PPA/board/Fmax claim; acceptedPrefixValidation remains false'],
}


def need(condition, message):
    if not condition:
        raise RuntimeError(message)


def inputs():
    found = base.source_inputs()
    # Include the public compile producer's complete resource/source closure so
    # later source drift is recorded without re-verifying mutable JVM outputs.
    for path in scala.compile_source_paths(common.ROOT):
        found[str(path.relative_to(common.ROOT))] = base.sha(path)
    for name in (*IMMUTABLE,
                 'src/test/scala/platform/PreparedHeadStoreCpuGsim.scala',
                 'simulator/gsim/harness/prepared_head_store_cpu.cpp',
                 'simulator/gsim/prepared_head_store_cpu.py',
                 'fpga/common/scala_compile_receipt.py'):
        found[name] = base.sha(common.ROOT / name)
    return dict(sorted(found.items()))


def effective(directory):
    return {kind: base.read_json((directory / name).read_text()) for kind, name in
            [('config', 'effective-config.json'), ('core', 'effective-parameters.json')]}


def differences(old, new):
    return {key: [old.get(key), new.get(key)] for key in sorted(set(old) | set(new))
            if key not in old or key not in new or old[key] != new[key]}


def compare_params(old, new, enabled):
    result = {}
    for kind in ('config', 'core'):
        added = {key: new[kind][key] for key in new[kind].keys() - old[kind].keys()}
        removed = sorted(old[kind].keys() - new[kind].keys())
        changed = {key: [value, new[kind].get(key)] for key, value in old[kind].items()
                   if new[kind].get(key) != value}
        need(added == {'preparedHeadStoreOperands': str(enabled).lower()} and not changed and not removed,
             f'unexpected {kind} profile delta: {added}, {changed}, removed={removed}')
        result[kind] = {'added': added, 'changed': changed, 'removed': removed}
    return result


def host_source_gate():
    need(base.sha(OLD_HOST) == OLD_HOST_SHA, 'immutable published checked-flow host changed')
    old, new = OLD_HOST.read_bytes(), HOST.read_bytes()
    need(old.split(b'class Run {', 1)[0] == new.split(b'class Run {', 1)[0],
         'immutable independent ISA/program/PMP/PTE/service definitions changed')
    for start, end in [(b'    void drive(', b'    bool tick('),
                       (b'    bool tick(', b'\npublic:')]:
        a = old[old.index(start):old.index(end, old.index(start) + len(start))]
        b = new[new.index(start):new.index(end, new.index(start) + len(start))]
        if start == b'    bool tick(':
            need(b.count(b'        rowObserve();\n') == 1,
                 'exactly one passive rowObserve insertion required in original tick')
            b = b.replace(b'        rowObserve();\n', b'')
        need(a == b, 'original CPU external drive/service/retirement flow changed')
    # In particular, do not strip flowObserve as the previous runner did when
    # comparing against M3. This candidate retains the checked-flow observer.
    # The reviewed row observer occupies one new contiguous class block between
    # flowFinish and forwardObserve. Remove only that block, not old methods.
    row_start, row_end = b'    struct PreparedRow {', b'    void forwardObserve() {'
    need(new.count(row_start) == 1 and new.count(row_end) == 1,
         'exactly one bounded prepared-row observer block required')
    start, end = new.index(row_start), new.index(row_end)
    need(start < end, 'prepared-row observer block moved outside its reviewed boundary')
    without_row = new[:start] + new[end:]
    for start, end in [(b'    void flowObserve()', b'    void flowFinish()'),
                       (b'    void flowFinish()', b'    void forwardObserve()')]:
        a = old[old.index(start):old.index(end, old.index(start) + len(start))]
        b = without_row[without_row.index(start):without_row.index(end, without_row.index(start) + len(start))]
        need(a == b, 'original checked-flow per-owner observer/finish gate changed')
    need(new.count(b'        flowFinish();\n') == 1 and new.count(b'        rowFinish();\n') == 1,
         'original flowFinish and added rowFinish must each run exactly once')
    original_class = old.split(b'\nint main(', 1)[0]
    candidate_class = without_row.split(b'\nint main(', 1)[0]
    for added, replacement in (
            (b'        rowObserve();\n', b''), (b'        rowFinish();\n', b''),
            (b', bool rowMutation = false)', b')'),
            (b'; rowNegative = rowMutation;', b';'), (b' && !rowNegative,', b',')):
        need(candidate_class.count(added) == 1, 'unexpected prepared-row class insertion: ' + repr(added))
        candidate_class = candidate_class.replace(added, replacement)
    need(candidate_class == original_class,
         'original host methods/retirement/oracles changed beyond reviewed passive row additions')
    return {'oracle_and_external_service_source_exact': True,
            'original_flow_observer_source_exact': True,
            'tick_delta': 'one passive rowObserve call only; original flowObserve retained',
            'old_host_sha256': OLD_HOST_SHA}


def program_gate(out, cxx):
    report = host_source_gate()
    flags = ['-std=c++20', '-O1', '-g', '-fsanitize=address,undefined',
             '-fno-sanitize-recover=all', '-DA1_VM_ORACLE_ONLY=1']
    for source, name in [(OLD_HOST, 'old-oracle'), (HOST, 'new-oracle')]:
        binary = out / name
        common.run([cxx, *flags, source, '-o', binary], log=out / (name + '-compile.log'))
        common.run([binary, '--dump-programs'], env=base.runtime_env(), log=out / (name + '-programs.log'))
    a = (out / 'old-oracle-programs.log').read_bytes()
    b = (out / 'new-oracle-programs.log').read_bytes()
    need(a == b and len(a.splitlines()) == 3, 'published all-three raw program/setup bytes changed')
    common.run([out / 'new-oracle', '--oracle-only'], env=base.runtime_env(), log=out / 'oracle.log')
    oracle = (out / 'oracle.log').read_text()
    base.check_log(oracle)
    need(oracle.splitlines().count('A1_VM_CPU_ORACLE_PASS') == 1, 'independent original oracle did not pass')
    report.update(published_all_three_generator_bytes_exact=True, actual_cpu_cases=list(CASES),
                  program_dump_sha256=hashlib.sha256(a).hexdigest())
    return report


def read_owners(log):
    owners = {name: [] for name in CASES}
    seen = {name: set() for name in CASES}
    fields = {'guest', 'index', 'tag', 'pc', 'va', 'pa', 'write', 'prechecked',
              'upstream', 'checked', 'physical', 'reply'}
    for line in log.read_text().splitlines():
        if not line.startswith('CHECKED_FLOW_OWNER '):
            continue
        pairs = [piece.split('=', 1) for piece in line.split()[1:]]
        row = base.unique_object(pairs)
        need(set(row) == fields and row['guest'] in CASES, 'invalid checked-flow owner record')
        name = row.pop('guest')
        row = {key: int(value) for key, value in row.items()}
        need(all(value >= 0 for value in row.values()) and row['write'] in (0, 1) and
             row['prechecked'] in (0, 1) and not (row['write'] and row['prechecked']),
             'invalid checked-flow owner values')
        token = (row['index'], row['tag'])
        need(token not in seen[name], 'duplicate checked-flow full-token owner')
        seen[name].add(token)
        need(row['upstream'] < row['checked'] < row['physical'] < row['reply'],
             'checked-flow ingress/register/reply stage ordering changed')
        owners[name].append(row)
    histograms = {}
    for name, prechecked in zip(CASES, (7, 55)):
        rows = owners[name]
        hist = {kind: Counter() for kind in ('store', 'raw_load', 'prechecked')}
        for row in rows:
            kind = 'prechecked' if row['prechecked'] else ('store' if row['write'] else 'raw_load')
            hist[kind][row['physical'] - row['upstream']] += 1
        need(hist == {'store': Counter({24: 1, 2: 48}), 'raw_load': Counter({2: 2}),
                      'prechecked': Counter({2: prechecked})},
             'per-owner cold24/raw2/prechecked2 stage histogram changed: ' + name)
        histograms[name] = {kind: dict(values) for kind, values in hist.items()}
    return owners, histograms


def baseline_binding(path, current_inputs, tools, report):
    path = path.resolve()
    need(base.sha(path) == BASELINE_SHA, 'published checked-flow receipt bytes changed')
    old = base.read_json(path.read_text())
    need(old['status'] == 'PASS_BOUNDED_CHECKED_FLOW_ACTUAL_CPU' and
         old['inputs_unchanged'] and old['tools_unchanged'] and old['baseline_artifacts_unchanged'] and
         old['inputs_before'] == old['inputs_after'] and old['tools_before'] == old['tools_after'],
         'invalid historical checked-flow baseline')
    need(tools == old['tools_after'], 'historical/current pinned tool identity differs')
    bound = {str(path): BASELINE_SHA}
    for name, expected in old['artifacts_sha256'].items():
        source = (path.parent / name).resolve()
        need(path.parent in source.parents and base.sha(source) == expected,
             'retained checked-flow artifact changed: ' + name)
        bound[str(source)] = expected
    for name, expected in old['baseline_binding']['artifacts'].items():
        need(base.sha(name) == expected, 'retained transitive baseline binding changed: ' + name)
        bound[name] = expected
    for name in IMMUTABLE:
        need(current_inputs[name] == old['inputs_before'][name],
             'immutable baseline fixture/host/runner changed: ' + name)
        bound[str(common.ROOT / name)] = current_inputs[name]
    need(base.sha(OLD_HOST) == OLD_HOST_SHA, 'immutable published checked-flow host changed')
    need([row['name'] for row in old['cases']] == list(CASES) and
         [row['work_cycles'] for row in old['cases']] == [735, 1071] and
         [row['roi_cycles'] for row in old['cases']] == [567, 903],
         'published checked-flow cycle baseline changed')
    owners, histograms = read_owners(path.parent / OLD_PROFILE / 'test.log')
    report['baseline_binding'] = {
        'receipt': str(path), 'receipt_sha256': BASELINE_SHA, 'artifacts': bound,
        'source_revision': old['source_revision'], 'historical_tools_exact': True,
        'historical_current_source_differences': differences(old['inputs_before'], current_inputs),
    }
    report['baseline_latency_owners'] = owners
    report['baseline_latency'] = histograms
    return old


def bind_compile_receipt(path, report):
    path = path.resolve(strict=True)
    before = base.sha(path)
    record = scala.verify_receipt(path, common.ROOT)
    need(record.get('status') == 'PASS_SCALA_COMPILE', 'successful full compile status required')
    need(base.sha(path) == before and record['sourceCommit'] == report['source_revision'],
         'compile receipt changed during verification or source revision differs')
    manifest = record['sourceManifest']
    report['scala_compile_receipt'] = {
        'path': str(path), 'sha256': before, 'schema': record['schema'],
        'source_revision': record['sourceCommit'], 'verified_before_model_emission': True,
        'source_manifest': manifest, 'source_input_count': len(record['sourceInputs']),
        'source_inputs_sha256': base.digest_json(record['sourceInputs']),
        'compiled_classpath_sha256': base.digest_json(record['compiledClasspath']),
        'verification': 'public scala_compile_receipt.verify_receipt; no later JVM-output reverification',
        'artifacts': {str(path): before, manifest['path']: manifest['sha256']},
    }


def normalize_fir(data):
    # Quoted assertion/diagnostic strings are opaque, even if they contain @[].
    # In particular, changed embedded source line numbers must fail this gate.
    return re.sub(rb'"(?:\\.|[^"\\])*"| @\[[^\]\n]*\]',
                  lambda match: match[0] if match[0].startswith(b'"') else b'', data)


def bind_reused_control(path, report):
    path = path.resolve(strict=True)
    need(path == common.BUILD / 'prepared-head-store-cpu-20261024-r1/receipt.json' and
         base.sha(path) == REUSE_RECEIPT_SHA, 'only the pinned failed r1 control receipt may be reused')
    prior = base.read_json(path.read_text())
    need(prior.get('schema') == 'prepared-head-store-cpu-v1' and prior.get('status') == 'FAIL' and
         prior.get('failure', '').startswith('RuntimeError: FRESH_BASELINE_REQUIRED: disabled control differs beyond source annotations;'),
         'reused control is not the pinned structural-gate failure')
    need(all(prior.get(key) is True for key in ('inputs_unchanged', 'tools_unchanged',
             'baseline_artifacts_unchanged', 'scala_compile_receipt_unchanged')) and
         prior['inputs_before'] == prior['inputs_after'] and prior['tools_before'] == prior['tools_after'],
         'failed r1 source/tool/artifact guards must all be unchanged')
    runner = 'simulator/gsim/prepared_head_store_cpu.py'
    delta = differences(prior['inputs_before'], report['inputs_before'])
    need(set(delta) == {runner} and delta[runner][0] == REUSE_RUNNER_SHA,
         'control reuse permits only the archived runner repair; other inputs changed')
    need(prior['source_revision'] == report['source_revision'] and
         prior['tools_after'] == report['tools_before'] and
         prior['scala_compile_receipt'] == report['scala_compile_receipt'],
         'control reuse source revision, tools, or compile receipt changed')
    need(prior['baseline_fir_gate']['diff_sha256'] == REUSE_DIFF_SHA and
         prior['baseline_fir_gate']['old_fir_sha256'] == REUSE_OLD_FIR_SHA and
         prior['baseline_fir_gate']['new_fir_sha256'] == REUSE_NEW_FIR_SHA,
         'pinned r1 structural failure binding differs')
    bound = {str(path): REUSE_RECEIPT_SHA}
    for name, expected in prior['artifacts_sha256'].items():
        source = (path.parent / name).resolve()
        need(path.parent in source.parents and base.sha(source) == expected,
             'failed r1 artifact changed: ' + name)
        bound[str(source)] = expected
    actual = {str(p.relative_to(path.parent)) for p in path.parent.rglob('*')
              if p.is_file() and p != path}
    need(actual == set(prior['artifacts_sha256']), 'failed r1 artifact set changed')
    for binding in ('baseline_binding', 'scala_compile_receipt'):
        need(unchanged_artifacts(prior[binding]), 'failed r1 retained binding changed: ' + binding)
    report['control_reuse'] = {
        'receipt': str(path), 'receipt_sha256': REUSE_RECEIPT_SHA, 'artifacts': bound,
        'source_input_differences': delta, 'compile_receipt_exact': True, 'tools_exact': True,
        'control_artifacts': {name: digest for name, digest in prior['artifacts_sha256'].items()
                              if name.startswith('baseline-structural-gate/')},
        'scope': 'reuse only the already emitted disabled control FIR/config/parameters/logs; candidate builds fresh',
    }


def approved_diagnostic_mapping(a, b):
    old = b'"Assertion failed at IntegerBackend.scala:3454\\n"'
    new = b'"Assertion failed at IntegerBackend.scala:3472\\n"'
    need(a.count(old) == 1 and b.count(new) == 1 and a.count(new) == 0 and b.count(old) == 0,
         'approved complete assertion diagnostic must occur exactly once on each respective side')
    mapped = a.replace(old, new)
    need(mapped == b, 'control differs beyond the one explicitly approved complete diagnostic mapping')
    return mapped, {
        'old': old.decode(), 'new': new.decode(), 'old_occurrences': 1, 'new_occurrences': 1,
        'approval_rationale': 'Explicitly approved exact complete diagnostic line mapping; reviewed identical PopCount dispatcher-bound assertion and all remaining source-annotation-normalized FIR bytes.',
        'all_remaining_normalized_bytes_identical': True,
    }


def structural_gate(out, baseline, old, report):
    control = out / 'baseline-structural-gate'
    control.mkdir()
    reuse = report.get('control_reuse')
    if reuse:
        for name, digest in reuse['control_artifacts'].items():
            source = Path(reuse['receipt']).parent / name
            need(base.sha(source) == digest, 'reused control changed before copying: ' + name)
            destination = control / ('reused-source-only.diff' if Path(name).name == 'normalized.diff' else Path(name).name)
            shutil.copyfile(source, destination)
            need(base.sha(destination) == digest, 'reused control copy mismatch: ' + name)
    else:
        common.run(['mill', '-i', 'IonSoC.test.runMain', CONTROL_MAIN, control], log=control / 'elaborate.log')
    report['baseline_parameters'] = compare_params(old['effective_parameters'], effective(control), False)
    oldfir = baseline.parent / OLD_PROFILE / (TOP + '.fir')
    newfir = control / (TOP + '.fir')
    a, b = normalize_fir(oldfir.read_bytes()), normalize_fir(newfir.read_bytes())
    mapped, mapping = a, None
    if reuse:
        need(base.sha(oldfir) == REUSE_OLD_FIR_SHA and base.sha(newfir) == REUSE_NEW_FIR_SHA,
             'approved diagnostic mapping requires the exact pinned old/new raw FIR')
        mapped, mapping = approved_diagnostic_mapping(a, b)
    diff = control / 'normalized.diff'
    diff.write_text(''.join(difflib.unified_diff(mapped.decode().splitlines(True), b.decode().splitlines(True),
                                              fromfile=str(oldfir), tofile=str(newfir))))
    report['baseline_fir_gate'] = {
        'normalization': ('only FIR @[source locator] annotations outside quoted strings; then the recorded one exact approved complete diagnostic mapping'
                          if reuse else 'only FIR @[source locator] annotations outside quoted strings; no diagnostic or logic normalization'),
        'old_fir_sha256': base.sha(oldfir), 'new_fir_sha256': base.sha(newfir),
        'old_normalized_sha256': hashlib.sha256(a).hexdigest(),
        'new_normalized_sha256': hashlib.sha256(b).hexdigest(),
        'source_only_exact': a == b, 'approved_diagnostic_mapping': mapping,
        'old_final_mapped_sha256': hashlib.sha256(mapped).hexdigest(),
        'new_final_mapped_sha256': hashlib.sha256(b).hexdigest(),
        'exact': mapped == b, 'diff_sha256': base.sha(diff), 'diff': str(diff),
    }
    base.save_receipt(out, report)
    need(mapped == b, 'FRESH_BASELINE_REQUIRED: disabled control differs beyond source annotations; diagnostic strings are not normalized; see ' + str(diff))


def parse(log, prefix):
    text = log.read_text()
    base.check_log(text)
    need(text.splitlines().count(PASS) == 1, 'missing exact prepared-head-store CPU PASS')
    need('_NEGATIVE_REACHED' not in text, 'positive execution reached a sampled negative')
    rows = [base.read_json(line[len(prefix):]) for line in text.splitlines() if line.startswith(prefix)]
    need(all(isinstance(row, dict) for row in rows) and
         [row.get('name') for row in rows] == list(CASES), 'not exactly two matched bounded CPU guests: ' + prefix)
    return rows


def check_prepared(row, traffic):
    need(set(row) == ROW_FIELDS, 'unexpected prepared-store metric fields')
    need(all(type(value) is int and value >= 0 for key, value in row.items() if key != 'name'),
         'noninteger/negative prepared-store counter')
    need(all(row[key] == 49 for key in ('starts', 'requests', 'replies', 'completions')) and
         row['prepared_starts'] + row['fallback_starts'] == 49,
         'prepared/fallback store-start/request/reply/completion conservation changed')
    need(row['normal_load_starts'] == traffic['architectural_loads'] and
         row['normal_memory_issued'] == row['normal_load_starts'] + row['fallback_starts'],
         'normal memory source conservation changed')
    need(row['fallback_without_prepared'] + row['fallback_different_owner'] == row['fallback_starts'],
         'prepared-store fallback reasons do not partition actual fallback starts')
    if row['name'] == 'vm_store_stream':
        need(row['prepared_starts'] > 0, 'stream did not exercise prepared-store starts')
    else:
        need(row['fallback_starts'] > 0, 'dependency guest did not exercise live fallback')


def compare_metrics(old, report):
    report['comparison'] = []
    for ordinal, name in enumerate(CASES):
        row, prev = report['cases'][ordinal], old['cases'][ordinal]
        traffic, flow = report['forwarding'][ordinal], report['flow'][ordinal]
        need(traffic == old['forwarding'][ordinal], 'prior forwarding/actual memory metric differs: ' + name)
        need(flow == old['flow'][ordinal], 'prior checked-flow histogram/conservation metric differs: ' + name)
        need(all(traffic[key] == 49 for key in ('architectural_stores', 'physical_stores', 'store_replies', 'store_completions')) and
             traffic['forwarded_loads'] == traffic['forwarded_retired'] == 48,
             '48 forwarded/49 actual-store conservation changed')
        need(set(row) == set(prev) and set(report['stages'][ordinal]) == set(old['stages'][ordinal]),
             'original CPU/stage metric schema changed')
        need(all(row[key] == prev[key] for key in ('retired', 'bootstrap_retired', 'roi_retired', 'placement')),
             'architectural retirement count or guest placement changed')
        need(row['work_cycles'] == row['bootstrap_cycles'] + row['roi_cycles'],
             'bootstrap/ROI/work cycle accounting mismatch')
        check_prepared(report['prepared_store'][ordinal], traffic)
        before, after = report['baseline_latency_owners'][name], report['latency_owners'][name]
        need(len(before) == len(after), 'actual DTA owner count changed')
        owner_diffs = []
        for index, (a, b) in enumerate(zip(before, after)):
            need(all(a[key] == b[key] for key in ('pc', 'va', 'pa', 'write', 'prechecked')),
                 'matched ordered DTA owner payload/shape changed')
            delta = differences(a, b)
            if delta:
                owner_diffs.append({'ordinal': index, 'pc': a['pc'], 'differences': delta})
        report['comparison'].append({
            'name': name, 'baseline_work': prev['work_cycles'], 'candidate_work': row['work_cycles'],
            'delta_work': row['work_cycles'] - prev['work_cycles'],
            'baseline_roi': prev['roi_cycles'], 'candidate_roi': row['roi_cycles'],
            'delta_roi': row['roi_cycles'] - prev['roi_cycles'], 'retired': row['retired'],
            'all_cpu_field_differences': differences(prev, row),
            'all_stage_field_differences': differences(old['stages'][ordinal], report['stages'][ordinal]),
            'all_owner_field_differences': owner_diffs,
            'actual_stage_observations': flow, 'prepared_store_observations': report['prepared_store'][ordinal],
        })


def negative(model, flag, marker, diagnostic):
    log = model / (flag[2:] + '.log')
    with log.open('x') as stream:
        result = subprocess.run([str(model / 'run'), flag], stdout=stream, stderr=subprocess.STDOUT,
                                timeout=180, env=base.runtime_env())
    text = log.read_text()
    base.check_log(text)
    need(result.returncode == 1 and text.count(marker) == 1 and diagnostic in text and PASS not in text,
         'negative missing exact sampled rejection: ' + flag)
    return {'flag': flag, 'returncode': result.returncode, 'marker': marker,
            'diagnostic': diagnostic, 'log_sha256': base.sha(log)}


def fresh_build_gate(model):
    path = model / 'run-compile-receipt.json'
    build = base.read_json(path.read_text())
    expected = {str(path) for path in model.glob(TOP + '[0-9]*.cpp')} | {str(HOST)}
    objects = build.get('objects', [])
    need(build.get('schema') == 'real-gsim-header-gate-v1' and build.get('syntax_pass') is True and
         len(objects) == len(expected) and {entry['source'] for entry in objects} == expected and
         all(entry.get('reused') is False for entry in objects), 'candidate must compile every DUT/host object fresh')
    return {'receipt': str(path), 'sha256': base.sha(path), 'all_objects_fresh': True,
            'generated_dut_objects': len(objects) - 1, 'host_objects': 1}


def unchanged_artifacts(binding):
    return all(Path(path).is_file() and base.sha(path) == expected
               for path, expected in binding.get('artifacts', {}).items())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--gsim', type=Path, required=True)
    parser.add_argument('--baseline', type=Path, default=common.BUILD / 'checked-flow-cpu-20261024-r2/receipt.json')
    parser.add_argument('--compile-receipt', type=Path,
                        help='successful current-source full Scala compile receipt; mandatory with --build-run')
    parser.add_argument('--reuse-control', type=Path,
                        help='opt in to the pinned failed r1 receipt/control and its one approved diagnostic mapping; no control re-emission')
    parser.add_argument('--build-run', action='store_true')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.tag):
        parser.error('fresh safe tag required')
    if args.build_run and args.compile_receipt is None:
        parser.error('--build-run requires --compile-receipt')
    before = inputs()
    if not args.build_run:
        print(json.dumps({'status': 'PREFLIGHT_ONLY', 'inputs': len(before), 'scope': SCOPE,
                          'host_source_gate': host_source_gate(), 'prepared_store_metric_fields': sorted(ROW_FIELDS)}, indent=2))
        return
    out = common.BUILD / args.tag
    out.mkdir(parents=True, exist_ok=False)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    gate.install()
    tools = base.tool_binding(True)
    cxx = tools['compiler']['command']
    need(args.gsim.resolve() == Path(tools['gsim']['path']).resolve(), 'pinned GSIM required')
    report = {'schema': 'prepared-head-store-cpu-v1', 'status': 'RUNNING',
              'source_revision': base.git(common.ROOT, 'rev-parse', 'HEAD').strip(),
              'inputs_before': before, 'tools_before': tools, 'scope': SCOPE}
    base.save_receipt(out, report)
    try:
        bind_compile_receipt(args.compile_receipt, report)
        if args.reuse_control:
            bind_reused_control(args.reuse_control, report)
        base.save_receipt(out, report)
        old = baseline_binding(args.baseline, before, tools, report)
        report['program_gate'] = program_gate(out, cxx)
        need(report['program_gate']['program_dump_sha256'] == old['program_gate']['program_dump_sha256'],
             'original published three-program dump binding changed')
        structural_gate(out, args.baseline, old, report)
        need(inputs() == before, 'source drift before candidate generation')
        model = common.test(args.gsim, cxx, args.tag + '/' + PROFILE, MAIN, TOP, HOST.name,
                            defines={}, timeout=180)
        report['candidate_fresh_build'] = fresh_build_gate(model)
        report['effective_parameters'] = effective(model)
        report['candidate_parameters'] = compare_params(old['effective_parameters'], report['effective_parameters'], True)
        for field, prefix in [('cases', 'A1_VM_CPU_METRIC '), ('stages', 'A1_VM_STAGE_METRIC '),
                              ('forwarding', 'M3_CPU_FORWARD_METRIC '), ('flow', 'CHECKED_FLOW_METRIC '),
                              ('prepared_store', 'PREPARED_STORE_METRIC ')]:
            report[field] = parse(model / 'test.log', prefix)
        report['latency_owners'], report['latency'] = read_owners(model / 'test.log')
        compare_metrics(old, report)
        base.save_receipt(out, report)
        report['negative_controls'] = [negative(model, *entry) for entry in (
            ('--inject-prepared-data', 'PREPARED_STORE_NEGATIVE_REACHED', 'independent prepared-store owner/payload mismatch'),
            ('--inject-retirement-data', 'A1_RETIREMENT_NEGATIVE_REACHED', 'data pc='))]
        report['status'] = 'PASS_BOUNDED_PREPARED_HEAD_STORE_ACTUAL_CPU'
    except BaseException as error:
        report.update(status='FAIL', failure=f'{type(error).__name__}: {error}')
        raise
    finally:
        report['inputs_after'] = inputs()
        report['inputs_unchanged'] = report['inputs_after'] == before
        report['source_input_drift'] = differences(before, report['inputs_after'])
        report['tools_after'] = base.tool_binding(True)
        report['tools_unchanged'] = report['tools_after'] == tools
        report['baseline_artifacts_unchanged'] = unchanged_artifacts(report.get('baseline_binding', {}))
        report['scala_compile_receipt_unchanged'] = unchanged_artifacts(report.get('scala_compile_receipt', {}))
        report['reused_control_artifacts_unchanged'] = unchanged_artifacts(report.get('control_reuse', {}))
        if not all(report[key] for key in ('inputs_unchanged', 'tools_unchanged',
                                          'baseline_artifacts_unchanged', 'scala_compile_receipt_unchanged',
                                          'reused_control_artifacts_unchanged')):
            report['status'] = 'FAIL_INPUT_DRIFT'
        report['artifacts_sha256'] = {str(path.relative_to(out)): base.sha(path) for path in sorted(out.rglob('*'))
                                     if path.is_file() and path.name not in ('receipt.json', 'receipt.json.tmp')}
        base.save_receipt(out, report)
    need(report['status'].startswith('PASS_'), report['status'])
    print(json.dumps({'status': report['status'], 'receipt': str(out / 'receipt.json'),
                      'comparison': report['comparison']}, indent=2))


if __name__ == '__main__':
    main()
