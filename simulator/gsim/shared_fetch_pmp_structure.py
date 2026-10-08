#!/usr/bin/env python3
"""Count elaborated packet PMP structure, never infer physical PPA from it."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re


def inspect(path):
    text = Path(path).read_text()
    match = re.search(r'^  (?:public )?module PacketFetchPmp :[^\n]*\n(.*?)'
                      r'(?=^  (?:public )?(?:ext)?module |\Z)', text, re.M | re.S)
    if not match:
        raise RuntimeError('exact PacketFetchPmp module not found: ' + str(path))
    module = match.group(1)
    if re.search(r'^    (?:reg|regreset|smem|cmem|mem) ', module, re.M):
        raise RuntimeError('unexpected state in packet PMP module')
    counts = Counter(re.findall(r'\b(lt|leq|gt|geq|eq|neq|add|sub|mux)\(', module))
    bounds = {}
    for field in ('regionLow', 'regionEnd', 'regionActive', 'cfg'):
        refs = re.findall(r'io\.state\.' + field + r'\[(\d+)\]', module)
        bounds[field] = {'distinct_input_entries': len(set(refs)), 'textual_references': len(refs)}
    return {'fir_sha256': hashlib.sha256(Path(path).read_bytes()).hexdigest(),
            'module': 'PacketFetchPmp', 'elaborated_primitive_counts': dict(sorted(counts.items())),
            'input_references': bounds, 'registers_or_memories': 0}


def report(directory):
    directory = Path(directory)
    pairs = {}
    for width in (2, 4):
        baseline = inspect(directory / f'packet-{width}-baseline/PmpCheckerGsim.fir')
        shared = inspect(directory / f'packet-{width}-shared/PmpCheckerGsim.fir')
        for field in baseline['input_references']:
            if (baseline['input_references'][field]['distinct_input_entries'] != 16 or
                    shared['input_references'][field]['distinct_input_entries'] != 16):
                raise RuntimeError('PMP state-entry coverage changed: ' + field)
        # TimingArithmetic splits the 62-bit baseline and 59/60-bit shared
        # high comparison into eight unsigned less-than slices each.
        if baseline['elaborated_primitive_counts'].get('lt') != 32 * (width + 1) * 8:
            raise RuntimeError('baseline ordering structure changed')
        if shared['elaborated_primitive_counts'].get('lt') != 32 * 8:
            raise RuntimeError('shared ordering structure changed')
        pairs[str(width)] = {'baseline': baseline, 'shared': shared,
            'logical_baseline_62_bit_orderings': 32 * (width + 1),
            'logical_shared_high_orderings': 32,
            'logical_shared_high_width': 62 - width.bit_length(),
            'logical_shared_low_width': width.bit_length(),
            'logical_used_low_orderings': 32 * (width + 1),
            'instruction_start_candidates': 2 * width - 1}
    return {'status': 'PASS_ELABORATED_STRUCTURE_ONLY', 'pairs': pairs,
        'limits': ['Counts are pre-optimization CHIRRTL, including unused returned comparison directions.',
                   'Input references are wires, not physical register-file read ports.',
                   'No new state or cycle; no synthesis, LUT, Fmax, routed timing, power or physical fanout claim.']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory')
    args = parser.parse_args()
    print(json.dumps(report(args.directory), indent=2))
