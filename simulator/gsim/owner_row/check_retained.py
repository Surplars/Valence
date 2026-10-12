#!/usr/bin/env python3
"""Check the final52 public receipt and current source/configuration; never rerun hardware."""
import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path, PurePosixPath
import re
import tempfile

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[2]
RECEIPT_PATH = 'simulator/gsim/owner_row/evidence/public-receipt.json'
RECEIPT_SHA256 = '9e3012abadb499e753a3c2d7caf7c719049dc012aed5e1cdb442300936b1eada'
BASE = '3fcfaf6d63b0bfa628f51856644678fcb5639928'
BASE_TREE = 'fdaad0fbf9d101df8ddfb2f6f8858980753dfcc1'
QUALIFIED_TREE = '6a4d8f4c87a314757e07b1928ce9afe6d5ac3280'
SOURCE_SET_SHA256 = 'bbfb2232c32c157d5ba1946d6bdbd31cb046266d0a0516ec42474cc909c22e99'
SOURCE_COUNT = 35
FIELDS = {'schema', 'baseline_commit', 'baseline_tree', 'qualified_candidate_tree', 'verification_scope',
          'recorded_qualification', 'configuration', 'source_fingerprints', 'production_source_closure',
          'qualified_scala_source_closure', 'full_receipt_sha256', 'external_evidence', 'prior_failures_and_limits'}
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
    need(str(path) == name and not path.is_absolute() and '..' not in path.parts, 'invalid relative source path')
    target = root / name
    need(target.is_file() and all(not p.is_symlink() for p in [target, *target.parents] if p != root.parent),
         'missing or symlink source: ' + name)
    need(target.resolve().is_relative_to(root.resolve()), 'source escapes root')
    return target

def read_receipt(source):
    path = safe_file(source, RECEIPT_PATH)
    need(sha(path) == RECEIPT_SHA256, 'public receipt identity changed')
    value = json.loads(path.read_text())
    need(set(value) == FIELDS and value['schema'] == 'valence-owner-row-public-qualification-v1', 'public receipt schema changed')
    need((value['baseline_commit'], value['baseline_tree'], value['qualified_candidate_tree']) ==
         (BASE, BASE_TREE, QUALIFIED_TREE), 'qualified source identity changed')
    return value

def check_closure(source, closure, scopes):
    need(closure['scope'] == scopes, 'source closure scope changed')
    actual = {p.relative_to(source).as_posix(): sha(safe_file(source, p.relative_to(source).as_posix()))
              for folder in scopes for p in sorted((source / folder).rglob('*')) if p.is_file() and (scopes != SCALA or p.suffix == '.scala')}
    need(len(actual) == closure['file_count'] and digest(actual) == closure['canonical_sha256'], 'source closure bytes changed')
    return len(actual)

def check(source, external=None):
    source = source.resolve()
    value = read_receipt(source)
    fingerprints = value['source_fingerprints']
    need(len(fingerprints) == SOURCE_COUNT and digest(sorted(fingerprints)) == SOURCE_SET_SHA256, 'necessary source set changed')
    for name, expected in fingerprints.items():
        need(re.fullmatch(r'[0-9a-f]{64}', expected) is not None and sha(safe_file(source, name)) == expected,
             'necessary source fingerprint changed: ' + name)
    production_count = check_closure(source, value['production_source_closure'], PRODUCTION)
    scala_count = check_closure(source, value['qualified_scala_source_closure'], SCALA)
    record = value['recorded_qualification']
    need(record['status'] == 'PASS_COMBINED_OWNER_ROW_QUALIFICATION' and record['physical_qualification'] is False
         and all(record[k] == 'NOT_RUN' for k in ('actual_netlist', 'STA', 'mapped_resources'))
         and record['network_concurrency_qualification'] is False, 'recorded qualification scope changed')
    need(record['new_pipeline_cycles'] == record['new_prf_ports'] == 0, 'recorded cycle/port scope changed')
    cpu, native, nemu = (record[k] for k in ('cpu', 'native', 'nemu'))
    need(cpu['inclusive_cycles'] == {'sv39': 191618, 'bare': 194153} and cpu['functional_fields_per_case'] == 105
         and cpu['equal_result_sections_per_case'] == 12 and cpu['inclusive_roi_tail_deltas'] == [0, 0, 0]
         and cpu['raw_axi_supply_exact'] is True and cpu['complete_stdout_exact'] is True, 'recorded CPU result changed')
    need(cpu['negative_controls'] == ['read', 'memory', 'trap'] and
         (cpu['fresh_on_models'], cpu['off_models'], cpu['model_translation_units'], cpu['compiler_jobs']) == (1, 0, 36, 1),
         'recorded CPU run scope changed')
    need(native['module_count'] == 239 and native['changed_modules'] == ['IntegerBackend.sv', 'TileLinkAxi4BurstBridge.sv']
         and native['all_module_ports_identical'] is True and native['all_declared_state_identical'] is True
         and native['removed_consumer_full_token_comparisons'] == 16 and native['upper_row_connections_per_slot'] == 7
         and native['actual_slots'] == 4 and native['bank0_data_write_enable_unchanged'] is True, 'recorded native result changed')
    need(nemu['same_cpu_object_count'] == 36 and nemu['case_cycles'] == {'hot': 1847, 'compressed': 958}
         and nemu['negative_control_exits'] == {'pc': 1, 'gpr': 1, 'memory': 1}
         and nemu['zero_work'] == {'dut_generations': 0, 'dut_object_compiles': 0, 'reference_builds': 0, 'state_resynchronizations': 0},
         'recorded NEMU result changed')
    config = value['configuration']
    old = json.loads(safe_file(source, 'fpga/next/timing-batch-zero-cycle-cleanup-profile.json').read_text())['native_options']
    options = config['native_options']
    need(len(old) == 50 and options == old + ['--shared-canonical-store-owner-match', '--local-payload-write-row']
         and len(set(options)) == 52, 'exact final50 option extension changed')
    need(config['constructor_counts'] == {'OooParams': 158, 'FpgaNextConfig': 70, 'DdrBridgeConfig': 9, 'CoherentCacheConcurrency': 22}
         and config['fixture_overrides'] == {} and config['native_mac_t1'] is True and config['jtag_user_chain'] == 2,
         'recorded product constructor changed')
    owner = config['actual_owner_row']
    need(owner['sharedCanonicalStoreOwnerMatch'] is True and owner['slotCount'] == len(owner['slots']) == 4
         and all(row['localPayloadWriteRow'] is True and row['localPayloadWriteEnable'] is True and row['lineReadChannel'] is True
                 for row in [owner['wrapper'], owner['manager'], *owner['slots']]), 'actual owner/slot forwarding changed')
    for name, field in [('OooParams.scala', 'sharedCanonicalStoreOwnerMatch'), ('DdrBridgeConfig.scala', 'localPayloadWriteRow')]:
        need(re.search(field + r':\s*Boolean\s*=\s*false', safe_file(source, 'src/main/scala/core/ooo/' + name).read_text()) is not None,
             'generic default changed')
    spec = importlib.util.spec_from_file_location('checked_final52_entry', source / 'fpga/next/board_final.py')
    final = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(final)
    profile = final.load_profile()
    need(profile['qualification_receipt']['sha256'] == RECEIPT_SHA256 and profile['native_options'] ==
         options + ['--native-mac-local-pad-reset-release'], 'final52 receipt/options changed')
    with tempfile.TemporaryDirectory(prefix='valence-source-check-') as directory:
        absent = Path(directory) / 'must-remain-absent'
        with contextlib.redirect_stdout(io.StringIO()) as stream:
            final.main(['--output', str(absent)])
        preflight = json.loads(stream.getvalue())
        need(not absent.exists() and preflight['status'] == 'PREFLIGHT_ONLY', 'preflight produced unexpected output')
    need(sorted(preflight['command'][5:]) == sorted(options) and preflight['native_mac_mode'] == profile['mode']
         and final.digest(preflight['configuration']) == config['export_profile_sha256'], 'local configuration bridge changed')
    expected = {'cpu_hz': 100000000, 'issue_width': 2, 'rob_entries': 16, 'physical_registers': 48, 'lsu_entries': 4,
                'data_translation_entries': 16, 'instruction_translation_entries': 8, 'pte_cache_entries': 4,
                'instruction_cache_lines': 512, 'data_cache_lines': 512, 'cache_ways': 2, 'cache_read_mshrs': 2,
                'cache_response_entries': 2, 'cache_writeback_entries': 2, 'pending_virtual_store_proof_slots': 2,
                'pending_store_early_load_credits': 2, 'ddr_bytes': 2147483648, 'bscan_chain': 2,
                'experimental_trispeed_ethernet': True, 'shared_canonical_store_owner_match': True, 'local_payload_write_row': True}
    need(all(preflight['configuration'].get(k) == v for k, v in expected.items()), 'product preflight parameters changed')
    verified = []
    for role, path in (external or {}).items():
        need(role in value['external_evidence'] and sha(path) == value['external_evidence'][role]['sha256'],
             'external bundle content hash changed: ' + role)
        verified.append(role)
    return {'status': 'PASS_PUBLIC_RECEIPT_AND_LOCAL_SOURCE_CONFIG_SUBSET', 'receipt_sha256': RECEIPT_SHA256,
            'locally_checked_source_fingerprints': len(fingerprints), 'production_source_files': production_count,
            'qualified_scala_source_files': scala_count, 'native_option_count': 52, 'physical_T1_option_count': 1,
            'recorded_qualification_status': record['status'], 'full_qualification_reexecuted': False,
            'external_bundles_hash_verified': sorted(verified),
            'external_unverified_references': sorted(set(value['external_evidence']) - set(verified)),
            'synthesis_consumer_executed': False, 'physical_qualification': False}

def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--source', type=Path, default=SOURCE)
    parser.add_argument('--external', action='append', default=[], metavar='ROLE=FILE', help='Verify the exact referenced bundle bytes, without executing it')
    args = parser.parse_args()
    external = {}
    for item in args.external:
        role, path = item.split('=', 1)
        need(role not in external, 'duplicate external role')
        external[role] = Path(path)
    print(json.dumps(check(args.source, external), indent=2))

if __name__ == '__main__':
    main()
