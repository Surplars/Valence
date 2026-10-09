#!/usr/bin/env python3
"""Build six source-only four-pass hot guests with the existing RISC-V toolchain.

No archived receipt, hardware model, simulator, download or installation is used.
A fixed guest.o filename prevents GCC's random temporary FILE symbol in the ELF.
All paths in the manifest are relative; copied payload sources travel with it.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import run as common

CASES = tuple(f'{op}-{size}' for size in (4096, 8192) for op in ('read', 'write', 'copy'))
ARTIFACTS = ('guest.o', 'guest.elf', 'guest.bin', 'cpu_hot_bandwidth_symbols.h')
PAYLOADS = ('simulator/gsim/payloads/cpu_hot_bandwidth.S',
            'simulator/gsim/payloads/cpu_hot_bandwidth.ld')
SYMBOLS = {'hot_begin', 'hot_kernel_end', 'hot_drain_end', 'hot_complete_end',
           'hot_done', 'hot_kernel', 'hot_image_end'}
SCHEMA = 'valence-cpu-hot-guests-v1'
STATUS = 'PASS_CPU_HOT_GUEST_BUILD'
PROFILE = {'repetitions': 4, 'store_buffer_entries': 2, 'march': 'rv64im_zicsr_zifencei', 'mabi': 'lp64'}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def stable(path, expected, label):
    require(Path(path).is_file(), 'missing ' + label + ': ' + str(path))
    require(sha(path) == expected, 'hash mismatch for ' + label + ': ' + str(path))


def contained(base, relative):
    path = Path(relative)
    require(not path.is_absolute() and '..' not in path.parts, 'nonportable manifest path: ' + str(path))
    result = (base / path).resolve()
    require(result.is_relative_to(base.resolve()), 'manifest path escapes bundle')
    return result


def header(symbols):
    require(set(symbols) == SYMBOLS, 'missing or unexpected hot symbols')
    require(all(type(v) is int and 0x80200000 <= v < 0x80210000 for v in symbols.values()),
            'hot symbol address outside guest image')
    return ''.join(f'#define {name.upper()} {value}ULL\n' for name, value in symbols.items())


def toolchain():
    tools = {}
    for key, suffix in (('cc', 'gcc'), ('objcopy', 'objcopy'), ('nm', 'nm')):
        found = shutil.which('riscv64-unknown-elf-' + suffix)
        require(found is not None, 'existing RISC-V toolchain required: riscv64-unknown-elf-' + suffix)
        tools[key] = Path(found).resolve()
    # Hash the actual assembler/linker/preprocessor used by this GCC driver too.
    for name in ('as', 'ld', 'cc1'):
        found = subprocess.check_output([tools['cc'], '-print-prog-name=' + name], text=True).strip()
        path = Path(found) if Path(found).is_absolute() else Path(shutil.which(found) or found)
        require(path.is_file(), 'missing GCC component: ' + name)
        tools[name] = path.resolve()
    records = {}
    for key, path in tools.items():
        # cc1 --version can succeed with empty output. Its GCC driver supplies
        # the release label; cc1's own executable hash still pins its bytes.
        version = (records['cc']['version'] if key == 'cc1' else
                   subprocess.check_output([path, '--version'], text=True, stderr=subprocess.STDOUT).splitlines()[0])
        records[key] = {'name': path.name, 'sha256': sha(path), 'version': version,
                        'version_source': 'gcc-driver' if key == 'cc1' else 'executable --version'}
    return tools, records


def load_manifest(path, root=common.ROOT):
    """Validate a portable build bundle without executing guest or compiler code."""
    path = Path(path).resolve()
    state = json.loads(path.read_text())
    require(state.get('schema') == SCHEMA and state.get('status') == STATUS, 'not a successful fresh guest manifest')
    require(state.get('profile') == PROFILE, 'guest profile drift')
    require(set(state.get('cases', {})) == set(CASES), 'incomplete or unexpected guest case set')
    stable(Path(__file__), state['builder_sha256'], 'guest builder source')
    require(set(state.get('sources', {})) == set(PAYLOADS), 'guest source inventory drift')
    for name, record in state['sources'].items():
        stable(root / name, record['sha256'], 'current guest source')
        stable(contained(path.parent, record['path']), record['sha256'], 'bundled guest source')
    require(set(state.get('toolchain', {})) == {'cc', 'objcopy', 'nm', 'as', 'ld', 'cc1'}, 'incomplete guest toolchain')
    for record in state['toolchain'].values():
        require(bool(re.fullmatch('[0-9a-f]{64}', record.get('sha256', ''))) and record.get('version'),
                'missing guest toolchain hash/version')
    result = {}
    for case in CASES:
        record = state['cases'][case]
        op, size = case.split('-')
        require(record.get('configuration') == {'op': op, 'bytes': int(size), 'repetitions': 4}, 'guest case config drift: ' + case)
        directory = contained(path.parent, record['directory'])
        require(set(record.get('artifacts', {})) == set(ARTIFACTS), 'guest artifact inventory drift: ' + case)
        for name, expected in record['artifacts'].items():
            stable(contained(path.parent, Path(record['directory']) / name), expected, case + '/' + name)
        require((directory / 'cpu_hot_bandwidth_symbols.h').read_text() == header(record['symbols']),
                'guest symbol/header mismatch: ' + case)
        require(record['symbols']['hot_image_end'] == 0x80200000 + (directory / 'guest.bin').stat().st_size,
                'guest image size/symbol mismatch: ' + case)
        result[case] = {'directory': directory, 'artifacts': record['artifacts']}
    return state, result


def build(out, root=common.ROOT):
    out = Path(out).resolve()
    require(not out.exists(), 'choose a fresh guest output directory')
    source_hashes = {name: sha(root / name) for name in PAYLOADS}
    builder_hash = sha(__file__)
    tools, versions = toolchain()
    out.mkdir(parents=True)
    (out / 'sources').mkdir()
    state = {'schema': SCHEMA, 'status': 'RUNNING', 'profile': PROFILE,
             'builder_sha256': builder_hash, 'sources': {}, 'toolchain': versions, 'cases': {}, 'commands': [],
             'limits': ['Guest assembly build only; no execution or hardware/model qualification.',
                        'Tool versions and executable hashes are recorded; no tools are installed.']}
    manifest = out / 'manifest.json'

    def save():
        manifest.write_text(json.dumps(state, indent=2) + '\n')

    def command(case, name, cmd):
        directory = out / case
        # Commands use bare tool names and bundle-relative paths, never build-root paths.
        with (directory / (name + '.log')).open('x') as log:
            result = subprocess.run(list(map(str, cmd)), cwd=directory, stdout=log, stderr=subprocess.STDOUT,
                                    timeout=60, env={**os.environ, 'LC_ALL': 'C', 'SOURCE_DATE_EPOCH': '0'})
        record = {'cwd': case, 'command': [Path(cmd[0]).name, *map(str, cmd[1:])],
                  'exit': result.returncode, 'log': case + '/' + name + '.log',
                  'log_sha256': sha(directory / (name + '.log'))}
        state['commands'].append(record)
        save()
        require(result.returncode == 0, 'guest build failed: ' + str(directory / (name + '.log')))
        return (directory / (name + '.log')).read_text()

    try:
        for name, digest in source_hashes.items():
            destination = out / 'sources' / Path(name).name
            shutil.copyfile(root / name, destination)
            stable(destination, digest, 'copied guest source')
            state['sources'][name] = {'path': destination.relative_to(out).as_posix(), 'sha256': digest}
        save()
        for case in CASES:
            op, size = case.split('-')
            directory = out / case
            directory.mkdir()
            flags = ['-march=' + PROFILE['march'], '-mabi=' + PROFILE['mabi'], '-mno-relax']
            defines = ['-DHOT_SB_ENTRIES=2', '-DHOT_OP=' + str(('read', 'write', 'copy').index(op)),
                       '-DHOT_BYTES=' + size, '-DHOT_REPS=4']
            command(case, 'assemble', [tools['cc'], *flags, *defines, '-c', '../sources/cpu_hot_bandwidth.S', '-o', 'guest.o'])
            command(case, 'link', [tools['cc'], *flags, '-nostdlib', '-nostartfiles', '-Wl,--no-relax',
                                   '-Wl,--build-id=none', '-T', '../sources/cpu_hot_bandwidth.ld', 'guest.o', '-o', 'guest.elf'])
            command(case, 'binary', [tools['objcopy'], '-O', 'binary', 'guest.elf', 'guest.bin'])
            symbols = {}
            for line in command(case, 'symbols', [tools['nm'], '-n', 'guest.elf']).splitlines():
                fields = line.split()
                if len(fields) == 3 and fields[2].startswith('hot_'):
                    require(fields[2] not in symbols, 'duplicate hot symbol')
                    symbols[fields[2]] = int(fields[0], 16)
            (directory / 'cpu_hot_bandwidth_symbols.h').write_text(header(symbols))
            state['cases'][case] = {'directory': case, 'configuration': {'op': op, 'bytes': int(size), 'repetitions': 4},
                                    'symbols': symbols, 'artifacts': {name: sha(directory / name) for name in ARTIFACTS}}
            save()
        for name, digest in source_hashes.items():
            stable(root / name, digest, 'guest source during build')
        stable(__file__, builder_hash, 'guest builder during build')
        for name, path in tools.items():
            stable(path, versions[name]['sha256'], 'toolchain during build')
        state['status'] = STATUS
        save()
        load_manifest(manifest, root)
    except BaseException as error:
        state['status'] = 'FAIL'; state['error'] = str(error); save(); raise
    print(STATUS, manifest, flush=True)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--out', type=Path)
    group.add_argument('--verify', type=Path, help='Read-only hash/source/config validation of a manifest')
    args = parser.parse_args()
    if args.verify:
        load_manifest(args.verify)
        print('PASS_CPU_HOT_GUEST_MANIFEST', args.verify)
    else:
        build(args.out)


if __name__ == '__main__':
    main()
