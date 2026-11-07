#!/usr/bin/env python3
"""Finite AIA 1.0 hart-control GSIM acceptance, not whole-CPU ISA qualification.

Compiles only the new standalone control module and emitter with hash-pinned cached
Scala dependencies, then checks WARL/commit storage, M/HS default order, and the full
VS candidate/priority rules with an independent C++ oracle. Uses no physical tools,
Verilator, downloads, or existing production harness changes.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
SOURCES = [
    'src/main/scala/core/ooo/system/AiaHartControl.scala',
    'src/test/scala/ip/AiaHartControlGsim.scala',
]
HARNESS = 'simulator/gsim/harness/aia_hart_control.cpp'
INPUTS = SOURCES + [HARNESS, 'simulator/gsim/aia_hart_control_acceptance.py']


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--gsim', type=Path, required=True)
    parser.add_argument('--cxx', type=Path, required=True)
    parser.add_argument('--runtime-manifest', type=Path, required=True)
    parser.add_argument('--scala-cache', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    record = dict(status='RUNNING', commands=[], sources={s: sha(ROOT/s) for s in INPUTS},
                  tools={str(t): sha(t) for t in [args.gsim, args.cxx]},
                  reference_urls=['https://docs.riscv.org/reference/aia/v1.0/MSLevel.html',
                                  'https://docs.riscv.org/reference/aia/v1.0/VSLevel.html'],
                  physical_timing_qualified=False, whole_cpu_isa_qualified=False)

    def save():
        (out/'receipt.json').write_text(json.dumps(record, indent=2)+'\n')

    def run(argv, name, negative=False):
        argv = list(map(str, argv))
        start = time.monotonic()
        with (out/name).open('w') as log:
            result = subprocess.run(argv, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                    timeout=600, env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'})
        record['commands'].append(dict(argv=argv, exit=result.returncode,
                                       seconds=time.monotonic()-start, log=name))
        save()
        result_text = (out/name).read_text()
        if negative:
            assert result.returncode == 1 and 'independent AIA hart control oracle' in result_text, result_text
        else:
            assert result.returncode == 0, result_text
        return result_text

    try:
        save()
        dependencies = json.loads(args.runtime_manifest.read_text())
        for path, digest in dependencies.items():
            assert sha(path) == digest, 'dependency hash mismatch: '+path

        def jar(fragment):
            matches = list(args.scala_cache.resolve().rglob(fragment))
            assert len(matches) == 1, (fragment, matches)
            return str(matches[0])

        compiler = [jar('scala-'+name+'-2.13.17.jar') for name in ['compiler', 'library', 'reflect']]
        plugin = jar('chisel-plugin_2.13.17-7.3.0.jar')
        classes = out/'classes'
        classes.mkdir()
        record['runtime_dependencies'] = dependencies
        record['scala_tools'] = {p: sha(p) for p in compiler+[plugin]}
        cp = ':'.join(dependencies)
        run(['java', '-Xmx2g', '-XX:ActiveProcessorCount=2', '-cp', ':'.join(compiler),
             'scala.tools.nsc.Main', '-classpath', cp, '-Xplugin:'+plugin,
             '-language:reflectiveCalls', '-d', classes, *[ROOT/s for s in SOURCES]], 'compile.log')
        run(['java', '-Xmx2g', '-XX:ActiveProcessorCount=2', '-cp', str(classes)+':'+cp,
             'ip.AiaHartControlGsimMain', out], 'emit.log')
        fir = out/'AiaHartControl.fir'
        if fir.stat().st_size % 4096 == 0:
            fir.write_bytes(fir.read_bytes()+b'\n')
        run([args.gsim, '--threads=1', '--dir='+str(out), fir], 'generate.log')
        generated = sorted(out.glob('AiaHartControl[0-9]*.cpp'))
        assert generated
        binary = out/'run'
        run([args.cxx, '-std=c++20', '-O1', '-fsanitize=address,undefined',
             '-fno-sanitize-recover=all', '-I'+str(out), *generated,
             ROOT/HARNESS, '-ldl', '-o', binary], 'link.log')
        result_text = run([binary], 'run.log')
        assert 'PASS AIA hart control:' in result_text, result_text
        print(result_text, end='', flush=True)
        run([binary, '--wrong-priority'], 'negative.log', negative=True)
        assert record['sources'] == {s: sha(ROOT/s) for s in INPUTS}, 'sources changed during regression'
        record['status'] = 'PASS_FINITE_AIA_HART_CONTROL'
    except BaseException as error:
        record['status'] = 'FAIL'
        record['error'] = repr(error)
        raise
    finally:
        record['artifacts'] = {str(p.relative_to(out)): sha(p) for p in out.rglob('*')
                               if p.is_file() and p.name != 'receipt.json'}
        save()


if __name__ == '__main__':
    main()
