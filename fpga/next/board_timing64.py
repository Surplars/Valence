#!/usr/bin/env python3
"""Explicit exact59-plus-five native entry with the existing MAC T1/USER2 contract.

Default is preflight only. An explicit --emit uses export.py and its unchanged
board_t1/media/BSCAN staging. No CPU, mapping, synthesis or FPGA tool runs here.
Old library/mapped cda7 certificates do not qualify this new RTL.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MANIFEST = HERE / 'timing-batch-locality64-profile.json'
FLAGS = ('--fetch-ready-data-clear', '--memory-preparation-head-mask',
         '--direct-rank0-memory-source-ids', '--retirement-slot-identity',
         '--local-cache-read-selection')


def exporter_module():
    spec = importlib.util.spec_from_file_location('timing64_exporter', HERE / 'export.py')
    exporter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(exporter)
    return exporter


def load_profile():
    profile = json.loads(MANIFEST.read_text())
    if profile['schema'] != 'valence-timing-locality64-entry-v1' or profile['status'] != 'SOURCE_ONLY_EXPLICIT_ENTRY_NOT_QUALIFICATION':
        raise RuntimeError('timing64 entry identity changed')
    path = HERE / profile['default52_manifest']
    if path.name != 'timing-batch-owner-row-profile.json' or hashlib.sha256(path.read_bytes()).hexdigest() != profile['default52_sha256']:
        raise RuntimeError('retained default52 manifest changed')
    baseline = json.loads(path.read_text())['native_options']
    retained = profile['retained59_options']
    seven = ['--predecoded-head-drain', '--retirement-intent', '--fetch-address-before-pmp',
             '--queued-head-selection', '--aligned-next-line-pmp', '--register-probe-lookup',
             '--local-address-ranges']
    if len(baseline) != 52 or retained != baseline + seven or len(set(retained)) != 59:
        raise RuntimeError('retained59 must remain exact default52 plus the reviewed seven')
    if profile['additional_options'] != list(FLAGS) or profile['native_option_count'] != 64 or profile['physical_T1_option_count'] != 1:
        raise RuntimeError('timing64 must add exactly five explicit options')
    options = retained + list(FLAGS)
    if len(set(options)) != 64 or not {'--selected', '--experimental-trispeed-ethernet', '--experimental-jtag-bscan=2'}.issubset(options):
        raise RuntimeError('timing64 selected/tri-speed/USER2 contract changed')
    if any(profile[key] is not False for key in ('qualified_rtl_certificate_reused', 'full_cpu_qualification', 'physical_qualification')):
        raise RuntimeError('source-only entry cannot inherit RTL/CPU/physical qualification')
    if profile['historical_mapped_library_certificate'] != {'identity_prefix': 'cda7', 'reused_for_new_rtl': False}:
        raise RuntimeError('historical mapped/library certificate cannot qualify the new RTL')
    leaves = profile['production_leaf_sha256']
    if len(leaves) != 11:
        raise RuntimeError('expected the eleven reviewed production leaves')
    spec = importlib.util.spec_from_file_location('timing64_mac_platform_bridge', HERE / 'mac_platform_source_bridge.py')
    bridge = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bridge)
    changed = bridge.checked_sources()
    for name, digest in leaves.items():
        if name in changed and changed[name]['old_sha256'] != digest:
            raise RuntimeError('timing64 platform bridge old source differs: ' + name)
        expected = changed[name]['new_sha256'] if name in changed else digest
        if not name.startswith('src/main/scala/core/ooo/') or '..' in Path(name).parts or \
                hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected:
            raise RuntimeError('timing64 changed production leaf differs: ' + name)
    return options


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--emit', action='store_true')
    args = parser.parse_args(argv)
    exporter = exporter_module()
    options = ['--output', str(args.output), *(x for x in load_profile() if x != '--selected'), exporter.board_t1.FLAG]
    if args.emit:
        options.append('--emit')
    exporter.main(options)


if __name__ == '__main__':
    main()
