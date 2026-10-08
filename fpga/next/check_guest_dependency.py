#!/usr/bin/env python3
"""Close the historical ddr_bench.c inventory omission by exact guest rebuilds.

This never edits old evidence and never reruns the DUT. The supplied receipts must
already bind successful, identical guest binaries and the explicit source recipe.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
BASE = 'ea5406ea15d2d0797ce2c5ef7a4951827c55145e'
DEPENDENCY = 'fpga/firmware/ddr_bench.c'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--receipt', action='append', required=True, type=Path)
    ap.add_argument('--output', required=True, type=Path)
    args = ap.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    paths = [path.resolve() for path in args.receipt]
    receipts = [json.loads(path.read_text()) for path in paths]
    dependency = ROOT / DEPENDENCY
    archived = subprocess.check_output(['git', 'show', BASE + ':' + DEPENDENCY], cwd=ROOT)
    if hashlib.sha256(archived).hexdigest() != sha(dependency):
        raise RuntimeError('included benchmark dependency differs from baseline')
    names = [DEPENDENCY, 'fpga/firmware/sample_start.S', 'fpga/firmware/sample_app.ld',
             'simulator/gsim/payloads/board_memory_steady.c',
             'simulator/gsim/payloads/board_memory_independent.c']
    frozen = {name: sha(ROOT / name) for name in names}
    state = {'schema': 'valence-fpga-next-guest-dependency-closure-v1', 'status': 'RUNNING',
        'checker_sha256': sha(Path(__file__)), 'inputs': frozen,
        'historically_omitted_input': DEPENDENCY,
        'baseline_commit': BASE, 'included_file_equal_to_baseline': True,
        'receipts': [{'path': str(path), 'sha256': sha(path)} for path in paths],
        'commands': [], 'artifacts': {}, 'matches': {},
        'limits': ['Preserves the original receipts; this is a dependency supplement',
                   'Exact executed guest bytes are re-established; no new DUT or physical qualification']}
    flags = ['-O2', '-march=rv64im_zicsr_zifencei', '-mabi=lp64', '-mcmodel=medany',
        '-mno-relax', '-msmall-data-limit=0', '-ffreestanding', '-fno-builtin',
        '-fno-stack-protector', '-nostdlib', '-nostartfiles', '-Wl,--no-relax',
        '-Wl,--gc-sections', '-ffunction-sections', '-fdata-sections', '-DCPU_HZ=100000000ULL',
        '-DUART_BAUD=460800', '-Wl,--defsym=BOARD_RAM_BYTES=2147483648',
        '-Wl,--defsym=BOARD_MONITOR_BASE=4294934528']
    compiler = shutil.which('riscv64-unknown-elf-gcc')
    objcopy = shutil.which('riscv64-unknown-elf-objcopy')
    if not compiler or not objcopy:
        raise RuntimeError('load the verified cross-toolchain environment')
    state['compiler'] = {'path': compiler, 'sha256': sha(Path(compiler)),
        'version': subprocess.check_output([compiler, '--version'], text=True).splitlines()[0]}
    state['objcopy'] = {'path': objcopy, 'sha256': sha(Path(objcopy))}
    try:
        for index, receipt in enumerate(receipts):
            if receipt['status'] != 'PASS_FPGA_NEXT_BOARD_SUITE':
                raise RuntimeError('incomplete board receipt')
            for name in names[1:]:
                if receipt['inputs'].get(name) != frozen[name]:
                    raise RuntimeError('recorded guest source differs: ' + name)
        for guest, source in [('steady', names[3]), ('independent', names[4])]:
            elf, image = out / (guest + '.elf'), out / (guest + '.bin')
            command = [compiler, *flags, '-T', str(ROOT / names[2]), str(ROOT / names[1]),
                       str(ROOT / source), '-lgcc', '-o', str(elf)]
            for label, cmd in [(guest + '-compile', command),
                               (guest + '-objcopy', [objcopy, '-O', 'binary', str(elf), str(image)])]:
                log = out / (label + '.log')
                with log.open('w') as stream:
                    subprocess.run(cmd, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
                state['commands'].append({'command': cmd, 'log': log.name, 'log_sha256': sha(log)})
            digest = sha(image)
            bindings = []
            for path, receipt in zip(paths, receipts):
                name = 'firmware/' + guest + '.bin'
                original = path.parent / name
                if sha(original) != receipt['artifacts'][name] or digest != sha(original):
                    raise RuntimeError('rebuilt executed guest differs: ' + str(original))
                bindings.append({'receipt_sha256': sha(path), 'binary_sha256': digest})
            state['matches'][guest] = bindings
        if frozen != {name: sha(ROOT / name) for name in names}:
            raise RuntimeError('guest source changed during rebuild')
        state['status'] = 'PASS_INCLUDED_GUEST_SOURCE_REBUILD_EQUALITY'
    except BaseException as error:
        state['status'] = 'FAIL'; state['error'] = str(error)
        raise
    finally:
        state['artifacts'] = {path.name: sha(path) for path in out.iterdir() if path.is_file()}
        (out / 'receipt.json').write_text(json.dumps(state, indent=2) + '\n')
    print(state['status'])


if __name__ == '__main__':
    main()
