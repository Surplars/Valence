#!/usr/bin/env python3
"""Bounded inspection of firtool split SV module closure and actual storage instances, not equivalence."""
import argparse
import hashlib
import json
from pathlib import Path
import re


def inspect(root):
    identity = json.loads((root / 'ooc-identity.json').read_text())
    definitions, paths, edges = {}, {}, {}
    for path in sorted(root.glob('*.sv')):
        text = path.read_text()
        clean = re.sub(r'/\*.*?\*/|//[^\n]*', '', text, flags=re.S)
        modules = re.findall(r'\bmodule\s+(\w+)\s*\(.*?\bendmodule\b', clean, re.S)
        if len(modules) != 1:
            raise ValueError(f'Expected one split module per file: {path}')
        name = modules[0]
        if name in definitions or re.search(r'\(\*[^*]*blackbox', clean, re.I):
            raise ValueError('Duplicate/blackbox definition ' + name)
        definitions[name] = clean
        paths[name] = path.name
        if re.search(r'^\s*\w+\s*#\s*\(', clean, re.M):
            raise ValueError('Parameterized instance requires expanded closure inspection')
        edges[name] = [typ for typ, inst in re.findall(r'^\s{2}(\w+)\s+(\w+)\s*\(', clean, re.M)
                       if typ not in ('module', 'function', 'task')]
    missing = sorted({typ for refs in edges.values() for typ in refs} - definitions.keys())
    if missing:
        raise ValueError('Unresolved module names: ' + str(missing))
    reached, pending = set(), [identity['top']]
    while pending:
        name = pending.pop()
        if name not in reached:
            reached.add(name)
            pending.extend(edges[name])
    required = {'CommonA1CpuTile', 'CommonCpuClockBoundary', 'CommonMachineFabric',
                'IntegerCore', 'IntegerBackend', 'BankedIssuePayload', 'IndirectTargetPredictor',
                'MemoryCopyDma', 'MixedCoherentLineHome'}
    if not required <= reached:
        raise ValueError('Missing connected production implementations: ' + str(required - reached))
    candidate = identity['mode'].endswith('candidate')
    width = 32 if candidate else 64
    payload = definitions['BankedIssuePayload']
    if len(re.findall(r'immediateBank_8x' + str(width) + r'\s+immediateBank[01]_ext\s*\(', payload)) != 2:
        raise ValueError('Actual issue immediate memory width/instances differ')
    predictor = definitions['IndirectTargetPredictor']
    for bank in ('tagBank0_ext', 'tagBank1_ext', 'targetBank0_ext', 'targetBank1_ext'):
        present = bool(re.search(r'\w+\s+' + bank + r'\s*\(', predictor))
        if present != candidate:
            raise ValueError('Actual banked/register predictor mismatch')
    return {'mode': identity['mode'], 'top': identity['top'], 'module_definitions': len(definitions),
            'reachable_modules': len(reached), 'unresolved': missing, 'required_connected': sorted(required),
            'immediate_ram_width': width, 'banked_predictor_actual': candidate,
            'sv_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.glob('*.sv'))},
            'limits': 'Bounded firtool emitted-structure inspection, not a general SV parser or runtime proof'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('candidate', type=Path)
    parser.add_argument('baseline', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    a, b = (json.loads((p / 'ooc-identity.json').read_text()) for p in (args.candidate, args.baseline))
    delta = {key: [a['effectiveCore'].get(key), b['effectiveCore'].get(key)]
             for key in a['effectiveCore'].keys() | b['effectiveCore'].keys()
             if a['effectiveCore'].get(key) != b['effectiveCore'].get(key)}
    if set(delta) != {'bankedIndirectStorage', 'compactIssueImmediates'}:
        raise ValueError('Matched core parameter delta differs: ' + str(delta))
    if a['fabricConfig'] != b['fabricConfig'] or a['safeFetchRanges'] != b['safeFetchRanges']:
        raise ValueError('Matched fabric or fetch policy differs')
    report = {'status': 'PASS_STRUCTURAL_CLOSURE_ONLY', 'candidate': inspect(args.candidate),
              'baseline': inspect(args.baseline), 'effective_core_delta': delta,
              'combined_cpu_runtime': 'NOT_RUN', 'vivado': 'NOT_RUN'}
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(json.dumps({k:report[k] for k in ('status','effective_core_delta')}))


if __name__ == '__main__':
    main()
