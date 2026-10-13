#!/usr/bin/env python3
"""Explicit future-Home + STORE-PF LRU profile; source/configuration preflight by default."""
import argparse
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MANIFEST = HERE / 'timing-batch-home-future-lru-profile.json'


def load_profile():
    spec = importlib.util.spec_from_file_location('future_lru_final', HERE / 'board_final.py')
    final = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(final)
    base = final.load_profile()
    profile = json.loads(MANIFEST.read_text())
    options = json.loads((HERE / base['cpu_profile']['manifest']).read_text())['native_options']
    if final.sha(ROOT / "simulator/gsim/home_future_lru/evidence.json") != profile["retained_evidence_sha256"]:
        raise RuntimeError("experimental54 retained evidence identity changed")
    if (profile['schema'] != 'valence-future-home-lru-profile-v1' or
            profile['native_options'] != options + ['--future-home-way-reservation', '--store-prefetch-lru-victim'] or
            profile['native_option_count'] != 54 or profile['fixture_overrides'] != {} or
            profile['native_mac_t1'] is not True or profile['jtag_user_chain'] != 2 or
            profile['physical_qualification'] is not False):
        raise RuntimeError('experimental54 complete profile changed')
    return final, base, profile


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--emit', action='store_true')
    args = ap.parse_args(argv)
    final, base, profile = load_profile()
    exporter = final.exporter_module()
    options = ['--output', str(args.output),
               *(x for x in profile['native_options'] if x != '--selected'), exporter.board_t1.FLAG]
    if args.emit:
        options.append('--emit')
    exporter.main(options, expected_profile_sha256=profile['export_profile_sha256'])
    if args.emit:
        output = args.output.resolve()
        receipt = json.loads((output / 'receipt.json').read_text())
        if receipt['status'] != 'PASS_RTL_EXPORT_ONLY' or receipt['source_sha256'] != exporter.sources():
            raise RuntimeError('experimental54 export identity changed')
        if sorted(receipt['command'][5:]) != sorted(profile['native_options']):
            raise RuntimeError('experimental54 native command changed')
        final.check_staged_contracts(output, receipt, exporter)
        print(json.dumps({'status': 'PASS_EXPERIMENTAL54_EXPORT_ONLY', 'synthesis': False,
                          'physical_qualification': False}, indent=2))


if __name__ == '__main__':
    main()
