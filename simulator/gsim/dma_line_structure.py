#!/usr/bin/env python3
"""Source/CHIRRTL state and RAM-port audit, explicitly not mapped FPGA area."""
import argparse
import hashlib
import json
import re
from pathlib import Path

MODULES = ('MemoryCopyDma', 'AtomicMemory', 'MixedCoherentLineHome')


def inspect(path):
    text = path.read_text()
    result = {}
    for name in MODULES:
        match = re.search(r'^  module ' + name + r' :.*?(?=^  (?:module|extmodule) |\Z)', text, re.M | re.S)
        if not match:
            raise RuntimeError('Missing module ' + name)
        module = match[0]
        regs = {m[1]: int(m[2]) for m in re.finditer(r'^\s+(?:reg|regreset) (\w+) : UInt<(\d+)>(?=\s*,)', module, re.M)}
        register_types = {m[1]: m[2] for m in re.finditer(r'^\s+(?:reg|regreset) (\w+) : (.+?), clock(?:\s|$)', module, re.M)}
        non_scalar_types = {k: v for k, v in register_types.items() if k not in regs}
        memories = [line.strip().split(' @[')[0] for line in module.splitlines()
                    if re.match(r'\s+(?:cmem|smem|mem) ', line)]
        ports = [line.strip().split(' @[')[0] for line in module.splitlines()
                 if re.match(r'\s+(?:read|write|rdwr) mport ', line)]
        result[name] = {'scalar_uint_registers': regs, 'non_scalar_register_types': non_scalar_types,
                        'memories': memories, 'memory_ports': ports}
    return {'fir_sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'modules': result}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--baseline', type=Path, required=True)
    ap.add_argument('--candidate', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    a = ap.parse_args()
    baseline, candidate = inspect(a.baseline), inspect(a.candidate)
    report = {'status': 'PASS_STRUCTURAL_ONLY', 'baseline': baseline, 'candidate': candidate,
              'not_measured': ['mapped LUT', 'mapped FF', 'mapped BRAM', 'routed setup/hold', 'Fmax'],
              'new_scalar_state_bits': 0, 'module_deltas': {}}
    for module in MODULES:
        old, new = baseline['modules'][module], candidate['modules'][module]
        added = {k: width for k, width in new['scalar_uint_registers'].items() if k not in old['scalar_uint_registers']}
        removed = {k: width for k, width in old['scalar_uint_registers'].items() if k not in new['scalar_uint_registers']}
        resized = {k: [old['scalar_uint_registers'][k], v] for k, v in new['scalar_uint_registers'].items()
                   if k in old['scalar_uint_registers'] and old['scalar_uint_registers'][k] != v}
        delta = sum(added.values()) - sum(removed.values()) + sum(v[1] - v[0] for v in resized.values())
        report['new_scalar_state_bits'] += delta
        report['module_deltas'][module] = {'added': added, 'removed': removed, 'resized': resized,
            'scalar_bits_delta': delta, 'memory_declarations_identical': old['memories'] == new['memories'],
            'memory_port_counts': [len(old['memory_ports']), len(new['memory_ports'])],
            'non_scalar_register_types_identical': old['non_scalar_register_types'] == new['non_scalar_register_types']}
        if old['non_scalar_register_types'] != new['non_scalar_register_types']:
            raise RuntimeError('Unexpected vector/bundle register type change in ' + module)
        if old['memories'] != new['memories'] or len(old['memory_ports']) != len(new['memory_ports']):
            raise RuntimeError('Unexpected RAM/port change in ' + module)
    # Bundle/vector payloads are unchanged by this feature. The new data buffers
    # must be exactly the one DMA payload and one saved home write payload.
    assert report['module_deltas']['MemoryCopyDma']['added']['payload'] == 512
    assert report['module_deltas']['MixedCoherentLineHome']['added']['lineWriteData'] == 512
    report['new_payload_state_bits'] = 1024
    report['new_payload_bytes'] = 128
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(report, indent=2) + '\n')
    print('PASS_STRUCTURAL_ONLY scalar_bits_delta=' + str(report['new_scalar_state_bits']))


if __name__ == '__main__':
    main()
