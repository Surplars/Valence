#!/usr/bin/env python3
"""Bounded GSIM proof for default-off virtual RAM load certificates and overlap.

Independent external page-table, architectural, fault, ownership and permission
oracles. No synthesis, full regression, board run or PPA claim.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import run as common


def source_hashes():
    files = sorted((common.ROOT / 'src').rglob('*.scala'))
    files += [Path(__file__), *(common.HERE / 'harness').glob('virtual_load*'),
              common.HERE / 'harness/virtual_ram_preparation.cpp',
              common.HERE / 'harness/virtual_prechecked_store_buffer.cpp']
    return {str(path.relative_to(common.ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(set(files))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--reuse', action='append', default=[], help='Prior run directory; reuse generated model only if every Scala source hash matches')
    parser.add_argument('--models', default='preparation,store-buffer,adapter,adapter-identity,backend')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.tag):
        parser.error('tag must contain only letters, numbers, underscores and hyphens')
    models = args.models.split(',')
    if not set(models).issubset({'preparation', 'store-buffer', 'adapter', 'adapter-identity', 'backend'}):
        parser.error('models must be preparation,store-buffer,adapter,adapter-identity,backend')
    output = common.BUILD / ('virtual-load-precheck-' + args.tag)
    output.mkdir(parents=True, exist_ok=False)
    receipt = {'status': 'RUNNING', 'source_sha256': source_hashes(), 'models': {},
               'scope': 'actual GSIM RTL; isolated preparation, real DTLB+adapter, and decoded-instruction backend composition; no full CPU/board/PPA claim'}
    (output / 'freeze.json').write_text(json.dumps(receipt, indent=2) + '\n')
    try:
        gsim, cxx = common.setup(False)
        common.run(['mill', '-i', 'IonSoC.test.testOnly', 'ooo.VirtualLoadPrecheckSpec'], log=output / 'configuration.log')
        receipt['configuration'] = 'PASS'
        for model in models:
            top, harness, anchor, mutation, fail = {
                'preparation': ('VirtualRamPreparationGsim', 'virtual_ram_preparation.cpp',
                                'VIRTUAL_RAM_PREPARATION_PASS', '--inject-allowed', 'independent certificate payload/permission mismatch'),
                'store-buffer': ('StoreBufferGsim', 'virtual_prechecked_store_buffer.cpp',
                                 'VIRTUAL_PRECHECKED_STORE_BUFFER_PASS', '--inject-local', 'prechecked read bypassed physical reauthorization through local forwarding'),
                'adapter': ('VirtualLoadPrecheckGsim', 'virtual_load_precheck.cpp',
                            'VIRTUAL_LOAD_PRECHECK_PASS', '--inject-address', 'independent physical translation/attribute mismatch'),
                'adapter-identity': ('VirtualLoadPrecheckGsim', 'virtual_load_precheck.cpp',
                                     'VIRTUAL_LOAD_PRECHECK_PASS', '--inject-address', 'independent physical translation/attribute mismatch'),
                'backend': ('VirtualLoadConcurrencyGsim', 'virtual_load_concurrency.cpp',
                            'VIRTUAL_LOAD_CONCURRENCY_PASS', '--inject-result', 'independent architectural result mismatch'),
            }[model]
            results = {}
            for flag in ([1] if model in ('preparation', 'store-buffer', 'adapter-identity') else [0, 1]):
                target = output / f'{model}-{flag}'
                target.mkdir()
                parameters = () if model == 'preparation' else (
                    ('2', 'registered-local-response', 'registered-owners') if model == 'store-buffer' else
                    ('1', 'identity') if model == 'adapter-identity' else (str(flag),))
                reused = None
                scala_hashes = {name: digest for name, digest in receipt['source_sha256'].items() if name.startswith('src/')}
                elaborated = False
                for prior in args.reuse:
                    prior = Path(prior)
                    prior_freeze = json.loads((prior / 'freeze.json').read_text())
                    prior_scala = {name: digest for name, digest in prior_freeze['source_sha256'].items() if name.startswith('src/')}
                    old = prior / f'{model}-{flag}'
                    if not (old / (top + '.h')).exists():
                        continue
                    if prior_scala != scala_hashes and not elaborated:
                        common.run(['mill', '-i', 'IonSoC.test.runMain', 'ooo.' + top + 'Main', target, *parameters],
                                   log=target / 'elaborate.log')
                        elaborated = True
                    equivalent = prior_scala == scala_hashes or (
                        elaborated and (old / (top + '.fir')).read_bytes() == (target / (top + '.fir')).read_bytes())
                    if equivalent:
                        for path in old.iterdir():
                            if path.suffix in ('.h', '.cpp', '.fir', '.o'):
                                shutil.copy2(path, target / path.name)
                        reused = str(old)
                        break
                if not reused:
                    if not elaborated:
                        common.run(['mill', '-i', 'IonSoC.test.runMain', 'ooo.' + top + 'Main', target, *parameters],
                                   log=target / 'elaborate.log')
                    common.run([gsim, '--threads=1', f'--dir={target}', target / (top + '.fir')],
                               log=target / 'generate.log')
                else:
                    print(f'Reusing verified model sources: {reused}', flush=True)
                flags = ['-std=c++20', '-O1', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=all', f'-I{target}']
                objects = []
                for source in sorted(target.glob(top + '[0-9]*.cpp')):
                    obj = source.with_suffix('.o')
                    if not obj.exists():
                        common.run([cxx, *flags, '-c', source, '-o', obj], log=obj.with_suffix('.compile.log'))
                    objects.append(obj)
                common.run([cxx, *flags, f'-DPRECHECK_ENABLED={flag}', common.HERE / 'harness' / harness,
                            *objects, '-ldl', '-o', target / 'run'], log=target / 'compile.log')
                common.run([target / 'run'], log=target / 'test.log', timeout=120,
                           env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'})
                print((target / 'test.log').read_text(), end='', flush=True)
                log = (target / 'test.log').read_text()
                assert anchor in log, f'{model} PASS anchor missing'
                negative = subprocess.run([target / 'run', mutation], capture_output=True, text=True,
                                          timeout=120, env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'})
                (target / 'negative.log').write_text(negative.stdout + negative.stderr)
                assert negative.returncode == 1 and fail in negative.stdout + negative.stderr, f'{model} mutation not rejected'
                cases = {}
                for line in log.splitlines():
                    if line.startswith('VIRTUAL_LOAD_CASE '):
                        fields = dict(value.split('=', 1) for value in line.split()[1:])
                        name = fields.pop('name')
                        cases[name] = {key: int(value) for key, value in fields.items()}
                results[str(flag)] = {'positive': 'PASS', 'mutation': 'REJECTED', 'cases': cases, 'log': log, 'reused_model': reused,
                                      'chirrtl_sha256': hashlib.sha256((target / (top + '.fir')).read_bytes()).hexdigest(),
                                      'model_object_sha256': {obj.name: hashlib.sha256(obj.read_bytes()).hexdigest() for obj in objects}}
                receipt['models'][model] = results
                (output / 'progress.json').write_text(json.dumps(receipt, indent=2) + '\n')
            if model == 'backend':
                baseline = results['0']['cases']; candidate = results['1']['cases']
                assert baseline.keys() == candidate.keys()
                for case in baseline:
                    for metric in ('trace', 'retired', 'physical', 'traps', 'cancellations'):
                        if case == 'cancel_token_reuse' and metric == 'physical':
                            continue
                        assert baseline[case][metric] == candidate[case][metric], (case, metric, baseline[case], candidate[case])
                assert baseline['warm_overlap']['peak'] == 1 and candidate['warm_overlap']['peak'] == 2
                for name in ('head_serial_single', 'cold_head_serial_single', 'fault_4'):
                    assert baseline[name]['cycles'] == candidate[name]['cycles'], (name, 'serial head timing drift')
                receipt['architectural_ab_equivalence'] = 'PASS'
        assert source_hashes() == receipt['source_sha256'], 'source changed during focused acceptance'
        receipt['status'] = 'PASS'
    except BaseException as error:
        receipt['status'] = 'FAIL'; receipt['error'] = str(error)
        raise
    finally:
        (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')


if __name__ == '__main__':
    main()
