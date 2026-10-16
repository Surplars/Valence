#!/usr/bin/env python3
"""Bounded real-home boundary/metadata/hold proof. Installed tools only; no board model."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import run as common

CASES = ((0, 0, 0), (1, 0, 0), (0, 1, 1), (1, 1, 1), (1, 0, 1), (1, 1, 0))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tag', required=True)
    ap.add_argument('--gsim-binary', type=Path, default=common.SOURCE / 'build/gsim/gsim')
    args = ap.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.tag):
        ap.error('unsafe output tag')
    output = common.BUILD / ('prearbiter-home-' + args.tag)
    output.mkdir(parents=True, exist_ok=False)
    gsim = args.gsim_binary.resolve()
    if not gsim.is_file():
        ap.error('installed GSIM binary missing; no automatic download is permitted')
    cxx, version = common.compiler()
    paths = sorted((common.ROOT / 'src/main/scala').rglob('*.scala')) + [
        common.ROOT / 'src/test/scala/ooo/PrearbiterHomeGsim.scala',
        common.HERE / 'harness/prearbiter_home.cpp', common.HERE / 'harness/prearbiter_home_base.cpp',
        Path(__file__).resolve()]
    def hashes():
        return {str(p.relative_to(common.ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    report = {'status': 'RUNNING', 'source_sha256': hashes(), 'compiler': version,
        'gsim_sha256': hashlib.sha256(gsim.read_bytes()).hexdigest(), 'cases': {},
        'scope': '16-line compact MixedCoherentLineHome, real boundary and arbiter; coordinated hold reset; '
                 'not MachinePlatform/full board, physical timing or sustained-bandwidth qualification'}
    env = {**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'}
    try:
        for enabled, raw_request, raw_response in CASES:
            key = f'{enabled}-{raw_request}-{raw_response}'
            d = common.test(gsim, cxx, output.name + '/' + key,
                'ooo.prearbiterhome.PrearbiterHomeGsimMain', 'HomeMshrGsim', 'prearbiter_home.cpp',
                parameters=(2, 1, 16, 1, enabled, raw_request, raw_response),
                defines={'HOME_ENTRIES': 2, 'HOME_LINES': 16, 'HOME_MIXED': 1, 'HOME_BASE': '0xffff0000ULL'},
                timeout=180)
            log = (d / 'test.log').read_text()
            if not all(marker in log for marker in ('buffered_a_hold', 'partial_d_hold', 'PREARBITER_HOME_PASS')):
                raise RuntimeError('missing explicit home/hold result marker')
            negative = subprocess.run([str(d / 'run'), '--inject-data'], capture_output=True, text=True,
                timeout=120, env=env)
            (d / 'negative.log').write_text(negative.stdout + negative.stderr)
            if negative.returncode == 0 or 'independent Grant data mismatch' not in negative.stderr:
                raise RuntimeError('negative payload oracle missed intended failure')
            report['cases'][key] = {'log': log, 'negative_exit': negative.returncode}
        def metrics(log):
            return {parts[1]: {field: int(value) for field, value in
                (item.split('=') for item in parts[2:])}
                for line in log.splitlines() if line.startswith('HOME_TAG_CASE ')
                for parts in [line.split()]}
        observed = {key: metrics(value['log']) for key, value in report['cases'].items()}
        for off, on in (('0-0-0', '1-0-0'), ('0-1-1', '1-1-1')):
            if observed[off].keys() != observed[on].keys():
                raise RuntimeError('paired protocol case set changed')
            for case in observed[off]:
                for field in ('acquires', 'grants', 'releases', 'probes', 'writes', 'reset_canceled'):
                    if observed[off][case][field] != observed[on][case][field]:
                        raise RuntimeError(f'paired protocol traffic changed: {case}/{field}')
        for key in ('1-0-0', '1-0-1', '1-1-0'):
            if observed[key] != observed['1-1-1']:
                raise RuntimeError('raw metadata settings changed the matched protocol transcript')
        report['matched_protocol_counts_and_metadata_transcripts'] = 'PASS'
        report['cycle_comparison'] = {case: {'off': observed['0-0-0'][case]['cycles'],
            'on': observed['1-0-0'][case]['cycles']} for case in observed['0-0-0']}
        if hashes() != report['source_sha256']:
            raise RuntimeError('source changed during paired test')
        report['status'] = 'PASS_LOCAL_HOME_ONLY'
    except Exception as exc:
        report['status'] = 'FAIL'
        report['error'] = str(exc)
        raise
    finally:
        (output / 'receipt.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
