#!/usr/bin/env python3
"""Exact timing ready/raw73 entry. Source preflight by default; native emission requires --emit."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
HERE = Path(__file__).resolve().parent
NAME = 'combined-timing-ready-raw73-r1'
PROFILE_SHA256 = 'fc66ccb6e878d8d480c7c52ace4e512f55e06228c9995df63713c29db1e28ab7'
NATIVE_MAIN = 'ooo.TimingReady73NativeMain'

def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def require_equal(actual, expected, reason):
    if json.dumps(actual, sort_keys=True, separators=(',', ':'), allow_nan=False) != json.dumps(expected, sort_keys=True, separators=(',', ':'), allow_nan=False):
        raise RuntimeError(reason)

def expected(p, side, key):
    def expand(value):
        if isinstance(value, dict):
            if set(value) == {'$timing_core'}:
                if value['$timing_core'] != side:
                    raise RuntimeError('cross-side core reference')
                return json.loads(json.dumps(p[side + '_profile']['core']))
            return {k: expand(v) for k, v in value.items()}
        if isinstance(value, list):
            return [expand(v) for v in value]
        return value
    return expand(p[side + '_' + key])

def load_profile():
    path = HERE / 'timing-ready73-profile.json'
    if hashlib.sha256(path.read_bytes()).hexdigest() != PROFILE_SHA256:
        raise RuntimeError('strict timing profile identity changed')
    p = json.loads(path.read_text())
    bridge = load('timing_entry_bridge', 'timing_ready73_source_bridge.py')
    closure = bridge.checked_sources()
    parent_path = HERE / 'timing-closure-profile.json'
    if hashlib.sha256(parent_path.read_bytes()).hexdigest() != p['parent74_profile_sha256']:
        raise RuntimeError('immutable74 parent changed')
    parent = json.loads(parent_path.read_text())
    def frozen_off(value):
        if isinstance(value, dict):
            result = {}
            for k, v in value.items():
                if k == 'frozenStoreCheckedFlow':
                    if v is not True: raise RuntimeError('parent74 frozen flag is not literal true')
                    result[k] = False
                else: result[k] = frozen_off(v)
            return result
        if isinstance(value, list): return [frozen_off(v) for v in value]
        return value
    for key in ('on_profile', 'on_existing_audits', 'on_timing_audit', 'on_fabric'):
        require_equal(p[key], frozen_off(parent[key]), 'only frozen flow may differ from full74: ' + key)
    base_path = HERE / 'combined-cpu-profile.json'
    if hashlib.sha256(base_path.read_bytes()).hexdigest() != p['baseline_profile_sha256']:
        raise RuntimeError('immutable combined baseline changed')
    base = json.loads(base_path.read_text())
    if p['schema'] != 'valence-timing-ready73-profile-v1' or p['name'] != NAME or p['off_options'] != base['native_options'] or p['on_options'] != p['off_options'] + ['--registered-load-result-ready', '--tri-speed-raw-clock-handoff'] or len(p['on_options']) != 73 or len(set(p['on_options'])) != 73:
        raise RuntimeError('exact ordered73 native options changed')
    require_equal(p['physical_options'], base['physical_options'], 'approved physical options changed')
    off = json.loads(json.dumps(base['expected_profile']))
    for kind in ('core', 'profile'):
        for flag in ('registeredLoadResultReady', 'frozenStoreCheckedFlow'):
            off[kind][flag] = False
    require_equal(p['off_profile'], off, 'complete retained OFF configuration changed')
    on = json.loads(json.dumps(off))
    for kind in ('core', 'profile'):
        for flag in ('registeredLoadResultReady', 'frozenStoreCheckedFlow'):
            on[kind][flag] = flag == 'registeredLoadResultReady'
    on['profile']['triSpeedRawClockHandoff'] = True
    require_equal(p['on_profile'], on, 'complete ON differs beyond one core/two platform booleans')
    for kind, count in [('core', 177), ('profile', 94)]:
        if p[kind + '_fields'] != closure['current_' + kind + '_names'] or len(p[kind + '_fields']) != count:
            raise RuntimeError('complete field order differs: ' + kind)
        for side in ('off', 'on'):
            bridge.validate_parameter_types(p[side + '_profile'][kind], kind, closure)
    return p

def export_arguments(p, output, emit=False):
    args = ['--output', str(output), *(x for x in p['on_options'] if x != '--selected'), *p['physical_options']]
    return args + (['--emit'] if emit else [])

def bind_native_command(command, raw_arguments, output, emit):
    p = load_profile()
    if raw_arguments != export_arguments(p, output, emit):
        raise RuntimeError('named timing entry refuses override, omission, reordering or extras')
    if command[:4] != ['mill', '-i', 'IonSoC.test.runMain', 'ooo.FpgaNextMain'] or len(command) != 78 or len(set(command[5:])) != 73 or sorted(command[5:]) != sorted(p['on_options']):
        raise RuntimeError('native writer resolved options differ from exact73 constructor')
    return command[:3] + [NATIVE_MAIN, command[4], *p['on_options']]

def completion(p):
    return {'schema': 'timing-ready73-native-actual-v1', 'name': NAME,
        'coreFields': 177, 'profileFields': 94, 'options': p['on_options'], 'rawMac': True,
        'completeActualConstructorsVerified': True, 'physicalQualification': False,
        'cdcQualified': False, 'phyQualified': False}

def validate_native_output(directory):
    p = load_profile()
    def read(name):
        return json.loads((directory / name).read_text())
    require_equal(read('profile.json'), p['on_profile'], 'actual full native profile differs')
    require_equal(read('actual-product-field-order.json'), {k: p[k + '_fields'] for k in ('core', 'profile')}, 'actual field order differs')
    require_equal(read('actual-timing-closure.json'), expected(p, 'on', 'timing_audit'), 'complete timing constructor differs')
    for file, key in [('actual-held-alu-forwarding.json', 'held'), ('actual-resident-memory.json', 'resident'), ('actual-mac-raw-handoff.json', 'mac')]:
        require_equal(read(file), expected(p, 'on', 'existing_audits')[key], 'complete actual native constructor differs: ' + key)
    require_equal(read('timing-ready73-entry.json'), completion(p), 'strict timing completion differs')
    if (directory / 'options.txt').read_text() != ''.join(x + '\n' for x in p['on_options']):
        raise RuntimeError('actual exact ordered options differ')

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--emit', action='store_true')
    args = parser.parse_args(argv)
    p = load_profile()
    load('timing_exporter', 'export.py').main(export_arguments(p, args.output, args.emit), named_entry=NAME)

if __name__ == '__main__':
    main()
