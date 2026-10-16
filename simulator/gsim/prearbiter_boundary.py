#!/usr/bin/env python3
"""Focused paired home-A timing-boundary proof; installed GSIM only, no downloads."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import run as common


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tag', required=True)
    ap.add_argument('--gsim-binary', type=Path, default=common.SOURCE / 'build/gsim/gsim')
    args = ap.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.tag):
        ap.error('unsafe output tag')
    output = common.BUILD / ('prearbiter-boundary-' + args.tag)
    output.mkdir(parents=True, exist_ok=False)
    gsim = args.gsim_binary.resolve()
    if not gsim.is_file():
        ap.error('installed GSIM binary missing; this runner never downloads tools')
    cxx, version = common.compiler()
    sources = sorted((common.ROOT / 'src/main/scala').rglob('*.scala')) + [
        common.ROOT / 'src/test/scala/ooo/PrearbiterBoundaryGsim.scala',
        common.HERE / 'harness/prearbiter_line_write.cpp',
        common.HERE / 'harness/prearbiter_stress.cpp', Path(__file__).resolve()]
    def hashes():
        return {str(p.relative_to(common.ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    report = {'status': 'RUNNING', 'source_sha256': hashes(),
        'gsim_sha256': hashlib.sha256(gsim.read_bytes()).hexdigest(), 'compiler': version,
        'scope': 'Writer plus real arbiter; no integrated home/board, routed timing or utilization claim',
        'pairs': {}}
    env = {**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'}
    try:
        for on in (0, 1):
            d = common.test(gsim, cxx, output.name + '/' + str(on), 'ooo.PrearbiterBoundaryGsimMain',
                'PrearbiterBoundaryGsim', 'prearbiter_line_write.cpp', parameters=(1, on),
                defines={'LINE_DISPATCH_FLOW': 1, 'PREARBITER_BOUNDARY': on})
            common.run([cxx, '-std=c++20', '-O1', '-g', '-fsanitize=address,undefined',
                '-fno-sanitize-recover=all', '-I' + str(d), *sorted(d.glob('PrearbiterBoundaryGsim[0-9]*.cpp')),
                common.HERE / 'harness/prearbiter_stress.cpp', '-ldl', '-o', d / 'stress'],
                log=d / 'stress-compile.log')
            common.run([d / 'stress'], log=d / 'stress.log', env=env)
            negative = subprocess.run([str(d / 'run'), '--inject-mismatch'], capture_output=True,
                text=True, env=env, timeout=120)
            (d / 'negative.log').write_text(negative.stdout + negative.stderr)
            if negative.returncode == 0 or 'line write oracle mismatch' not in negative.stderr:
                raise RuntimeError('negative payload oracle did not reject at intended check')
            report['pairs'][str(on)] = {'directed': (d / 'test.log').read_text(),
                'stress': (d / 'stress.log').read_text(), 'negative_exit': negative.returncode}
        if hashes() != report['source_sha256']:
            raise RuntimeError('source drift during paired check')
        report['status'] = 'PASS_LOCAL_ONLY'
    except Exception as exc:
        report['status'] = 'FAIL'
        report['error'] = str(exc)
        raise
    finally:
        (output / 'receipt.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
