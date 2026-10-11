#!/usr/bin/env python3
"""Short independent cache-way/ordered-response and authorized LSU-handoff checks.

No capacity growth, synthesis or whole-CPU claim. Actual CPU A/B is measured by
cpu_sv39_bandwidth.py with --profiles accepted admission, using fixed R32/B32.
"""
import argparse
from contextlib import redirect_stdout
import json
import os
from pathlib import Path
import re
import subprocess
import run as common
from cpu_sv39_bandwidth import inputs as cpu_inputs, sha


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tag', required=True)
    args = ap.parse_args()
    if not re.fullmatch('[A-Za-z0-9_-]+', args.tag):
        ap.error('unsafe tag')
    out = common.BUILD/('independent-demand-admission-'+args.tag)
    out.mkdir(parents=True, exist_ok=False)

    def inputs():
        assets = [Path(__file__), *[common.HERE/'harness'/n for n in
                  ('coherent_read_mshr.cpp', 'canonical_store_lsu.cpp', 'canonical_store_oracle.h')]]
        return {**cpu_inputs(), **{str(p.relative_to(common.ROOT)): sha(p) for p in assets}}

    frozen = inputs()
    state = {'status': 'RUNNING', 'source_sha256': frozen, 'commands': [], 'artifacts': {}}

    def save():
        (out/'receipt.json').write_text(json.dumps(state, indent=2)+'\n')

    save()
    try:
        gsim, cxx = common.setup(False)
        state['toolchain'] = {**common.LOCK, 'compiler': common.compiler()[1], 'gsim_sha256': sha(gsim)}
        for label, main, model, driver, params, defines, anchor, negative in (
            ('cache', 'ooo.CoherentReadMshrGsimMain', 'CoherentReadMshrGsim', 'coherent_read_mshr.cpp',
             ('2', '32', '2', '8', '1', str(0x80010000), '--banked-cache-tags', '--independent-demand-admission'),
             {'READ_MSHRS': 2, 'CACHE_LINES': 32, 'CACHE_WAYS': 2, 'INDEPENDENT_DEMAND_ADMISSION': 1,
              'COMPACT_TAG_TEST': 1}, 'COHERENT_READ_MSHR_PASS', '--inject-mismatch'),
            ('lsu', 'ooo.CanonicalStoreLsuGsimMain', 'CanonicalStoreLsuGsim', 'canonical_store_lsu.cpp',
             ('2', '--canonical-handoff'), {'CANONICAL_HANDOFF': 1}, 'CANONICAL_STORE_LSU_PASS', '--inject-payload')
        ):
            if inputs() != frozen:
                raise RuntimeError('source drift before boundary gate')
            with (out/(label+'-driver.log')).open('x') as trace, redirect_stdout(trace):
                directory = common.test(gsim, cxx, out.name+'/'+label, main, model, driver,
                                        parameters=params, defines=defines, timeout=120)
            if anchor not in (directory/'test.log').read_text():
                raise RuntimeError('missing positive anchor '+label)
            result = subprocess.run([str(directory/'run'), negative], cwd=common.ROOT,
                                    capture_output=True, text=True, timeout=120,
                                    env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'})
            log = out/(label+'-negative.log')
            log.write_text(result.stdout+result.stderr)
            expected = ('CPU independent data mismatch' if label == 'cache' else
                        'LSU payload no longer belongs to the independently accepted start')
            state['commands'].append({'name': label+'-negative', 'exit': result.returncode,
                                      'anchor': expected, 'log_sha256': sha(log)})
            if result.returncode == 0 or expected not in log.read_text():
                raise RuntimeError('negative oracle failed '+label+'\n'+log.read_text()[-2000:])
        if inputs() != frozen:
            raise RuntimeError('source drift during short boundary gate')
        state['artifacts'] = {str(p.relative_to(out)): sha(p) for p in out.rglob('*')
                              if p.is_file() and p.name != 'receipt.json'}
        state['status'] = 'PASS_INDEPENDENT_DEMAND_AND_AUTHORIZED_HANDOFF'
        save()
        print(state['status'], flush=True)
    except Exception as e:
        state['status'] = 'FAIL'
        state['error'] = str(e)
        save()
        raise


if __name__ == '__main__':
    main()
