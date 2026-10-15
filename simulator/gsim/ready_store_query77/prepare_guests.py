#!/usr/bin/env python3
"""Explicit guest-only recipes; never build/run a DUT, host or NEMU reference.
Guest generation is opt-in and never called by prepare.py or emission stages.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
sys.dont_write_bytecode = True
from prepare import HERE, sha, verify


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def check(path, digest):
    if sha(path) != digest:
        raise ValueError('qualified byte identity mismatch: ' + str(path))


def main():
    if sys.flags.optimize:
        raise ValueError('generator assertions must remain enabled')
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('kind', choices=['pmp', 'copy', 'nemu', 'held'])
    parser.add_argument('--repository', type=Path, default=HERE.parents[2])
    parser.add_argument('--output', type=Path, required=True)
    for name in ('gcc', 'objcopy', 'nm'):
        parser.add_argument('--' + name, type=Path)
    parser.add_argument('--nemu-reference', type=Path, help='Required for nemu; hash checked, never loaded')
    args = parser.parse_args()
    root, output = args.repository.resolve(), args.output.resolve()
    manifest = verify(root)
    recipe = manifest['guest_generation'][args.kind]
    if output.exists() or output.is_relative_to(HERE):
        raise ValueError('fresh guest output outside package required')
    tools, tool_hashes = {}, {}
    if args.kind != 'held':
        for name in ('gcc', 'objcopy', 'nm'):
            if getattr(args, name) is None:
                raise ValueError('--' + name + ' required for assembly guest generation')
            tools[name] = getattr(args, name).resolve()
            tool_hashes[name] = sha(tools[name])
    reference = None
    if args.kind == 'nemu':
        if args.nemu_reference is None:
            raise ValueError('--nemu-reference required; no implicit reference selection')
        reference = args.nemu_reference.resolve()
        check(reference, recipe['reference_sha256'])
    output.mkdir(parents=True)
    commands = []
    def run(command):
        command = list(map(str, command))
        result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=120)
        commands.append(command)
        return result.stdout
    def assemble(target, source, linker, march, defines=()):
        target.mkdir()
        run([tools['gcc'], '-march=' + march, '-mabi=lp64', '-mno-relax', '-nostdlib',
             '-nostartfiles', '-Wl,--no-relax', '-Wl,--build-id=none',
             *('-D' + value for value in defines), '-T', linker, source, '-o', target / 'guest.elf'])
        run([tools['objcopy'], '-O', 'binary', target / 'guest.elf', target / 'guest.bin'])
        text = run([tools['nm'], '-n', target / 'guest.elf'])
        # Preserve nm order for the qualified COPY symbol-header bytes.
        names = {}
        for line in text.splitlines():
            fields = line.split()
            if len(fields) == 3:
                if fields[2] in names:
                    raise ValueError('duplicate guest symbol: ' + fields[2])
                names[fields[2]] = int(fields[0], 16)
        return names
    selected = {}
    if args.kind == 'pmp':
        source = root / recipe['source']
        symbols = []
        for mode in ('short', 'word'):
            target = output / mode
            names = assemble(target, source / 'guest.S', source / 'guest.ld', 'rv64imac_zicsr_zifencei',
                             ['SHORT_INSTRUCTION=' + str(int(mode == 'short'))])
            values = {name: names[name] for name in ('_start', 'target_word', 'target_pc', 'trap_handler', 'finished_ecall')}
            if [values[n] for n in ('_start', 'target_word', 'target_pc', 'trap_handler')] != [0x80200000, 0x80200100, 0x80200102, 0x80200180]:
                raise ValueError('PMP guest address layout drift')
            check(target / 'guest.bin', recipe['expected_bins'][mode])
            symbols.append(values)
        if symbols[0] != symbols[1]:
            raise ValueError('PMP symbol disagreement')
        header = output / 'pmp_trap_symbols.h'
        header.write_text('#pragma once\nstatic constexpr uint64_t PMP_TARGET_PC = 0x80200102ULL;\nstatic constexpr uint64_t PMP_FINISHED_ECALL = ' + hex(symbols[0]['finished_ecall']) + 'ULL;\n')
        check(header, recipe['expected_symbols_sha256'])
        selected = symbols[0]
    elif args.kind == 'copy':
        target = output / 'copy'
        names = assemble(target, root / recipe['source'], root / recipe['linker'], 'rv64im_zicsr_zifencei')
        selected = {name: value for name, value in names.items() if name in ('bw_begin', 'bw_end', 'bw_drain', 'bw_done')}
        if len(selected) != 4:
            raise ValueError('missing COPY markers')
        header = target / 'cpu_sv39_symbols.h'
        header.write_text(''.join(f'#define {name.upper()} {value}ULL\n' for name, value in selected.items()))
        check(target / 'guest.bin', recipe['expected_bin_sha256'])
        check(header, recipe['expected_symbols_sha256'])
    elif args.kind == 'nemu':
        target = output / 'hot'
        names = assemble(target, root / recipe['source'], root / recipe['linker'],
                         'rv64im_zicsr_zifencei', recipe['defines'])
        check(target / 'guest.bin', recipe['expected_hot_sha256'])
        module = load('query77_compressed_input', HERE / 'nemu/compressed_call_return.py')
        record = module.emit(output / 'compressed')
        check(output / 'compressed/compressed.bin', recipe['expected_compressed_sha256'])
        if record['done'] != recipe['compressed_done']:
            raise ValueError('compressed done marker drift')
        selected = {'hot_done': names['hot_done'], 'compressed_done': record['done']}
        check(reference, recipe['reference_sha256'])
    else:
        source = root / recipe['source']
        load('directed_inputs', source.parent / 'directed_inputs.py')
        module = load('query77_held_inputs', source)
        guests, controls = module.generated_guests(), module.generated_controls()
        (output / 'guest.bin').write_bytes(guests[recipe['guest_selection']])
        (output / 'input.txt').write_bytes(controls[recipe['control_selection']])
        check(output / 'guest.bin', recipe['expected_guest_sha256'])
        check(output / 'input.txt', recipe['expected_control_sha256'])
    for name, digest in tool_hashes.items():
        check(tools[name], digest)
    receipt = {'status': 'GUEST_BYTES_VERIFIED_NO_DUT_EXECUTION', 'kind': args.kind,
               'tools': tool_hashes, 'commands': commands, 'manifest_sha256': sha(HERE / 'inputs.json'),
               'symbols': selected, 'files': {str(p.relative_to(output)): sha(p) for p in output.rglob('*') if p.is_file()},
               'independent_reference_sha256': recipe['reference_sha256'] if reference else None}
    (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')


if __name__ == '__main__':
    main()
