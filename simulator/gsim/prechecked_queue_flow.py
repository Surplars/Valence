#!/usr/bin/env python3
"""Paired actual-RTL GSIM qualification of default-off prechecked request queue flow.

Both sides retain registered ingress, registered checked authorization, real DTLB
and virtual-load certificates. The only parameter delta is queue flow. Timing is
measured from accepted and issued events; no synthetic future-latency arithmetic.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import run as common


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sources():
    paths = list((common.ROOT / 'src/main').rglob('*.scala'))
    paths += list((common.ROOT / 'third_party/berkeley-hardfloat').rglob('*.scala'))
    paths += [common.ROOT / 'build.mill', common.ROOT / '.mill-version', common.ROOT / '.mill-jvm-opts']
    paths += [common.ROOT / 'src/test/scala/ooo/PrecheckedQueueFlowGsim.scala',
              common.ROOT / 'src/test/scala/ooo/PrecheckedQueueFlowSpec.scala',
              common.ROOT / 'src/test/scala/ooo/PhysicalLoadIngressFlowSpec.scala',
              common.HERE / 'harness/prechecked_queue_flow.cpp',
              common.HERE / 'harness/prechecked_queue_flow_backend.cpp',
              common.HERE / 'harness/virtual_load_test_memory.h',
              common.HERE / 'run.py', common.HERE / 'config/toolchain.json', Path(__file__)]
    return {str(path.relative_to(common.ROOT)): digest(path) for path in sorted(set(paths))}


def parse_cases(log, prefix):
    cases = {}
    for line in log.splitlines():
        if line.startswith(prefix + ' '):
            fields = dict(item.split('=', 1) for item in line.split()[1:])
            name = fields.pop('name')
            assert name not in cases, ('duplicate case', name)
            cases[name] = {key: int(value) for key, value in fields.items()}
    assert cases, 'case observations missing'
    return cases


def reuse_model(priors, model, flag, top, target):
    """Only reuse receipt-frozen outputs whose exact FIR and file hashes still match.

    An interrupted model without an output manifest is deliberately rebuilt. A
    previous harness failure does not invalidate a completed model's manifest,
    because the current harness and all positive/negative cases are rerun.
    """
    for prior in priors:
        root = Path(prior)
        old = root / f'{model}-{flag}'
        receipt_path = root / 'receipt.json'
        if not receipt_path.exists() or not (old / (top + '.fir')).exists():
            continue
        recorded = json.loads(receipt_path.read_text()).get('models', {}).get(model, {}).get(str(flag), {})
        if not recorded or digest(target / (top + '.fir')) != recorded.get('chirrtl_sha256'):
            continue
        manifests = {**recorded.get('generated_source_sha256', {}), **recorded.get('model_object_sha256', {})}
        if not manifests or not (old / (top + '.h')).exists():
            continue
        assert digest(old / (top + '.fir')) == recorded['chirrtl_sha256'], ('reuse FIR hash drift', old)
        assert all((old / name).is_file() and digest(old / name) == expected
                   for name, expected in manifests.items()), ('reuse model hash drift', old)
        files = [old / (top + '.h'), *(old / name for name in manifests)]
        copied = {path.name: digest(path) for path in files}
        for path in files:
            shutil.copy2(path, target / path.name)
        assert all(digest(target / name) == expected for name, expected in copied.items())
        return {'source': str(old), 'receipt_sha256': digest(receipt_path),
                'chirrtl_equality': 'byte-exact', 'copied_file_sha256': copied}
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--models', default='adapter,adapter-prefetch,backend')
    parser.add_argument('--baseline-ref', help='Exact git reference for a real-RTL shadow off baseline')
    parser.add_argument('--reuse', action='append', default=[], help='Reuse model objects only after exact FIR equality')
    args = parser.parse_args()
    if not re.fullmatch('[A-Za-z0-9_-]+', args.tag):
        parser.error('tag must use letters, digits, underscores or hyphens')
    models = args.models.split(',')
    if not models or not set(models).issubset({'adapter', 'adapter-prefetch', 'backend'}):
        parser.error('models must be adapter,adapter-prefetch,backend')
    output = common.BUILD / ('prechecked-queue-flow-' + args.tag)
    output.mkdir(parents=True, exist_ok=False)
    receipt = {'status': 'RUNNING', 'git_base': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(), 'source_sha256': sources(), 'models': {},
               'scope': 'actual GSIM off/on adapter and decoded-instruction backend composition; no full CPU, synthesis, routed timing or board claim',
               'policy': 'Both sides enable virtualRamLoadPrecheck; only precheckedDataRequestFlow changes. Malformed alignment/mask hardening is opt-in and is the sole intentional response-policy delta.',
               'mapping_boundary': 'Adapter trusts legal same-epoch PA. Backend independent software page tables and full-token retirement ownership validate the certificate producer; adapter does not repeat TLB translation.'}
    for name in receipt['source_sha256']:
        frozen = output / 'source' / name
        frozen.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(common.ROOT / name, frozen)
    (output / 'freeze.json').write_text(json.dumps(receipt, indent=2) + '\n')
    try:
        gsim, cxx = common.setup(False)
        common.run(['mill', '-i', 'IonSoC.test.testOnly', 'ooo.PrecheckedQueueFlowSpec', 'ooo.PhysicalLoadIngressFlowSpec'], log=output / 'configuration.log')
        receipt['configuration'] = 'PASS'
        for model in models:
            top = 'PrecheckedQueueFlowGsim' if model.startswith('adapter') else 'PrecheckedQueueFlowBackendGsim'
            harness = 'prechecked_queue_flow.cpp' if model.startswith('adapter') else 'prechecked_queue_flow_backend.cpp'
            anchor = 'PRECHECKED_QUEUE_FLOW_PASS' if model.startswith('adapter') else 'PRECHECKED_QUEUE_FLOW_BACKEND_PASS'
            prefix = 'PRECHECKED_QUEUE_FLOW_CASE' if model.startswith('adapter') else 'PRECHECKED_QUEUE_FLOW_BACKEND_CASE'
            mutations = ({'--inject-address': 'independent physical order/address/shape mismatch',
                          '--inject-response': 'independent ordered response/fault mismatch',
                          '--inject-prefetch': 'independent next-line authorization mismatch',
                          '--inject-fault': 'independent ordered response/fault mismatch'} if model.startswith('adapter') else
                         {'--inject-result': 'independent architectural result mismatch',
                          '--inject-token': 'LSU start used cancelled/stale full ROB token',
                          '--inject-certificate-pa': 'canonical physical alias mismatch'})
            results = {}
            receipt['models'][model] = results
            for flag in (0, 1):
                target = output / f'{model}-{flag}'
                target.mkdir()
                common.run(['mill', '-i', 'IonSoC.test.runMain', 'ooo.' + top + 'Main', target, str(flag), *(['prefetch'] if model == 'adapter-prefetch' else [])],
                           log=target / 'elaborate.log')
                reused = reuse_model(args.reuse, model, flag, top, target)
                if not reused:
                    common.run([gsim, '--threads=1', f'--dir={target}', target / (top + '.fir')], log=target / 'generate.log')
                flags = ['-std=c++20', '-O1', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=all', f'-I{target}']
                objects = []
                for source in sorted(target.glob(top + '[0-9]*.cpp')):
                    obj = source.with_suffix('.o')
                    if not obj.exists():
                        common.run([cxx, *flags, '-c', source, '-o', obj], log=obj.with_suffix('.compile.log'))
                    objects.append(obj)
                assert objects, 'generated GSIM translation units missing'
                common.run([cxx, *flags, f'-DQUEUE_FLOW_ENABLED={flag}', '-DPRECHECK_ENABLED=1', f'-DPREFETCH_ENABLED={int(model == "adapter-prefetch")}',
                            common.HERE / 'harness' / harness, *objects, '-ldl', '-o', target / 'run'], log=target / 'compile.log')
                env = {**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'}
                common.run([target / 'run'], log=target / 'test.log', timeout=120, env=env)
                log = (target / 'test.log').read_text()
                print(log, end='', flush=True)
                assert anchor in log, f'{model} PASS anchor missing'
                negatives = {}
                for mutation, failure in mutations.items():
                    negative = subprocess.run([target / 'run', mutation], capture_output=True, text=True, timeout=120, env=env)
                    negative_log = negative.stdout + negative.stderr
                    (target / (mutation[2:] + '.log')).write_text(negative_log)
                    assert negative.returncode == 1 and failure in negative_log, (model, mutation, 'negative control not rejected')
                    negatives[mutation] = 'REJECTED'
                results[str(flag)] = {'positive': 'PASS', 'negative_controls': negatives,
                                      'cases': parse_cases(log, prefix), 'reused_model': reused,
                                      'chirrtl_sha256': digest(target / (top + '.fir')),
                                      'binary_sha256': digest(target / 'run'),
                                      'generated_source_sha256': {p.name: digest(p) for p in sorted(target.glob(top + '*.cpp'))},
                                      'model_object_sha256': {p.name: digest(p) for p in objects}}
                (output / 'progress.json').write_text(json.dumps(receipt, indent=2) + '\n')
            off, on = results['0']['cases'], results['1']['cases']
            assert off.keys() == on.keys(), 'paired case set drift'
            for case in off:
                if model.startswith('adapter') and case == 'shape_hardening':
                    assert off[case]['faults'] == 0 and on[case]['faults'] == 2
                    continue
                keys = ('trace', 'accepted', 'responses', 'physical', 'faults') if model.startswith('adapter') else (
                    'trace', 'retired', 'physical', 'traps', 'cancellations')
                for key in keys:
                    assert off[case][key] == on[case][key], (model, case, key, off[case], on[case])
            if model.startswith('adapter'):
                a, b = off['registered_latency'], on['registered_latency']
                assert a['min_latency'] == b['min_latency'] + 1, 'queue flow did not remove exactly one registered stage'
                assert b['min_latency'] >= 2, 'mandatory registered boundaries collapsed'
                a, b = off['unblocked_throughput'], on['unblocked_throughput']
                assert a['physical_span'] == b['physical_span'] == 47, 'unblocked stream failed II=1'
                receipt['measured_' + model + '_timing'] = {'off_request_latency': off['registered_latency']['min_latency'],
                                                     'on_request_latency': on['registered_latency']['min_latency'],
                                                     'off_48_request_issue_span': a['physical_span'], 'on_48_request_issue_span': b['physical_span'],
                                                     'unit': 'actual GSIM RTL cycles'}
            else:
                for case in ('head_serial_single', 'cold_head_serial_single', 'fault_4'):
                    assert off[case]['cycles'] == on[case]['cycles'], (case, 'serial non-prechecked timing drift')
            receipt[model + '_paired_equivalence'] = 'PASS'
        if args.baseline_ref:
            baseline_revision = subprocess.check_output(['git', 'rev-parse', args.baseline_ref], text=True).strip()
            archive = output / 'baseline-source.tar'
            with archive.open('wb') as stream:
                subprocess.run(['git', 'archive', baseline_revision], stdout=stream, check=True, cwd=common.ROOT)
            baseline_root = output / 'baseline-source'
            baseline_root.mkdir()
            with tarfile.open(archive) as stream:
                stream.extractall(baseline_root, filter='data')
            original_wrapper = common.ROOT / 'src/test/scala/ooo/PrecheckedQueueFlowGsim.scala'
            wrapper = baseline_root / original_wrapper.relative_to(common.ROOT)
            original = original_wrapper.read_text()
            old = original.replace('precheckedDataRequestFlow = enabled,', '')
            assert old != original and 'precheckedDataRequestFlow' not in old
            wrapper.write_text(old)
            receipt['baseline_shadow'] = {'revision': baseline_revision, 'archive_sha256': digest(archive),
                                          'wrapper_delta': 'Remove only the unavailable new parameter assignment, leaving baseline default-off behavior.',
                                          'wrapper_sha256': digest(wrapper), 'models': {}}
            for model in models:
                top = 'PrecheckedQueueFlowGsim' if model.startswith('adapter') else 'PrecheckedQueueFlowBackendGsim'
                harness = 'prechecked_queue_flow.cpp' if model.startswith('adapter') else 'prechecked_queue_flow_backend.cpp'
                prefix = 'PRECHECKED_QUEUE_FLOW_CASE' if model.startswith('adapter') else 'PRECHECKED_QUEUE_FLOW_BACKEND_CASE'
                target = output / ('baseline-' + model)
                target.mkdir()
                common.run(['mill', '-i', 'IonSoC.test.runMain', 'ooo.' + top + 'Main', target, '0', *(['prefetch'] if model == 'adapter-prefetch' else [])],
                           cwd=baseline_root, log=target / 'elaborate.log')
                common.run([gsim, '--threads=1', f'--dir={target}', target / (top + '.fir')], log=target / 'generate.log')
                flags = ['-std=c++20', '-O1', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=all', f'-I{target}']
                objects = []
                for source in sorted(target.glob(top + '[0-9]*.cpp')):
                    obj = source.with_suffix('.o')
                    common.run([cxx, *flags, '-c', source, '-o', obj], log=obj.with_suffix('.compile.log'))
                    objects.append(obj)
                common.run([cxx, *flags, '-DQUEUE_FLOW_ENABLED=0', '-DPRECHECK_ENABLED=1', f'-DPREFETCH_ENABLED={int(model == "adapter-prefetch")}',
                            common.HERE / 'harness' / harness, *objects, '-ldl', '-o', target / 'run'], log=target / 'compile.log')
                common.run([target / 'run'], log=target / 'test.log', timeout=120,
                           env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'})
                baseline_log = (target / 'test.log').read_text()
                cases = parse_cases(baseline_log, prefix)
                assert cases == receipt['models'][model]['0']['cases'], (model, 'exact baseline case/cycle/trace drift')
                receipt['baseline_shadow']['models'][model] = {
                    'case_cycle_trace_equality': 'PASS', 'cases': cases,
                    'chirrtl_sha256': digest(target / (top + '.fir')), 'binary_sha256': digest(target / 'run'),
                    'generated_source_sha256': {p.name: digest(p) for p in sorted(target.glob(top + '*.cpp'))},
                    'model_object_sha256': {p.name: digest(p) for p in objects}}
                (output / 'progress.json').write_text(json.dumps(receipt, indent=2) + '\n')
            receipt['exact_baseline_external_behavior'] = 'PASS for every directed case, including cycle counts, pressure counters and traces; not a formal all-input equivalence proof'
        assert sources() == receipt['source_sha256'], 'qualification source changed during acceptance'
        receipt['status'] = 'PASS'
    except BaseException as error:
        receipt['status'] = 'FAIL'; receipt['error'] = str(error)
        raise
    finally:
        (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')


if __name__ == '__main__':
    main()
