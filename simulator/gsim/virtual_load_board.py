#!/usr/bin/env python3
"""Frozen same-ELF Sv39 board A/B: real two-issue CPU/cache/AXI, ordinary fixed AXI model.

No forced response holds, UART timing, Linux/full regression or FPGA timing claim.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import run as common
from build_virtual_load_core import build as build_guest

OPTIONS = ('--compact-tags', '--identity-data-flow', '--banked-rob', '--shared-store-reads',
           '--ddr-write-slots=2', '--cache-writebacks=2', '--overlap-writeback-refill',
           '--unordered-ddr-responses', '--lvt-prf', '--data-next-line-prefetch')
PARAMETERS = ('ddr', '100000000', 'staged-fetch-turnover', '460800', '2', '2', '1', 'rv64gc',
              '2147483648', '1', '512', '1', '512', '4', '16', '2', '2', '1', *OPTIONS)
DEFINES = ('-DDDR_MODEL=1', '-DDDR_MULTI_ID_MODEL=1', '-DBOARD_CPU_HZ=100000000U',
           '-DBOARD_UART_BAUD=460800U', '-DUART_DIVISOR=1', '-DBOARD_DDR_BYTES=2147483648ULL',
           '-DDDR_READ_CREDITS=8', '-DDDR_READ_LATENCY=32', '-DDDR_READ_BEAT_GAP=1',
           '-DBOARD_CYCLE_LIMIT=1000000ULL')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inputs():
    files = sorted((common.ROOT / 'src/main/scala').rglob('*.scala'))
    files += sorted((common.ROOT / 'third_party/berkeley-hardfloat/src/main/scala').rglob('*.scala'))
    files += [common.ROOT / 'src/test/scala/ooo/BoardSocGsimMain.scala',
              common.ROOT / 'build.mill', common.ROOT / '.mill-version', Path(__file__),
              common.HERE / 'build_virtual_load_core.py', common.HERE / 'run.py',
              common.HERE / 'config/toolchain.json', common.HERE / 'payloads/virtual_load_core.S',
              common.HERE / 'payloads/virtual_load_core.ld']
    files += [common.HERE / 'harness' / name for name in (
        'virtual_load_board.cpp', 'board_boot.cpp', 'board_ddr_multiid.h', 'backend_observer.h',
        'backend_ownership_ledger.h', 'performance_observer.h')]
    return {str(path.relative_to(common.ROOT)): sha(path) for path in sorted(set(files))}


def parse(log):
    result = {'roi': {}, 'architecture': {}, 'performance': {}}
    for line in log.splitlines():
        kind = line.split(' ', 1)[0]
        if kind not in ('VIRTUAL_BOARD_ROI', 'VIRTUAL_BOARD_ARCH', 'VIRTUAL_BOARD_PASS', 'BOARD_IPC'):
            continue
        fields = dict(word.split('=', 1) for word in line.split()[1:])
        name = fields.pop('name', None)
        parsed = {key: float(value) if key == 'ipc' else int(value) for key, value in fields.items()}
        if kind == 'VIRTUAL_BOARD_ROI':
            result['roi'][name] = parsed
        elif kind == 'BOARD_IPC':
            result['performance'][name] = parsed
        elif kind == 'VIRTUAL_BOARD_ARCH':
            result['architecture'] = parsed
        else:
            result['run'] = parsed
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--reuse', action='append', type=Path, default=[])
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.tag):
        parser.error('unsafe output tag')
    output = common.BUILD / ('virtual-load-board-' + args.tag)
    output.mkdir(parents=True, exist_ok=False)
    frozen = inputs()
    receipt = {'status': 'RUNNING', 'inputs': frozen, 'parameters': PARAMETERS, 'defines': DEFINES,
               'models': {}, 'commands': [], 'artifacts': {}, 'limitations': [
                   'Independent directed guest and host oracle, not NEMU or ISA compliance',
                   'Fixed host AXI latency/credits and deterministic arbitration, not a DDR PHY model',
                   'No external DMA/coherence probe or interrupt injection',
                   'No FPGA routed timing, power, resources or board measurement']}
    def save():
        (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    def guard():
        if inputs() != frozen:
            raise RuntimeError('frozen source changed during full-core acceptance')
        for path, digest in receipt['artifacts'].items():
            if sha(path) != digest:
                raise RuntimeError('frozen artifact changed: ' + path)
    def command(name, argv, expected=0, anchor=None, timeout=900):
        guard()
        logfile = output / (name + '.log')
        began = time.monotonic()
        print('+ ' + ' '.join(map(str, argv)), flush=True)
        with logfile.open('w') as stream:
            process = subprocess.run(list(map(str, argv)), cwd=common.ROOT, stdout=stream,
                                     stderr=subprocess.STDOUT, timeout=timeout,
                                     env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'})
        log = logfile.read_text()
        receipt['commands'].append({'argv': list(map(str, argv)), 'exit': process.returncode,
                                    'log': str(logfile), 'log_sha256': sha(logfile),
                                    'seconds': time.monotonic() - began})
        save()
        if process.returncode != expected or (anchor and anchor not in log):
            raise RuntimeError(str(logfile) + '\n' + log[-8000:])
        return log
    save()
    try:
        gsim, cxx = common.setup(False)
        guest = build_guest(output / 'guest')
        guard()
        elf, binary = Path(guest['elf']), Path(guest['binary'])
        symbols = guest['symbols']
        for path in (elf, binary, output / 'guest/guest.json', output / 'guest/guest.dis'):
            receipt['artifacts'][str(path)] = sha(path)
        receipt['guest'] = {'elf': str(elf), 'elf_sha256': sha(elf), 'binary': str(binary),
                            'binary_sha256': sha(binary), 'symbols': symbols}
        symbol_header = output / 'virtual_load_guest_symbols.h'
        values = {name.upper(): value for name, value in symbols.items()}
        values['ENTRY'] = values.pop('_START')
        values['IMAGE_END'] = symbols['_start'] + binary.stat().st_size
        symbol_header.write_text('#pragma once\n' + ''.join(
            f'#define VIRTUAL_GUEST_{name} 0x{value:x}ULL\n' for name, value in values.items()))
        receipt['artifacts'][str(symbol_header)] = sha(symbol_header)
        flags = ('-std=c++20', '-O1', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=all')
        receipt['compiler_flags'] = flags
        for enabled in (0, 1):
            model = output / f'flag{enabled}'; model.mkdir()
            parameters = (*PARAMETERS, *(('--virtual-ram-load-precheck',) if enabled else ()))
            command(f'flag{enabled}-elaborate', ['mill', '-i', 'IonSoC.test.runMain', 'ooo.BoardSocGsimMain', model, *parameters])
            emitted = model / 'BoardSocGsim.fir'
            reused = None
            reuse_proof = None
            for old_root in args.reuse:
                old_root = old_root.resolve()
                old = old_root / f'flag{enabled}'
                prior_receipt = json.loads((old_root / 'receipt.json').read_text())
                prior = prior_receipt.get('models', {}).get(str(enabled), {})
                if (tuple(prior_receipt.get('parameters', ())) != PARAMETERS or
                        tuple(prior_receipt.get('defines', ())) != DEFINES or
                        not (old / 'BoardSocGsim.h').exists() or not (old / 'BoardSocGsim.fir').exists()):
                    continue
                if (old / 'BoardSocGsim.fir').read_bytes() != emitted.read_bytes():
                    continue
                old_artifacts = prior_receipt.get('artifacts', {})
                needed = [old / 'BoardSocGsim.h', *old.glob('BoardSocGsim[0-9]*.cpp'), *old.glob('BoardSocGsim[0-9]*.o')]
                if not needed or any(str(path) not in old_artifacts or sha(path) != old_artifacts[str(path)] for path in needed):
                    continue
                for path in needed:
                    shutil.copy2(path, model / path.name)
                reused = str(old)
                reuse_proof = 'byte-identical CHIRRTL and verified archived artifacts'
                break
            if not reused:
                command(f'flag{enabled}-generate', [gsim, '--threads=1', f'--dir={model}', emitted])
            generated = [model / 'BoardSocGsim.h', *sorted(model.glob('BoardSocGsim[0-9]*.cpp'))]
            if not reused:
                # Source-location changes can alter FIR text without changing GSIM
                # output. Reuse objects only for byte-identical generated header
                # and every numbered C++ unit, with matching recorded compile flags.
                for old_root in args.reuse:
                    old_root = old_root.resolve(); old = old_root / f'flag{enabled}'
                    old_receipt = json.loads((old_root / 'receipt.json').read_text())
                    if tuple(old_receipt.get('parameters', ())) != PARAMETERS or tuple(old_receipt.get('defines', ())) != DEFINES:
                        continue
                    old_sources = [old / path.name for path in generated]
                    old_objects = [path.with_suffix('.o') for path in old_sources if path.suffix == '.cpp']
                    records = old_receipt.get('artifacts', {})
                    if set(path.name for path in old.glob('BoardSocGsim[0-9]*.cpp')) != set(path.name for path in generated if path.suffix == '.cpp'):
                        continue
                    if any(not prior.exists() or prior.read_bytes() != current.read_bytes()
                           for prior, current in zip(old_sources, generated)):
                        continue
                    if any(str(path) not in records or not path.exists() or sha(path) != records[str(path)]
                           for path in old_sources + old_objects):
                        continue
                    matching_compiles = True
                    for obj in old_objects:
                        matches = [record['argv'] for record in old_receipt.get('commands', [])
                                   if record.get('exit') == 0 and '-c' in record.get('argv', ()) and
                                   record['argv'][-2:] == ['-o', str(obj)]]
                        if not matches or any(argv[0] != cxx or tuple(argv[1:1 + len(flags)]) != flags for argv in matches):
                            matching_compiles = False
                    if not matching_compiles:
                        continue
                    for obj in old_objects:
                        shutil.copy2(obj, model / obj.name)
                    reused = str(old)
                    reuse_proof = 'byte-identical generated header/C++ plus matching compiler arguments and archived object hashes'
                    print('Reusing exact generated-model objects: ' + reused, flush=True)
                    break
            for path in [emitted, *generated]:
                receipt['artifacts'][str(path)] = sha(path)
            objects = []
            for source in sorted(model.glob('BoardSocGsim[0-9]*.cpp')):
                obj = source.with_suffix('.o')
                if not obj.exists():
                    command(f'flag{enabled}-{source.stem}-compile', [cxx, *flags, f'-I{model}', '-c', source, '-o', obj], timeout=1800)
                receipt['artifacts'][str(obj)] = sha(obj); objects.append(obj)
                save()
            check_header = generated[0].read_text()
            if not all(name in check_header for name in ('get_dataPathEvents', 'get_backendEvents', 'get_io$$ddrAxi$$ar$$valid')):
                raise RuntimeError('selected board lacks required passive observations/AXI port')
            executable = model / 'run'
            command(f'flag{enabled}-link', [cxx, *flags, *DEFINES, f'-I{model}', f'-I{output}',
                                            common.HERE / 'harness/virtual_load_board.cpp', *objects, '-ldl', '-o', executable])
            receipt['artifacts'][str(executable)] = sha(executable)
            receipt['models'][str(enabled)] = {'status': 'BUILT', 'chirrtl_sha256': sha(emitted), 'reused': reused, 'reuse_proof': reuse_proof}
            save()
            log = command(f'flag{enabled}-run', [executable, binary], anchor='VIRTUAL_BOARD_PASS', timeout=600)
            print(log, end='', flush=True)
            metrics = parse(log)
            if set(metrics['roi']) != {'warm_independent', 'cold_pages', 'dependent_chase'}:
                raise RuntimeError('missing exact full-core ROI set')
            receipt['models'][str(enabled)].update(status='PASS', metrics=metrics, negative={})
            for mutation, anchor in (
                ('signature', 'independent full-core signature mismatch'),
                ('trap', 'independent full-core trap provenance mismatch'),
                ('marker', 'ROI boundary order/uniqueness mismatch')):
                command(f'flag{enabled}-negative-{mutation}', [executable, binary, '--inject-' + mutation],
                        expected=1, anchor=anchor, timeout=600)
                receipt['models'][str(enabled)]['negative'][mutation] = 'REJECTED'
            save()
        baseline = receipt['models']['0']['metrics']; candidate = receipt['models']['1']['metrics']
        for key in ('signature_hash', 'retired', 'pc_trace', 'traps', 'trap_pc', 'trap_cause', 'trap_tval', 'lsr_reads'):
            if baseline['architecture'][key] != candidate['architecture'][key]:
                raise RuntimeError('same-ELF architectural difference: ' + key)
        comparison = {}
        for name, old in baseline['roi'].items():
            new = candidate['roi'][name]
            if (old['retired'], old['pc_trace']) != (new['retired'], new['pc_trace']):
                raise RuntimeError('same-ELF retired ROI stream differs: ' + name)
            comparison[name] = {'off_cycles': old['cycles'], 'on_cycles': new['cycles'], 'retired': old['retired'],
                                'off_ipc': old['retired'] / old['cycles'], 'on_ipc': new['retired'] / new['cycles'],
                                'cycle_change_percent': 100 * (new['cycles'] / old['cycles'] - 1),
                                'off_physical_peak': old['physical_peak'], 'on_physical_peak': new['physical_peak'],
                                'off_lsu_peak': old['lsu_peak'], 'on_lsu_peak': new['lsu_peak']}
        receipt['comparison'] = comparison
        for old_root in args.reuse:
            prior = json.loads((old_root / 'receipt.json').read_text())
            if prior.get('status') != 'PASS_SAME_ELF_FULL_CORE':
                continue
            if (prior.get('guest', {}).get('elf_sha256') != receipt['guest']['elf_sha256'] or
                    prior.get('guest', {}).get('binary_sha256') != receipt['guest']['binary_sha256'] or
                    tuple(prior.get('parameters', ())) != PARAMETERS or tuple(prior.get('defines', ())) != DEFINES):
                continue
            old_baseline = prior['models']['0']['metrics']
            if baseline != old_baseline:
                raise RuntimeError('default-off full-core metrics changed from matched prior control')
            receipt['prior_control'] = {'receipt': str(old_root.resolve() / 'receipt.json'),
                                       'sha256': sha(old_root / 'receipt.json'),
                                       'default_off_metrics_identical': True,
                                       'same_elf_and_binary': True,
                                       'prior_enabled_roi': prior['models']['1']['metrics']['roi']}
            break
        receipt['architectural_ab_equivalence'] = 'PASS'
        receipt['warm_physical_overlap_witness'] = candidate['roi']['warm_independent']['physical_peak'] >= 2
        receipt['interval_definition'] = 'ELF marker retirement cycles inclusive; retired instructions lane-exact; bus/cache events boundary-cycle-inclusive'
        guard(); receipt['status'] = 'PASS_SAME_ELF_FULL_CORE'
    except BaseException as error:
        receipt['status'] = 'FAIL'; receipt['error'] = str(error)
        raise
    finally:
        save()
    print('PASS_SAME_ELF_FULL_CORE ' + str(output / 'receipt.json'), flush=True)


if __name__ == '__main__':
    main()
