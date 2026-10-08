#!/usr/bin/env python3
"""Census optimized firtool --ir-fir output; counts storage geometry, not FPGA LUTs."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re


def census(text):
    modules = defaultdict(lambda: {'memories': [], 'register_bits': 0, 'queue_register_bits': 0,
        'queue_fields': Counter(), 'hint_register_bits': 0, 'hint_fields': Counter()})
    module = None
    for line in text.splitlines():
        match = re.search(r'firrtl.module(?: private)? @([\w$]+)', line)
        if match:
            module = match[1]
        if module is None:
            continue
        row = modules[module]
        match = re.search(r'%([\w$]+) = firrtl.reg(?:reset)? .*', line)
        if match:
            types = re.findall(r'!firrtl.uint<(\d+)>', line)
            if not types:
                continue
            width = int(types[-1])
            row['register_bits'] += width
            name = match[1]
            if name.startswith('queue_'):
                row['queue_register_bits'] += width
                row['queue_fields'][re.sub(r'^queue_\d+_', '', name)] += width
            if name.startswith('hint'):
                row['hint_register_bits'] += width
                row['hint_fields'][re.sub(r'_\d+$', '', name)] += width
        if ' = firrtl.mem ' in line:
            name = re.search(r'name = "([^"]+)"', line)[1]
            depth = int(re.search(r'depth = (\d+)', line)[1])
            widths = set(map(int, re.findall(r'data(?: flip)?: uint<(\d+)>', line)))
            if len(widths) != 1:
                raise ValueError('unsupported nonuniform memory: ' + name)
            width = widths.pop()
            row['memories'].append({'name': name, 'depth': depth, 'width': width,
                'declared_bits': width * depth, 'read_ports': line.count('data flip:'),
                'write_ports': line.count('mask:'),
                'read_latency': int(re.search(r'readLatency = (\d+)', line)[1]),
                'write_latency': int(re.search(r'writeLatency = (\d+)', line)[1])})
    return {'kind': 'firtool_optimized_fir_storage_geometry', 'physical_mapping': 'unverified',
        'replication_note': 'asynchronous read ports may require replicated physical LUTRAM; declared bits are not mapped bits',
        'modules': {name: row for name, row in modules.items() if row['memories'] or row['queue_register_bits'] or
                    row['hint_register_bits'] or name.startswith(('BankedIssuePayload', 'OwnerBankedFetchHints'))}}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('input', type=Path)
    ap.add_argument('--output', type=Path)
    a = ap.parse_args()
    result = json.dumps(census(a.input.read_text()), indent=2) + '\n'
    if a.output:
        a.output.write_text(result)
    else:
        print(result, end='')


if __name__ == '__main__':
    main()
