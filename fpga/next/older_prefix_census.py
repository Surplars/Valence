#!/usr/bin/env python3
"""Source-bound literal storage proxy for the exact LSU4 older-prefix OFF/ON pair.

This reuses the fail-closed flat-firtool grammar and fresh fixed-storage checker.
It does not estimate LUT count, physical fanout, critical path, or routed timing.
"""
import argparse
import json
from pathlib import Path

import lsu_capacity_census as base
import export as native_export


def expected_profile(enabled):
    """The complete selected experiment, not just equality between two exports."""
    profile = json.loads((Path(__file__).with_name('baseline.json')).read_text())['profile']
    profile.update({
        'name': 'fpga-next-selected-v2-physical-ingress-flow-lsu4' +
                ('-older-load-retire' if enabled else '') + '-dma-lines-owners4',
        'lsu_entries': 4, 'load_order_older_retire': enabled,
        'physical_load_ingress_flow': True, 'virtual_ram_load_precheck': False,
        'prechecked_data_flow': False, 'prefetch_candidate_cycles': 1,
        'prefetch_break_on_store': False, 'experimental_trispeed_ethernet': False,
        'tri_speed_tx_frame_slots': 1, 'dma_line_transfers': True,
        'dma_line_entries': 4, 'dma_line_yield_cycles': 0,
        'jtag_pins_reserved': True, 'jtag_transport_experimental': False,
        'jtag_ram_download': False, 'jtag_backend': 'standalone-dtm',
        'bscan_chain': None, 'debug_module_implemented': False,
    })
    for name in ('independent_fetch_payload_capture', 'owner_local_issue_ready',
                 'shared_fetch_pmp_relations', 'share_protected_head_payload',
                 'banked_instruction_data', 'banked_issue_payload', 'banked_fetch_hints',
                 'fp_state_ram', 'fp_shared_rounders', 'banked_cache_tags', 'fp_shared_product'):
        profile[name] = True
    return profile


def validate_pair(a, b):
    require = base.require
    current_sources = native_export.sources()
    require(current_sources and a['source_sha256'] == b['source_sha256'] == current_sources,
            'native source inventories must match the complete current source set')
    for label, item, enabled in (('off', a, False), ('on', b, True)):
        profile = item['profile']
        require(profile == expected_profile(enabled), label + ' exact selected profile drift')
        require(profile['lsu_entries'] == 4, label + ' must retain four LSU owners')
        require(profile['load_order_older_retire'] is enabled, label + ' flag mismatch')
        require(profile['physical_load_ingress_flow'] is True, label + ' physical ingress must remain enabled')
        require(profile['virtual_ram_load_precheck'] is False and profile['prechecked_data_flow'] is False,
                label + ' virtual precheck profile drift')
        require(profile['dma_line_transfers'] is True and profile['dma_line_entries'] == 4 and
                profile['dma_line_yield_cycles'] == 0, label + ' DMA profile drift')
    ignored = {'name', 'load_order_older_retire'}
    require({k: v for k, v in a['profile'].items() if k not in ignored} ==
            {k: v for k, v in b['profile'].items() if k not in ignored}, 'unrelated profile field changed')
    require(b['profile']['name'].replace('-older-load-retire', '', 1) == a['profile']['name'] and
            b['profile']['name'].count('-older-load-retire') == 1, 'profile name/flag mismatch')
    require(set(a['scopes']) == set(b['scopes']), 'reachable scope inventory differs')
    for scope in a['scopes']:
        require(a['scopes'][scope]['excluded_external_instances'] ==
                b['scopes'][scope]['excluded_external_instances'], 'external IP multiplicity changed')
    for wrapper in ('InstructionRom', 'ManagedClockBuffer'):
        require(a['modules'][wrapper]['sha256'] == b['modules'][wrapper]['sha256'],
                'external IP wrapper changed: ' + wrapper)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--off', type=Path, required=True)
    ap.add_argument('--on', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    tools = [Path(__file__), Path(base.__file__), Path(base.__file__).with_name('native_storage_census.py'),
             Path(native_export.__file__), Path(__file__).with_name('baseline.json')]
    tool_hashes = {path.name: base.sha(path) for path in tools}
    exports = {'off': base.census(args.off), 'on': base.census(args.on)}
    validate_pair(exports['off'], exports['on'])
    storage = {}
    for label, directory in (('off', args.off), ('on', args.on)):
        row = base.fresh_storage(directory)
        export = exports[label]
        base.require(row['status'] == 'PASS_SELECTED_NATIVE_STORAGE_CENSUS' and
                     row['export_receipt_sha256'] == export['receipt_sha256'], 'fixed-storage export mismatch')
        base.require(len(row['groups']) == 10, 'fixed-storage group inventory mismatch')
        for group in row['groups'].values():
            base.require(group['parent_sha256'] == export['modules'][group['parent']]['sha256'],
                         'fixed-storage parent changed')
            for bank in group['banks']:
                base.require(bank['helper_sha256'] == export['modules'][bank['module']]['sha256'],
                             'fixed-storage helper changed')
        storage[label] = row
    base.require(storage['off']['groups'] == storage['on']['groups'], 'fixed-storage groups changed')
    a, b = exports['off'], exports['on']
    result = {
        'status': 'PASS_LITERAL_REACHABLE_OLDER_PREFIX_CENSUS',
        'tools': tool_hashes, 'exports': exports, 'fresh_fixed_storage_runs': 2,
        'fixed_storage': storage,
        'delta': {scope: {kind: b['scopes'][scope][kind] - a['scopes'][scope][kind]
                          for kind in ('scalar_reg_bits', 'array_reg_bits')} for scope in a['scopes']},
        'retirement_modules': {name: {label: {kind: exports[label]['modules'][name][kind]
                                             for kind in ('sha256', 'scalar_reg_bits', 'array_reg_bits')}
                                     for label in exports} for name in ('IntegerBackend', 'RenameRob')},
        'limits': [
            'Literal reachable register declarations weighted by explicit emitted hierarchy, not mapped resources.',
            'Register arrays may map to FF, LUTRAM, BRAM or be optimized away.',
            'External ROM and clock primitive state excluded; wrapper hashes and multiplicities must match.',
            'No mapped LUT/FF/BRAM, 100 MHz timing, FPGA or board qualification.',
        ],
    }
    for label, directory in (('off', args.off), ('on', args.on)):
        base.require(base.census(directory) == exports[label], 'native export changed during census')
    validate_pair(exports['off'], exports['on'])
    base.require({path.name: base.sha(path) for path in tools} == tool_hashes, 'census tool changed')
    base.require(not args.out.exists(), 'refusing to overwrite an existing receipt')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + '\n')
    print(result['status'], json.dumps(result['delta']))


if __name__ == '__main__':
    main()
