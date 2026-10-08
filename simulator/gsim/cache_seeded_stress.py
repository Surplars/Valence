#!/usr/bin/env python3
"""Replay runtime-seeded cache contention against already emitted RTL models."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import run as common


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--registers', type=Path, required=True)
    ap.add_argument('--banked', type=Path, required=True)
    ap.add_argument('--tag', required=True)
    ap.add_argument('--qualified-receipt', type=Path, default=common.ROOT/'docs/evidence/fpga-cache-tags-20261008.json')
    ap.add_argument('--case', default='data-prefetch')
    ap.add_argument('--seeds', default='1,2,3,5,8,13,21,34')
    ap.add_argument('--iterations', type=int, default=1024)
    ap.add_argument('--reuse-binaries', action='store_true')
    ap.add_argument('--build-only', action='store_true')
    args = ap.parse_args()
    seeds = [int(x) for x in args.seeds.split(',')]
    out = common.BUILD/args.tag
    out.mkdir(parents=True, exist_ok=False)
    harness = common.HERE/'harness/cache_concurrency_stress.cpp'
    inputs = [harness, common.HERE/'harness/coherent_cache_home.cpp', common.HERE/'harness/board_ddr_mixed.h',
              common.HERE/'harness/mshr_occupancy.h', Path(__file__)]
    before = {str(p.relative_to(common.ROOT)): sha(p) for p in inputs}
    report = {'status': 'RUNNING', 'sources': before, 'models': {}, 'seeds': seeds,
              'iterations': args.iterations, 'scope': 'independent random RTL memory/coherence replay; no FPGA or CPU measurement'}
    try:
        cxx, version = common.compiler()
        report['compiler'] = version
        qualified = json.loads(args.qualified_receipt.read_text())
        assert qualified['status'].startswith('PASS'), 'qualified receipt has not passed'
        report['qualified_receipt_sha256'] = sha(args.qualified_receipt)
        for layout, model in [('registers', args.registers.resolve()), ('banked', args.banked.resolve())]:
            receipt = json.loads((model.parent/'receipt.json').read_text())
            for rel, expected in receipt['source_sha256'].items():
                if rel.startswith('src/') and rel.endswith('.scala'):
                    assert sha(common.ROOT/rel) == expected, 'RTL changed since model emission: '+rel
            model_files = [model/'CoherentCacheHomeGsim.fir', model/'CoherentCacheHomeGsim.h',
                           *sorted(model.glob('CoherentCacheHomeGsim[0-9]*.cpp'))]
            model_hashes = {p.name: sha(p) for p in model_files}
            qualified_artifacts = qualified['cases'][args.case][layout]['artifacts']
            assert all(qualified_artifacts.get(name) == digest for name,digest in model_hashes.items()), 'emitted model differs from qualified receipt'
            binary = model/'seeded-stress'
            contract = model/'seeded-stress-build.json'
            expected_contract = {'model': model_hashes, 'sources': {k:v for k,v in before.items() if not k.endswith('cache_seeded_stress.py')}, 'compiler': version}
            if args.reuse_binaries:
                saved_contract = json.loads(contract.read_text())
                saved_contract['sources'].pop('simulator/gsim/cache_seeded_stress.py', None)
                expected_binary_sha256 = saved_contract.pop('binary_sha256', None)
                assert binary.is_file() and expected_binary_sha256 == sha(binary), 'reused binary digest mismatch'
                assert binary.is_file() and saved_contract == expected_contract, 'unverified binary reuse'
            else:
                flags = ['-std=c++20', '-O1', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                         '-DREAD_MSHRS=2', '-DCACHE_LINES=512', '-DRESPONSE_ENTRIES=2',
                         '-DAXI_SLOTS=4', '-DMIXED_MODEL=1', '-DMIXED_RTL=1', '-I'+str(model)]
                objects = []
                for cpp in sorted(model.glob('CoherentCacheHomeGsim[0-9]*.cpp')):
                    obj = cpp.with_suffix('.stress.o')
                    stamp = obj.with_suffix('.json')
                    object_contract = {'cpp_sha256': sha(cpp), 'header_sha256': sha(model/'CoherentCacheHomeGsim.h'),
                                       'compiler': version, 'flags': flags}
                    saved_object = json.loads(stamp.read_text()) if stamp.is_file() else {}
                    saved_object_sha256 = saved_object.pop('object_sha256', None)
                    if not obj.is_file() or saved_object != object_contract or saved_object_sha256 != sha(obj):
                        common.run([cxx, *flags, '-c', cpp, '-o', obj], log=out/(layout+'-'+cpp.stem+'-compile.log'))
                        stamp.write_text(json.dumps({**object_contract, 'object_sha256': sha(obj)}, indent=2)+'\n')
                    objects.append(obj)
                common.run([cxx, *flags, *objects, harness, '-ldl', '-o', binary],
                           log=out/(layout+'-driver-compile.log'))
                contract.write_text(json.dumps({**expected_contract, 'binary_sha256': sha(binary)}, indent=2)+'\n')
            if args.build_only:
                report['models'][layout] = {'model_sha256': model_hashes, 'binary_sha256': sha(binary), 'built': True}
                continue
            results = {}
            for seed in seeds:
                path = out/(layout+'-'+str(seed)+'.log')
                common.run([binary, '--seed', seed, '--iterations', args.iterations], log=path,
                    timeout=180, env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'})
                results[str(seed)] = path.read_text()
            negative = subprocess.run([binary, '--seed', str(seeds[0]), '--iterations', '64', '--inject-mismatch'],
                text=True, capture_output=True, timeout=180, env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'})
            (out/(layout+'-negative.log')).write_text(negative.stdout+negative.stderr)
            assert negative.returncode != 0 and 'CPU independent byte oracle mismatch' in negative.stdout+negative.stderr
            report['models'][layout] = {'model_sha256': model_hashes, 'binary_sha256': sha(binary),
                                        'results': results, 'negative': 'PASS'}
            (out/'progress.json').write_text(json.dumps(report, indent=2)+'\n')
        if not args.build_only:
            assert report['models']['registers']['results'] == report['models']['banked']['results'], 'seeded cycle/metric mismatch'
        assert before == {str(p.relative_to(common.ROOT)): sha(p) for p in inputs}, 'driver changed during replay'
        report['status'] = 'BUILD_ONLY' if args.build_only else 'PASS'
    except BaseException as error:
        report['status'] = 'FAIL'; report['error'] = str(error); raise
    finally:
        (out/'receipt.json').write_text(json.dumps(report, indent=2)+'\n')


if __name__ == '__main__': main()
