#!/usr/bin/env python3
"""Explicit near-term A source/profile entry. Defaults to validation; --emit exports RTL only."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MANIFEST = HERE / 'near-term-a-profile.json'
CPU_FLAGS = ('--fetch-accepted-prefix-validation', '--aligned-fetch-single-page',
             '--factor-checked-next-allowed', '--local-tagged-response-ready')


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def load_profile():
    profile = json.loads(MANIFEST.read_text())
    if profile['schema'] != 'valence-near-term-a-entry-v1' or profile['status'] != 'SOURCE_ONLY_REVIEW_PENDING':
        raise RuntimeError('near-term A entry identity changed')
    rollback_path = HERE / profile['rollback_manifest']
    if rollback_path.name != 'timing-batch-locality64-profile.json' or \
            hashlib.sha256(rollback_path.read_bytes()).hexdigest() != profile['rollback_sha256']:
        raise RuntimeError('exact64 rollback manifest differs')
    rollback = load_module('near_term_a_rollback', HERE / 'board_timing64.py').load_profile()
    options = rollback + list(CPU_FLAGS)
    if profile['rollback_options'] != rollback or profile['additional_cpu_options'] != list(CPU_FLAGS) or \
            profile['native_options'] != options or len(options) != len(set(options)) or len(options) != 68 or \
            profile['native_option_count'] != 68 or profile['core_field_count'] != 172:
        raise RuntimeError('near-term A requires exact64 plus only the four CPU options')
    if profile['physical_option_count'] != 2 or any(profile[n] is not False for n in
            ('full_cpu_qualification', 'physical_qualification', 'historical_certificate_reused')):
        raise RuntimeError('CPU and physical option/qualification domains differ')
    leaves = profile['production_leaf_sha256']
    if not leaves:
        raise RuntimeError('unfrozen near-term A production leaves')
    changed = load_module('a_mac_platform_source_bridge', HERE / 'mac_platform_source_bridge.py').checked_sources()
    for name, digest in leaves.items():
        path = Path(name)
        expected = changed[name]['new_sha256'] if name in changed else digest
        if path.is_absolute() or '..' in path.parts or hashlib.sha256((ROOT / path).read_bytes()).hexdigest() != expected:
            raise RuntimeError('near-term A production leaf differs: ' + name)
    return profile


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--emit', action='store_true')
    args = parser.parse_args(argv)
    profile = load_profile()
    exporter = load_module('near_term_a_exporter', HERE / 'export.py')
    physical = [exporter.board_t1.FLAG, exporter.board_t1.SELECTED_FLAG]
    if profile['physical_options'] != physical:
        raise RuntimeError('near-term A physical generic bridge differs')
    options = ['--output', str(args.output), *(x for x in profile['native_options'] if x != '--selected'), *physical]
    if args.emit:
        options.append('--emit')
    exporter.main(options)


if __name__ == '__main__':
    main()
