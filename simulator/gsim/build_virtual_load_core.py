#!/usr/bin/env python3
"""Build one immutable guest image for the virtual-load full-core off/on comparison."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
PAYLOAD = ROOT / 'simulator/gsim/payloads'
SYMBOLS = ('_start', 'warm_begin', 'warm_end', 'cold_begin', 'cold_end', 'chase_begin', 'chase_end',
           'cancel_begin', 'cancel_branch', 'cancel_target', 'wrong_path_begin', 'wrong_path_end',
           'allowed_mmio_load', 'fault_load', 'fault_resume', 'trap_handler', 'done', 'fail')


def build(output: Path) -> dict:
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    prefix = os.environ.get('RISCV_PREFIX', 'riscv64-unknown-elf-')
    gcc = shutil.which(prefix + 'gcc')
    objcopy = shutil.which(prefix + 'objcopy')
    objdump = shutil.which(prefix + 'objdump')
    nm = shutil.which(prefix + 'nm')
    if not all((gcc, objcopy, objdump, nm)):
        raise RuntimeError('source scripts/cloud/env.sh or provide the approved RISC-V toolchain in PATH')
    source, linker = PAYLOAD / 'virtual_load_core.S', PAYLOAD / 'virtual_load_core.ld'
    elf, binary, obj = output / 'guest.elf', output / 'guest.bin', output / 'guest.o'
    # A named intermediate avoids GCC's random temporary FILE symbol in the ELF.
    compile_command = [gcc, '-march=rv64imac_zicsr_zifencei', '-mabi=lp64', '-mno-relax',
                       '-c', str(source), '-o', str(obj)]
    command = [gcc, '-march=rv64imac_zicsr_zifencei', '-mabi=lp64', '-mno-relax', '-nostdlib',
               '-nostartfiles', '-Wl,--no-relax', '-Wl,-T,' + str(linker), str(obj), '-o', str(elf)]
    subprocess.run(compile_command, check=True)
    subprocess.run(command, check=True)
    subprocess.run([objcopy, '-O', 'binary', str(elf), str(binary)], check=True)
    disassembly = subprocess.check_output([objdump, '-d', str(elf)], text=True)
    (output / 'guest.dis').write_text(disassembly)
    symbol_text = subprocess.check_output([nm, '-n', str(elf)], text=True)
    (output / 'guest.nm').write_text(symbol_text)
    all_symbols = {parts[2]: int(parts[0], 16) for line in symbol_text.splitlines()
                   if len(parts := line.split()) == 3}
    symbols = {name: all_symbols[name] for name in SYMBOLS}
    assert symbols['_start'] == 0x80200000 and 0 < binary.stat().st_size < 65536
    assert symbols['wrong_path_begin'] < symbols['wrong_path_end'] == symbols['cancel_target']
    for region in ('warm', 'cold', 'chase'):
        assert symbols[region + '_begin'] < symbols[region + '_end']
    manifest = {
        'status': 'BUILT_NOT_EXECUTED', 'elf': str(elf), 'binary': str(binary), 'symbols': symbols,
        'compile_commands': [compile_command, command],
        'toolchain': subprocess.check_output([gcc, '--version'], text=True).splitlines()[0],
        'sha256': {str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p):
                   hashlib.sha256(p.read_bytes()).hexdigest() for p in (source, linker, elf, binary)},
        'memory_contract': {
            'entry': 0x80200000, 'root': 0x80300000, 'middle': 0x80301000, 'leaf': 0x80302000,
            'virtual_base': 0x40000000, 'physical_base': 0x80400000, 'signature': 0x80600000,
            'leaf_flags': 0xc7, 'page_6_aliases_page_0': True, 'page_7_uart': 0x10000000,
            'page_8_unmapped': True, 'page_0_first_words': list(range(1, 9)),
            'cold_pages': [2, 3, 4, 5], 'cold_word_formula': '0x100 + page_index',
            'chain_nodes': 64, 'chain_stride': 64, 'chain_next_formula':
                '0x40001000 + ((node_index + 1) % 64) * 64',
            'warm_iterations': 64, 'chase_hops': 256,
            'signature_words': ['magic 0x564952544c4f4144', 'warm sum', 'cold sum', 'chase endpoint',
                                'cancel guard 0x123', 'trap count 1', 'cause 13', 'tval 0x40008000',
                                'mepc fault_load', 'alias value 0x99']},
        'scope': 'single byte-identical guest; no full-core, board or PPA result until run separately'}
    (output / 'guest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    manifest = build(args.output)
    print(json.dumps({'manifest': str(args.output.resolve() / 'guest.json'),
                      'binary': manifest['binary'], 'symbols': manifest['symbols']}, indent=2))


if __name__ == '__main__':
    main()
