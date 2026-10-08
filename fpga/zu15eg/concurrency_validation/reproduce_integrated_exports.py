#!/usr/bin/env python3
"""Optional native RTL reproduction with already installed pinned tools; no Vivado."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from verify_dev_sources import verify_dev_sources


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    packet = Path(__file__).resolve().parent
    binding = verify_dev_sources(args.repo, args.commit, packet / 'integrated-source-sha256.json')
    output = args.output.resolve()
    if output.exists():
        raise RuntimeError('preserve prior exports; choose a fresh output')
    output.mkdir(parents=True)
    export = json.loads((packet / 'EXPORT-RECEIPT.json').read_text())
    # No installation/download step: set CHISEL_FIRTOOL_PATH to the directory
    # containing the already installed firtool 1.135.0 before this optional run.
    if not os.environ.get('CHISEL_FIRTOOL_PATH'):
        raise RuntimeError('set CHISEL_FIRTOOL_PATH to the installed pinned firtool directory')
    for name in ('integrated-off', 'integrated-on'):
        variant = export['variants'][name]
        dest = output / name
        command = ['mill', '-i', 'IonSoC.test.runMain', export['native_main'],
                   str(dest), *variant['parameters_after_output']]
        with (output / (name + '.log')).open('w') as log:
            subprocess.run(command, cwd=args.repo, stdout=log, stderr=subprocess.STDOUT, check=True)
        actual = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in dest.glob('*.sv')}
        if actual != variant['rtl_sha256']:
            raise RuntimeError('native RTL differs from cloud export: ' + name)
        verify_dev_sources(args.repo, args.commit, packet / 'integrated-source-sha256.json')
    (output / 'reproduction.json').write_text(json.dumps({'status': 'PASS', 'source_binding': binding}, indent=2)+'\n')


if __name__ == '__main__':
    main()
