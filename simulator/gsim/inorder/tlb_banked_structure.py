#!/usr/bin/env python3
"""Report generic LUT6 mapping size/depth; not FPGA timing, MHz or placement."""
import argparse
from collections import Counter
from functools import lru_cache
import json
from pathlib import Path


def analyze(path, owner, entries):
    module = json.loads(path.read_text())['modules']['FiveStageTranslationHarness']
    cells = module['cells']
    kinds = Counter(cell['type'] for cell in cells.values())
    dependencies = {}
    for cell in cells.values():
        if cell['type'] == '$lut':
            for output in cell['connections']['Y']:
                dependencies[output] = cell['connections']['A']
    ports, nets = module['ports'], module['netnames']

    def bits(names, collection=ports):
        return {bit for name in names if name in collection for bit in collection[name]['bits'] if isinstance(bit, int)}

    def depth(target, sources=None):
        @lru_cache(None)
        def walk(bit):
            if not isinstance(bit, int):
                return 0 if sources is None else -1000000
            if sources is not None and bit in sources:
                return 0
            if bit not in dependencies:
                return 0 if sources is None else -1000000
            return 1 + max(walk(prior) for prior in dependencies[bit])
        result = max(walk(bit) for bit in target)
        return result if result >= 0 else None

    address_inputs = (['io_candidate0', 'io_candidate1'] if owner == 'instruction' else
                      ['io_dataCandidate0_address', 'io_dataCandidate1_address'])
    select_input = 'io_candidateSecond' if owner == 'instruction' else 'io_dataCandidateEarly'
    physical = bits(['io_physicalRequest_bits_address'])
    grant = bits(['io_request_ready', 'io_physicalRequest_valid'])
    proof_pa = bits([name for name in nets if 'fastReadPhysicalPage_' in name or 'fastWritePhysicalPage_' in name], nets)
    all_targets = set()
    for port in ports.values():
        if port['direction'] == 'output':
            all_targets.update(port['bits'])
    for cell in cells.values():
        if 'DFF' in cell['type']:
            for name, direction in cell['port_directions'].items():
                if direction == 'input' and name != 'C':
                    all_targets.update(cell['connections'][name])
    return dict(owner=owner, entries=entries, banked=entries>8, lut6=kinds['$lut'],
        ff_bits=sum(count for kind, count in kinds.items() if 'DFF' in kind),
        max_lut_levels=depth(all_targets),
        candidate_address_to_pa=depth(physical, bits(address_inputs)),
        late_candidate_select_to_pa=depth(physical, bits([select_input])),
        proof_pa_q_to_pa=depth(physical, proof_pa),
        candidate_address_to_grant=depth(grant, bits(address_inputs)),
        note='Generic ABC LUT6 combinational graph; register Q roots. Excludes routing, fanout, device carry/RAM and clock delay.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mapped-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    rows = []
    for entries in (4, 8, 16, 32):
        for owner in ('instruction', 'data'):
            path = args.mapped_root/f'{owner}-{entries}'/'mapped.json'
            if not path.is_file() and owner == 'data' and entries == 8:
                path = args.mapped_root/'data-8-r2'/'mapped.json'
            rows.append(analyze(path, owner, entries))
    args.output.write_text(json.dumps(dict(physical_timing_qualified=False, rows=rows), indent=2)+'\n')
    for row in rows:
        print(row)


if __name__ == '__main__':
    main()
