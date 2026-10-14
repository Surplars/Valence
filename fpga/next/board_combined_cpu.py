#!/usr/bin/env python3
"""Explicit qualified CPU combination; preflight by default, native RTL only with --emit."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
NAME = 'combined-young-resident-held-r1'
PROFILE_SHA256 = '5f515773787a45a6fba0854a0bdf040938b0caba7322ff90bc179de5661226ab'


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def require_equal(actual, expected, reason):
    if canonical(actual) != canonical(expected):
        raise RuntimeError(reason)


def load_profile():
    path = HERE / 'combined-cpu-profile.json'
    if hashlib.sha256(path.read_bytes()).hexdigest() != PROFILE_SHA256:
        raise RuntimeError('strict combined profile identity changed')
    p = json.loads(path.read_text())
    bridge = load('combined_resident_source_bridge', 'resident_memory_source_bridge.py')
    closure = bridge.checked_sources()
    resident = load('combined_resident_entry', 'board_resident_memory.py').load_profile()
    expected_options = resident['native_options'] + ['--held-alu-issue-forwarding']
    if p['schema'] != 'valence-combined-cpu-native-entry-v1' or p['name'] != NAME or \
            p['native_main'] != 'ooo.CombinedCpuFeaturesNativeMain' or \
            p['constructor_main'] != 'ooo.CombinedCpuFeaturesConstructorMain' or \
            p['native_options'] != expected_options or len(expected_options) != len(set(expected_options)) or \
            len(expected_options) != 71 or p['physical_options'] != resident['physical_options']:
        raise RuntimeError('combined entry must be exact Young69 + resident + held71 with unchanged physical options')
    for kind, count in [('core', 175), ('profile', 92)]:
        if p[kind + '_fields'] != closure['current_' + kind + '_names'] or len(p[kind + '_fields']) != count:
            raise RuntimeError('complete current ordered product names differ: ' + kind)
        bridge.validate_parameter_types(p['expected_profile'][kind], kind, closure)
        for feature in ('postedYoungerLoadSealDeferral', 'residentMemoryPayloadReuse', 'heldAluIssueForwarding'):
            if p['expected_profile'][kind][feature] is not True:
                raise RuntimeError('combined feature must be literal true: ' + kind + '/' + feature)
    if p['expected_profile']['profile']['triSpeedRawClockHandoff'] is not False or \
            '--tri-speed-raw-clock-handoff' in p['native_options']:
        raise RuntimeError('raw MAC handoff is an independent OFF option')
    expected = json.loads((ROOT / closure['reference']['profile_file']).read_text())
    for kind in ('core', 'profile'):
        expected[kind]['residentMemoryPayloadReuse'] = True
        expected[kind]['heldAluIssueForwarding'] = True
    expected['profile']['triSpeedRawClockHandoff'] = False
    require_equal(p['expected_profile'], expected, 'all complete measured Young typed/nested values must be preserved')
    for kind in ('resident', 'held'):
        for leaf in ('core', 'backend', 'ledger'):
            require_equal(p['expected_constructor'][kind][leaf], expected['core'], 'complete actual leaf expectation')
    if p['qualification']['physical_qualification'] is not False or p['qualification']['raw_mac_handoff'] is not False:
        raise RuntimeError('CPU qualification cannot imply physical or raw MAC qualification')
    return p


def export_arguments(profile, output, emit=False):
    args = ['--output', str(output), *(x for x in profile['native_options'] if x != '--selected'),
            *profile['physical_options']]
    return args + (['--emit'] if emit else [])


def bind_native_command(command, raw_arguments, output, emit):
    """The generic writer may canonicalize order; only its exact matching option set is rebound."""
    p = load_profile()
    if raw_arguments != export_arguments(p, output, emit):
        raise RuntimeError('named combination refuses override, omission, reordering or extra arguments')
    if command[:4] != ['mill', '-i', 'IonSoC.test.runMain', 'ooo.FpgaNextMain'] or \
            len(command) != 76 or len(set(command[5:])) != 71 or sorted(command[5:]) != sorted(p['native_options']):
        raise RuntimeError('native writer resolved options differ from the exact combined constructor')
    return command[:3] + [p['native_main'], command[4], *p['native_options']]


def validate_native_output(directory):
    p = load_profile()
    def read(name):
        return json.loads((directory / name).read_text())
    require_equal(read('profile.json'), p['expected_profile'], 'actual full native profile differs')
    require_equal(read('actual-product-field-order.json'),
                  {'core': p['core_fields'], 'profile': p['profile_fields']}, 'actual native field order differs')
    for name, key in [('actual-held-alu-forwarding.json', 'held'),
                      ('actual-resident-memory.json', 'resident'), ('actual-mac-raw-handoff.json', 'mac')]:
        require_equal(read(name), p['expected_constructor'][key], 'actual complete native constructor differs: ' + key)
    expected = {'schema': 'combined-cpu-native-actual-v1', 'name': NAME, 'options': p['native_options'],
                'coreFields': 175, 'profileFields': 92, 'young': True, 'resident': True, 'held': True,
                'rawMac': False, 'completeActualConstructorsVerified': True, 'physicalQualification': False}
    require_equal(read('combined-cpu-entry.json'), expected, 'strict actual named-entry completion missing')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--emit', action='store_true')
    args = parser.parse_args(argv)
    p = load_profile()
    exporter = load('combined_cpu_exporter', 'export.py')
    exporter.main(export_arguments(p, args.output, args.emit), named_entry=NAME)


if __name__ == '__main__':
    main()
