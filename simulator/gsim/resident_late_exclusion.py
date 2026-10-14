#!/usr/bin/env python3
"""Short selector-only old/new hardware and independent ordered-walk proof."""
import argparse
import hashlib
import json
from pathlib import Path
import re

import run as common
from issue_frontend_storage import negative


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', default='resident-late-exclusion')
    parser.add_argument('--build-run', action='store_true')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.tag):
        parser.error('invalid tag')
    files = sorted((common.ROOT / 'src/main/scala').rglob('*.scala')) + [
        common.ROOT / 'src/test/scala/ooo/ResidentLateExclusionGsim.scala',
        common.HERE / 'harness/resident_late_exclusion.cpp', Path(__file__),
        common.HERE / 'run.py', common.HERE / 'issue_frontend_storage.py']
    def hashes():
        return {str(path.relative_to(common.ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    before = hashes()
    if not args.build_run:
        print(json.dumps({'status': 'PREPARED_NOT_RUN', 'new_state': 0, 'extra_prf_ports': 0,
            'scope': 'selector only, both head modes, old topology, full-token validity boundary, ordered-walk oracle'}))
        return
    out = common.BUILD / args.tag
    out.mkdir(parents=True, exist_ok=False)
    receipt = {'status': 'RUNNING', 'source_sha256': before, 'physical_timing': 'unverified'}
    try:
        gsim, cxx = common.setup(False)
        model = common.test(gsim, cxx, args.tag + '/selector', 'ooo.ResidentLateExclusionGsimMain',
            'ResidentLateExclusionGsim', 'resident_late_exclusion.cpp', defines={}, timeout=180)
        receipt['positive'] = (model / 'test.log').read_text()
        receipt['negative'] = {
            'oracle': negative(model / 'run', (), '--inject-mismatch',
                'resident late exclusion independent oracle mismatch', model / 'negative-oracle.log'),
            'owner': negative(model / 'run', (), '--invalid-issued',
                "accepted memory start must name the caller's exact live resident", model / 'negative-owner.log')}
        if hashes() != before:
            raise RuntimeError('source changed during selector proof')
        receipt['status'] = 'PASS_SELECTOR_ONLY'
    except Exception as error:
        receipt['status'] = 'FAIL'
        receipt['error'] = str(error)
        raise
    finally:
        (out / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')


if __name__ == '__main__':
    main()
