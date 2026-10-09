#!/usr/bin/env python3
"""Source-bound native RTL declarations and raw fetch mux cone, never FPGA PPA.

Read only completed OFF/ON exports. Reuse the strict flat-firtool declaration,
hierarchy and fixed-storage parsers without their older-prefix/LSU2 profiles.
No elaboration, simulation, synthesis or full-FIR evidence is used.
"""
import argparse
import copy
import json
from pathlib import Path
import re
import subprocess

import export as native_export
import lsu_capacity_census as base

PRODUCTION_COMMIT = '2288c7f008e9d6440e8a28e339da28152b54892a'
WINDOW = 'RegisteredFetchWindow'
FIELDS = ('data', 'accessFaults', 'pageFaults')
KINDS = ('scalar_reg_bits', 'array_reg_bits')
require = base.require


def expected_profile(enabled):
    profile = json.loads(Path(__file__).with_name('baseline.json').read_text())['profile']
    profile.update({
        'name': 'fpga-next-selected-v2-physical-ingress-flow-lsu4' +
                ('-fetch-previous-packet' if enabled else '') + '-dma-lines-owners4',
        'lsu_entries': 4, 'load_order_older_retire': False,
        'fetch_previous_packet': enabled, 'physical_load_ingress_flow': True,
        'virtual_ram_load_precheck': False, 'prechecked_data_flow': False,
        'prefetch_candidate_cycles': 1, 'prefetch_break_on_store': False,
        'experimental_trispeed_ethernet': False, 'tri_speed_tx_frame_slots': 1,
        'dma_line_transfers': True, 'dma_line_entries': 4, 'dma_line_yield_cycles': 0,
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


def validate_pair(exports):
    a, b = exports['off'], exports['on']
    current = native_export.sources()
    require(current and a['source_sha256'] == b['source_sha256'] == current,
            'complete current production source inventory mismatch')
    for label, enabled in (('off', False), ('on', True)):
        require(exports[label]['profile'] == expected_profile(enabled),
                label + ' exact fetch-history profile mismatch')
    require(set(a['modules']) == set(b['modules']), 'emitted module inventory changed')
    changed = [name for name in a['modules']
               if a['modules'][name]['sha256'] != b['modules'][name]['sha256']]
    require(changed == [WINDOW], 'unexpected changed native modules: ' + str(changed))
    for scope in a['scopes']:
        for key in ('instances', 'excluded_external_instances'):
            require(a['scopes'][scope][key] == b['scopes'][scope][key],
                    scope + ' reachable hierarchy/external multiplicity changed')
    require(a['scopes']['BoardSocTop']['instances'].get(WINDOW) == 1,
            'expected one reachable registered fetch window')
    for name in a['modules']:
        require(a['modules'][name]['children'] == b['modules'][name]['children'],
                name + ' structural children changed')
    return changed


def compact(text):
    return re.sub(r'\s+', '', text)


def window_model(raw):
    """Bounded dependency graph: continuous expressions, inputs and flop leaves.

    The window has no children or combinational procedural blocks. Stop at
    registers deliberately: this proves a combinational cone, not a sequential
    noninterference property. Reject unresolved identifiers and cone cycles.
    """
    text = base.strip(raw)
    base.declarations(text)
    require(base.structural_instances(text, {WINDOW}) == [], 'window gained children')
    require(re.findall(r'\balways\s*@\s*\(([^)]*)\)', text) == ['posedge clock'] and
            not re.search(r'\binitial\b', text), 'unexpected window procedural structure')
    regs = {}
    for high, low, name in re.findall(r'\breg\s*(?:\[(\d+):(\d+)\]\s*)?(\w+)\s*;', text):
        require(name not in regs, 'duplicate register')
        regs[name] = abs(int(high) - int(low)) + 1 if high else 1
    require(sum(regs.values()) == base.declarations(text)['scalar_reg_bits'],
            'window scalar grammar not fully consumed')
    header = re.search(r'\bmodule\s+RegisteredFetchWindow\s*\((.*?)\);', text, re.S)
    require(header is not None, 'missing window header')
    inputs, outputs, direction = set(), set(), None
    for part in header[1].split(','):
        m = re.match(r'\s*(input|output)\b', part)
        if m:
            direction = m[1]
        names = re.findall(r'[A-Za-z_][A-Za-z_0-9]*', part)
        require(direction is not None and names, 'unsupported window port')
        (inputs if direction == 'input' else outputs).add(names[-1])
    graph = {}
    for name, rhs in re.findall(r'\bwire\s*(?:\[\d+:\d+\]\s*)?(\w+)\s*=\s*([^;]+);', text):
        require(name not in graph, 'duplicate wire driver')
        graph[name] = rhs
    require(len(graph) == len(re.findall(r'\bwire\b', text)), 'unconsumed wire declaration')
    for name, rhs in re.findall(r'\bassign\s+(\w+)\s*=\s*([^;]+);', text):
        require(name in outputs and name not in graph, 'unexpected continuous driver')
        graph[name] = rhs
    require(outputs <= set(graph), 'undriven window output')

    def leaves(name, stack=()):
        require(name not in stack, 'combinational cycle')
        if name in regs or name in inputs:
            return {name}
        require(name in graph, 'unresolved combinational identifier: ' + name)
        rhs = re.sub(r"\b\d+'[sS]?[bBoOdDhH][0-9a-fA-F_xXzZ?]+", '', graph[name])
        result = set()
        for dep in re.findall(r'\b[A-Za-z_][A-Za-z_0-9]*\b', rhs):
            result |= leaves(dep, stack + (name,))
        return result

    cones = {name: sorted(leaves(name)) for name in sorted(outputs)}
    for name, deps in cones.items():
        if '_bits_' in name:
            require(set(deps) <= set(regs) | {'io_readBase', 'io_readContext'},
                    'raw payload combinational cone includes invalidate/query/reset: ' + name)
        else:
            require('io_invalidate' in deps, 'validity lost immediate invalidate')
    updates = {}
    for name, rhs in re.findall(r'\b(\w+)\s*<=\s*([^;]+);', text):
        require(name in regs, 'unknown sequential target')
        updates.setdefault(name, []).append(compact(rhs))
    require(set(updates) == set(regs), 'unassigned window register')
    return {'regs': regs, 'graph': {k: compact(v) for k, v in graph.items()},
            'output_cone_leaves': cones, 'updates': updates}


def validate_window_pair(a, b):
    added = {k: v for k, v in b['regs'].items() if k not in a['regs']}
    require(added == {'history_1_data': 64, 'history_1_accessFaults': 2,
                     'history_1_pageFaults': 2, 'history_2': 61, 'history_3': 3, 'history_4': 1},
            'unexpected history register declarations')
    require(all(b['regs'].get(k) == v and b['updates'][k] == a['updates'][k]
                for k, v in a['regs'].items()), 'pre-existing window state changed')
    expected_updates = {
        'history_1_data': ['contents_0_data'],
        'history_1_accessFaults': ['contents_0_accessFaults'],
        'history_1_pageFaults': ['contents_0_pageFaults'],
        'history_2': ['{regions_1,offsets_2}'], 'history_3': ['context_0'],
        'history_4': ["1'h0", 'present_0&~io_invalidate'],
    }
    require({k: b['updates'][k] for k in added} == expected_updates,
            'history capture/invalidation expression changed')
    primary = 'keyMatches_2&present_0|keyMatches_3&present_1|keyMatches_4&present_2'
    require(b['graph']['primaryPresent'] == primary, 'primary mux selector changed')
    require(a['graph']['io_packets_0_valid'] == '~io_invalidate&(' + primary + ')',
            'OFF validity expression changed')
    require(b['graph']['io_packets_0_valid'] ==
            '~io_invalidate&(primaryPresent|history_4&history_2==io_readBase[63:3]&history_3==io_readContext)',
            'history validity/full-key/context check changed')
    for name, rhs in a['graph'].items():
        if name.startswith('io_packets_0_'):
            continue
        require(b['graph'].get(name) == rhs, 'unrelated window expression changed: ' + name)
    for field in FIELDS:
        name = 'io_packets_0_bits_' + field
        require(b['graph'][name] == 'primaryPresent?' + a['graph'][name] + ':history_1_' + field,
                'raw primary/history mux changed: ' + field)
        require(not {'history_2', 'history_3', 'history_4'} & set(b['output_cone_leaves'][name]),
                'saved-key/context/valid authorization enters raw data mux')
    return {'added_registers': added, 'added_bits': sum(added.values()),
            'unchanged_registers': len(a['regs']), 'unchanged_register_bits': sum(a['regs'].values()),
            'raw_history_mux_width_bits': sum(added['history_1_' + f] for f in FIELDS),
            'raw_data_mux_selector': 'primaryPresent',
            'off': a, 'on': b}


def representative_negatives(exports, raw_on):
    tests = []
    bad = copy.deepcopy(exports)
    bad['on']['profile']['load_order_older_retire'] = True
    cases = [('unrelated_older_prefix_profile_change', lambda: validate_pair(bad)),
             ('invalidate_in_raw_data_mux', lambda: window_model(raw_on.replace(
                 'assign io_packets_0_bits_data =',
                 'assign io_packets_0_bits_data = io_invalidate ? 64\'h0 :', 1)))]
    for name, action in cases:
        try:
            action()
        except RuntimeError as error:
            tests.append({'case': name, 'status': 'REJECTED', 'reason': str(error)})
        else:
            raise RuntimeError('checker negative unexpectedly accepted: ' + name)
    return tests


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--off', type=Path, required=True)
    ap.add_argument('--on', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    require(not args.out.exists(), 'refusing to overwrite an existing receipt')
    tools = [Path(__file__), Path(base.__file__), Path(base.__file__).with_name('native_storage_census.py'),
             Path(native_export.__file__), Path(__file__).with_name('baseline.json')]
    hashes = {p.name: base.sha(p) for p in tools}
    directories = {'off': args.off, 'on': args.on}
    exports = {label: base.census(path) for label, path in directories.items()}
    changed = validate_pair(exports)
    bindings = {}
    for label, path in directories.items():
        receipt = json.loads((path / 'receipt.json').read_text())
        require(receipt['git_head'] == PRODUCTION_COMMIT, 'unexpected production export revision')
        require(receipt['synthesis'] is False and receipt['physical_qualification'] is False,
                'unexpected export evidence class')
        require(base.sha(path / 'synthesis-files.f') == receipt['synthesis_filelist_sha256'],
                'synthesis filelist drift')
        expected_flags = ['--selected', '--dma-line-transfers', '--dma-line-entries=4',
                          '--lsu-entries=4', '--physical-load-ingress-flow']
        if label == 'on':
            expected_flags += ['--fetch-previous-packet']
        require(receipt['command'][:4] == ['mill', '-i', 'IonSoC.test.runMain', 'ooo.FpgaNextMain'] and
                receipt['command'][5:] == expected_flags and
                Path(receipt['command'][4]).resolve() == (path / 'rtl').resolve(),
                'export command/profile binding mismatch')
        bindings[label] = {'directory': str(path.resolve()), 'production_commit': receipt['git_head'],
                           'export_command': receipt['command']}
    raw = {label: (path / 'rtl' / (WINDOW + '.sv')).read_text() for label, path in directories.items()}
    window = validate_window_pair(window_model(raw['off']), window_model(raw['on']))
    storage = {label: base.fresh_storage(path) for label, path in directories.items()}
    for label, row in storage.items():
        require(row['status'] == 'PASS_SELECTED_NATIVE_STORAGE_CENSUS' and
                row['export_receipt_sha256'] == exports[label]['receipt_sha256'] and
                row['source_commit'] == PRODUCTION_COMMIT and len(row['groups']) == 10,
                'fresh fixed-storage export binding mismatch')
        for group in row['groups'].values():
            require(group['parent_sha256'] == exports[label]['modules'][group['parent']]['sha256'],
                    'fixed-storage parent mismatch')
            for bank in group['banks']:
                require(bank['helper_sha256'] == exports[label]['modules'][bank['module']]['sha256'],
                        'fixed-storage helper mismatch')
    require(storage['off']['groups'] == storage['on']['groups'], 'fixed-storage groups changed')
    delta = {scope: {kind: exports['on']['scopes'][scope][kind] -
                           exports['off']['scopes'][scope][kind] for kind in KINDS}
             for scope in exports['off']['scopes']}
    require(delta['BoardSocTop'] == {'scalar_reg_bits': window['added_bits'], 'array_reg_bits': 0},
            'reachable top delta differs from measured history declarations')
    require(all(value == 0 for scope in delta if scope != 'BoardSocTop' for value in delta[scope].values()),
            'backend/LSU/store-buffer state changed')
    result = {
        'status': 'PASS_LITERAL_REACHABLE_FETCH_HISTORY_CENSUS', 'tools': hashes,
        'host_commit_at_census': subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'], cwd=native_export.ROOT, text=True).strip(),
        'bindings': bindings, 'exports': exports, 'delta': delta,
        'changed_modules': changed, 'unchanged_module_hashes': len(exports['off']['modules']) - len(changed),
        'fresh_fixed_storage_runs': 2, 'fixed_storage': storage, 'window_mux_and_state': window,
        'representative_checker_negatives': representative_negatives(exports, raw['on']),
        'limits': [
            'Literal reachable reg declarations, weighted by explicit hierarchy, not mapped FF/LUT/BRAM.',
            'Array declarations may become FF, LUTRAM, BRAM or be optimized away.',
            'External ROM and clock primitive state excluded; wrappers and multiplicities are unchanged.',
            'Raw payload cone stops at registers; it proves no same-cycle invalidate/query/reset path.',
            'History has a measured 68-bit raw mux; this is not a LUT, delay, fanout or Fmax estimate.',
            'No compile, export, simulation, synthesis, routed timing, board or bitstream run.',
        ],
    }
    for label, path in directories.items():
        require(base.census(path) == exports[label], 'export changed during census')
    validate_pair(exports)
    require({p.name: base.sha(p) for p in tools} == hashes, 'census tools changed during run')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('x') as handle:
        handle.write(json.dumps(result, indent=2) + '\n')
    print(result['status'], json.dumps(delta))


if __name__ == '__main__':
    main()
