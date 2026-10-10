#!/usr/bin/env python3
"""Exact 2-GiB aperture bank/service/PMP endpoint gate; coordinator slot required."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import shutil
import subprocess
import time
import run as common

TOP = 'MemoryProofFrontierExactRangeGsim'
ANCHOR = 'MEMORY_PROOF_FRONTIER_EXACT_RANGE_PASS'
ORIGINAL_SHA = 'eb5a919aa7462d4cf05cdf21378201796b83a67c3e0287f97341dce3099d2b8f'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sources():
    files = list((common.ROOT / 'src').rglob('*.scala'))
    files += [Path(__file__), common.HERE / 'run.py',
              common.HERE / 'harness/memory_proof_frontier_exact_range.cpp',
              common.HERE / 'harness/memory_proof_frontier_exact_reference.h']
    return {str(p.relative_to(common.ROOT)): sha(p) for p in sorted(set(files))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--gsim', required=True, type=Path)
    parser.add_argument('--firtool', type=Path, default=os.environ.get('FIRTOOL'))
    parser.add_argument('--original-parameters', required=True, type=Path)
    parser.add_argument('--flag', choices=('1',), default='1')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.tag):
        parser.error('tag must be a simple unique output label')
    if not args.firtool:
        parser.error('--firtool or activated FIRTOOL is required; no structural-check fallback')
    original = args.original_parameters.resolve(strict=True)
    if sha(original) != ORIGINAL_SHA:
        raise AssertionError('original actual parameter manifest differs from its immutable pin')
    expected = json.loads(original.read_text())
    gsim, firtool = args.gsim.resolve(strict=True), Path(args.firtool).resolve(strict=True)
    cxx, cxx_version = common.compiler()
    cxx_path = Path(shutil.which(cxx) or cxx).resolve(strict=True)
    output = common.BUILD / ('memory-proof-frontier-exact-range-' + args.tag)
    output.mkdir(parents=True, exist_ok=False)
    pinned = sources()
    receipt = {'status': 'RUNNING', 'source_sha256': pinned, 'commands': [],
               'original_parameters_sha256': sha(original), 'flag': int(args.flag),
               'tools': {str(p): sha(p) for p in (gsim, firtool, cxx_path)}, 'cxx_version': cxx_version,
               'scope': 'Exact bank/service/PMP aperture endpoints only; no backend/cache/external demand witness'}
    (output / 'freeze.json').write_text(json.dumps(receipt, indent=2) + '\n')
    env = {**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'}

    def execute(argv, log, timeout=600, expected_reason=None):
        argv = list(map(str, argv))
        usage_before = resource.getrusage(resource.RUSAGE_CHILDREN)
        record = {'argv': argv, 'cwd': str(common.ROOT), 'log': str(log), 'timeout_seconds': timeout,
                  'resource_semantics': 'Cumulative usage of waited child processes. ru_maxrss_KiB is the cumulative maximum of waited children, not concurrent aggregate RSS or a per-step peak.',
                  'children_usage_before': {'ru_maxrss_KiB': usage_before.ru_maxrss,
                                            'user_seconds': usage_before.ru_utime,
                                            'system_seconds': usage_before.ru_stime}}
        receipt['commands'].append(record)
        start = time.monotonic()
        try:
            with log.open('w') as stream:
                result = subprocess.run(argv, cwd=common.ROOT, stdout=stream, stderr=subprocess.STDOUT,
                                        timeout=timeout, env=env)
            record['returncode'] = result.returncode
            text = log.read_text()
            if expected_reason:
                if result.returncode == 0 or expected_reason not in text:
                    raise AssertionError('negative control missed its intended reason: ' + expected_reason)
            elif result.returncode:
                raise RuntimeError(f'command failed ({result.returncode}); see {log}')
            return text
        except subprocess.TimeoutExpired:
            record['timeout'] = True
            raise
        finally:
            usage_after = resource.getrusage(resource.RUSAGE_CHILDREN)
            record['children_usage_after'] = {'ru_maxrss_KiB': usage_after.ru_maxrss,
                                              'user_seconds': usage_after.ru_utime,
                                              'system_seconds': usage_after.ru_stime}
            record['waited_children_cpu_delta'] = {'user_seconds': usage_after.ru_utime - usage_before.ru_utime,
                                                   'system_seconds': usage_after.ru_stime - usage_before.ru_stime}
            record['elapsed_seconds'] = time.monotonic() - start
            if log.exists():
                record['log_sha256'] = sha(log)
            (output / 'progress.json').write_text(json.dumps(receipt, indent=2) + '\n')

    try:
        execute(['mill', '-i', 'IonSoC.test.runMain', 'ooo.' + TOP + 'Main', output], output / 'elaborate.log')
        actual = json.loads((output / 'exact-parameters.json').read_text())
        core = actual['actualBankParameters']
        extra = {'memoryProofFrontier': bool(int(args.flag)), 'memoryProofRows': 16, 'memoryProofCacheSets': 256}
        if len(expected['expectedCore']) != 136 or len(core) != 139 or core != {**expected['expectedCore'], **extra}:
            raise AssertionError('exact component did not preserve all 136 original core fields plus exactly 3 new fields')
        if actual['canonicalOptions'] != expected['canonicalOptions']:
            raise AssertionError('exact bank canonical option set differs from original model')
        receipt['exact_parameters_sha256'] = sha(output / 'exact-parameters.json')
        receipt['original_fields_equal'] = 136
        receipt['all_current_core_fields_checked'] = 139
        fir = output / (TOP + '.fir')
        receipt['fir_sha256'] = sha(fir)
        # A required structural gate, with binary pin/argv/output/exit kept even on failure.
        execute([firtool, fir, '--verilog', '-o', output / 'structural.sv'], output / 'firtool.log')
        receipt['structural_verilog_sha256'] = sha(output / 'structural.sv')
        execute([gsim, '--threads=1', f'--dir={output}', fir], output / 'generate.log')
        cflags = ['-std=c++20', '-O1', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=all', f'-I{output}']
        receipt['generated_header_sha256'] = sha(output / (TOP + '.h'))
        execute([cxx, '-std=c++20', '-fsyntax-only', f'-I{output}', '-DMEMORY_PROOF_ENABLED=' + args.flag,
                 common.HERE / 'harness/memory_proof_frontier_exact_range.cpp'], output / 'driver-header-syntax.log', 120)
        receipt['actual_header_syntax'] = 'PASS'
        objects = []
        for source in sorted(output.glob(TOP + '[0-9]*.cpp')):
            obj = source.with_suffix('.o')
            execute([cxx, *cflags, '-c', source, '-o', obj], obj.with_suffix('.compile.log'))
            objects.append(obj)
        if not objects:
            raise AssertionError('GSIM generated no model translation units')
        receipt['model_objects_sha256'] = {p.name: sha(p) for p in objects}
        run = output / 'run'
        execute([cxx, *cflags, '-DMEMORY_PROOF_ENABLED=' + args.flag,
                 common.HERE / 'harness/memory_proof_frontier_exact_range.cpp', *objects, '-ldl', '-o', run], output / 'driver-compile.log')
        positive = execute([run], output / 'positive.log', 180)
        if ANCHOR not in positive or 'cases=13' not in positive:
            raise AssertionError('exact range endpoint cases incomplete')
        execute([run, '--inject-pa'], output / 'negative-pa.log', 180,
                'frontier full tuple differs from host owner/permission model')
        if sources() != pinned or any(sha(path) != digest for path, digest in receipt['tools'].items()):
            raise AssertionError('source or pinned tool changed during exact qualification')
        receipt['status'] = 'PASS'
    except BaseException as error:
        receipt['status'] = 'FAIL'
        receipt['error'] = str(error)
        raise
    finally:
        (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')


if __name__ == '__main__':
    main()
