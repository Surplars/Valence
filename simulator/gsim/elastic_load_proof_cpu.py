#!/usr/bin/env python3
"""One fresh actual-tile elastic-proof DUT, two immutable VM + two load guests.

The old store-row DUT is reused only as historical evidence after complete tool,
artifact, source and disabled-control FIR gates. A second new host links the same
fresh DUT objects after key/SHA verification, never inheriting an old PASS.
No general model-resume entry point is used. Default invocation is read-only.
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

sys.dont_write_bytecode = True
import run as common
import a1_common_cpu_retirement as base
import prepared_head_store_cpu as row
import m2_r1_compile_gate as gate

TOP = row.TOP
MAIN = 'soc.core.ooo.ElasticLoadProofCpuGsimMain'
PROFILE = 'full-r1-m3-checked-flow-store-row-elastic-proof'
OLD_PROFILE = row.PROFILE
OLD = common.BUILD / 'prepared-head-store-cpu-20261024-r2/receipt.json'
OLD_SHA = '8822545165993f9a8a604b2577126a3d562b0e25441902d672e4ce92dbba3390'
LOAD = common.BUILD / 'independent-load-supply-20261024-r1'
LOAD_SHA = 'd715acca33aed1b78d5a27b697fd037a331381ad770b03d8aacf7a491c7b4455'
MANIFEST_SHA = '260130a9404f7821d2d579ee525d74e06791d1172cee254bd6f5c640bf8c0b39'
OLD_LOAD_SHA = '11d5b11324ffc1592212decbc63ce2fbf55e6d5e9cb7594db2c035fd45cf4d7f'
HOST = common.HERE / 'harness/elastic_load_supply.cpp'
CACHE = 'src/main/scala/core/ooo/cache/NonBlockingCoherentLineCache.scala'
NEW_FILES = ('src/test/scala/platform/ElasticLoadProofCpuGsim.scala',
             'simulator/gsim/harness/elastic_load_supply.cpp',
             'simulator/gsim/elastic_load_proof_cpu.py')
SCOPE = {
    'DUT': 'one fresh full-resource CommonA1CpuTile, full-r1-m3-checked-flow-store-row-elastic-proof',
    'delta': 'elasticLoadProofSupply=true only; existing default/old proof module retained',
    'guests': 'two immutable 233-retirement VM guests plus immutable hot256/cold16 independent-load guests',
    'services': 'original per-host service laws, whole-line 512-bit Grant, not Home/DDR/AXI/CDC',
    'proof': 'passive query/full-token/VA/size/epoch -> registered permission -> actual prechecked issue; tiny module owns adversarial FSM coverage',
    'descriptorPreempt': 'constant false by reviewed contract; D cleanup still through raw valid/live, issued and flush paths',
    'performance': 'observed per-case cycles, stage/owner histograms; no required speedup or claim of PPA/Fmax/DDR bandwidth',
    'build': 'one fresh generated DUT; immutable VM host then independent new load host with explicitly rechecked DUT object keys/SHA',
    'negative_scope': 'two existing VM observation mutations, not RTL mutants; no new load-host mutant',
    'limits': 'CPU does not inject arbitrary backpressure/recovery; no alias rerun/full regression/native/board/STA',
}
need = row.need
sha = base.sha
read = lambda p: base.read_json(Path(p).read_text())


def inputs():
    result = row.inputs()
    for name in NEW_FILES:
        result[name] = sha(common.ROOT / name)
    return dict(sorted(result.items()))


def host_source_gate():
    old = (LOAD / 'load_supply.cpp').read_text()
    new = HOST.read_text()
    need(sha(LOAD / 'load_supply.cpp') == OLD_LOAD_SHA, 'old load host bytes changed')
    start = ' // Passive elastic evidence.'
    end = ' void retireOne(const Retire&r,Token t)'
    need(new.count(start) == new.count(end) == 1, 'one passive proof observer block required')
    new = new[:new.index(start)] + new[new.index(end):]
    for a, b in {
        'dut.get_supply$$offer()': 'dut.tile$core$core$core$backend$_lsu_io_start_valid_T_4',
        'dut.get_supply$$ready()': 'dut.tile$core$core$core$backend$lsu$_io_start_ready_T_12',
        'dut.get_supply$$choice()': 'dut.tile$core$core$core$backend$_memoryChoice_valid_T_4',
        'dut.get_supply$$staged()': 'dut.tile$core$core$core$backend$stagedMemoryValid',
        'dut.get_supply$$owner##N##$$index(),dut.get_supply$$owner##N##$$tag()':
            'dut.tile$core$core$core$backend$lsu$slots_##N##$operation$$token$$index,dut.tile$core$core$core$backend$lsu$slots_##N##$operation$$token$$tag',
        'new_full_r1_m3_checked_flow_store_row_elastic_proof': 'saved_full_r1_m3_checked_flow_store_row',
        'occupancy(s,grant);flow(s);proofObserve();': 'occupancy(s,grant);flow(s);',
        '}report();proofReport();}': '}report();}',
    }.items():
        need(new.count(a) == 1, 'unexpected passive host substitution count: ' + a)
        new = new.replace(a, b)
    start, end = '  const std::array<unsigned,4>state{', '  // An idle operation'
    a, b = new.index(start), new.index(end)
    replacement = new[a:b]
    expected = ('  const std::array<unsigned,4>state{unsigned(dut.get_supply$$states())&3u,(unsigned(dut.get_supply$$states())>>2)&3u,(unsigned(dut.get_supply$$states())>>4)&3u,(unsigned(dut.get_supply$$states())>>6)&3u};\n'
                '  const std::array<bool,4>cancel{bool(dut.get_supply$$cancelled()&1),bool(dut.get_supply$$cancelled()&2),bool(dut.get_supply$$cancelled()&4),bool(dut.get_supply$$cancelled()&8)};\n')
    need(replacement == expected, 'stable slot observation mapping changed')
    new = new[:a] + old[old.index(start):old.index(end)] + new[b:]
    need(new == old, 'load guest/service/ISA/PMP/PTE/retirement/ROI source changed beyond exact passive additions')
    need(sha(row.HOST) == 'bd993d81fcd52c79bf3d045bc0bdefc298fbf54318253d00fa8d4ab04582cc5d',
         'old two-VM host must remain byte-identical')
    return {'old_vm_host_exact': True, 'load_host_restored_bytes_exact': True,
            'allowed_delta': 'stable backend observation mapping, passive proof block/calls, displayed model identity only'}


def bind_baselines(report):
    need(sha(OLD) == OLD_SHA and sha(LOAD / 'receipt.json') == LOAD_SHA and
         sha(LOAD / 'manifest.json') == MANIFEST_SHA, 'historical baseline receipt/manifest changed')
    old, load = read(OLD), read(LOAD / 'receipt.json')
    need(old['status'] == 'PASS_BOUNDED_PREPARED_HEAD_STORE_ACTUAL_CPU' and
         old['inputs_unchanged'] and old['tools_unchanged'] and old['baseline_artifacts_unchanged'],
         'old CPU evidence lacks unchanged successful binding')
    need(report['tools_before'] == old['tools_after'], 'historical/current tool identity mismatch')
    need(load['status'] == 'PASS' and load['new_DUT_builds'] == 0 and load['hardware_guest_runs'] == 2,
         'old independent-load evidence invalid')
    need(load['compiler']['command'] == report['tools_before']['compiler']['command'] and
         load['compiler']['resolved_sha256'] == report['tools_before']['compiler']['sha256'],
         'historical load compiler command/hash changed')
    bound = {str(OLD): OLD_SHA, str(LOAD / 'manifest.json'): MANIFEST_SHA}
    for name, digest in old['artifacts_sha256'].items():
        path = (OLD.parent / name).resolve()
        need(OLD.parent in path.parents and sha(path) == digest, 'old CPU artifact changed: ' + name)
        bound[str(path)] = digest
    for name, digest in old['baseline_binding']['artifacts'].items():
        need(sha(name) == digest, 'old transitive artifact changed: ' + name)
        bound[name] = digest
    for name, digest in read(LOAD / 'manifest.json')['files'].items():
        path = (LOAD / name).resolve()
        need(LOAD in path.parents and sha(path) == digest, 'old load evidence changed: ' + name)
        bound[str(path)] = digest
    for name, digest in read(LOAD / 'input-bindings.json')['files'].items():
        path = common.ROOT / name
        need(sha(path) == digest, 'old load DUT binding changed: ' + name)
        bound[str(path)] = digest
    immutable = (*row.IMMUTABLE, 'src/test/scala/platform/PreparedHeadStoreCpuGsim.scala',
                 'simulator/gsim/harness/prepared_head_store_cpu.cpp',
                 'simulator/gsim/prepared_head_store_cpu.py', CACHE)
    for name in immutable:
        need(report['inputs_before'][name] == old['inputs_after'][name], 'historical source changed: ' + name)
    need([x['work_cycles'] for x in old['cases']] == [687, 1071] and
         [x['roi_work_cycles'] for x in load['metrics']] == [784, 360], 'historical cycle reference changed')
    report['baseline_binding'] = {'artifacts': bound, 'CPU_receipt': str(OLD), 'load_receipt': str(LOAD / 'receipt.json'),
                                 'source_differences': row.differences(old['inputs_after'], report['inputs_before']),
                                 'tool_identity_exact': True}
    report['baseline_latency_owners'], report['baseline_latency'] = row.read_owners(OLD.parent / OLD_PROFILE / 'test.log')
    return old, load


def compare_params(old, new, enabled):
    delta = {}
    for kind in ('core', 'config'):
        added = {k: new[kind][k] for k in new[kind].keys() - old[kind].keys()}
        need(added == {'elasticLoadProofSupply': str(enabled).lower()} and
             all(new[kind].get(k) == v for k, v in old[kind].items()), 'unexpected effective ' + kind + ' delta')
        delta[kind] = added
    return delta


def bind_control_reuse(path, report):
    path = path.resolve(strict=True)
    need(path == common.BUILD / 'elastic-load-proof-cpu-20261024-r1/receipt.json' and
         sha(path) == '3b402f4683884760997a1b9d5674fb9349aab42e28b875fb7132cd9c699410cf',
         'only the exact historical failed r1 control may be reused')
    prior = read(path)
    need(prior['status'] == 'FAIL' and prior['failure'].startswith('RuntimeError: FRESH_BASELINE_REQUIRED:') and
         all(prior[k] for k in ('inputs_unchanged', 'tools_unchanged', 'baseline_artifacts_unchanged', 'scala_compile_receipt_unchanged')),
         'reused r1 must be a clean structural-only rejection')
    runner = 'simulator/gsim/elastic_load_proof_cpu.py'
    delta = row.differences(prior['inputs_before'], report['inputs_before'])
    need(set(delta) == {runner} and delta[runner][0] == '09ebe291114c4964c3b401572dda70674eb6ce75e60b905a1004b8272cb1bf9b',
         'r1 control reuse permits only this explicitly approved runner-only mapping change')
    need(prior['tools_after'] == report['tools_before'] and
         prior['scala_compile_receipt']['sha256'] == report['scala_compile_receipt']['sha256'],
         'r1 control compile/tool identity mismatch')
    bound = {str(path): sha(path)}
    for name, digest in prior['artifacts_sha256'].items():
        source = (path.parent / name).resolve()
        need(path.parent in source.parents and sha(source) == digest, 'r1 artifact changed: ' + name)
        bound[str(source)] = digest
    actual = {str(p.relative_to(path.parent)) for p in path.parent.rglob('*') if p.is_file() and p != path}
    need(actual == set(prior['artifacts_sha256']), 'r1 artifact set changed')
    report['control_reuse'] = {'receipt': str(path), 'artifacts': bound, 'input_differences': delta,
        'control_artifacts': {name: digest for name, digest in prior['artifacts_sha256'].items()
                              if name.startswith('baseline-structural-gate/')},
        'scope': 'already emitted control only; no old candidate or new functional PASS is reused'}


def structural_gate(out, old, report):
    control = out / 'baseline-structural-gate'
    control.mkdir()
    reuse = report.get('control_reuse')
    if reuse:
        for name, digest in reuse['control_artifacts'].items():
            source = Path(reuse['receipt']).parent / name
            destination = control / ('r1-source-only.diff' if Path(name).name == 'normalized.diff' else Path(name).name)
            shutil.copyfile(source, destination)
            need(sha(destination) == digest, 'copied r1 control differs')
    else:
        common.run(['mill', '-i', 'IonSoC.test.runMain', 'soc.core.ooo.PreparedHeadStoreCpuGsimMain', control],
                   log=control / 'elaborate.log')
    report['baseline_parameters'] = compare_params(old['effective_parameters'], row.effective(control), False)
    oldfir, newfir = OLD.parent / OLD_PROFILE / (TOP + '.fir'), control / (TOP + '.fir')
    a, b = row.normalize_fir(oldfir.read_bytes()), row.normalize_fir(newfir.read_bytes())
    mapped, mapping = a, None
    if reuse:
        need(sha(oldfir) == 'c6d2ebc23e63a79db0cfe807f90d19c961988b22f9397644691acea620c1d86b' and
             sha(newfir) == 'dbd4b91f15cc1f1781d4063e44a9b62295fbeedd5574b308fc6674dce3337a00',
             'approved mapping requires exact old/new raw FIR')
        old_text = b'"Assertion failed at IntegerBackend.scala:3472\\n"'
        new_text = b'"Assertion failed at IntegerBackend.scala:3520\\n"'
        need(a.count(old_text) == b.count(new_text) == 1 and not a.count(new_text) and not b.count(old_text),
             'approved complete diagnostic must occur exactly once')
        mapped = a.replace(old_text, new_text)
        mapping = {'old': old_text.decode(), 'new': new_text.decode(), 'old_count': 1, 'new_count': 1,
                   'approval': 'Root reviewed identical PopCount dispatcher-bound assertion, clock/predicates/label; exact single diagnostic locator mapping only.'}
    diff = control / 'normalized.diff'
    diff.write_text(''.join(difflib.unified_diff(mapped.decode().splitlines(True), b.decode().splitlines(True),
                                               fromfile=str(oldfir), tofile=str(newfir))))
    report['baseline_fir_gate'] = {'old_fir_sha256': sha(oldfir), 'new_fir_sha256': sha(newfir),
        'old_normalized_sha256': hashlib.sha256(a).hexdigest(), 'new_normalized_sha256': hashlib.sha256(b).hexdigest(),
        'normalization': 'source annotations outside quoted strings; only on pinned r1 reuse, exact approved complete diagnostic 3472 -> 3520 count1',
        'raw_exact': oldfir.read_bytes() == newfir.read_bytes(), 'source_only_exact': a == b,
        'approved_diagnostic_mapping': mapping, 'mapped_old_sha256': hashlib.sha256(mapped).hexdigest(),
        'mapped_new_sha256': hashlib.sha256(b).hexdigest(), 'exact': mapped == b,
        'diff': str(diff), 'diff_sha256': sha(diff)}
    base.save_receipt(out, report)
    need(mapped == b, 'FRESH_BASELINE_REQUIRED: disabled control differs beyond source annotations; see ' + str(diff))


def cache_gate(model, out, report):
    def module(path):
        data = row.normalize_fir(path.read_bytes())
        matches = re.findall(rb'^  module NonBlockingCoherentLineCache :[^\n]*\n.*?(?=^  (?:module|extmodule|intmodule) |\Z)',
                             data, re.M | re.S)
        need(len(matches) == 1, 'exactly one actual NonBlockingCoherentLineCache module required')
        return matches[0]
    a = module(OLD.parent / OLD_PROFILE / (TOP + '.fir'))
    b = module(model / (TOP + '.fir'))
    report['cache_observation_gate'] = {'source': CACHE, 'source_sha256': sha(common.ROOT / CACHE),
        'old_module_sha256': hashlib.sha256(a).hexdigest(), 'new_module_sha256': hashlib.sha256(b).hexdigest(),
        'exact_after_source_annotations': a == b,
        'scope': 'same private named cache/engine members; all backend temporary names replaced by explicit wrapper outputs'}
    base.save_receipt(out, report)
    need(a == b, 'private cache observer module changed; cannot silently reuse named fields')


def program_gate(out, cxx):
    report = host_source_gate()
    binary = out / 'load-oracle'
    flags = ['-std=c++20', '-O1', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=all']
    common.run([cxx, *flags, '-DA1_LOAD_ORACLE_ONLY', HOST, '-o', binary], log=out / 'oracle-compile.log')
    common.run([binary, '--dump-programs'], env=base.runtime_env(), log=out / 'programs.log')
    need((out / 'programs.log').read_bytes() == (LOAD / 'programs.log').read_bytes(), 'raw hot/cold programs differ')
    common.run([binary, '--oracle-only'], env=base.runtime_env(), log=out / 'oracle.log')
    text = (out / 'oracle.log').read_text()
    base.check_log(text)
    need(text.splitlines().count('LOAD_SUPPLY_PASS') == 1, 'standalone load oracle failed')
    report['load_programs_sha256'] = sha(out / 'programs.log')
    return report


def second_host(model, out, cxx, report):
    """Explicit same-new-model object proof, not the mock-only generic resume tool."""
    receipt_path = model / 'run-compile-receipt.json'
    record_sha = sha(receipt_path)
    build = read(receipt_path)
    need(build['schema'] == 'real-gsim-header-gate-v1' and build['syntax_pass'] and
         build['host'] == str(row.HOST) and build['host_sha256'] == sha(row.HOST), 'first fresh model build binding invalid')
    need(build['compiler'] == str(Path(cxx).resolve()), 'second host compiler identity mismatch')
    files = {str(receipt_path): record_sha, **build['headers']}
    objects = []
    generated = {str(p) for p in model.glob(TOP + '[0-9]*.cpp')}
    for entry in build['objects']:
        source = Path(entry['source'])
        need(not entry['reused'] and sha(source) == entry['source_sha256'] and
             sha(entry['object']) == entry['object_sha256'], 'first-build source/object SHA changed')
        key = hashlib.sha256(json.dumps({'source': sha(source), 'headers': build['headers'],
              'flags': build['flags'], 'compiler': sha(cxx)}, sort_keys=True).encode()).hexdigest()
        need(key == entry['key'], 'first-build full object content key mismatch')
        files[str(source)] = entry['source_sha256']
        files[entry['object']] = entry['object_sha256']
        if str(source) in generated:
            objects.append(entry['object'])
    need(len(objects) == len(generated) > 0 and len(build['objects']) == len(generated) + 1,
         'DUT object/source set incomplete or unexpected extra object')
    need(row.unchanged_artifacts({'artifacts': files}), 'same-model artifact drift before load host')
    target = out / 'load-host'
    target.mkdir()
    flags = build['flags']
    common.run([cxx, *flags, '-fsyntax-only', HOST], log=target / 'header-syntax.log')
    obj = target / 'elastic_load_supply.o'
    common.run([cxx, *flags, '-c', HOST, '-o', obj], log=target / 'host-compile.log')
    common.run([cxx, *flags, *objects, obj, '-ldl', '-o', target / 'run'], log=target / 'host-link.log')
    record = {'schema': 'elastic-same-fresh-dut-second-host-v1', 'first_build_receipt': str(receipt_path),
              'first_build_receipt_sha256': record_sha, 'artifacts': files, 'all_DUT_keys_and_SHAs_verified': True,
              'host': str(HOST), 'host_sha256': sha(HOST), 'host_object_sha256': sha(obj),
              'compiler': str(Path(cxx).resolve()), 'compiler_sha256': sha(cxx), 'ordered_flags': flags,
              'binary_sha256': sha(target / 'run'), 'new_DUT_compilations': 0, 'new_host_compilations': 1,
              'status': 'BUILT_NOT_RUN'}
    record_path = target / 'link-receipt.json'
    record_path.write_text(json.dumps(record, indent=2) + '\n')
    report['second_host'] = {'receipt': str(record_path), 'sha256': sha(record_path)}
    base.save_receipt(out, report)
    common.run([target / 'run', '--trace'], env=base.runtime_env(), log=target / 'test.log', timeout=180)
    need(row.unchanged_artifacts({'artifacts': files}), 'same-model artifacts changed after execution')
    record.update(status='PASS_NEW_LOAD_HOST', artifacts_unchanged=True, log_sha256=sha(target / 'test.log'))
    record_path.write_text(json.dumps(record, indent=2) + '\n')
    report['second_host']['sha256'] = sha(record_path)
    return target


def load_metrics(log, prefix):
    text = log.read_text()
    base.check_log(text)
    need(text.splitlines().count('LOAD_SUPPLY_PASS') == 1, 'load host exact PASS missing')
    records = [base.read_json(line[len(prefix):]) for line in text.splitlines() if line.startswith(prefix)]
    need([r['name'] for r in records] == ['hot_loads', 'delayed_cold_loads'], 'two exact load cases required')
    return records



def compare_loads(previous, current):
    result = []
    need(len(previous) == len(current) == 2, 'exactly two prior/current load records required')
    for prev, case in zip(previous, current):
        need(set(prev) == set(case), 'old load metric schema changed')
        for key in ('name', 'service', 'retired', 'warm_loads', 'measured_loads', 'measured_iterations',
                    'roi_instructions_including_loop', 'roi_loop_overhead_retired', 'fixture', 'roi_work_boundary'):
            need(prev[key] == case[key], 'load oracle/service/ROI contract changed: ' + key)
        result.append({'name': case['name'], 'baseline_work': prev['work_cycles'],
            'candidate_work': case['work_cycles'], 'delta_work': case['work_cycles'] - prev['work_cycles'],
            'baseline_roi': prev['roi_work_cycles'], 'candidate_roi': case['roi_work_cycles'],
            'delta_roi': case['roi_work_cycles'] - prev['roi_work_cycles'],
            'all_field_differences': row.differences(prev, case)})
    return result


def finalize_existing(path, out):
    """Read-only recovery of the one pinned parser-name rejection, no tool/model execution."""
    path = path.resolve(strict=True)
    need(path == common.BUILD / 'elastic-load-proof-cpu-20261024-r2/receipt.json' and
         sha(path) == '3694e4f3e84077dd5ce119d29aa826b0f1453b2f93179506bc5e3e2afed25c62',
         'only exact r2 parser failure may be finalized')
    before = inputs()
    prior = read(path)
    need(prior['status'] == 'FAIL' and prior['failure'] == 'RuntimeError: two exact load cases required' and
         all(prior[k] for k in ('inputs_unchanged', 'tools_unchanged', 'baseline_artifacts_unchanged',
                                'scala_compile_receipt_unchanged', 'control_reuse_unchanged')),
         'not the approved post-execution parser-name failure')
    runner = 'simulator/gsim/elastic_load_proof_cpu.py'
    delta = row.differences(prior['inputs_after'], before)
    need(set(delta) == {runner} and delta[runner][0] == '7335b2c29185a94c79de5fa0744b1fc413206e9c80891184b6dad6aff855eef7',
         'only approved parser/finalizer Python bytes may differ from r2')
    need(base.tool_binding(True) == prior['tools_after'], 'tool identity differs from successful executions')
    bound = {str(path): sha(path)}
    for name, digest in prior['artifacts_sha256'].items():
        source = (path.parent / name).resolve()
        need(path.parent in source.parents and sha(source) == digest, 'r2 execution artifact changed: ' + name)
        bound[str(source)] = digest
    actual = {str(p.relative_to(path.parent)) for p in path.parent.rglob('*') if p.is_file() and p != path}
    need(actual == set(prior['artifacts_sha256']), 'r2 execution artifact set changed')
    for binding in ('baseline_binding', 'scala_compile_receipt', 'control_reuse'):
        need(row.unchanged_artifacts(prior[binding]), 'r2 transitive binding changed: ' + binding)
    link_path = Path(prior['second_host']['receipt'])
    need(sha(link_path) == prior['second_host']['sha256'], 'second host link receipt changed')
    link = read(link_path)
    need(link['status'] == 'PASS_NEW_LOAD_HOST' and link['artifacts_unchanged'] and
         link['all_DUT_keys_and_SHAs_verified'] and row.unchanged_artifacts(link), 'same-DUT host execution binding invalid')
    model = path.parent / PROFILE
    for field, prefix in [('cases', 'A1_VM_CPU_METRIC '), ('stages', 'A1_VM_STAGE_METRIC '),
                          ('forwarding', 'M3_CPU_FORWARD_METRIC '), ('flow', 'CHECKED_FLOW_METRIC '),
                          ('prepared_store', 'PREPARED_STORE_METRIC ')]:
        need(row.parse(model / 'test.log', prefix) == prior[field], 'r2 VM parsed fields differ: ' + field)
    need(len(prior['negative_controls']) == 2, 'both original VM negatives required')
    for entry in prior['negative_controls']:
        log = model / (entry['flag'][2:] + '.log')
        text = log.read_text()
        base.check_log(text)
        need(sha(log) == entry['log_sha256'] and entry['returncode'] == 1 and
             text.count(entry['marker']) == 1 and entry['diagnostic'] in text and row.PASS not in text,
             'existing exact negative evidence differs')
    cases = load_metrics(path.parent / 'load-host/test.log', 'LOAD_SUPPLY_METRIC ')
    proofs = load_metrics(path.parent / 'load-host/test.log', 'ELASTIC_PROOF_METRIC ')
    comparisons = compare_loads(read(LOAD / 'receipt.json')['metrics'], cases)
    out.mkdir(parents=True, exist_ok=False)
    report = {k: prior[k] for k in ('source_revision', 'scope', 'baseline_binding', 'baseline_fir_gate',
             'baseline_parameters', 'candidate_parameters', 'effective_parameters', 'cache_observation_gate',
             'candidate_fresh_build', 'second_host', 'scala_compile_receipt', 'control_reuse', 'program_gate',
             'cases', 'stages', 'forwarding', 'flow', 'prepared_store', 'latency', 'latency_owners',
             'comparison', 'negative_controls', 'tools_after')}
    report.update(schema='elastic-load-proof-readonly-finalize-v1', status='PASS_BOUNDED_ELASTIC_LOAD_PROOF_ACTUAL_CPU',
        execution_receipt=str(path), execution_receipt_sha256=sha(path), execution_original_status='FAIL',
        execution_failure='post-execution parser expected cold_loads, immutable actual guest is delayed_cold_loads; not a DUT failure',
        execution_artifacts=bound, execution_source_inputs=prior['inputs_after'],
        finalizer_inputs_before=before, finalizer_source_difference=delta,
        new_hardware_runs=0, new_DUT_compilations=0, new_host_compilations=0,
        load_cases=cases, proof_metrics=proofs, load_comparison=comparisons)
    report['finalizer_inputs_after'] = inputs()
    report['execution_artifacts_unchanged'] = row.unchanged_artifacts({'artifacts': bound})
    report['finalizer_inputs_unchanged'] = before == report['finalizer_inputs_after']
    need(report['execution_artifacts_unchanged'] and report['finalizer_inputs_unchanged'], 'finalization input drift')
    base.save_receipt(out, report)
    print(json.dumps({'status': report['status'], 'receipt': str(out / 'receipt.json'),
                      'new_hardware_runs': 0, 'load_comparison': comparisons}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--gsim', required=True, type=Path)
    parser.add_argument('--compile-receipt', type=Path)
    parser.add_argument('--reuse-control', type=Path, help='only pinned failed r1 control; exact approved diagnostic mapping')
    parser.add_argument('--finalize-existing', type=Path, help='read only: pinned r2 parser failure after all four real guests passed')
    parser.add_argument('--build-run', action='store_true')
    args = parser.parse_args()
    need(re.fullmatch(r'[A-Za-z0-9_-]+', args.tag), 'safe fresh tag required')
    if args.finalize_existing:
        need(not args.build_run and not args.reuse_control, 'read-only finalization cannot build/run or emit')
        finalize_existing(args.finalize_existing, common.BUILD / args.tag)
        return
    before = inputs()
    if not args.build_run:
        print(json.dumps({'status': 'PREFLIGHT_ONLY', 'inputs': len(before), 'source_gate': host_source_gate(), 'scope': SCOPE}, indent=2))
        return
    need(args.compile_receipt is not None, 'current full Scala compile receipt required')
    out = common.BUILD / args.tag
    out.mkdir(parents=True, exist_ok=False)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    tools = base.tool_binding(True)
    cxx = tools['compiler']['command']
    need(args.gsim.resolve() == Path(tools['gsim']['path']).resolve(), 'pinned GSIM required')
    report = {'schema': 'elastic-load-proof-actual-cpu-v1', 'status': 'RUNNING', 'scope': SCOPE,
              'source_revision': base.git(common.ROOT, 'rev-parse', 'HEAD').strip(),
              'inputs_before': before, 'tools_before': tools}
    base.save_receipt(out, report)
    try:
        row.bind_compile_receipt(args.compile_receipt, report)
        old, load = bind_baselines(report)
        report['program_gate'] = program_gate(out, cxx)
        if args.reuse_control:
            bind_control_reuse(args.reuse_control, report)
        structural_gate(out, old, report)
        need(inputs() == before, 'source drift before candidate emission')
        gate.install()
        gated_run = common.run
        def with_cache_gate(command, **kwargs):
            if str(command[0]) == str(args.gsim):
                cache_gate(out / PROFILE, out, report)
            return gated_run(command, **kwargs)
        common.run = with_cache_gate
        model = common.test(args.gsim, cxx, args.tag + '/' + PROFILE, MAIN, TOP, row.HOST.name,
                            defines={}, timeout=180)
        report['candidate_fresh_build'] = row.fresh_build_gate(model)
        report['effective_parameters'] = row.effective(model)
        report['candidate_parameters'] = compare_params(old['effective_parameters'], report['effective_parameters'], True)
        for field, prefix in [('cases', 'A1_VM_CPU_METRIC '), ('stages', 'A1_VM_STAGE_METRIC '),
                              ('forwarding', 'M3_CPU_FORWARD_METRIC '), ('flow', 'CHECKED_FLOW_METRIC '),
                              ('prepared_store', 'PREPARED_STORE_METRIC ')]:
            report[field] = row.parse(model / 'test.log', prefix)
        report['latency_owners'], report['latency'] = row.read_owners(model / 'test.log')
        row.compare_metrics(old, report)
        base.save_receipt(out, report)
        report['negative_controls'] = [row.negative(model, *entry) for entry in (
            ('--inject-prepared-data', 'PREPARED_STORE_NEGATIVE_REACHED', 'independent prepared-store owner/payload mismatch'),
            ('--inject-retirement-data', 'A1_RETIREMENT_NEGATIVE_REACHED', 'data pc='))]
        target = second_host(model, out, cxx, report)
        report['load_cases'] = load_metrics(target / 'test.log', 'LOAD_SUPPLY_METRIC ')
        report['proof_metrics'] = load_metrics(target / 'test.log', 'ELASTIC_PROOF_METRIC ')
        report['load_comparison'] = []
        for prev, current in zip(load['metrics'], report['load_cases']):
            need(set(prev) == set(current), 'old load metric schema changed')
            for key in ('service', 'retired', 'warm_loads', 'measured_loads', 'measured_iterations',
                        'roi_instructions_including_loop', 'roi_loop_overhead_retired', 'fixture', 'roi_work_boundary'):
                need(prev[key] == current[key], 'load oracle/service/ROI contract changed: ' + key)
            report['load_comparison'].append({'name': current['name'],
                'baseline_work': prev['work_cycles'], 'candidate_work': current['work_cycles'],
                'delta_work': current['work_cycles'] - prev['work_cycles'],
                'baseline_roi': prev['roi_work_cycles'], 'candidate_roi': current['roi_work_cycles'],
                'delta_roi': current['roi_work_cycles'] - prev['roi_work_cycles'],
                'all_field_differences': row.differences(prev, current)})
        report['status'] = 'PASS_BOUNDED_ELASTIC_LOAD_PROOF_ACTUAL_CPU'
    except BaseException as error:
        report.update(status='FAIL', failure=f'{type(error).__name__}: {error}')
        raise
    finally:
        report['inputs_after'] = inputs()
        report['inputs_unchanged'] = before == report['inputs_after']
        report['source_input_drift'] = row.differences(before, report['inputs_after'])
        report['tools_after'] = base.tool_binding(True)
        report['tools_unchanged'] = tools == report['tools_after']
        report['baseline_artifacts_unchanged'] = row.unchanged_artifacts(report.get('baseline_binding', {}))
        report['scala_compile_receipt_unchanged'] = row.unchanged_artifacts(report.get('scala_compile_receipt', {}))
        report['control_reuse_unchanged'] = row.unchanged_artifacts(report.get('control_reuse', {}))
        if not all(report[k] for k in ('inputs_unchanged', 'tools_unchanged', 'baseline_artifacts_unchanged', 'scala_compile_receipt_unchanged', 'control_reuse_unchanged')):
            report['status'] = 'FAIL_INPUT_DRIFT'
        report['artifacts_sha256'] = {str(p.relative_to(out)): sha(p) for p in sorted(out.rglob('*'))
                                     if p.is_file() and p.name not in ('receipt.json', 'receipt.json.tmp')}
        base.save_receipt(out, report)
    need(report['status'].startswith('PASS_'), report['status'])
    print(json.dumps({'status': report['status'], 'receipt': str(out / 'receipt.json'),
                      'VM_comparison': report['comparison'], 'load_comparison': report['load_comparison']}, indent=2))


if __name__ == '__main__':
    main()
