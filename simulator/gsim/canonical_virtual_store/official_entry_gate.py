#!/usr/bin/env python3
"""Bind the public performance entry to the qualified native/CPU profile.

Preflight is host-only. --emit requires an explicitly granted heavy slot and
emits two native tops, never a GSIM model or a new CPU performance run. Only FIR
source locators may be removed. Generated RTL is compared as literal raw bytes.
"""
import argparse
import contextlib
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / 'fpga/next'))
import export as exporter
import performance


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(value, message):
    if not value:
        raise ValueError(message)


def equal(actual, expected, label):
    require(json.dumps(actual, sort_keys=True, separators=(',', ':')) ==
            json.dumps(expected, sort_keys=True, separators=(',', ':')), label)


def normalized_fir(text):
    return re.sub(r' @\[[^\n]*?\]', '', text)


def compare_profile(official, qualified, side):
    expected = json.loads(json.dumps(qualified))
    equal(expected.pop('developmentTreatment'), {'canonicalVirtualStoreOverlap': side == 'on',
        'productionCliSupportsTreatment': False}, 'qualified development treatment changed')
    expected['profile']['canonicalVirtualStoreOverlap'] = side == 'on'
    equal(official, expected, 'complete official profile differs from qualified profile')
    require(len(official['profile']) == 27 and len(official['core']) == 136, 'incomplete full profile')


def compare_actual(official, qualified, side):
    require(official['allActualParametersEqualExpected'] is True and official['hardwareMutation'] is False,
            'official actual parameter audit did not pass')
    equal(official['expectedCore'], qualified['expectedCore'], 'actual expected core differs')
    require(official['expectedCore']['canonicalVirtualStoreOverlap'] is (side == 'on'), 'wrong actual treatment')
    for key, count in [('coreParameters', 6), ('ddrParameters', 2), ('cacheConcurrency', 3)]:
        a, b = official[key], qualified[key]
        require(len(a) == count and len(b) == count, 'omitted actual instance: ' + key)
        equal([(r['instancePath'], r['values']) for r in a],
              [(r['instancePath'], r['values']) for r in b], 'actual values differ: ' + key)
    equal([r['values'] for r in official['cacheTileLinkParameters']],
          [r['values'] for r in qualified['cacheTileLinkParameters']], 'cache TileLink differs')


def raw_tree(path):
    return {p.relative_to(path).as_posix(): sha(p) for p in sorted(path.rglob('*')) if p.is_file()}


def bound_sources():
    result = exporter.sources()
    for path in sorted((ROOT / "src/test/scala").rglob("*.scala")):
        result[path.relative_to(ROOT).as_posix()] = sha(path)
    for path in (Path(__file__).resolve(), HERE / "official-reference-pins.json"):
        result[path.relative_to(ROOT).as_posix()] = sha(path)
    return result


def verify_production():
    manifest = HERE / 'evidence/production-freeze-r1.sha256'
    expected = {}
    for line in manifest.read_text().splitlines():
        digest, name = line.split(None, 1)
        expected[name] = digest
        require(sha(ROOT / name) == digest, 'qualified production source changed: ' + name)
    require(len(expected) == 11, 'incomplete production freeze')
    return expected


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--native-reference', type=Path, required=True)
    parser.add_argument('--cpu-reference', type=Path, required=True)
    parser.add_argument('--mill', type=Path)
    parser.add_argument('--firtool', type=Path)
    parser.add_argument('--emit', action='store_true')
    parser.add_argument('--slot-granted', action='store_true')
    args = parser.parse_args(argv)
    require(not args.output.exists(), 'fresh gate output required')
    require(not args.emit or (args.slot_granted and args.mill and args.firtool), 'emit requires slot and exact tools')
    pins = json.loads((HERE / 'official-reference-pins.json').read_text())
    production = verify_production()
    before = bound_sources()
    report = {'schema': 'canonical-official-entry-correspondence-v1', 'status': 'PREFLIGHT_ONLY',
        'production_source': production, 'source_before': before, 'reference_pins': pins,
        'qualification_inherited': False, 'new_cpu_runtime': False, 'sides': {}}
    for side in ('off', 'on'):
        native = args.native_reference / ('native-' + side.upper())
        cpu = args.cpu_reference / ('model-' + side + '-r1')
        for key, item in pins['references'][side].items():
            parent = cpu if key.startswith('cpu_') else native
            require(sha(parent / item['path']) == item['sha256'], 'reference identity changed: ' + key)
        native_receipt = json.loads((native / 'receipt.json').read_text())
        expected_rtl = native_receipt['rtl_sha256']
        require(expected_rtl and all(name.startswith('rtl/') for name in expected_rtl),
                'invalid native reference artifact inventory')
        equal(raw_tree(native / 'rtl'), {name[4:]: digest for name, digest in expected_rtl.items()},
              'native reference raw artifact drift: ' + side)
        capture = io.StringIO()
        with contextlib.redirect_stdout(capture):
            performance.main(['--output', str(args.output / side)] +
                (['--disable-canonical-store-overlap'] if side == 'off' else []))
        public = json.loads(capture.getvalue())
        options = public['command'][5:]
        require(('--canonical-virtual-store-overlap' in options) == (side == 'on'), 'public treatment absent')
        command = [str(args.mill), '-i', '-j', '1', 'IonSoC.test.runMain',
            'ooo.CanonicalVirtualStoreActualParamsMain', str(args.output / side), side, *options]
        row = {'public_preflight': public, 'actual_emit_command': command}
        report['sides'][side] = row
        if args.emit:
            args.output.mkdir(exist_ok=True, parents=True)
            with (args.output / (side + '-emit.log')).open('w') as log:
                subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
            actual = args.output / side
            compare_profile(json.loads((actual / 'profile.json').read_text()),
                            json.loads((native / 'profile.json').read_text()), side)
            current = json.loads((actual / 'actual-parameters.json').read_text())
            for reference in (native, cpu):
                compare_actual(current, json.loads((reference / 'actual-parameters.json').read_text()), side)
            old_fir = normalized_fir((native / 'FpgaNextSocTop.fir').read_text())
            new_fir = normalized_fir((actual / 'FpgaNextSocTop.fir').read_text())
            require(old_fir == new_fir, 'official/native FIR differs beyond source locators: ' + side)
            lower = [str(args.firtool), str(actual / 'FpgaNextSocTop.fir'), '--format=fir', '--split-verilog',
                '--strip-debug-info', '--disable-all-randomization', '--default-layer-specialization=disable',
                '-o', str(actual / 'rtl')]
            with (args.output / (side + '-lower.log')).open('w') as log:
                subprocess.run(lower, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
            equal(raw_tree(actual / 'rtl'), raw_tree(native / 'rtl'), 'official/native raw RTL differs: ' + side)
            row.update(status='PASS_ACTUAL_PARAMETERS_AND_RAW_NATIVE', normalized_fir_sha256=
                hashlib.sha256(new_fir.encode()).hexdigest(), raw_rtl=raw_tree(actual / 'rtl'),
                actual_parameter_sha256=sha(actual / 'actual-parameters.json'))
    equal(bound_sources(), before, 'source changed during gate')
    report['status'] = 'PASS_OFFICIAL_ENTRY_ACTUAL_PARAMETERS_AND_RAW_NATIVE' if args.emit else 'PREFLIGHT_ONLY'
    args.output.mkdir(exist_ok=True, parents=True)
    (args.output / 'receipt.json').write_text(json.dumps(report, indent=2) + '\n')
    print(report['status'], args.output / 'receipt.json')


if __name__ == '__main__':
    main()
