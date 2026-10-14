#!/usr/bin/env python3
"""Explicit A68 plus B1 validation-only entry; --emit is a separate native action."""
import argparse
import importlib.util
import json
from pathlib import Path
HERE = Path(__file__).resolve().parent
FLAG = '--held-alu-issue-forwarding'


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_profile():
    bridge = load('held_alu_bridge', 'held_alu_source_bridge.py')
    closure = bridge.checked_sources()
    base = load('held_alu_a', 'board_near_term_a.py').load_profile()
    profile = json.loads((HERE / 'held-alu-profile.json').read_text())
    options = base['native_options'] + [FLAG]
    if profile['schema'] != 'held-alu-integration-entry-v1' or \
            profile['native_options'] != options or len(set(options)) != 69 or \
            profile['physical_options'] != base['physical_options'] or \
            profile['core_fields'] != closure['current_core_names'] or \
            profile['profile_fields'] != closure['current_profile_names'] or \
            profile['physical_raw_handoff'] is not False or \
            profile['dynamic_qualification'] is not False or profile['physical_qualification'] is not False:
        raise RuntimeError('explicit B1 entry differs from source-bound A68 plus one CPU option')
    return profile


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--emit', action='store_true')
    args = parser.parse_args(argv)
    p = load_profile()
    exporter = load('held_alu_export', 'export.py')
    options = ['--output', str(args.output), *(x for x in p['native_options'] if x != '--selected'), *p['physical_options']]
    if args.emit:
        options.append('--emit')
    exporter.main(options)


if __name__ == '__main__':
    main()
