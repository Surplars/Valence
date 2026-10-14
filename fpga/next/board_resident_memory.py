#!/usr/bin/env python3
"""Explicit Young69 plus resident memory source-only entry; validation by default."""
import argparse
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
FLAG = '--resident-memory-payload-reuse'
YOUNG_FLAG = '--posted-younger-load-seal-deferral'


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_profile():
    bridge = load('resident_memory_entry_bridge', 'resident_memory_source_bridge.py')
    closure = bridge.checked_sources()
    base = load('resident_memory_a', 'board_near_term_a.py').load_profile()
    profile = json.loads((HERE / 'resident-memory-profile.json').read_text())
    off = base['native_options'] + [YOUNG_FLAG]
    on = off + [FLAG]
    if profile['schema'] != 'resident-memory-integration-entry-v1' or \
            profile['status'] != 'SOURCE_ONLY_YOUNG69_REFERENCE_RELEASE_PENDING' or \
            profile['reference_native_options'] != off or profile['native_options'] != on or \
            len(off) != len(set(off)) or len(off) != 69 or len(on) != len(set(on)) or len(on) != 70 or \
            profile['physical_options'] != base['physical_options'] or \
            profile['core_fields'] != closure['current_core_names'] or \
            profile['profile_fields'] != closure['current_profile_names'] or \
            profile['reference'] != closure['reference'] or \
            profile['held_alu_forwarding'] is not False or profile['physical_raw_handoff'] is not False or \
            profile['resident_memory_payload_reuse'] is not True or \
            profile['dynamic_qualification'] is not False or profile['physical_qualification'] is not False:
        raise RuntimeError('resident entry differs from source-bound Young69 plus one exact CPU option')
    if '--held-alu-issue-forwarding' in on or '--tri-speed-raw-clock-handoff' in on:
        raise RuntimeError('resident entry cannot enable held ALU or raw MAC')
    return profile


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--emit', action='store_true')
    args = parser.parse_args(argv)
    p = load_profile()
    exporter = load('resident_memory_export', 'export.py')
    options = ['--output', str(args.output), *(x for x in p['native_options'] if x != '--selected'), *p['physical_options']]
    if args.emit:
        options.append('--emit')
    exporter.main(options)


if __name__ == '__main__':
    main()
