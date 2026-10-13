#!/usr/bin/env python3
"""Independent A + one default-OFF MAC platform option. Validation by default."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MANIFEST = HERE / 'near-term-a-raw-handoff-profile.json'
FLAG = '--tri-speed-raw-clock-handoff'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_profile():
    profile = json.loads(MANIFEST.read_text())
    parent_path = HERE / 'near-term-a-profile.json'
    if profile['schema'] != 'near-term-a-mac-raw-handoff-v1' or sha(parent_path) != profile['parent_manifest_sha256']:
        raise RuntimeError('frozen parent A entry differs')
    parent = json.loads(parent_path.read_text())
    expected = parent['native_options'] + [FLAG]
    if profile['native_options'] != expected or len(expected) != len(set(expected)) or len(expected) != 69:
        raise RuntimeError('entry must be the exact A options plus one platform flag')
    if profile['physical_options'] != parent['physical_options'] or profile['core_field_count'] != 172 or \
            profile['profile_field_count'] != 89 or profile['new_platform_fields'] != {'triSpeedRawClockHandoff': True}:
        raise RuntimeError('platform/core/physical contract changed')
    for key in ('historical_certificate_reused', 'physical_qualification', 'full_cpu_run_required'):
        if profile[key] is not False:
            raise RuntimeError('unapproved qualification or execution claim: ' + key)
    for name, digest in profile['production_leaf_sha256'].items():
        path = Path(name)
        if path.is_absolute() or '..' in path.parts or sha(ROOT / path) != digest:
            raise RuntimeError('source-bound MAC entry leaf differs: ' + name)
    return profile


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--emit', action='store_true')
    args = parser.parse_args(argv)
    profile = load_profile()
    spec = importlib.util.spec_from_file_location('mac_raw_handoff_export', HERE / 'export.py')
    exporter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(exporter)
    options = ['--output', str(args.output), *(x for x in profile['native_options'] if x != '--selected'),
               *profile['physical_options']]
    if args.emit:
        options.append('--emit')
    exporter.main(options)


if __name__ == '__main__':
    main()
