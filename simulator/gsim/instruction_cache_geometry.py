#!/usr/bin/env python3
"""Bounded independent cache geometry checks; never runs the board or full GSIM.

Default production-width coverage: 8 and 32 lines. --edges adds 4 and 256.
Needs the parameterized InstructionLineCacheGsim wrapper and CACHE_LINES oracle.
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from run import BUILD, ROOT, setup, test
from control_stage import negative


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--lines', nargs='+', type=int, default=[8, 32])
    parser.add_argument('--edges', action='store_true')
    parser.add_argument('--words', type=int, choices=[2, 4], default=2)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.tag):
        parser.error('Unsafe tag')
    lines = sorted(set(args.lines + ([4, 256] if args.edges else [])))
    if any(n < 4 or n > 256 or n & (n - 1) for n in lines):
        parser.error('Line counts must be powers of two in 4..256')
    cases = [{'name': f'icache-geometry-{args.tag}-w{args.words}-n{n}',
              'lines': n, 'sets': n // 2, 'ways': 2, 'line_bytes': 64,
              'set_stride_bytes': 64 * (n // 2), 'packet_words': args.words}
             for n in lines]
    if args.dry_run:
        print(json.dumps(cases, indent=2))
        return
    # Refuse overwriting receipts from an earlier geometry run.
    for case in cases:
        if (BUILD / case['name']).exists():
            raise RuntimeError('Output exists: ' + str(BUILD / case['name']))
    source_paths = [Path(__file__), ROOT / 'src/main/scala/core/ooo/InstructionLineCache.scala',
                    ROOT / 'src/main/scala/core/ooo/InstructionTileLinkBridge.scala',
                    ROOT / 'src/main/scala/ip/tilelink/TileLinkLineFillEngine.scala',
                    ROOT / 'src/test/scala/ooo/InstructionLineCacheGsim.scala',
                    ROOT / 'simulator/gsim/harness/instruction_line_cache.cpp']
    def hashes(paths):
        return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    source_hashes = hashes(source_paths)
    gsim, cxx = setup(False)
    for case in cases:
        output = test(gsim, cxx, case['name'], 'ooo.InstructionLineCacheGsimMain',
                      'InstructionLineCacheGsim', 'instruction_line_cache.cpp',
                      parameters=('no-prefetch', str(args.words), f"lines={case['lines']}"),
                      defines={'PACKET_WORDS': args.words, 'CACHE_LINES': case['lines']})
        fir = (output / 'InstructionLineCacheGsim.fir').read_text()
        cache = re.search(r'  module InstructionLineCache :.*?(?=\n  module |\Z)', fir, re.S)
        sets = case['sets']
        tag_bits = 58 - (sets.bit_length() - 1)
        if not cache or not all(f'smem data_{way} : UInt<512>[{sets}]' in cache[0] for way in range(2)):
            raise RuntimeError('Emitted cache SRAM geometry does not match requested configuration')
        if f'reg tags : UInt<{tag_bits}>[2][{sets}]' not in cache[0]:
            raise RuntimeError('Emitted cache tag geometry does not match requested configuration')
        case['emitted_geometry'] = {'status': 'PASS', 'sets': sets, 'tag_bits': tag_bits}
        negative(output / 'run', (), 'instruction cache returned incorrect code', output / 'negative.log')
        case['negative_oracle'] = 'PASS injected returned-data corruption rejected'
        case['status'] = 'PASS_FOCUSED_GEOMETRY'
        case['source_sha256'] = source_hashes
        if hashes(source_paths) != source_hashes:
            raise RuntimeError('Geometry source changed during test batch')
        case['artifact_sha256'] = hashes([output / 'InstructionLineCacheGsim.fir',
                                          output / 'run', output / 'test.log', output / 'negative.log'])
        (output / 'geometry.json').write_text(json.dumps(case, indent=2) + '\n')


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, subprocess.SubprocessError, OSError) as error:
        print(f'GSIM instruction cache geometry: {error}', file=sys.stderr)
        sys.exit(1)
