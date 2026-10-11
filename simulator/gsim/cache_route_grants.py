#!/usr/bin/env python3
"""Affected cache-grant checks only: existing adoption and exhausted-fallback gates.

This runner never synthesizes or executes a CPU. The complete owner/byte oracles
are reused unchanged. The only transport adaptation fully initializes the pinned
GSIM trivially-copyable object before the fixture's real reset edges.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
HERE = ROOT / 'simulator/gsim'
TOP = 'PostedPrefetchCoexistGsim'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inputs():
    names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT, text=True).split('\0')
    return {name: sha(ROOT / name) for name in names if name and (ROOT / name).is_file()}


def main():
    ap = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--run-grant', action='store_true')
    args = ap.parse_args()
    if not args.run_grant:
        ap.error('explicit serial compilation slot required')
    assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT)
    out = args.output.resolve()
    assert not out.exists(), 'preserve every prior attempt'
    assert shutil.disk_usage(ROOT).free > 1024 ** 3
    out.mkdir(parents=True)
    env = Path(os.environ['VALENCE_CLOUD_ENV'])
    gsim = env / 'gsim-src/build/gsim/gsim'
    cxx = env / 'sysroot/usr/bin/clang++-19'
    mill = Path(shutil.which('mill'))
    bound_inputs = inputs()
    tools = {str(p): sha(p.resolve()) for p in (gsim, cxx, mill)}
    receipt = {'schema': 'cache-route-grants-affected-gates-v1', 'status': 'RUNNING',
               'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
               'inputs': bound_inputs, 'tools': tools, 'commands': [],
               'models': ['adoption-off-generation64', 'adoption-on-generation64',
                          'coexistence-on-generation2-writebacks2'],
               'historical_pass_inherited': False, 'compiler_jobs': 1,
               'gsim_cpp_max_size_KB': 1024, 'executing_cpu': False,
               'physical_qualification': False}

    def save():
        (out / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')

    def run(name, command, anchor=None, timeout=1200):
        assert inputs() == bound_inputs
        assert {p: sha(Path(p).resolve()) for p in tools} == tools
        command = list(map(str, command))
        print('+', name, ' '.join(command), flush=True)
        started = time.monotonic()
        log = out / (name + '.log')
        with log.open('x') as stream:
            result = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                                    timeout=timeout, env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0',
                                                        'PYTHONDONTWRITEBYTECODE': '1'})
        text = log.read_text()
        receipt['commands'].append({'name': name, 'argv': command, 'exit': result.returncode,
                                    'seconds': time.monotonic() - started, 'log_sha256': sha(log)})
        save()
        assert result.returncode == 0, name + ': ' + text[-4000:]
        if anchor:
            assert anchor in text, name + ': missing terminal anchor'
        assert inputs() == bound_inputs

    try:
        save()
        run('adoption-affected-gates', [sys.executable, '-B', HERE / 'prefetch_demand_adoption.py',
            '--output', out / 'adoption', '--run-grant'], 'PASS_COMPONENT_ONLY')
        adoption = json.loads((out / 'adoption/receipt.json').read_text())
        assert adoption['status'] == 'PASS_COMPONENT_ONLY'
        assert adoption['models']['off']['directed_cases'] == 2
        assert adoption['models']['on']['directed_cases'] == 18
        model = out / 'fallback'
        model.mkdir()
        run('fallback-emit', [mill, '-i', '-j', '1', 'IonSoC.test.runMain',
            'ooo.PostedPrefetchCoexistGsimMain', model, '1', '2', '2'])
        run('fallback-generate', [gsim, '--threads=1', '--cpp-max-size-KB=1024',
            '--dir=' + str(model), model / (TOP + '.fir')])
        spec = importlib.util.spec_from_file_location('coexist_ports', HERE / 'posted_prefetch_coexist/ports.py')
        ports = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ports)
        driver = model / 'driver.cpp'
        ports.emit_driver(driver)
        original = driver.read_text()
        (model / 'driver-original.cpp').write_text(original)
        anchor = ' SPostedPrefetchCoexistGsim d;'
        assert original.count(anchor) == 1
        driver.write_text(original.replace('#include <cstdint>',
            '#include <cstdint>\n#include <cstring>\n#include <type_traits>').replace(anchor,
            anchor + '\n static_assert(std::is_trivially_copyable_v<SPostedPrefetchCoexistGsim>);'
            '\n std::memset(&d, 0, sizeof(d)); d.LOG_START = 1; d.activateAll();'))
        flags = ['-std=c++20', '-O1', '-g', '-gz=zlib', '-fsanitize=address,undefined',
                 '-fno-sanitize-recover=all', '-I' + str(model)]
        units = sorted(model.glob(TOP + '[0-9]*.cpp'))
        assert units
        run('fallback-host-syntax', [cxx, *flags, '-fsyntax-only', driver])
        objects = []
        for i, unit in enumerate(units):
            obj = unit.with_suffix('.o')
            run('fallback-compile-' + str(i), [cxx, *flags, '-c', unit, '-o', obj])
            objects.append(obj)
        executable = model / 'run'
        run('fallback-link', [cxx, *flags, driver, *objects, '-ldl', '-o', executable])
        run('fallback-cases', [sys.executable, '-B', HERE / 'posted_prefetch_coexist/fixture.py',
            '--executable', executable, '--output', model / 'cases', '--policy', '1',
            '--generation-bits', '2', '--wb-entries', '2'],
            'POSTED_PREFETCH_COEXIST_PASS policy=1 generation_bits=2 cases=5')
        fallback = json.loads((model / 'cases/result.json').read_text())
        assert fallback['status'] == 'PASS' and len(fallback['cases']) == 5
        assert sum(c['status'] == 'EXPECTED_RTL_ASSERTION' for c in fallback['cases']) == 1
        receipt['adoption_receipt_sha256'] = sha(out / 'adoption/receipt.json')
        receipt['fallback_result_sha256'] = sha(model / 'cases/result.json')
        receipt['fallback_artifacts'] = {str(p.relative_to(model)): sha(p)
                                         for p in sorted(model.rglob('*')) if p.is_file()}
        receipt['scope'] = ('Real cache/home adoption OFF2/ON18 with exact owner, byte and error oracles; '
                            'synthetic-manager gen2 fallback4 + actual context-before-WB-drain assertion; '
                            'new route equations asserted in all executed cache instances.')
        receipt['status'] = 'PASS_AFFECTED_CACHE_GRANT_GATES'
    except BaseException as error:
        receipt['status'] = 'FAIL'
        receipt['error'] = str(error)
        raise
    finally:
        save()
    print(receipt['status'], out / 'receipt.json', flush=True)


if __name__ == '__main__':
    main()
