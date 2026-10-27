#!/usr/bin/env python3
"""Fresh same-tool actual-CPU control/candidate, four immutable guests each.

Default mode is a read-only source preflight. --build-run requires the public
full Scala compile receipt. Exactly two fresh DUTs are elaborated/generated and
built once each; a second immutable host links only that DUT's verified objects.
The old cleanup receipt is historical context, never reusable functional proof.
No generic model resume, old object reuse, native/NEMU/STA/board run is offered.
"""
import argparse
from collections import Counter
import difflib
import hashlib
import json
from pathlib import Path
import re
import resource
import subprocess
import sys
import tarfile

sys.dont_write_bytecode = True
import run as common
import a1_common_cpu_retirement as base
import prepared_head_store_cpu as row
import m2_r1_compile_gate as gate

need, sha = row.need, base.sha
TOP = 'CommonA1VmPipelineGsim'
MAIN = 'soc.core.ooo.RegisteredRawCertifiedCpuGsimMain'
CONTROL = 'full-r1-m3-checked-flow-store-row-elastic-proof'
CANDIDATE = CONTROL + '-registered-raw'
PROFILES = (CONTROL, CANDIDATE)
SELF = 'simulator/gsim/registered_raw_certified_cpu.py'
WRAPPER = 'src/test/scala/platform/RegisteredRawCertifiedCpuGsim.scala'
HOST = common.HERE / 'harness/registered_raw_certified_cpu.cpp'
LOAD_HOST = common.HERE / 'harness/elastic_load_supply.cpp'
OLD_HOST_SHA = 'bd993d81fcd52c79bf3d045bc0bdefc298fbf54318253d00fa8d4ab04582cc5d'
LOAD_HOST_SHA = 'd06c7ea0d9f979361cd66fc70010c287fb60e592eeee11d6523b5126fca5d329'
HISTORY = common.BUILD / 'elastic-proof-control-cut-cpu-20261024-r2/receipt.json'
HISTORY_SHA = 'b0eb81853983dbedf468a350cfd8b9cf171457bf19ba83cdce9dc60405e09150'
HISTORY_ARCHIVE = common.ROOT / 'build/elastic-proof-control-cut-20261024-r2/final-frozen-inputs.tar.gz'
HISTORY_ARCHIVE_SHA = '9ae22c5eb3bc2273ce33bf41460de82242533797d3a51df0d160d4a0ed06e626'
HISTORY_MANIFEST = HISTORY_ARCHIVE.parent / 'final-source-manifest.json'
HISTORY_MANIFEST_SHA = '0106d5a2a6118ab408769ff05fc730098740355e9551758e1169b7594b71dc19'
CACHE = 'src/main/scala/core/ooo/cache/NonBlockingCoherentLineCache.scala'
VM_CASES = ('vm_store_stream', 'vm_dependency')
LOAD_CASES = ('hot_loads', 'delayed_cold_loads')
VM_PREFIXES = {
    'cases': 'A1_VM_CPU_METRIC ', 'stages': 'A1_VM_STAGE_METRIC ',
    'forwarding': 'M3_CPU_FORWARD_METRIC ', 'flow': 'NEW_REGISTERED_FLOW_METRIC ',
    'prepared_store': 'PREPARED_STORE_METRIC ',
}
FLOW_HISTOGRAMS = ('prechecked_latency', 'raw_store_latency', 'raw_load_latency', 'cold_store_latency')
FLOW_FIELDS = {'name', 'registered', 'requests', 'replies', 'prechecked_passes',
               'certified_spills', 'raw_passes', 'prechecked_samples', *FLOW_HISTOGRAMS}
OWNER_FIELDS = {'guest', 'index', 'tag', 'pc', 'va', 'pa', 'write', 'prechecked',
                'upstream', 'checked', 'physical', 'reply'}
LOAD_INVARIANTS = ('name', 'service', 'retired', 'warm_loads', 'measured_loads',
                   'measured_iterations', 'roi_instructions_including_loop',
                   'roi_loop_overhead_retired', 'fixture', 'roi_work_boundary')
SCOPE = {
    'DUT': 'two fresh full-resource CommonA1CpuTile models, one same-tool control and one registered-raw candidate',
    'guests_per_model': 'original vm_store_stream/vm_dependency plus immutable hot_loads/delayed_cold_loads',
    'parameter_delta': 'config: registeredRawCertifiedFlow/registeredDataTranslation false->true; translationHitFlow/combinedCheckedDataFlow true->false; core: same except no translationHitFlow field',
    'service': 'unchanged original per-host service, whole-line 512-bit Grant; not Home/DDR/AXI/CDC timing',
    'build': 'each DUT emitted/generated/built fresh once; only its second host reuses content-key/SHA-verified objects',
    'history': 'pinned cleanup receipt metrics/geometry are context; old FIR/source archive bind structural control provenance only, never old tools/objects/functional PASS reuse',
    'latency': 'control raw2/cold24/certified2; candidate warm raw3 and full certified histogram with only >=2 hard gate; candidate cold observed',
    'negative': 'candidate --inject-prechecked-pa observation mutation must hit marker and independent PA oracle rejection; not an RTL mutant',
    'load_model_label': 'immutable load host prints its historical model label; receipt effective profile and actual binary binding are authoritative',
    'limits': 'no required speedup, new CPU arbitrary backpressure/alias/native/NEMU/SoC/DDR/CDC/STA/PPA/Fmax/board qualification',
}


def read(path):
    return base.read_json(Path(path).read_text())


def inputs():
    result = row.inputs()
    for name in (SELF, WRAPPER, CACHE, 'src/test/scala/platform/ElasticLoadProofCpuGsim.scala',
                 str(HOST.relative_to(common.ROOT)), str(LOAD_HOST.relative_to(common.ROOT))):
        result[name] = sha(common.ROOT / name)
    return dict(sorted(result.items()))


def bounded_block(data, start, end):
    need(data.count(start) == 1, 'source block start must occur once')
    begin = data.index(start)
    need(data[begin:].count(end) == 1, 'source block end must occur once after start')
    finish = data.index(end, begin + len(start))
    need(begin < finish, 'source block boundaries reversed')
    return begin, finish, data[begin:finish]


def host_source_gate():
    """Restore exactly the reviewed passive additions, then compare every byte."""
    need(sha(row.HOST) == OLD_HOST_SHA, 'original VM host changed')
    need(sha(LOAD_HOST) == LOAD_HOST_SHA, 'immutable independent-load host changed')
    old, new = row.HOST.read_bytes(), HOST.read_bytes()
    need(old.split(b'class Run {', 1)[0] == new.split(b'class Run {', 1)[0],
         'independent ISA/program/PMP/PTE/service prefix changed')
    for start, end in ((b'    void drive(', b'    bool tick('),
                       (b'    bool tick(', b'\npublic:')):
        need(bounded_block(old, start, end)[2] == bounded_block(new, start, end)[2],
             'original drive/tick/service/retirement flow changed')
    old_start, old_end, old_finish = bounded_block(old, b'    void flowFinish()', b'    struct PreparedRow {')
    new_start, new_end, new_finish = bounded_block(new, b'    static void flowHistogram(', b'    struct PreparedRow {')
    restored = new[:new_start] + old_finish + new[new_end:]
    additions = (
        b'    uint64_t registeredCertifiedSpills = 0;\n',
        b'        registeredCertifiedSpills += dut.get_io$$translated$$valid() &&\n'
        b'            dut.get_io$$translated$$bits$$precheckedLoad();\n',
    )
    for addition in additions:
        need(restored.count(addition) == 1 and addition not in old,
             'passive spill coverage addition changed or duplicated')
        restored = restored.replace(addition, b'')
    need(restored == old, 'VM host changed outside exact flow report/finish and passive spill counter additions')
    need(old_start < old_end and new_finish.count(b'    void flowFinish()') == 1,
         'new histogram helper/flow finish block malformed')
    return {'original_vm_host_sha256': OLD_HOST_SHA, 'new_vm_host_sha256': sha(HOST),
            'immutable_load_host_sha256': LOAD_HOST_SHA, 'restored_original_bytes_exact': True,
            'program_service_drive_tick_oracles_exact': True,
            'new_flow_finish_block_sha256': hashlib.sha256(new_finish).hexdigest(),
            'allowed_delta': 'one contiguous flowHistogram/flowFinish replacement and two exact passive spill counter insertions',
            'standalone_program_or_oracle_runs': 0}


def historical_reference(report):
    need(sha(HISTORY) == HISTORY_SHA, 'historical cleanup reference receipt changed')
    old = read(HISTORY)
    need(old['status'].startswith('PASS_') and
         [case['work_cycles'] for case in old['cases']] == [681, 1018] and
         [case['work_cycles'] for case in old['load_cases']] == [1253, 906] and
         [case['roi_work_cycles'] for case in old['load_cases']] == [531, 360],
         'wrong historical cleanup reference')
    old_fir = HISTORY.parent / CONTROL / (TOP + '.fir')
    old_fir_sha = old['artifacts_sha256'][str(old_fir.relative_to(HISTORY.parent))]
    need(sha(old_fir) == old_fir_sha and sha(HISTORY_ARCHIVE) == HISTORY_ARCHIVE_SHA and
         sha(HISTORY_MANIFEST) == HISTORY_MANIFEST_SHA, 'historical structural FIR/source archive binding changed')
    manifest = read(HISTORY_MANIFEST)['complete_inputs']
    with tarfile.open(HISTORY_ARCHIVE, 'r:gz') as archive:
        members = [entry for entry in archive.getmembers() if entry.isfile()]
        need(len(members) == len(manifest) and {entry.name for entry in members} == set(manifest),
             'historical frozen source archive member set differs')
        for entry in members:
            need(hashlib.sha256(archive.extractfile(entry).read()).hexdigest() == manifest[entry.name],
                 'historical frozen source member differs: ' + entry.name)
    report['historical_reference'] = {
        'receipt': str(HISTORY), 'sha256': HISTORY_SHA,
        'artifacts': {str(HISTORY): HISTORY_SHA, str(old_fir): old_fir_sha,
                      str(HISTORY_ARCHIVE): HISTORY_ARCHIVE_SHA, str(HISTORY_MANIFEST): HISTORY_MANIFEST_SHA},
        'scope': 'historical metrics/geometry plus strict old-FIR control provenance only, not current functional evidence',
        'historical_source_archive': str(HISTORY_ARCHIVE), 'verified_archive_members': len(manifest),
        'old_fir': str(old_fir), 'old_fir_sha256': old_fir_sha,
        'old_functional_artifact_reuse': False, 'old_tool_identity_required': False,
        'old_DUT_build_or_run': False, 'old_object_reuse': False,
        'VM_work_cycles': [681, 1018], 'load_work_cycles': [1253, 906], 'load_roi_cycles': [531, 360],
    }
    return old


def control_fir_gate(model, out, report):
    old_fir = Path(report['historical_reference']['old_fir'])
    new_fir = model / (TOP + '.fir')
    a, b = row.normalize_fir(old_fir.read_bytes()), row.normalize_fir(new_fir.read_bytes())
    diff = out / 'control-source-normalized.diff'
    diff.write_text('' if a == b else ''.join(difflib.unified_diff(
        a.decode().splitlines(True), b.decode().splitlines(True), fromfile=str(old_fir), tofile=str(new_fir))))
    report['historical_control_fir_gate'] = {
        'old_fir_sha256': sha(old_fir), 'new_fir_sha256': sha(new_fir),
        'old_source_normalized_sha256': hashlib.sha256(a).hexdigest(),
        'new_source_normalized_sha256': hashlib.sha256(b).hexdigest(),
        'raw_exact': old_fir.read_bytes() == new_fir.read_bytes(), 'source_only_exact': a == b,
        'normalization': 'source annotations outside strings only; no diagnostic or name mappings',
        'diff': str(diff), 'diff_sha256': sha(diff),
        'scope': 'original cleanup hardware control structural provenance, not historical functional or same-tool performance reuse'}
    base.save_receipt(out, report)
    need(a == b, 'FRESH_BASELINE_REQUIRED: control FIR differs beyond source annotations; see ' + str(diff))


def parameter_gate(control, candidate, historical):
    result = {}
    for kind in ('config', 'core'):
        a, b, old = control[kind], candidate[kind], historical[kind]
        need(set(a) == set(b), 'control/candidate effective field set differs: ' + kind)
        expected = {'registeredRawCertifiedFlow': ['false', 'true'],
                    'registeredDataTranslation': ['false', 'true'],
                    'combinedCheckedDataFlow': ['true', 'false']}
        if kind == 'config':
            expected['translationHitFlow'] = ['true', 'false']
        else:
            need('translationHitFlow' not in a and 'translationHitFlow' not in b,
                 'translationHitFlow is not a core parameter')
        delta = row.differences(a, b)
        need(delta == expected, 'unexpected exact effective parameter delta: ' + kind + ' ' + repr(delta))
        need(set(a) == set(old) | {'registeredRawCertifiedFlow'} and
             a['registeredRawCertifiedFlow'] == 'false' and
             all(a[key] == value for key, value in old.items()),
             'fresh control changed full historical parameter/resource geometry: ' + kind)
        result[kind] = delta
    return {'exact_control_candidate_delta': result, 'historical_resource_geometry_preserved': True,
            'all_other_effective_fields_exact': True}


def cache_gate(control, candidate):
    def module(path):
        matches = re.findall(rb'^  module NonBlockingCoherentLineCache :[^\n]*\n.*?(?=^  (?:module|extmodule|intmodule) |\Z)',
                             row.normalize_fir(path.read_bytes()), re.M | re.S)
        need(len(matches) == 1, 'exactly one actual NonBlockingCoherentLineCache required')
        return matches[0]
    a, b = module(control / (TOP + '.fir')), module(candidate / (TOP + '.fir'))
    need(a == b, 'fresh control/candidate cache private observer module differs beyond source annotations')
    return {'source': CACHE, 'source_sha256': sha(common.ROOT / CACHE),
            'control_module_sha256': hashlib.sha256(a).hexdigest(),
            'candidate_module_sha256': hashlib.sha256(b).hexdigest(),
            'exact_after_source_annotations': True,
            'normalization': 'only source annotations outside strings; diagnostics/logic are not normalized'}


def parse(log, prefix, names, marker):
    text = log.read_text()
    base.check_log(text)
    need(text.splitlines().count(marker) == 1 and '_NEGATIVE_REACHED' not in text,
         'positive log missing unique PASS or contains negative marker: ' + str(log))
    records = [base.read_json(line[len(prefix):]) for line in text.splitlines() if line.startswith(prefix)]
    need(all(isinstance(record, dict) for record in records) and
         [record.get('name') for record in records] == list(names),
         'missing/duplicate/unexpected exact guest records: ' + prefix)
    return records


def histogram(value):
    need(isinstance(value, dict) and value, 'nonempty latency histogram required')
    need(all(isinstance(k, str) and re.fullmatch(r'[1-9][0-9]*', k) and
             type(v) is int and v > 0 for k, v in value.items()), 'invalid latency histogram bin/count')
    return {int(k): v for k, v in value.items()}


def read_owners(log):
    owners = {name: [] for name in VM_CASES}
    seen = {name: set() for name in VM_CASES}
    for line in log.read_text().splitlines():
        if not line.startswith('CHECKED_FLOW_OWNER '):
            continue
        record = base.unique_object([piece.split('=', 1) for piece in line.split()[1:]])
        need(set(record) == OWNER_FIELDS and record['guest'] in owners, 'invalid full-token owner schema')
        name = record.pop('guest')
        need(all(re.fullmatch(r'[0-9]+', value) for value in record.values()), 'invalid owner unsigned integer')
        record = {key: int(value) for key, value in record.items()}
        need(record['write'] in (0, 1) and record['prechecked'] in (0, 1) and
             not (record['write'] and record['prechecked']), 'invalid owner load/store class')
        token = (record['index'], record['tag'])
        need(token not in seen[name], 'duplicate actual full-token DTA owner')
        seen[name].add(token)
        need(record['upstream'] < record['checked'] < record['physical'] < record['reply'],
             'owner ingress/register/reply stages not strictly ordered')
        if owners[name]:
            need(all(owners[name][-1][key] < record[key] for key in ('upstream', 'checked', 'physical', 'reply')),
                 'actual single-lane FIFO owner stage order changed')
        owners[name].append(record)
    summaries = {}
    for name, records in owners.items():
        need(records, 'missing owner trace: ' + name)
        groups = {key: [] for key in FLOW_HISTOGRAMS}
        first_store = True
        for owner in records:
            if owner['prechecked']:
                key = 'prechecked_latency'
            elif not owner['write']:
                key = 'raw_load_latency'
            elif first_store:
                key, first_store = 'cold_store_latency', False
            else:
                key = 'raw_store_latency'
            groups[key].append(owner)
        summaries[name] = {
            key: {stage: dict(Counter(owner[right] - owner[left] for owner in entries))
                  for stage, left, right in (('upstream_checked', 'upstream', 'checked'),
                                             ('checked_physical', 'checked', 'physical'),
                                             ('physical_reply', 'physical', 'reply'),
                                             ('upstream_physical', 'upstream', 'physical'))}
            for key, entries in groups.items()
        }
    return owners, summaries


def vm_metrics(model, registered):
    log = model / 'test.log'
    result = {field: parse(log, prefix, VM_CASES, row.PASS) for field, prefix in VM_PREFIXES.items()}
    need('CHECKED_FLOW_METRIC ' not in log.read_text(), 'obsolete scalar-only flow histogram report emitted')
    result['latency_owners'], result['owner_stage_histograms'] = read_owners(log)
    for n, name in enumerate(VM_CASES):
        case, stages, traffic, flow = (result[key][n] for key in ('cases', 'stages', 'forwarding', 'flow'))
        need(case['retired'] == 233 and case['bootstrap_retired'] == 32 and case['roi_retired'] == 201 and
             case['placement'] == 'rom' and case['work_cycles'] == case['bootstrap_cycles'] + case['roi_cycles'],
             'original VM guest/retirement/cycle accounting changed')
        need(all(traffic[key] == 49 for key in ('architectural_stores', 'physical_stores', 'store_replies', 'store_completions')) and
             traffic['forwarded_loads'] == traffic['forwarded_retired'] == 48 and traffic['alias_forwards'] == 0 and
             traffic['architectural_loads'] == (57 if n == 0 else 105) and
             traffic['upstream_loads'] == traffic['physical_loads'] == traffic['load_replies'] == traffic['architectural_loads'] - 48,
             'hard 49-store/48-forward/original actual-memory conservation failed')
        row.check_prepared(result['prepared_store'][n], traffic)
        need(stages['registered_translation'] == int(registered) and stages['accepted_prefix_validation'] is False and
             stages['circular_payload'] == 1, 'unexpected active VM profile observation')
        need(set(flow) == FLOW_FIELDS and all(type(value) is int and value >= 0 for key, value in flow.items()
                                             if key != 'name' and key not in FLOW_HISTOGRAMS),
             'new registered flow metric schema/counters changed')
        hist = {key: histogram(flow[key]) for key in FLOW_HISTOGRAMS}
        owners = result['latency_owners'][name]
        need(flow['registered'] == int(registered) and
             flow['requests'] == flow['replies'] == len(owners) == 49 + traffic['physical_loads'] and
             flow['prechecked_samples'] == stages['prechecked_loads'] > 0 and
             flow['prechecked_passes'] + flow['certified_spills'] == flow['prechecked_samples'],
             'flow samples/pass/spill/full-owner conservation failed')
        need(all(hist[key] == result['owner_stage_histograms'][name][key]['upstream_physical']
                 for key in FLOW_HISTOGRAMS), 'full flow histogram differs from actual owner timestamps')
        need(hist['raw_store_latency'] == {3 if registered else 2: 48} and
             hist['raw_load_latency'] == {3 if registered else 2: 2} and
             sum(hist['cold_store_latency'].values()) == 1 and
             sum(hist['prechecked_latency'].values()) == flow['prechecked_samples'],
             'warm raw stage latency/sample contract failed')
        if registered:
            need(min(hist['prechecked_latency']) >= 2 and flow['raw_passes'] == 0,
                 'candidate certified latency/raw bypass contract failed')
        else:
            need(hist['cold_store_latency'] == {24: 1} and
                 hist['prechecked_latency'] == {2: flow['prechecked_samples']} and
                 flow['certified_spills'] == 0 and flow['raw_passes'] == 50,
                 'fresh control cold24/raw2/certified2 contract failed')
    return result


def verify_first_build(model, cxx):
    """Verify the actual first compile receipt, not merely its PASS spelling."""
    path = model / 'run-compile-receipt.json'
    build = read(path)
    generated = {str(p) for p in model.glob(TOP + '[0-9]*.cpp')}
    expected = generated | {str(HOST)}
    flags = ['-std=c++20', '-O1', '-g', '-fsanitize=address,undefined',
             '-fno-sanitize-recover=all', '-I' + str(model)]
    headers = {str(p): sha(p) for p in sorted(model.glob('*.h'))}
    need(str(model / (TOP + '.h')) in headers and headers,
         'actual generated model header missing')
    need(build.get('schema') == 'real-gsim-header-gate-v1' and build.get('syntax_pass') is True and
         build.get('host') == str(HOST) and build.get('host_sha256') == sha(HOST) and
         build.get('compiler') == str(Path(cxx).resolve()) and build.get('flags') == flags and
         build.get('headers') == headers, 'first compile receipt/header/host/compiler/flags binding invalid')
    entries = build.get('objects', [])
    need(generated and len(entries) == len(expected) and {entry['source'] for entry in entries} == expected,
         'first compile DUT/host source-object set incomplete or duplicate')
    bound = {str(path): sha(path), **headers, str(HOST): sha(HOST)}
    dut_objects = []
    for entry in entries:
        source, obj = Path(entry['source']), Path(entry['object'])
        key = hashlib.sha256(json.dumps({'source': sha(source), 'headers': headers,
              'flags': flags, 'compiler': sha(cxx)}, sort_keys=True).encode()).hexdigest()
        need(entry.get('reused') is False and entry['source_sha256'] == sha(source) and
             entry['key'] == key and obj == model / (source.stem + '-' + key[:16] + '.o') and
             entry['object_sha256'] == sha(obj), 'first fresh object full content key/SHA/identity mismatch')
        bound[str(source)], bound[str(obj)] = entry['source_sha256'], entry['object_sha256']
        bound[str(model / (obj.name + '.log'))] = sha(model / (obj.name + '.log'))
        if str(source) in generated:
            dut_objects.append(str(obj))
    need(len(dut_objects) == len(generated) and build['binary_sha256'] == sha(model / 'run'),
         'first binary or generated DUT object set binding failed')
    for name in ('run', 'run-header-syntax.log', 'compile.log', 'generate.log', 'elaborate.log',
                 TOP + '.fir', 'effective-config.json', 'effective-parameters.json', 'scope.txt'):
        bound[str(model / name)] = sha(model / name)
    need(row.unchanged_artifacts({'artifacts': bound}), 'first build artifacts changed while verifying')
    return {'receipt': str(path), 'sha256': sha(path), 'artifacts': bound,
            'all_objects_fresh': True, 'all_DUT_keys_and_SHAs_verified': True,
            'generated_dut_objects': len(dut_objects), 'host_objects': 1,
            'DUT_objects': dut_objects, 'ordered_flags': flags}


def second_host(model, cxx, first):
    fresh = verify_first_build(model, cxx)
    need(fresh == first, 'first model build binding changed before second host')
    target = model / 'load-host'
    target.mkdir()
    flags, objects = fresh['ordered_flags'], fresh['DUT_objects']
    common.run([cxx, *flags, '-fsyntax-only', LOAD_HOST], log=target / 'header-syntax.log', timeout=180)
    obj, binary = target / 'elastic_load_supply.o', target / 'run'
    common.run([cxx, *flags, '-c', LOAD_HOST, '-o', obj], log=target / 'host-compile.log', timeout=600)
    common.run([cxx, *flags, *objects, obj, '-ldl', '-o', binary], log=target / 'host-link.log', timeout=600)
    need(row.unchanged_artifacts(first), 'same-DUT artifacts changed while linking second host')
    record = {'schema': 'registered-raw-same-fresh-dut-second-host-v1', 'status': 'BUILT_NOT_RUN',
              'effective_profile': model.name, 'first_build_receipt': first['receipt'],
              'first_build_receipt_sha256': first['sha256'], 'artifacts': first['artifacts'],
              'all_DUT_keys_and_SHAs_verified': True, 'new_DUT_compilations': 0,
              'new_host_compilations': 1, 'host': str(LOAD_HOST), 'host_sha256': sha(LOAD_HOST),
              'host_object_sha256': sha(obj), 'binary_sha256': sha(binary),
              'compiler': str(Path(cxx).resolve()), 'compiler_sha256': sha(cxx), 'ordered_flags': flags,
              'model_label_override': 'printed historical host label is not identity; effective_profile and binary/object bindings are authoritative'}
    path = target / 'link-receipt.json'
    path.write_text(json.dumps(record, indent=2) + '\n')
    common.run([binary, '--trace'], env=base.runtime_env(), log=target / 'test.log', timeout=180)
    cases = parse(target / 'test.log', 'LOAD_SUPPLY_METRIC ', LOAD_CASES, 'LOAD_SUPPLY_PASS')
    proofs = parse(target / 'test.log', 'ELASTIC_PROOF_METRIC ', LOAD_CASES, 'LOAD_SUPPLY_PASS')
    need(row.unchanged_artifacts(first) and sha(LOAD_HOST) == LOAD_HOST_SHA and
         record['binary_sha256'] == sha(binary) and record['host_object_sha256'] == sha(obj),
         'second host or same-DUT artifacts changed after execution')
    record.update(status='PASS_NEW_LOAD_HOST', artifacts_unchanged=True, log_sha256=sha(target / 'test.log'))
    record['second_host_artifacts'] = {str(p): sha(p) for p in sorted(target.iterdir()) if p.is_file() and p != path}
    path.write_text(json.dumps(record, indent=2) + '\n')
    binding = {'receipt': str(path), 'sha256': sha(path),
               'artifacts': {str(path): sha(path), **record['second_host_artifacts']},
               'effective_profile': model.name, 'same_fresh_DUT_objects_only': True}
    return binding, cases, proofs


def negative(model):
    flag, marker = '--inject-prechecked-pa', 'CHECKED_FLOW_NEGATIVE_REACHED'
    diagnostic = 'independent checked-flow PA/permission owner mismatch'
    log = model / 'inject-prechecked-pa.log'
    with log.open('x') as stream:
        result = subprocess.run([str(model / 'run'), flag], stdout=stream, stderr=subprocess.STDOUT,
                                timeout=180, env=base.runtime_env())
    text = log.read_text()
    base.check_log(text)
    need(result.returncode == 1 and text.splitlines().count(marker) == 1 and
         text.splitlines().count('A1_VM_CPU_RETIREMENT_FAIL ' + diagnostic) == 1 and row.PASS not in text,
         'candidate observation negative lacks exact reached marker and independent prechecked PA rejection')
    return {'flag': flag, 'marker': marker, 'diagnostic': diagnostic, 'returncode': result.returncode,
            'scope': 'sampled checked-PA observation mutation, not RTL mutation',
            'binary_sha256': sha(model / 'run'), 'log': str(log), 'log_sha256': sha(log)}


def comparisons(control, candidate, historical):
    result = {'VM': [], 'loads': [], 'historical_control_deltas_not_equivalence': []}
    for n, name in enumerate(VM_CASES):
        a, b = control['cases'][n], candidate['cases'][n]
        need(control['forwarding'][n] == candidate['forwarding'][n],
             'same-tool VM architectural/forwarding/actual traffic differs')
        for field in VM_PREFIXES:
            need(set(control[field][n]) == set(candidate[field][n]), 'paired VM metric schema mismatch: ' + field)
        before, after = control['latency_owners'][name], candidate['latency_owners'][name]
        need(len(before) == len(after) and all(all(x[key] == y[key] for key in ('pc', 'va', 'pa', 'write'))
                                              for x, y in zip(before, after)),
             'same-tool ordered actual owner independent architectural payload changed')
        result['VM'].append({'name': name, 'control_work': a['work_cycles'], 'candidate_work': b['work_cycles'],
            'delta_work': b['work_cycles'] - a['work_cycles'], 'control_roi': a['roi_cycles'],
            'candidate_roi': b['roi_cycles'], 'delta_roi': b['roi_cycles'] - a['roi_cycles'],
            'all_metric_differences': {field: row.differences(control[field][n], candidate[field][n]) for field in VM_PREFIXES},
            'all_owner_differences': [{'ordinal': i, 'differences': row.differences(x, y)}
                                      for i, (x, y) in enumerate(zip(before, after)) if x != y]})
        result['historical_control_deltas_not_equivalence'].append({
            'name': name, 'historical_work': historical['cases'][n]['work_cycles'],
            'fresh_control_work': a['work_cycles'], 'delta_work': a['work_cycles'] - historical['cases'][n]['work_cycles']})
    for n, name in enumerate(LOAD_CASES):
        a, b, old = control['load_cases'][n], candidate['load_cases'][n], historical['load_cases'][n]
        need(set(a) == set(b) == set(old), 'immutable load metric schema changed')
        need(all(a[key] == b[key] == old[key] for key in LOAD_INVARIANTS),
             'original independent-load ISA/service/ROI contract changed')
        need(a['model'] == b['model'] == 'new_full_r1_m3_checked_flow_store_row_elastic_proof',
             'immutable historical host model label unexpectedly changed')
        result['loads'].append({'name': name, 'control_work': a['work_cycles'], 'candidate_work': b['work_cycles'],
            'delta_work': b['work_cycles'] - a['work_cycles'], 'control_roi': a['roi_work_cycles'],
            'candidate_roi': b['roi_work_cycles'], 'delta_roi': b['roi_work_cycles'] - a['roi_work_cycles'],
            'all_metric_differences': row.differences(a, b),
            'all_proof_metric_differences': row.differences(control['proof_metrics'][n], candidate['proof_metrics'][n])})
        result['historical_control_deltas_not_equivalence'].append({
            'name': name, 'historical_work': old['work_cycles'], 'fresh_control_work': a['work_cycles'],
            'delta_work': a['work_cycles'] - old['work_cycles'], 'historical_roi': old['roi_work_cycles'],
            'fresh_control_roi': a['roi_work_cycles'], 'delta_roi': a['roi_work_cycles'] - old['roi_work_cycles']})
    return result


def emit_model(model, profile):
    model.mkdir()
    common.run(['mill', '-i', 'IonSoC.test.runMain', MAIN, model, profile], log=model / 'elaborate.log')


def build_model(model, gsim, cxx):
    need(not (model / 'run').exists() and not list(model.glob('*.o')) and not list(model.glob('*.cpp')),
         'fresh model directory already contains compiled/generated artifacts')
    common.run([gsim, '--threads=1', '--dir=' + str(model), model / (TOP + '.fir')], log=model / 'generate.log')
    sources = sorted(model.glob(TOP + '[0-9]*.cpp'))
    need(sources, 'GSIM emitted no model translation unit')
    common.run([cxx, '-std=c++20', '-O1', '-g', '-fsanitize=address,undefined',
                '-fno-sanitize-recover=all', '-I' + str(model), *sources, HOST,
                '-ldl', '-o', model / 'run'], log=model / 'compile.log', timeout=600)
    return verify_first_build(model, cxx)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--gsim', type=Path, required=True)
    parser.add_argument('--compile-receipt', type=Path)
    parser.add_argument('--build-run', action='store_true')
    args = parser.parse_args()
    need(re.fullmatch(r'[A-Za-z0-9_-]+', args.tag), 'safe fresh tag required')
    before = inputs()
    source_gate = host_source_gate()
    if not args.build_run:
        print(json.dumps({'status': 'PREFLIGHT_ONLY', 'inputs': len(before), 'scope': SCOPE,
                          'host_source_gate': source_gate, 'profiles': PROFILES}, indent=2))
        return
    need(args.compile_receipt is not None, 'successful current full Scala compile receipt required')
    out = common.BUILD / args.tag
    out.mkdir(parents=True, exist_ok=False)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    tools = base.tool_binding(True)
    cxx = tools['compiler']['command']
    need(args.gsim.resolve() == Path(tools['gsim']['path']).resolve(), 'prepared pinned GSIM required')
    report = {'schema': 'registered-raw-certified-actual-cpu-v1', 'status': 'RUNNING', 'scope': SCOPE,
              'source_revision': base.git(common.ROOT, 'rev-parse', 'HEAD').strip(),
              'inputs_before': before, 'tools_before': tools, 'program_service_source_gate': source_gate,
              'models': {}, 'new_DUT_builds': 0, 'hardware_guest_runs': 0, 'negative_runs': 0}
    base.save_receipt(out, report)
    try:
        row.bind_compile_receipt(args.compile_receipt, report)
        need(report['scala_compile_receipt']['schema'] == 'valence-scala-compile-v1',
             'public valence-scala-compile-v1 schema required')
        historical = historical_reference(report)
        report['emission_classpath_checks'] = []
        for profile in PROFILES:
            need(inputs() == before, 'source drift before model emission')
            compiled = row.scala.verify_receipt(args.compile_receipt, common.ROOT)
            report['emission_classpath_checks'].append({'profile': profile, 'phase': 'before',
                'compiled_classpath_sha256': base.digest_json(compiled['compiledClasspath'])})
            emit_model(out / profile, profile)
            compiled = row.scala.verify_receipt(args.compile_receipt, common.ROOT)
            report['emission_classpath_checks'].append({'profile': profile, 'phase': 'after',
                'compiled_classpath_sha256': base.digest_json(compiled['compiledClasspath'])})
            report['models'][profile] = {'effective_parameters': row.effective(out / profile)}
            if profile == CONTROL:
                control_fir_gate(out / profile, out, report)
            base.save_receipt(out, report)
        report['parameter_gate'] = parameter_gate(report['models'][CONTROL]['effective_parameters'],
            report['models'][CANDIDATE]['effective_parameters'], historical['effective_parameters'])
        report['cache_observation_gate'] = cache_gate(out / CONTROL, out / CANDIDATE)
        base.save_receipt(out, report)
        gate.install()
        for profile in PROFILES:
            need(inputs() == before and base.tool_binding(True) == tools, 'source/tool drift before fresh DUT build')
            model, record = out / profile, report['models'][profile]
            record['first_build'] = build_model(model, args.gsim, cxx)
            report['new_DUT_builds'] += 1
            base.save_receipt(out, report)
            common.run([model / 'run'], env=base.runtime_env(), log=model / 'test.log', timeout=180)
            record.update(vm_metrics(model, profile == CANDIDATE))
            record['VM_log_sha256'] = sha(model / 'test.log')
            record['execution_artifacts'] = {'artifacts': {str(model / 'test.log'): record['VM_log_sha256']}}
            report['hardware_guest_runs'] += 2
            base.save_receipt(out, report)
            record['second_host'], record['load_cases'], record['proof_metrics'] = second_host(model, cxx, record['first_build'])
            report['hardware_guest_runs'] += 2
            if profile == CANDIDATE:
                record['negative_controls'] = [negative(model)]
                for rejection in record['negative_controls']:
                    record['execution_artifacts']['artifacts'][rejection['log']] = rejection['log_sha256']
                report['negative_runs'] += 1
            need(all(row.unchanged_artifacts(record[key]) for key in ('first_build', 'second_host', 'execution_artifacts')),
                 'fresh model/host artifacts drifted after guests/negative')
            base.save_receipt(out, report)
        report['comparison'] = comparisons(report['models'][CONTROL], report['models'][CANDIDATE], historical)
        need(report['new_DUT_builds'] == 2 and report['hardware_guest_runs'] == 8 and report['negative_runs'] == 1,
             'exact two-model/eight-guest/one-observation-negative scope not satisfied')
        report['status'] = 'PASS_BOUNDED_REGISTERED_RAW_CERTIFIED_ACTUAL_CPU'
    except BaseException as error:
        report.update(status='FAIL', failure=f'{type(error).__name__}: {error}')
        raise
    finally:
        report['inputs_after'] = inputs()
        report['inputs_unchanged'] = before == report['inputs_after']
        report['source_input_drift'] = row.differences(before, report['inputs_after'])
        report['tools_after'] = base.tool_binding(True)
        report['tools_unchanged'] = tools == report['tools_after']
        report['historical_reference_unchanged'] = row.unchanged_artifacts(report.get('historical_reference', {}))
        report['scala_compile_receipt_unchanged'] = row.unchanged_artifacts(report.get('scala_compile_receipt', {}))
        report['model_build_artifacts_unchanged'] = all(
            row.unchanged_artifacts(record.get(binding, {})) for record in report['models'].values()
            for binding in ('first_build', 'second_host', 'execution_artifacts'))
        if not all(report[key] for key in ('inputs_unchanged', 'tools_unchanged', 'historical_reference_unchanged',
                                           'scala_compile_receipt_unchanged', 'model_build_artifacts_unchanged')):
            report['status'] = 'FAIL_INPUT_OR_ARTIFACT_DRIFT'
        report['artifacts_sha256'] = {str(path.relative_to(out)): sha(path) for path in sorted(out.rglob('*'))
                                     if path.is_file() and path not in (out / 'receipt.json', out / 'receipt.json.tmp')}
        base.save_receipt(out, report)
    need(report['status'].startswith('PASS_'), report['status'])
    print(json.dumps({'status': report['status'], 'receipt': str(out / 'receipt.json'),
                      'comparison': report['comparison']}, indent=2))


if __name__ == '__main__':
    main()
