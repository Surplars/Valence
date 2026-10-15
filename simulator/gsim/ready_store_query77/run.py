#!/usr/bin/env python3
"""Explicit opt-in emission interfaces. Default prints argv; no implicit execution.

Object build, link and fullCPU runtime deliberately remain unsupported until the
qualified dependency closure and generated input identities are independently reviewed.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode = True
from prepare import HERE, sha, verify


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('stage', choices=['config', 'compatibility', 'component-emit', 'fullcpu-emit', 'gsim-generate'])
    parser.add_argument('--repository', type=Path, default=HERE.parents[2])
    parser.add_argument('--output', type=Path, required=True, help='Fresh stage receipt directory')
    parser.add_argument('--model', type=Path, help='Existing FIR directory, GSIM generation only')
    parser.add_argument('--kind', choices=['component', 'fullcpu'], default='component')
    parser.add_argument('--enabled', choices=['0', '1'], default='1')
    parser.add_argument('--mill', default='mill')
    parser.add_argument('--gsim', default='gsim')
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    root, output = args.repository.resolve(), args.output.resolve()
    manifest = verify(root)
    if output.exists() or output.is_relative_to(HERE):
        raise ValueError('fresh output outside package source required')
    prefix = [args.mill, '-i', 'IonSoC.test.runMain']
    if args.stage == 'config':
        command = prefix + ['ooo.ReadyStoreQuery77ConfigMain']
    elif args.stage == 'compatibility':
        command = [args.mill, '-i', 'IonSoC.test.testOnly', 'ooo.ProfileAbi77CompatibilitySpec']
    elif args.stage == 'component-emit':
        command = prefix + ['ooo.ReadyStoreQuery77BackendGsimMain', str(output / 'model'), args.enabled]
    elif args.stage == 'fullcpu-emit':
        contract = json.loads((root / 'fpga/next/ready-store-query77-profile.json').read_text())
        options = contract['on_options']
        if len(options) != 77 or len(set(options)) != 77:
            raise ValueError('exact ordered77 options required')
        command = prefix + ['ooo.ReadyStoreQuery77CpuMain', str(output / 'model'), *options]
    else:
        if args.model is None:
            raise ValueError('--model required')
        model = args.model.resolve()
        top = 'BoardSocGsim' if args.kind == 'fullcpu' else 'ReadyStoreQuery77BackendGsim'
        fir = model / (top + '.fir')
        if not fir.is_file() or list(model.glob('*.cpp')) or list(model.glob('*.h')) or list(model.glob('*.o')):
            raise ValueError('FIR-only fresh generation directory required')
        if model.is_relative_to(root / 'src') or model.is_relative_to(root / 'simulator'):
            raise ValueError('generated model must be outside source directories')
        command = [args.gsim, '--threads=1', '--cpp-max-size-KB=1024', '--dir=' + str(model), str(fir)]
    print(json.dumps({'stage': args.stage, 'argv': command, 'execute': args.execute}, indent=2))
    if not args.execute:
        return
    output.mkdir(parents=True)
    receipt = {'stage': args.stage, 'argv': command, 'manifest_sha256': sha(HERE / 'inputs.json'),
               'status': 'FAILED_OR_INTERRUPTED', 'runtime_qualified': False}
    try:
        with (output / 'command.log').open('w') as log:
            subprocess.run(command, cwd=root, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=1200)
        receipt['status'] = 'STAGE_COMPLETED_NOT_RUNTIME_QUALIFIED'
    finally:
        (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')


if __name__ == '__main__':
    main()
