#!/usr/bin/env python3
"""Bind three completed native exports and census composed history/older-prefix.

Literal reachable state and exact changed-expression checks, never mapped PPA.
No compile, export, simulation, synthesis, or old LSU2 profile is involved.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import subprocess

import export as native_export
import fetch_history_census as history
import lsu_capacity_census as base

require = base.require
compact = history.compact
PRODUCTION = history.PRODUCTION_COMMIT
LABELS = ('both_off', 'history_only', 'both_on')
PREFIX_MODULES = ['IntegerBackend', 'RenameRob']
KINDS = history.KINDS


def expected_profile(label):
    require(label in LABELS, 'unknown profile')
    profile = history.expected_profile(label != 'both_off')
    if label == 'both_on':
        profile['load_order_older_retire'] = True
        profile['name'] = profile['name'].replace('-fetch-previous-packet',
                                                 '-older-load-retire-fetch-previous-packet')
    return profile


def git(*args, binary=False):
    return subprocess.check_output(['git', *args], cwd=native_export.ROOT, text=not binary)


def committed_sources(revision):
    """Reconstruct export.sources() at the recorded commit, including inventory."""
    require(re.fullmatch(r'[0-9a-f]{40}', revision), 'full source revision required')
    explicit = {'build.mill', '.mill-version', 'src/test/scala/ooo/FpgaNextMain.scala',
                'fpga/next/baseline.json', 'fpga/next/export.py', 'fpga/next/soc_top_fpga_next_ddr.sv',
                'fpga/zu15eg/soc_top_gmac_ddr.sv', 'fpga/next/check_jtag_chain.tcl'}
    names = git('ls-tree', '-rz', '--name-only', revision).split('\0')
    names = sorted(name for name in names if name in explicit or
                   name.startswith(('src/main/resources/', 'fpga/next/rtl/')) or
                   (name.endswith('.scala') and name.startswith(
                       ('src/main/scala/', 'third_party/berkeley-hardfloat/src/main/scala/'))))
    result = subprocess.run(['git', 'cat-file', '--batch'], cwd=native_export.ROOT,
                            input=''.join(revision + ':' + name + '\n' for name in names).encode(),
                            stdout=subprocess.PIPE, check=True).stdout
    cursor, hashes = 0, {}
    for name in names:
        end = result.index(b'\n', cursor)
        header = result[cursor:end].split()
        require(len(header) == 3 and header[1] == b'blob', 'source is not a committed blob: ' + name)
        size = int(header[2])
        start = end + 1
        hashes[name] = hashlib.sha256(result[start:start + size]).hexdigest()
        cursor = start + size + 1
        require(result[cursor - 1:cursor] == b'\n', 'malformed source object framing')
    require(cursor == len(result) and hashes, 'incomplete committed source inventory')
    return hashes


def module_parts(raw):
    """Strict ANSI header grammar; count body state separately from I/O signals."""
    text = base.strip(raw)
    header = re.match(r'\s*module\s+(\w+)\s*\((.*?)\);', text, re.S)
    require(header is not None, 'unsupported native header')
    ports, direction, width = {}, None, None
    for part in header[2].split(','):
        if not part.strip():
            require(not header[2].strip(), 'empty native port')
            continue
        match = re.fullmatch(r'\s*(?:(input|output)\s*(?:\[(\d+):(\d+)\]\s*)?)?(\w+)\s*', part)
        require(match is not None, 'unsupported native port declaration: ' + part)
        if match[1]:
            direction = match[1]
            width = abs(int(match[2]) - int(match[3])) + 1 if match[2] else 1
        require(direction is not None and match[4] not in ports, 'untyped or duplicate native port')
        ports[match[4]] = {'direction': direction, 'width': width}
    body = text[header.end():]
    require(not re.search(r'\b(?:input|output|inout)\b', body), 'non-ANSI port declaration')
    state = base.declarations(body)
    require(state == base.declarations(text), 'port counted as persistent state')
    return ports, body, state


def state_records(body):
    """Exact names/widths of scalar registers in the three changed modules."""
    records = {}
    for high, low, name in re.findall(r'\breg\s*(?:\[(\d+):(\d+)\]\s*)?(\w+)\s*;', body):
        require(name not in records, 'duplicate state declaration')
        records[name] = abs(int(high) - int(low)) + 1 if high else 1
    state = base.declarations(body)
    require(state['array_reg_bits'] == 0 and sum(records.values()) == state['scalar_reg_bits'],
            'changed-module scalar state grammar not fully consumed')
    return records


def replace_once(text, old, new, reason):
    require(text.count(old) == 1, reason)
    return text.replace(old, new, 1)


def validate_prefix(raw_off, raw_on):
    """Reverse only the reviewed native changes, then require whole-body equality.

    This rejects unrelated state, sequential conditions, instance wiring, and
    combinational path changes, even inside the two legitimately changed modules.
    It is a bounded source-expression check, not a logic/timing equivalence proof.
    """
    report = {}
    parts = {label: {name: module_parts(raw[name]) for name in PREFIX_MODULES}
             for label, raw in (('off', raw_off), ('on', raw_on))}
    for name in PREFIX_MODULES:
        a, b = parts['off'][name], parts['on'][name]
        regs_a, regs_b = state_records(a[1]), state_records(b[1])
        added = {'orderCheckTag': 64} if name == 'IntegerBackend' else {}
        require(regs_b == {**regs_a, **added} and not set(added) & set(regs_a),
                name + ' unexpected state delta')
        report[name] = {'added_registers': added, 'unchanged_scalar_registers': len(regs_a),
                        'unchanged_scalar_bits': sum(regs_a.values())}

    a, b = parts['off']['IntegerBackend'], parts['on']['IntegerBackend']
    require(a[0] == b[0], 'backend external interface changed')
    restored = compact(b[1])
    replacements = [
        ('regreplayPendingValid;', 'wirereplayRetirementHold;'),
        ('reg[63:0]orderCheckTag;', ''),
        ('reg[7:0]orderCheckLanes;', 'reg[7:0]orderCheckLanes;regreplayPendingValid;'),
        ('wirelsu_io_start_valid=',
         'assignreplayRetirementHold=orderCheckValid|replayPendingValid;wirelsu_io_start_valid='),
        ("orderCheckTag<=64'h0;", ''),
        ('if(memoryIssued)beginorderCheckIndex<=stagedMemoryIndex;'
         'orderCheckTag<=lsu_io_start_bits_token_tag;end',
         'if(memoryIssued)orderCheckIndex<=stagedMemoryIndex;'),
        ('.io_commitEnable(io_commitEnable&~branchRedirectValid&~replayPendingValid),'
         '.io_loadOrderRetireLimit_valid(orderCheckValid),'
         '.io_loadOrderRetireLimit_bits_index(orderCheckIndex),'
         '.io_loadOrderRetireLimit_bits_tag(orderCheckTag),',
         '.io_commitEnable(io_commitEnable&~branchRedirectValid&~replayRetirementHold),'),
    ]
    for old, new in replacements:
        restored = replace_once(restored, old, new, 'backend reviewed expression missing: ' + old)
    require(restored == compact(a[1]), 'backend unrelated state, condition, or path changed')

    a, b = parts['off']['RenameRob'], parts['on']['RenameRob']
    added_ports = {'io_loadOrderRetireLimit_valid': {'direction': 'input', 'width': 1},
                   'io_loadOrderRetireLimit_bits_index': {'direction': 'input', 'width': 4},
                   'io_loadOrderRetireLimit_bits_tag': {'direction': 'input', 'width': 64}}
    require(b[0] == {**a[0], **added_ports} and not set(added_ports) & set(a[0]),
            'ROB interface change is not exactly the 69 input bits')
    restored = compact(b[1])
    age = '_olderThanLoadCheck_T_6'
    authorization = '(~io_loadOrderRetireLimit_valid|{1\'h0,' + age + '}<count&' + \
        '_GEN[io_loadOrderRetireLimit_bits_index]==io_loadOrderRetireLimit_bits_tag)'
    lane0 = '(~io_loadOrderRetireLimit_valid|(|' + age + '))'
    lane1 = '(~io_loadOrderRetireLimit_valid|(|(' + age + '[3:1])))'
    replacements = [
        ('wire[3:0]' + age + '=io_loadOrderRetireLimit_bits_index-head;', ''),
        ('io_commitEnable&~recoveryCycle&' + authorization + '&(|count)&' + lane0,
         'io_commitEnable&~recoveryCycle&(|count)'),
        ("valid&_allocationPayload_io_read_0[6:0]!=7'h73&(|(count[4:1]))&" + lane1,
         "valid&_allocationPayload_io_read_0[6:0]!=7'h73&(|(count[4:1]))"),
    ]
    for old, new in replacements:
        restored = replace_once(restored, old, new, 'ROB reviewed expression missing: ' + old)
    require(restored == compact(a[1]), 'ROB unrelated state, condition, or path changed')
    tags = re.search(r'wire\[15:0\]\[63:0\]_GEN=([^;]+);', compact(b[1]))
    require(tags and tags[1] == '{' + ','.join('{entries_' + str(i) + '_tag}'
                                              for i in reversed(range(16))) + '}',
            'ROB full-tag selector geometry changed')
    report['retire_cone'] = {
        'new_input_ports_excluded_from_state_bits': 69,
        'checked_token_register_added_bits': 64,
        'existing_checked_index_bits': 4, 'existing_checked_valid_bits': 1,
        'modular_age_width_bits': 4, 'selected_existing_tag_entries': 16,
        'selected_existing_tag_width_bits': 64,
        'authorization_expression': authorization,
        'lane0_older_expression': lane0, 'lane1_older_expression': lane1,
        'description': [
            'A valid checked token must have modular (index - head) age < count and exact full 64-bit live tag.',
            'Lane 0 requires age > 0; lane 1 requires age > 1 and inherits lane 0 validity.',
            'Checked instruction and younger suffix remain blocked; a stale token blocks the whole prefix.',
            'Replay pending and branch redirect retain the global commit hold.',
            'The added 16-way 64-bit existing-tag selection/equality and 4-bit age predicates feed retire legality.',
            'This checks exact emitted expressions and unchanged surrounding logic, not delay or routed criticality.',
        ],
    }
    return report


def validate_exports(exports):
    current = native_export.sources()
    for label in LABELS:
        row = exports[label]
        require(row['source_sha256'] == current and current, label + ' current source inventory mismatch')
        require(row['profile'] == expected_profile(label), label + ' exact composed profile drift')
    changed = {}
    for before, after, expected in (
            ('both_off', 'history_only', [history.WINDOW]),
            ('history_only', 'both_on', PREFIX_MODULES),
            ('both_off', 'both_on', ['IntegerBackend', history.WINDOW, 'RenameRob'])):
        a, b = exports[before], exports[after]
        require(set(a['modules']) == set(b['modules']), 'native module inventory changed')
        names = [name for name in a['modules'] if a['modules'][name]['sha256'] != b['modules'][name]['sha256']]
        require(names == expected, 'unexpected changed native modules: ' + str(names))
        require(set(a['scopes']) == set(b['scopes']), 'reachable scope inventory changed')
        for scope in a['scopes']:
            for key in ('instances', 'excluded_external_instances'):
                require(a['scopes'][scope][key] == b['scopes'][scope][key], 'reachable hierarchy changed')
        for name in a['modules']:
            require(a['modules'][name]['children'] == b['modules'][name]['children'], name + ' children changed')
        changed[before + '_to_' + after] = names
    require(exports['both_on']['scopes']['BoardSocTop']['instances'].get(history.WINDOW) == 1,
            'expected exactly one reachable fetch window')
    return changed


def negative_checks(exports, raw):
    cases = []
    for field, value in (('lsu_entries', 2), ('fetch_previous_packet', False), ('dma_line_yield_cycles', 1)):
        bad = copy.deepcopy(exports)
        bad['both_on']['profile'][field] = value
        cases.append(('profile_drift_' + field, lambda bad=bad: validate_exports(bad)))
    bad = copy.deepcopy(exports)
    bad['both_on']['modules']['StoreBuffer']['sha256'] = '0' * 64
    cases.append(('unrelated_module_change', lambda: validate_exports(bad)))
    for name, module, old, new in (
            ('unrelated_backend_state', 'IntegerBackend', 'reg  [63:0]       orderCheckTag;',
             'reg  [63:0]       orderCheckTag; reg unrelatedState;'),
            ('unrelated_backend_path', 'IntegerBackend', 'memoryIssued & speculative;',
             'memoryIssued | speculative;'),
            ('stale_tag_authorization_bypass', 'RenameRob',
             '_GEN[io_loadOrderRetireLimit_bits_index] == io_loadOrderRetireLimit_bits_tag', "1'h1"),
            ('unrelated_rob_path', 'RenameRob', "_allocationPayload_io_read_0[6:0] != 7'h73",
             "_allocationPayload_io_read_0[6:0] != 7'h72")):
        mutant = dict(raw['both_on'])
        mutant[module] = replace_once(mutant[module], old, new, 'negative target missing')
        cases.append((name, lambda mutant=mutant: validate_prefix(raw['history_only'], mutant)))
    mutant = replace_once(raw['both_on'][history.WINDOW], 'assign io_packets_0_bits_data =',
                          "assign io_packets_0_bits_data = io_invalidate ? 64'h0 :", 'negative mux target missing')
    cases.append(('invalidate_in_raw_history_mux', lambda: history.window_model(mutant)))
    results = []
    for name, action in cases:
        try:
            action()
        except RuntimeError as error:
            results.append({'case': name, 'status': 'REJECTED', 'reason': str(error)})
        else:
            raise RuntimeError('checker accepted negative: ' + name)
    return results


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for label in LABELS:
        ap.add_argument('--' + label.replace('_', '-'), type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    require(not args.out.exists(), 'refusing to overwrite an existing receipt')
    tools = [Path(__file__), Path(history.__file__), Path(base.__file__), Path(native_export.__file__),
             Path(__file__).with_name('native_storage_census.py'), Path(__file__).with_name('baseline.json')]
    hashes = {p.name: base.sha(p) for p in tools}
    directories = {label: getattr(args, label) for label in LABELS}
    exports = {label: base.census(path) for label, path in directories.items()}
    changed = validate_exports(exports)
    production_sources = committed_sources(PRODUCTION)
    require(production_sources == native_export.sources(), 'current production differs from pinned source commit')
    commits, bindings, ports, raw = {PRODUCTION: production_sources}, {}, {}, {}
    for label, path in directories.items():
        receipt = json.loads((path / 'receipt.json').read_text())
        revision = receipt['git_head']
        if revision not in commits:
            commits[revision] = committed_sources(revision)
        require(commits[revision] == production_sources, label + ' export commit production source differs')
        require(receipt['synthesis'] is False and receipt['physical_qualification'] is False,
                'unexpected export evidence class')
        require(base.sha(path / 'synthesis-files.f') == receipt['synthesis_filelist_sha256'],
                'synthesis filelist drift')
        flags = ['--selected', '--dma-line-transfers', '--dma-line-entries=4',
                 '--lsu-entries=4', '--physical-load-ingress-flow']
        if label == 'both_on':
            flags.append('--load-order-older-retire')
        if label != 'both_off':
            flags.append('--fetch-previous-packet')
        require(receipt['command'][:4] == ['mill', '-i', 'IonSoC.test.runMain', 'ooo.FpgaNextMain'] and
                receipt['command'][5:] == flags and
                Path(receipt['command'][4]).resolve() == (path / 'rtl').resolve(),
                label + ' export command/profile mismatch')
        bindings[label] = {'directory': str(path.resolve()), 'export_commit': revision,
                           'production_commit': PRODUCTION, 'production_source_files': len(production_sources),
                           'command': receipt['command'],
                           'synthesis_filelist_sha256': receipt['synthesis_filelist_sha256']}
        raw[label], ports[label] = {}, {}
        for name, row in exports[label]['modules'].items():
            text = (path / 'rtl' / row['file']).read_text()
            interface, body, state = module_parts(text)
            require(all(state[key] == row[key] for key in (*KINDS, 'arrays')), 'body-only census mismatch')
            ports[label][name] = {direction + '_bits': sum(v['width'] for v in interface.values()
                                                         if v['direction'] == direction)
                                  for direction in ('input', 'output')}
            if name in [history.WINDOW, *PREFIX_MODULES]:
                raw[label][name] = text
    window = history.validate_window_pair(history.window_model(raw['both_off'][history.WINDOW]),
                                          history.window_model(raw['history_only'][history.WINDOW]))
    require(raw['history_only'][history.WINDOW] == raw['both_on'][history.WINDOW],
            'prefix changed history window')
    prefix = validate_prefix(raw['history_only'], raw['both_on'])
    storage = {label: base.fresh_storage(path) for label, path in directories.items()}
    for label, row in storage.items():
        require(row['status'] == 'PASS_SELECTED_NATIVE_STORAGE_CENSUS' and
                row['export_receipt_sha256'] == exports[label]['receipt_sha256'] and
                row['source_commit'] == bindings[label]['export_commit'] and len(row['groups']) == 10,
                'fresh fixed-storage export binding mismatch')
        for group in row['groups'].values():
            require(group['parent_sha256'] == exports[label]['modules'][group['parent']]['sha256'],
                    'fixed-storage parent mismatch')
            for bank in group['banks']:
                require(bank['helper_sha256'] == exports[label]['modules'][bank['module']]['sha256'],
                        'fixed-storage helper mismatch')
    require(all(storage[label]['groups'] == storage['both_off']['groups'] for label in LABELS),
            'dynamic indexed fixed-storage groups changed')
    delta = {}
    for before, after, top, backend in (('both_off', 'history_only', 133, 0),
                                       ('history_only', 'both_on', 64, 64),
                                       ('both_off', 'both_on', 197, 64)):
        comparison = before + '_to_' + after
        delta[comparison] = {scope: {kind: exports[after]['scopes'][scope][kind] -
                                    exports[before]['scopes'][scope][kind] for kind in KINDS}
                             for scope in exports[before]['scopes']}
        for scope, counts in delta[comparison].items():
            expected = top if scope == 'BoardSocTop' else backend if scope == 'IntegerBackend' else 0
            require(counts == {'scalar_reg_bits': expected, 'array_reg_bits': 0},
                    comparison + ' unexpected reachable state delta: ' + scope)
    result = {
        'status': 'PASS_LITERAL_REACHABLE_FETCH_PREFIX_CENSUS', 'tools': hashes,
        'host_commit_at_census': git('rev-parse', 'HEAD').strip(), 'bindings': bindings,
        'exports': exports, 'delta': delta, 'changed_modules': changed,
        'unchanged_modules_combined': len(exports['both_off']['modules']) - 3,
        'excluded_port_bit_inventory': ports, 'fixed_storage': storage, 'fresh_fixed_storage_runs': 3,
        'window_mux_and_state': window, 'prefix_cone_and_state': prefix,
        'representative_checker_negatives': negative_checks(exports, raw),
        'limits': [
            'Literal native reg declarations weighted by explicit reachable hierarchy, not mapped FF/LUT/BRAM.',
            'ANSI input/output ports and combinational wire aggregates are excluded from persistent state.',
            'Arrays may map to FF, LUTRAM, BRAM or be optimized away; fixed-storage contracts are checked independently.',
            'External ROM and clock primitive state excluded; wrappers and multiplicities are unchanged.',
            'History adds a 68-bit raw primary/history mux; its combinational cone stops at registers.',
            'History raw payload excludes same-cycle invalidate/query/reset and history key/context/valid gating.',
            'Prefix adds live full-tag selection/equality and modular-age predicates into retirement legality.',
            'Neither changed cone establishes LUT cost, fanout, path delay, Fmax, or routed timing.',
            'No compile, export, simulation, synthesis, board, bitstream, or performance replay run by this census.',
        ],
    }
    for label, path in directories.items():
        require(base.census(path) == exports[label], 'export changed during census')
    validate_exports(exports)
    require({p.name: base.sha(p) for p in tools} == hashes, 'census tools changed during run')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('x') as handle:
        handle.write(json.dumps(result, indent=2) + '\n')
    print(result['status'], json.dumps(delta))


if __name__ == '__main__':
    main()
