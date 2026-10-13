#!/usr/bin/env python3
"""Check optional53 receipt and local source/configuration; never rerun hardware."""
import argparse
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path, PurePosixPath
import re
import tempfile

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[2]
RECEIPT_PATH = 'simulator/gsim/eager_prefix/evidence/public-receipt.json'
RECEIPT_SHA256 = 'ae6305b0f59d38b94334ea36873691b7dde099308f51be96e85d1d159d22fd5f'
BASE = 'b22f10fde916a0c8209d070e282ebd98cf4c0b2f'
BASE_TREE = 'a931ea8ec32438b5fe45852509b0b3dc0a782a6b'
TESTED_TREE = '5736ae9442acfe05a4ffee1df58726c86e7d7e69'
SOURCE_SET_SHA256 = '5a6eede449efd93737c7135f461d0c8c6676ba7edd80c0fe534492f5beef01c5'
SOURCE_COUNT = 32
HISTORICAL_RECEIPT = 'simulator/gsim/owner_row/evidence/public-receipt.json'
HISTORICAL_SHA256 = '9e3012abadb499e753a3c2d7caf7c719049dc012aed5e1cdb442300936b1eada'
FIELDS = {'schema', 'baseline_commit', 'baseline_tree', 'tested_candidate_commit', 'tested_candidate_tree',
          'verification_scope', 'recorded_qualification', 'configuration', 'source_fingerprints',
          'production_source_closure', 'qualified_scala_source_closure', 'full_receipt_sha256',
          'external_evidence', 'default52_bridge', 'prior_failures_and_limits'}
PRODUCTION = ['src/main/scala', 'src/main/resources', 'third_party/berkeley-hardfloat/src/main/scala', 'fpga/next/rtl']
SCALA = ['src/main/scala', 'src/test/scala', 'third_party/berkeley-hardfloat/src/main/scala']


def need(value, message):
    if not value:
        raise RuntimeError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def safe_file(root, name):
    path = PurePosixPath(name)
    need(str(path) == name and not path.is_absolute() and '..' not in path.parts and '\\' not in name,
         'invalid relative source path')
    target = root / name
    need(target.is_file() and not root.is_symlink() and
         all(not p.is_symlink() for p in [target, *target.parents] if p != root.parent),
         'missing or symlink source: ' + name)
    need(target.resolve().is_relative_to(root.resolve()), 'source escapes root')
    return target


def read_receipt(source):
    path = safe_file(source, RECEIPT_PATH)
    need(sha(path) == RECEIPT_SHA256, 'public receipt identity changed')
    value = json.loads(path.read_text())
    need(set(value) == FIELDS and value['schema'] == 'valence-eager-prefix-public-qualification-v1', 'public receipt schema changed')
    need((value['baseline_commit'], value['baseline_tree'], value['tested_candidate_tree']) ==
         (BASE, BASE_TREE, TESTED_TREE), 'tested source identity changed')
    return value


def check_closure(source, closure, scopes, projection=None):
    need(closure['scope'] == scopes, 'source closure scope changed')
    actual = {p.relative_to(source).as_posix(): sha(safe_file(source, p.relative_to(source).as_posix()))
              for folder in scopes for p in sorted((source / folder).rglob('*'))
              if p.is_file() and (scopes != SCALA or p.suffix == '.scala')}
    if projection is not None:
        actual = projection(actual)
    need(len(actual) == closure['file_count'] and digest(actual) == closure['canonical_sha256'], 'source closure bytes changed')
    return len(actual)


def check_record(value):
    record = value['recorded_qualification']
    need(record['status'] == 'PASS_COMBINED_EAGER_PREFIX_QUALIFICATION' and record['physical_qualification'] is False
         and all(record[k] == 'NOT_RUN' for k in ('actual_netlist', 'STA', 'mapped_resources'))
         and record['network_concurrency_qualification'] is False, 'recorded qualification scope changed')
    need(record['new_pipeline_cycles'] == record['new_prf_ports'] == 0, 'recorded cycle/port scope changed')
    cpu, native, nemu, component, config = (record[k] for k in ('cpu', 'native', 'nemu', 'component', 'config'))
    need(cpu['inclusive_cycles'] == {'sv39': 191618, 'bare': 194153} and cpu['functional_fields_per_case'] == 105
         and cpu['equal_result_sections_per_case'] == 12 and cpu['inclusive_roi_tail_deltas'] == [0, 0, 0]
         and cpu['raw_axi_supply_exact'] is True and cpu['complete_stdout_exact'] is True, 'recorded CPU result changed')
    need(cpu['negative_controls'] == ['read', 'memory', 'trap'] and
         (cpu['fresh_on_models'], cpu['off_models'], cpu['model_translation_units'], cpu['compiler_jobs']) == (1, 0, 36, 1),
         'recorded CPU run scope changed')
    need(native['module_count'] == 239 and native['changed_modules'] == ['RegisteredFetchPacket.sv']
         and native['other_modules_byte_identical'] == 238 and native['all_module_ports_identical'] is True
         and native['all_declared_state_identical'] is True, 'recorded native result changed')
    need(native['removed_small_prefix_sums'] == 1 and native['removed_offset_decode_comparisons'] == 4
         and native['removed_indexed_64bit_selectors'] == 1 and native['removed_selector_inputs'] == 4
         and native['removed_selector_conditional_levels'] == 4
         and native['wide_masks_before_after'] == [3, 5] and native['wide_or_joins_before_after'] == [2, 4],
         'recorded topology tradeoff changed')
    need(nemu['same_cpu_object_count'] == 36 and nemu['case_cycles'] == {'hot': 1847, 'compressed': 958}
         and nemu['negative_control_exits'] == {'pc': 1, 'gpr': 1, 'memory': 1}
         and nemu['zero_work'] == {'dut_generations': 0, 'dut_object_compiles': 0, 'reference_builds': 0, 'state_resynchronizations': 0},
         'recorded NEMU result changed')
    need(component == {'whole_cycle_observations': 4140, 'whole_cycle_off_on_exact': True,
                       'negative_controls': 14, 'native_state_port_delta': 0}, 'recorded component scope changed')
    need(config == {'unfiltered_production_scala': 199, 'unfiltered_test_scala': 343, 'hardfloat_scala': 18,
                   'focused_scala_tests': 37, 'python_profile_tests': 15}, 'recorded compile/config scope changed')
    bridge = value['default52_bridge']
    need(bridge['historical_receipt_path'] == HISTORICAL_RECEIPT and bridge['historical_receipt_sha256'] == HISTORICAL_SHA256
         and bridge['new_off_cpu_runs'] == 0 and bridge['raw_native_byte_identical'] is False
         and bridge['exact_residual_identical'] is True and bridge['automatic_local_declarations'] == 2
         and bridge['all_other_modules_byte_identical'] == 238 and bridge['source_only_entry_rebind'] is True,
         'default52 historical/native bridge changed')


def check(source, external=None):
    source = source.resolve()
    value = read_receipt(source)
    fingerprints = value['source_fingerprints']
    need(len(fingerprints) == SOURCE_COUNT and digest(sorted(fingerprints)) == SOURCE_SET_SHA256, 'necessary source set changed')
    # The immutable receipt describes tested bytes. The pinned entry manifest
    # preserves the historical receipt. A separate exact future-Home source
    # projection identifies new source; this does not rerun the historical DUT.
    spec = importlib.util.spec_from_file_location('checked_optional53', source / 'fpga/next/board_eager_prefix.py')
    entry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(entry)
    final, profile, recorded = entry.load_profile()
    bridge = profile['source_only_entry_contract_bridge']
    future_module, future_bridge = final.future_source_bridge(profile)
    project = lambda values: future_module.project(values, future_bridge)
    for name, expected in fingerprints.items():
        if name in bridge['changed_python_sources']:
            identity = bridge['changed_python_sources'][name]
            need(expected == identity['qualified_sha256'], 'entry source bridge qualified fingerprint changed: ' + name)
            expected = identity['current_sha256']
        need(re.fullmatch(r'[0-9a-f]{64}', expected) is not None and project({name: sha(safe_file(source, name))}).get(name) == expected,
             'necessary source fingerprint changed: ' + name)
    production_count = check_closure(source, value['production_source_closure'], PRODUCTION, project)
    scala_count = check_closure(source, value['qualified_scala_source_closure'], SCALA, project)
    need(sha(safe_file(source, HISTORICAL_RECEIPT)) == HISTORICAL_SHA256, 'historical52 receipt bytes changed')
    check_record(value)
    config = value['configuration']
    base = json.loads(safe_file(source, 'fpga/next/timing-batch-owner-row-profile.json').read_text())['native_options']
    need(len(base) == 52 and config['native_options'] == base + ['--eager-fetch-prefix-select']
         and len(set(config['native_options'])) == 53, 'exact52 to optional53 option extension changed')
    need(config['constructor_counts'] == {'OooParams': 159, 'FpgaNextConfig': 71, 'DdrBridgeConfig': 9, 'CoherentCacheConcurrency': 22}
         and config['fixture_overrides'] == {} and config['native_mac_t1'] is True and config['jtag_user_chain'] == 2,
         'recorded product constructor changed')
    need(config['actual_eager_prefix'] == {'schema': 'actual-eager-prefix-v1', 'eagerFetchPrefixSelect': True,
          'alignedPermissionStage': True, 'selectedPacketEagerPrefixSelect': True}, 'actual packet constructor changed')
    for name in ('OooParams.scala', 'FpgaNextConfig.scala'):
        need(re.search(r'eagerFetchPrefixSelect:\s*Boolean\s*=\s*false', safe_file(source, 'src/main/scala/core/ooo/' + name).read_text()) is not None,
             'generic default changed')
    need(entry.RECEIPT_SHA256 == RECEIPT_SHA256 and recorded == value, 'entry public receipt binding changed')
    need(profile['qualification_receipt']['sha256'] == HISTORICAL_SHA256 and profile['native_options'] == base + ['--native-mac-local-pad-reset-release'],
         'default52 options/receipt changed')
    with tempfile.TemporaryDirectory(prefix='valence-optional-source-') as directory:
        absent = Path(directory) / 'must-remain-absent'
        with contextlib.redirect_stdout(io.StringIO()) as stream:
            final.main(['--output', str(absent)])
        off = json.loads(stream.getvalue())
        with contextlib.redirect_stdout(io.StringIO()) as stream:
            entry.main(['--output', str(absent)])
        on = json.loads(stream.getvalue())
        need(not absent.exists() and off['status'] == on['status'] == 'PREFLIGHT_ONLY', 'preflight produced unexpected output')
    need(sorted(off['command'][5:]) == sorted(base) and sorted(on['command'][5:]) == sorted(config['native_options'])
         and on['native_mac_mode'] == off['native_mac_mode'] == profile['mode']
         and final.digest(on['configuration']) == config['export_profile_sha256']
         and final.digest(off['configuration']) == config['default_export_profile_sha256'], 'source-only entry configuration bridge changed')
    restored = copy.deepcopy(on['configuration'])
    need(restored.pop('eager_fetch_prefix_select') is True and off['eager_fetch_prefix_select'] is False,
         'optional enable/default disable changed')
    restored['name'] = restored['name'].replace('-eager-fetch-prefix-select', '')
    need(restored == off['configuration'], 'optional53 changed another export configuration field')
    verified = []
    for role, path in (external or {}).items():
        need(role in value['external_evidence'] and sha(path) == value['external_evidence'][role]['sha256'],
             'external bundle content hash changed: ' + role)
        verified.append(role)
    return {'status': 'PASS_PUBLIC_RECEIPT_AND_LOCAL_SOURCE_CONFIG_SUBSET', 'receipt_sha256': RECEIPT_SHA256,
            'locally_checked_source_fingerprints': len(fingerprints), 'production_source_files': production_count,
            'qualified_scala_source_files': scala_count, 'default_native_option_count': 52, 'optional_native_option_count': 53,
            'physical_T1_option_count': 1, 'full_qualification_reexecuted': False, 'default52_cpu_rerun': False,
            'source_only_entry_contract_bridge': bridge['status'],
            'source_only_future_home_bridge': 'EXACT_CURRENT_TO_B1BB_HASH_PROJECTION',
            'current_scala_source_files': future_bridge['closures']['scala']['current_file_count'],
            'historical_qualification_reexecuted': False,
            'source_only_changed_python_files': sorted(bridge['changed_python_sources']),
            'newly_export_bound_tested_helpers': sorted(bridge['newly_export_bound_helpers']),
            'external_bundles_hash_verified': sorted(verified),
            'external_unverified_references': sorted(set(value['external_evidence']) - set(verified)),
            'synthesis_consumer_executed': False, 'physical_qualification': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--source', type=Path, default=SOURCE)
    parser.add_argument('--external', action='append', default=[], metavar='ROLE=FILE')
    args = parser.parse_args()
    external = {}
    for item in args.external:
        role, path = item.split('=', 1)
        need(role not in external, 'duplicate external role')
        external[role] = Path(path)
    print(json.dumps(check(args.source, external), indent=2))


if __name__ == '__main__':
    main()
