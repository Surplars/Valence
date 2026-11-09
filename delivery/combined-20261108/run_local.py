#!/usr/bin/env python3
"""Verify the immutable portable OOC package, then invoke local Vivado once."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess


def verify(root):
    manifest = json.loads((root / 'package.json').read_text())
    if manifest.get('schema') != 'valence-portable-ooc-package-v1':
        raise ValueError('Unsupported package schema')
    if manifest['part'] != 'xczu15eg-ffvb1156-2-i' or manifest['top'] != 'CombinedA1FabricTimingTop':
        raise ValueError('Unsupported package identity')
    for name, digest in manifest['sha256'].items():
        path = root / name
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError(f'Unsafe package member: {name}')
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError(f'Package hash mismatch: {name}')
    if not {'implement.tcl', 'run_local.py', 'rtl-files.txt', 'ooc-identity.json'}.issubset(manifest['sha256']):
        raise ValueError('Unbound package controls')
    listed = (root / 'rtl-files.txt').read_text().splitlines()
    if not listed or any(name not in manifest['sha256'] for name in listed):
        raise ValueError('Unbound RTL list')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-only', action='store_true')
    parser.add_argument('--vivado', default='vivado', help='Vivado executable (or Windows vivado.bat)')
    parser.add_argument('--out', type=Path, help='Fresh output directory; required unless --verify-only')
    parser.add_argument('--cpu-period', type=float, default=10.0, help='CPU period in ns; default 100 MHz target')
    parser.add_argument('--fabric-period', type=float, default=4.0, help='Fabric period in ns; default 250 MHz target')
    args = parser.parse_args()
    if any(not math.isfinite(p) or p <= 0 for p in (args.cpu_period, args.fabric_period)):
        parser.error('Clock periods must be finite and positive')
    root = Path(__file__).resolve().parent
    manifest = verify(root)
    print(f"Verified {len(manifest['sha256'])} files; {manifest['part']}; {manifest['top']}")
    if args.verify_only:
        return
    if args.out is None:
        parser.error('--out is required')
    out = args.out.resolve()
    if out.exists():
        parser.error('--out must not exist; retained runs are never overwritten')
    vivado = shutil.which(args.vivado)
    if vivado is None:
        parser.error('Vivado not found; provide --vivado or use a Vivado command prompt')
    out.mkdir(parents=True)
    command = [vivado, '-mode', 'batch', '-nojournal', '-log', str(out / 'vivado.log'),
               '-source', str(root / 'implement.tcl'), '-tclargs', str(root), str(out), str(args.cpu_period), str(args.fabric_period)]
    (out / 'invocation.json').write_text(json.dumps({'argv': command, 'package': manifest}, indent=2) + '\n')
    subprocess.run(command, cwd=out, check=True)


if __name__ == '__main__':
    main()
