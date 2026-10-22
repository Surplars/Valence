#!/usr/bin/env python3
"""Real I1/Home/RAM-loader four-clock runtime epoch native qualification.

Real CPU scalar-MMIO arm/status guest plus independent CPU RAM persistence and
DMI request/readback ledgers. Original native Icarus only. Mill emission requires an explicitly allocated shared compile slot.
No clock manager, gate ACK, PLL/backend, DDR, or physical timing claim.
"""
import argparse
import importlib.util
import json
import os
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASE = HERE / 'i1_msi_epoch_native.py'
spec = importlib.util.spec_from_file_location('unchanged_i1_epoch_guest', BASE)
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
FIXTURE = ROOT / 'src/test/scala/platform/CommonI1RuntimeDebugMain.scala'
PARENT_FIXTURE = ROOT / 'src/test/scala/platform/CommonI1RuntimeCdcMain.scala'
TB = HERE / 'i1_runtime_debug_tb.sv'
PASS = 'I1_RUNTIME_DEBUG_PASS'


def sources(guest_only=False):
    paths = [BASE, HERE / 'i1_runtime_debug.S', HERE / 'i1_runtime_debug.ld', Path(__file__).resolve()]
    if not guest_only:
        paths += [TB, FIXTURE, PARENT_FIXTURE, ROOT / 'build.mill', ROOT / 'scripts/cloud/env.sh']
        paths += sorted((ROOT / 'src/main/scala').rglob('*.scala'))
        paths += sorted((ROOT / 'src/main/resources').rglob('*.sv'))
    return {str(path.relative_to(ROOT)): base.sha(path) for path in paths}


SYMBOLS = ['_start', 'guard_store', 'control_open', 'control_read', 'control_generation', 'configured',
           'loop_previous', 'loop_previous_compare', 'loop_increment', 'loop_store', 'loop_load',
           'loop_compare', 'loop_control', 'loop_jump', 'guest_fail']


def guest(output, prefix, record):
    paths = {name: base.tool(prefix + name) for name in ['gcc', 'objcopy', 'nm', 'objdump']}
    record['tools'].update(base.tool_hashes(paths))
    commands = [
        ([paths['gcc'], '-march=rv64ima_zicsr_zifencei', '-mabi=lp64', '-mcmodel=medany',
          '-mno-relax', '-nostdlib', '-nostartfiles', '-Wl,--no-relax',
          '-T' + str(HERE / 'i1_runtime_debug.ld'), HERE / 'i1_runtime_debug.S', '-o', output / 'guest.elf'], 'guest-build'),
        ([paths['objcopy'], '-O', 'binary', output / 'guest.elf', output / 'guest.bin'], 'guest-binary'),
        ([paths['nm'], '-n', output / 'guest.elf'], 'guest-symbols'),
        ([paths['objdump'], '-d', output / 'guest.elf'], 'guest-disassembly'),
    ]
    for command, name in commands:
        rc, _ = base.run(command, output, name, 60, record)
        if rc:
            raise RuntimeError('guest build failed: ' + name)
    image = (output / 'guest.bin').read_bytes()
    if len(image) > 1024 or len(image) % 4:
        raise RuntimeError('guest must fit 256-word fixture ROM with whole RV instructions')
    padded = image + bytes(1024-len(image))
    (output / 'guest.hex').write_text(''.join(
        f'{int.from_bytes(padded[n:n+4], "little"):08x}\n' for n in range(0, 1024, 4)))
    symbols = {name: int(address, 16) for address, _, name in re.findall(
        r'^([0-9a-fA-F]+)\s+(\w)\s+(\S+)$', (output / 'guest-symbols.log').read_text(), re.M)}
    if any(name not in symbols for name in SYMBOLS) or symbols['_start'] != 0x80000000:
        raise RuntimeError('missing or misplaced architectural scoreboard PC symbols')
    (output / 'guest_symbols.svh').write_text(''.join(
        f"localparam [63:0] PC_{name.upper()} = 64'h{symbols[name]:016x};\n" for name in SYMBOLS))
    record['guest'] = dict(image_bytes=len(image), rom_words=256,
        symbols={name: symbols[name] for name in SYMBOLS},
        artifacts={name: base.sha(output / name) for name in
                   ['guest.elf', 'guest.bin', 'guest.hex', 'guest_symbols.svh']})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--emit-only', action='store_true')
    parser.add_argument('--cross-prefix', default='riscv64-unknown-elf-')
    parser.add_argument('--iverilog', default=os.environ.get('IVERILOG', 'iverilog'))
    parser.add_argument('--vvp', default=os.environ.get('VVP', 'vvp'))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--emit', action='store_true')
    mode.add_argument('--rtl-dir', type=Path)
    parser.add_argument('--emission-receipt', type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    if out.exists() or not out.parent.is_dir():
        parser.error('fresh output directory with existing parent required')
    if not args.prepare_only and not (args.emit or (args.rtl_dir and args.emission_receipt)):
        parser.error('use --emit or --rtl-dir with --emission-receipt')
    if args.emit_only and not args.emit:
        parser.error('--emit-only requires --emit')
    if not os.environ.get('VALENCE_CLOUD_ENV'):
        parser.error('source scripts/cloud/env.sh before running this test')
    out.mkdir()
    frozen = sources(args.prepare_only)
    if not args.prepare_only:
        (out / 'testbench.source.sv').write_bytes(TB.read_bytes())
        (out / 'fixture.source.scala').write_bytes(FIXTURE.read_bytes())
        (out / 'parent-fixture.source.scala').write_bytes(PARENT_FIXTURE.read_bytes())
        (out / 'runner.source.py').write_bytes(Path(__file__).read_bytes())
        (out / 'guest.source.S').write_bytes((HERE / 'i1_runtime_debug.S').read_bytes())
        (out / 'guest.source.ld').write_bytes((HERE / 'i1_runtime_debug.ld').read_bytes())
    record = dict(status='RUNNING', source_sha256=frozen, tools={}, cases=[],
        scope='real full I1/private caches/Home/internal 1 MiB RAM/production JtagRamLoader/production debug sequencer; independent CPU/fabric/AON/debug clocks; actual 4096-AON timeout; no gate/backend/PLL/DDR/physical qualification',
        ledger_boundary='source DMI accepted/replied requests, actual loader.memory request/response, actual CPU scalar control request/response, and independently assembled guest retirement PCs/data; counters compared only at stable checkpoints')
    try:
        guest(out, args.cross_prefix, record)
        if args.prepare_only:
            if sources(True) != frozen:
                raise RuntimeError('guest source drift')
            record['status'] = 'PASS_GUEST_ONLY'
            return
        tools = {name: base.tool(getattr(args, name)) for name in ['iverilog', 'vvp']}
        record['tools'].update(base.tool_hashes(tools))
        if args.emit:
            tools['mill'] = base.tool('mill')
            record['tools'].update(base.tool_hashes({'mill': tools['mill']}))
            rtl = out / 'rtl'
            rc, _ = base.run([tools['mill'], '--no-server', 'IonSoC.test.runMain',
                'platform.CommonI1RuntimeDebugNativeMain', rtl], out, 'emit', 600, record)
            if rc:
                raise RuntimeError('real four-clock debug fixture emission failed')
        else:
            rtl = args.rtl_dir.resolve()
        files = sorted(rtl.glob('*.sv'))
        if not files:
            raise RuntimeError('missing original emitted RTL')
        text = '\n'.join(path.read_text() for path in files)
        required = ['module CommonI1RuntimeDebugFixture', 'module CommonCpuClockBoundary',
                    'module CommonRuntimeEpochBoundary', '$fatal', 'module CommonDebugRuntimeSequencer', 'module DebugDmiAdmissionBoundary',
                    'module JtagRamLoader', 'observe_memoryRequestFire', 'observe_controlOwnersIdle']
        if any(name not in text for name in required):
            raise RuntimeError('real four-clock debug RTL or inline production assertions missing')
        rtl_hashes = {path.name: base.sha(path) for path in files}
        record['rtl_sha256'] = rtl_hashes
        if not args.emit:
            receipt = json.loads(args.emission_receipt.read_text())
            if receipt.get('status') not in ('PASS', 'PASS_EMIT_ONLY'):
                raise RuntimeError('passing emission receipt required')
            required_sources = {name: digest for name, digest in frozen.items()
                if name.startswith(('src/main/scala/', 'src/main/resources/')) or name in (str(FIXTURE.relative_to(ROOT)), str(PARENT_FIXTURE.relative_to(ROOT)))}
            if any(receipt.get('source_sha256', {}).get(name) != digest for name, digest in required_sources.items()):
                raise RuntimeError('emission not bound to current production/fixture sources')
            if receipt.get('rtl_sha256') != rtl_hashes:
                raise RuntimeError('emitted RTL hash mismatch')
            record['emission_receipt'] = dict(path=str(args.emission_receipt.resolve()), sha256=base.sha(args.emission_receipt))
        if args.emit_only:
            if sources() != frozen:
                raise RuntimeError('source drift during emission')
            record['status'] = 'PASS_EMIT_ONLY'
            return
        binary = out / 'sim.vvp'
        rc, _ = base.run([tools['iverilog'], '-g2012', '-I', out, '-s', 'i1_runtime_debug_tb',
            '-o', binary, *files, TB], out, 'compile', 600, record)
        if rc:
            raise RuntimeError('native compile failed')
        record['sim_sha256'] = base.sha(binary)
        command = [tools['vvp'], binary, '+rom=' + str(out / 'guest.hex')]
        record['clock_cases'] = [dict(name='unrelated', half_period_ns=[5, 7, 11, 13], phase_ns=[0, 2, 3, 4]),
                                 dict(name='reversed', half_period_ns=[11, 5, 7, 3], phase_ns=[0, 2, 3, 4])]
        record['ledgers'] = []
        for name, periods in [('unrelated', (5, 7, 11, 13)), ('reversed', (11, 5, 7, 3))]:
            case = command + [f'+cpu-half={periods[0]}', f'+fabric-half={periods[1]}', f'+aon-half={periods[2]}', f'+debug-half={periods[3]}']
            rc, log = base.run(case, out, name, 1200, record)
            if rc or PASS not in log:
                raise RuntimeError('real four-clock debug positive failed: ' + name)
            record['ledgers'] += [dict(case=name, line=line) for line in log.splitlines()
                                  if line.startswith('I1_RUNTIME_DEBUG_')]
        for negative, marker in [('wrong-data', 'independent debug readback data oracle'),
                                 ('wrong-drain', 'independent debug drain oracle')]:
            rc, log = base.run(command + ['+' + negative], out, negative, 300, record)
            if not rc or marker not in log or PASS in log:
                raise RuntimeError('independent negative monitor not rejected: ' + negative)
        if sources() != frozen:
            raise RuntimeError('source drift during native test')
        if rtl_hashes != {path.name: base.sha(path) for path in files}:
            raise RuntimeError('RTL drift during native test')
        for name, info in record['tools'].items():
            if base.sha(info['path']) != info['sha256']:
                raise RuntimeError('tool drift: ' + name)
        for name, digest in record['guest']['artifacts'].items():
            if base.sha(out / name) != digest:
                raise RuntimeError('guest artifact drift: ' + name)
        record['status'] = 'PASS'
    except BaseException as error:
        record.update(status='FAIL', error=repr(error))
        raise
    finally:
        record['logs_sha256'] = {path.name: base.sha(path) for path in out.glob('*.log')}
        (out / 'receipt.json').write_text(json.dumps(record, indent=2) + '\n')
        print(record['status'] + ' receipt=' + str(out / 'receipt.json'), flush=True)


if __name__ == '__main__':
    main()
