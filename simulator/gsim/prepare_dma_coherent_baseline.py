#!/usr/bin/env python3
"""Create an exact archived DUT baseline plus the independently maintained integration fixture."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[2]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--revision', default='8e78b5b3252311d19d728d815cf32ad3ec5cedb2')
    p.add_argument('--expected-tree', default='c82f46861725be23b8c4f68630e341b72281c05c',
                   help='Exact qualified baseline tree; refuses a different source tree')
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    out = args.output.resolve()
    if out.exists(): p.error('Output already exists; choose a fresh source snapshot directory')
    revision = subprocess.check_output(['git', 'rev-parse', '--verify', args.revision + '^{commit}'], cwd=ROOT, text=True).strip()
    tree = subprocess.check_output(['git', 'rev-parse', revision + '^{tree}'], cwd=ROOT, text=True).strip()
    if tree != args.expected_tree:
        p.error('Baseline tree mismatch: ' + tree + '; expected ' + args.expected_tree)
    archive = subprocess.check_output(['git', 'archive', revision], cwd=ROOT)
    out.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(out, filter='data')
    files = ['simulator/gsim/dma_coherent_line.py', 'simulator/gsim/harness/dma_coherent_line.cpp',
             'simulator/gsim/harness/dma_coherent_ddr.h']
    for path in files: shutil.copyfile(ROOT / path, out / path)
    shutil.copyfile(ROOT / 'simulator/gsim/fixtures/dma_coherent_line_baseline.scala',
                    out / 'src/test/scala/ooo/DmaCoherentLineGsim.scala')
    dut = sorted((out / 'src/main/scala').rglob('*.scala'))
    manifest = {'revision': revision, 'tree': tree, 'expected_tree': args.expected_tree, 'dut_source_sha256': {
        str(path.relative_to(out)): hashlib.sha256(path.read_bytes()).hexdigest() for path in dut}}
    (out / 'baseline-source.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(out)


if __name__ == '__main__': main()
