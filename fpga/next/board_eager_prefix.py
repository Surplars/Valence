#!/usr/bin/env python3
"""Explicit optional53 source-bound export; board_final.py remains default52.

Default: preflight only. --emit exports native RTL and stages MAC T1 / USER2
contracts. No synthesis, implementation, or physical qualification runs here.
"""
import argparse
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FLAG = '--eager-fetch-prefix-select'
MANIFEST = HERE / 'timing-batch-eager-prefix-profile.json'
RECEIPT_PATH = 'simulator/gsim/eager_prefix/evidence/public-receipt.json'
RECEIPT_SHA256 = 'ae6305b0f59d38b94334ea36873691b7dde099308f51be96e85d1d159d22fd5f'


def final_module():
    spec = importlib.util.spec_from_file_location('eager_prefix_final52', HERE / 'board_final.py')
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def load_profile():
    final = final_module()
    base = final.load_profile()
    if final.sha(ROOT / RECEIPT_PATH) != RECEIPT_SHA256:
        raise RuntimeError('optional53 public qualification receipt changed')
    receipt = json.loads((ROOT / RECEIPT_PATH).read_text())
    if receipt['schema'] != 'valence-eager-prefix-public-qualification-v1' or receipt['recorded_qualification']['status'] != 'PASS_COMBINED_EAGER_PREFIX_QUALIFICATION':
        raise RuntimeError('optional53 qualification identity changed')
    candidate = json.loads(MANIFEST.read_text())
    baseline = json.loads((HERE / base['cpu_profile']['manifest']).read_text())['native_options']
    options = candidate['native_options']
    if len(baseline) != 52 or candidate['native_option_count'] != 53 or options != [*baseline, FLAG] or receipt['configuration']['native_options'] != options:
        raise RuntimeError('optional53 must be exact final52 plus one eager prefix flag')
    if candidate['base_source_commit'] != receipt['baseline_commit'] or receipt['baseline_commit'] != 'b22f10fde916a0c8209d070e282ebd98cf4c0b2f':
        raise RuntimeError('optional53 base publication differs')
    config = receipt['configuration']
    if config['native_mac_t1'] is not True or config['jtag_user_chain'] != 2 or config['fixture_overrides'] != {}:
        raise RuntimeError('optional53 T1/USER2/fixture contract changed')
    return final, base, receipt


def check_export(output, exported, final, base, recorded):
    exporter = final.exporter_module()
    if exported.get('status') != 'PASS_RTL_EXPORT_ONLY' or exported.get('synthesis') is not False or exported.get('physical_qualification') is not False:
        raise RuntimeError('expected optional53 unqualified native export')
    if final.digest(exported['profile']) != recorded['configuration']['export_profile_sha256']:
        raise RuntimeError('optional53 complete export configuration changed')
    command = exported['command']
    options = recorded['configuration']['native_options']
    if command[:4] != ['mill', '-i', 'IonSoC.test.runMain', 'ooo.FpgaNextMain'] or len(command) < 5 or Path(command[4]).resolve() != output / 'rtl' or sorted(command[5:]) != sorted(options):
        raise RuntimeError('optional53 exact native command changed')
    if exported['source_sha256'] != exporter.sources():
        raise RuntimeError('optional53 current source inventory changed')
    if any(exported.get('native_mac_mode', {}).get(key) != value for key, value in base['mode'].items()):
        raise RuntimeError('optional53 MAC T1 mode changed')
    wrapper = exported.get('board_wrapper', {})
    if wrapper.get('media') != 'experimental-trispeed' or wrapper.get('additional_jtag_package_pins') != 0 or wrapper.get('qualified') is not False:
        raise RuntimeError('optional53 tri-speed and hard JTAG contract changed')
    final.check_staged_contracts(output, exported, exporter)


def binding(recorded, base):
    return {'schema': 'valence-optional-eager-prefix-export-binding-v1',
            'status': 'STAGED_REQUIRES_EXPLICIT_PHYSICAL_AB_CONSUMER',
            'public_receipt_sha256': RECEIPT_SHA256,
            'native_options': recorded['configuration']['native_options'],
            'export_profile_sha256': recorded['configuration']['export_profile_sha256'],
            'tested_actual_profile_sha256': recorded['configuration']['actual_profile_sha256'],
            'tested_actual_fabric_sha256': recorded['configuration']['actual_fabric_sha256'],
            'default_native_option_count': 52, 'mode': base['mode'],
            'synthesis_consumer_executed': False, 'physical_qualification': False}


def verify(output):
    final, base, recorded = load_profile()
    exported = json.loads((output / 'receipt.json').read_text())
    check_export(output, exported, final, base, recorded)
    item = exported['optional_eager_prefix_profile']
    path = output / 'board/optional-eager-prefix-profile.json'
    if item['path'] != 'board/optional-eager-prefix-profile.json' or item['sha256'] != final.sha(path) or json.loads(path.read_text()) != binding(recorded, base):
        raise RuntimeError('optional53 staged profile binding changed')
    return {'status': 'PASS_OPTIONAL53_EXPORT_BINDING_ONLY', 'native_option_count': 53,
            'default_native_option_count': 52, 'physical_T1_option_count': 1,
            'synthesis_consumer_executed': False, 'physical_qualification': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--emit', action='store_true')
    parser.add_argument('--verify-export', type=Path)
    args = parser.parse_args(argv)
    if args.verify_export is not None:
        if args.output is not None or args.emit:
            parser.error('--verify-export excludes --output and --emit')
        print(json.dumps(verify(args.verify_export.resolve()), indent=2))
        return
    if args.output is None:
        parser.error('--output is required')
    final, base, recorded = load_profile()
    exporter = final.exporter_module()
    options = ['--output', str(args.output), *(x for x in recorded['configuration']['native_options'] if x != '--selected'), exporter.board_t1.FLAG]
    if args.emit:
        options.append('--emit')
    exporter.main(options, expected_profile_sha256=recorded['configuration']['export_profile_sha256'])
    if args.emit:
        output = args.output.resolve()
        receipt_path = output / 'receipt.json'
        exported = json.loads(receipt_path.read_text())
        try:
            check_export(output, exported, final, base, recorded)
            path = output / 'board/optional-eager-prefix-profile.json'
            path.write_text(json.dumps(binding(recorded, base), indent=2) + '\n')
            exported['optional_eager_prefix_profile'] = {'path': 'board/optional-eager-prefix-profile.json', 'sha256': final.sha(path)}
        except BaseException as error:
            exported['status'] = 'FAIL'
            exported['error'] = str(error)
            raise
        finally:
            receipt_path.write_text(json.dumps(exported, indent=2) + '\n')
        print(json.dumps(verify(output), indent=2))


if __name__ == '__main__':
    main()
