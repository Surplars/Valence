#!/usr/bin/env python3
"""Focused full64/compact32 issue payload A/B, independent oracle and assertion negatives."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

import run as common


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--build-run', action='store_true')
    parser.add_argument('--skip-contracts', action='store_true', help='Contracts already ran in the combined Scala batch')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.tag):
        parser.error('invalid tag')
    paths = sorted((common.ROOT / 'src').rglob('*.scala')) + [Path(__file__).resolve(),
        common.HERE / 'harness/compact_issue_immediate.cpp',
        common.HERE / 'harness/decoder_immediate.cpp', common.HERE / 'run.py']
    inputs = {str(p.relative_to(common.ROOT)): sha(p) for p in paths}
    if not args.build_run:
        print(json.dumps({'status': 'PREFLIGHT_ONLY', 'inputs': len(inputs)}))
        return
    out = common.BUILD / args.tag
    out.mkdir(parents=True, exist_ok=False)
    report = {'status': 'RUNNING', 'inputs': inputs, 'cases': {}, 'negative': {},
              'limits': ['Focused payload only; no CPU equivalence or mapped resource/timing claim']}
    env = {**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'}
    try:
        if not args.skip_contracts:
            common.run(['mill', '-i', 'IonSoC.test.testOnly', 'ooo.FpgaIssueStorageSpec'], log=out / 'contracts.log')
        gsim, cxx = common.setup(False)
        for compact in (False, True):
            name = 'compact32' if compact else 'full64'
            model = common.test(gsim, cxx, args.tag + '/' + name, 'ooo.BankedIssuePayloadGsimMain',
                'BankedIssuePayloadGsim', 'compact_issue_immediate.cpp',
                parameters=('compact',) if compact else (), defines={})
            report['cases'][name] = (model / 'test.log').read_text()
            if not compact:
                common.run([model / 'run', '--arbitrary64'], env=env, log=model / 'arbitrary64.log', timeout=180)
                report['cases']['arbitrary64'] = (model / 'arbitrary64.log').read_text()
            negatives = [('--inject-payload-mismatch', 'immutable issue payload oracle mismatch'),
                         ('--inject-bank-collision', 'issue allocation writes must occupy distinct parity banks')]
            if compact:
                negatives.append(('--inject-noncanonical-immediate', 'compact issue immediate must be canonical signed32'))
            for flag, message in negatives:
                result = subprocess.run([str(model / 'run'), flag], capture_output=True, text=True,
                                        timeout=180, env=env)
                output = result.stdout + result.stderr
                (model / (flag.removeprefix('--') + '.log')).write_text(output)
                if result.returncode == 0 or message not in output:
                    raise RuntimeError('negative did not reject ' + name + '/' + flag)
                report['negative'][name + '/' + flag] = {'returncode': result.returncode, 'message': message}
        if report['cases']['full64'] != report['cases']['compact32']:
            raise RuntimeError('full64/compact32 cycle and coverage pair differs')
        decoder = common.test(gsim, cxx, args.tag + '/decoder', 'ooo.DecoderImmediateGsimMain',
            'DecoderImmediateGsim', 'decoder_immediate.cpp', defines={})
        report['cases']['decoder'] = (decoder / 'test.log').read_text()
        result = subprocess.run([str(decoder / 'run'), '--inject-mismatch'], capture_output=True, text=True,
                                timeout=180, env=env)
        output = result.stdout + result.stderr
        (decoder / 'negative.log').write_text(output)
        if result.returncode == 0 or 'decoder immediate outside signed32' not in output:
            raise RuntimeError('decoder range negative did not reject')
        report['negative']['decoder'] = {'returncode': result.returncode}
        report['status'] = 'PASS_COMPACT_ISSUE_IMMEDIATE'
    except Exception as error:
        report['status'] = 'FAIL'
        report['error'] = str(error)
        raise
    finally:
        changed = any(sha(p) != inputs[str(p.relative_to(common.ROOT))] for p in paths)
        if changed:
            report['status'] = 'FAIL_SOURCE_CHANGED'
        report['artifacts'] = {str(p.relative_to(out)): sha(p) for p in out.rglob('*')
                               if p.is_file() and p.name != 'receipt.json'}
        (out / 'receipt.json').write_text(json.dumps(report, indent=2) + '\n')
        if changed:
            raise RuntimeError('sources changed during proof')
    print(json.dumps({'status': report['status'], 'receipt': str(out / 'receipt.json')}))


if __name__ == '__main__':
    main()
