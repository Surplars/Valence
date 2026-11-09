#!/usr/bin/env python3
"""Freeze one emitted OOC mode as a portable RTL-only Vivado package (no tool execution)."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--emission', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    source = args.emission.resolve()
    identity = json.loads((source / 'ooc-identity.json').read_text())
    if identity['schema'] != 'valence-combined-a1-fabric-ooc-v1':
        raise ValueError('Not a dedicated combined OOC emission')
    if identity['top'] != 'CombinedA1FabricTimingTop' or identity['part'] != 'xczu15eg-ffvb1156-2-i':
        raise ValueError('Wrong top or target')
    rtl = sorted(p for p in source.rglob('*') if p.suffix in ('.v', '.sv'))
    if not rtl or not any(re.search(r'\bmodule\s+CombinedA1FabricTimingTop\b', p.read_text()) for p in rtl):
        raise ValueError('Missing lowered top RTL; CHIRRTL alone is not a Vivado package')
    for path in rtl:
        text = path.read_text()
        if re.search(r'\$readmem[hb]\s*\(', text):
            raise ValueError(f'Unexpected memory file dependency: {path}; review rather than patch RTL')
        if re.search(r'^\s*`include\s', text, re.M):
            raise ValueError(f'Unexpected include dependency: {path}; review dependency closure')
    out = args.out.resolve()
    if out.exists():
        raise ValueError('Output must be fresh')
    out.mkdir(parents=True)
    names = []
    for path in rtl:
        relative = Path('rtl') / path.relative_to(source)
        if path.is_symlink() or any(char in str(relative) for char in '\n\r'):
            raise ValueError('Unsupported RTL path')
        target = out / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        names.append(relative.as_posix())
    (out / 'rtl-files.txt').write_text('\n'.join(names) + '\n')
    shutil.copyfile(source / 'ooc-identity.json', out / 'ooc-identity.json')
    scripts = Path(__file__).resolve().parent
    for name in ('run_local.py', 'implement.tcl', 'README.md'):
        shutil.copyfile(scripts / name, out / name)
    paths = sorted(p for p in out.rglob('*') if p.is_file())
    manifest = {'schema': 'valence-portable-ooc-package-v1', 'part': identity['part'],
                'top': identity['top'], 'mode': identity['mode'],
                'qualification': 'EXPERIMENTAL_OOC_NOT_BOARD_QUALIFIED',
                'sha256': {p.relative_to(out).as_posix(): sha(p) for p in paths}}
    (out / 'package.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    print(f'Frozen {len(rtl)} RTL files at {out}')


if __name__ == '__main__':
    main()
