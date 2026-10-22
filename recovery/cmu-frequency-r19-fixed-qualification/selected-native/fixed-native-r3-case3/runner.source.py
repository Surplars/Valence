#!/usr/bin/env python3
"""Real I1/Home/AXI-CDC/fixed-timer eight-clock runtime epoch qualification.

Real CPU scalar-MMIO descriptor programming, cached RX/TX data/guard readback,
and independent packet/AXI/DMI ownership ledgers. DMA status reads are not tested. Original native Icarus only. Mill emission requires an explicitly allocated shared compile slot.
AXI RAM endpoint is a test model. No MIG, clock gate ACK, backend or physical timing claim.
"""
import argparse
import importlib.util
import json
import os
import re
import shutil
import signal
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASE = HERE / 'i1_msi_epoch_native.py'
spec = importlib.util.spec_from_file_location('unchanged_i1_epoch_guest', BASE)
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
FIXTURE = ROOT / 'src/test/scala/platform/CommonI1RuntimeFixedMain.scala'
PARENT_FIXTURE = ROOT / 'src/test/scala/platform/CommonI1RuntimeCdcMain.scala'
DEBUG_FIXTURE = ROOT / 'src/test/scala/platform/CommonI1RuntimeDebugMain.scala'
NETWORK_FIXTURE = ROOT / 'src/test/scala/platform/CommonI1RuntimeNetworkMain.scala'
TB = HERE / 'i1_runtime_fixed_tb.sv'
PASS = 'I1_RUNTIME_FIXED_PASS'


def run(command, output, name, timeout, record):
    """Bound each native child and reap its process group on EVERY exit."""
    command = list(map(str, command))
    started = time.monotonic()
    minimum_free = shutil.disk_usage(output).free
    if minimum_free < base.FLOOR:
        raise RuntimeError('4 GiB disk floor before ' + name)
    killed = timed_out = interrupted = False
    child = None
    try:
        with (output / (name + '.log')).open('w') as log:
            child = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                     start_new_session=True)
            while child.poll() is None:
                minimum_free = min(minimum_free, shutil.disk_usage(output).free)
                timed_out = time.monotonic() - started > timeout
                if timed_out or minimum_free < base.FLOOR:
                    os.killpg(child.pid, signal.SIGKILL)
                    killed = True
                    break
                time.sleep(0.05)
            child.wait()
    except BaseException:
        interrupted = True
        raise
    finally:
        if child is not None:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
                killed = True
            record['cases'].append(dict(name=name, command=command, returncode=child.returncode,
                elapsed_seconds=time.monotonic()-started, minimum_free_bytes=minimum_free,
                timed_out=timed_out, process_group_killed=killed, interrupted=interrupted,
                child_reaped=True))
    if killed:
        raise RuntimeError('wall-clock or disk resource bound: ' + name)
    return child.returncode, (output / (name + '.log')).read_text()


def sources(guest_only=False):
    paths = [BASE, HERE / 'i1_runtime_network.S', HERE / 'i1_runtime_network.ld', Path(__file__).resolve()]
    if not guest_only:
        paths += [TB, FIXTURE, PARENT_FIXTURE, DEBUG_FIXTURE, NETWORK_FIXTURE, ROOT / 'build.mill', ROOT / 'scripts/cloud/env.sh']
        paths += sorted((ROOT / 'src/main/scala').rglob('*.scala'))
        paths += sorted((ROOT / 'src/main/resources').rglob('*.sv'))
    return {str(path.relative_to(ROOT)): base.sha(path) for path in paths}


SYMBOLS = ['_start', 'control_open', 'selector_load', 'guard_store', 'tx_init_store', 'rx_arm', 'tx_start', 'configured', 'net_ready', 'heartbeat', 'check_command', 'rx_check_load', 'guard_check_load', 'tx_check_load', 'net_checked', 'guest_fail', 'timer_read', 'timer_compare_store', 'timer_compare_load', 'timer_heartbeat_read']


TIMER_GUEST = '''    li t1, 0x0200bff8
.globl timer_read, timer_compare_store, timer_compare_load
timer_read:
    ld t4, 0(t1)
    beqz t4, guest_fail
    li t1, 0x02004000
    li t4, 0
timer_compare_store:
    sd t4, 0(t1)
timer_compare_load:
    ld t5, 0(t1)
    bnez t5, guest_fail
    li s6, 0x0200bff8
'''


def guest(output, prefix, record):
    # Preserve the real packet/Home flow and add genuine CPU timer MMIO.
    # TX sets up its timer before launch so deliberately held DMA read traffic
    # cannot block CPU bootstrap; its active-epoch timer stalls occur later.
    # RX sets up after net_ready, allowing its accepted timer owner to be stalled
    # while the packet status tail is independently retained.
    original = (HERE / 'i1_runtime_network.S').read_text()
    needle = 'net_ready:\n    li s3, 0\n'
    if original.count(needle) != 1:
        raise RuntimeError('network guest insertion checkpoint changed')
    guest_source = output / 'guest.fixed.S'
    amended = original.replace('    bnez s2, 2f\n',
        '    beqz s2, 5f\n    jal ra, timer_setup\n5:\n    bnez s2, 2f\n')
    amended = amended.replace(needle,
        needle + '    bnez s2, 6f\n    jal ra, timer_setup\n6:\n')
    amended = amended.replace('heartbeat:\n    addi s3, s3, 1\n',
        'heartbeat:\n    addi s3, s3, 1\n.globl timer_heartbeat_read\ntimer_heartbeat_read:\n    ld t6, 0(s6)\n')
    guest_source.write_text(amended + '\ntimer_setup:\n' + TIMER_GUEST + '    ret\n')
    paths = {name: base.tool(prefix + name) for name in ['gcc', 'objcopy', 'nm', 'objdump']}
    record['tools'].update(base.tool_hashes(paths))
    commands = [
        ([paths['gcc'], '-march=rv64ima_zicsr_zifencei', '-mabi=lp64', '-mcmodel=medany',
          '-mno-relax', '-nostdlib', '-nostartfiles', '-Wl,--no-relax',
          '-T' + str(HERE / 'i1_runtime_network.ld'), guest_source, '-o', output / 'guest.elf'], 'guest-build'),
        ([paths['objcopy'], '-O', 'binary', output / 'guest.elf', output / 'guest.bin'], 'guest-binary'),
        ([paths['nm'], '-n', output / 'guest.elf'], 'guest-symbols'),
        ([paths['objdump'], '-d', output / 'guest.elf'], 'guest-disassembly'),
    ]
    for command, name in commands:
        rc, _ = run(command, output, name, 60, record)
        if rc:
            raise RuntimeError('guest build failed: ' + name)
    image = (output / 'guest.bin').read_bytes()
    if len(image) > 2048 or len(image) % 4:
        raise RuntimeError('guest must fit 512-word fixture ROM with whole RV instructions')
    padded = image + bytes(2048-len(image))
    (output / 'guest.hex').write_text(''.join(
        f'{int.from_bytes(padded[n:n+4], "little"):08x}\n' for n in range(0, 2048, 4)))
    symbols = {name: int(address, 16) for address, _, name in re.findall(
        r'^([0-9a-fA-F]+)\s+(\w)\s+(\S+)$', (output / 'guest-symbols.log').read_text(), re.M)}
    if any(name not in symbols for name in SYMBOLS) or symbols['_start'] != 0x80000000:
        raise RuntimeError('missing or misplaced architectural scoreboard PC symbols')
    (output / 'guest_symbols.svh').write_text(''.join(
        f"localparam [63:0] PC_{name.upper()} = 64'h{symbols[name]:016x};\n" for name in SYMBOLS))
    record['guest'] = dict(image_bytes=len(image), rom_words=512,
        symbols={name: symbols[name] for name in SYMBOLS},
        artifacts={name: base.sha(output / name) for name in
                   ['guest.fixed.S', 'guest.elf', 'guest.bin', 'guest.hex', 'guest_symbols.svh']})


def main():
    def interrupt(signum, frame):
        raise KeyboardInterrupt('signal ' + str(signum))
    signal.signal(signal.SIGTERM, interrupt)
    signal.signal(signal.SIGINT, interrupt)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--emit-only', action='store_true')
    parser.add_argument('--single-case', type=int, choices=range(4))
    parser.add_argument('--single-ratio', choices=['unrelated', 'reversed'])
    parser.add_argument('--timeout', type=float, default=180)
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
    if args.timeout <= 0:
        parser.error('--timeout must be positive')
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
        (out / 'guest.source.S').write_bytes((HERE / 'i1_runtime_network.S').read_bytes())
        (out / 'guest.source.ld').write_bytes((HERE / 'i1_runtime_network.ld').read_bytes())
    subset = args.single_case is not None or args.single_ratio is not None
    record = dict(status='RUNNING', source_sha256=frozen, tools={}, cases=[],
        requested_subset=dict(single_case=args.single_case, single_ratio=args.single_ratio,
                              full_matrix=not subset, negatives=not subset),
        native_case_timeout_seconds=args.timeout,
        scope='real I1/private caches/Atomic/Home/TL-to-AXI/packet DMA/RX/TX and network+debug epoch sequencers; eight independent clocks; fixed DDR UI transport and real timer MMIO; actual AON normal/cancel/4096-cycle timeout and terminal receipts; modeled AXI RAM endpoint, no MIG/PHY/gate/backend/physical qualification',
        ledger_boundary='actual packet native request/reply, external AXI AR/AW/W/R/B, RX/TX frame and status tails, real AON result/fabric terminal/debug/network retirement, CPU dirty-line probe data and independently assembled guest verification PCs; counters compared only at stable checkpoints')
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
            rc, _ = run([tools['mill'], '--no-server', 'IonSoC.test.runMain',
                'platform.CommonI1RuntimeFixedNativeMain', rtl], out, 'emit', 600, record)
            if rc:
                raise RuntimeError('real eight-clock network fixture emission failed')
        else:
            rtl = args.rtl_dir.resolve()
        files = sorted(rtl.glob('*.sv'))
        if not files:
            raise RuntimeError('missing original emitted RTL')
        text = '\n'.join(path.read_text() for path in files)
        required = ['module CommonI1RuntimeFixedFixture', 'module CommonCpuClockBoundary',
                    'module CommonRuntimeEpochBoundary', '$fatal', 'module CommonDebugRuntimeSequencer', 'module DebugDmiAdmissionBoundary',
                    'module JtagRamLoader', 'module CommonNetworkRuntimeSequencer', 'module EthernetPacketDma', 'module GmiiFrameRx', 'module GmiiFrameTx', 'module TileLinkAxi4Bridge', 'module Axi4ClockDomainBoundary', 'module RuntimeFixedTimebaseBoundary', 'module MachineTimer', 'module CommonFixedDomainEpochQualifier', 'observe_memoryRequestFire', 'observe_controlOwnersIdle']
        if any(name not in text for name in required):
            raise RuntimeError('real eight-clock network RTL or inline production assertions missing')
        rtl_hashes = {path.name: base.sha(path) for path in files}
        record['rtl_sha256'] = rtl_hashes
        if not args.emit:
            receipt = json.loads(args.emission_receipt.read_text())
            if receipt.get('status') not in ('PASS', 'PASS_EMIT_ONLY'):
                raise RuntimeError('passing emission receipt required')
            required_sources = {name: digest for name, digest in frozen.items()
                if name.startswith(('src/main/scala/', 'src/main/resources/')) or name in (str(FIXTURE.relative_to(ROOT)), str(PARENT_FIXTURE.relative_to(ROOT)), str(DEBUG_FIXTURE.relative_to(ROOT)), str(NETWORK_FIXTURE.relative_to(ROOT)))}
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
        preprocessed = out / 'preprocessed.sv'
        rc, _ = run([tools['iverilog'], '-g2012', '-DSTOP_COND=1', '-DASSERT_VERBOSE_COND=1',
            '-E', '-o', preprocessed, *files], out, 'preprocess', 120, record)
        if rc:
            raise RuntimeError('native preprocessing failed')
        preprocessed_text = preprocessed.read_text()
        assertions = ['network runtime prepare changed before actual acceptance',
                      'network epoch retired before actual admission release',
                      'fabric epoch retired before fixed-domain consumed retirement receipt',
                      'fixed fixture B before accepted WLAST']
        if not all(message in preprocessed_text for message in assertions) or '$fatal' not in preprocessed_text:
            raise RuntimeError('production protocol assertions are not enabled')
        record['production_assertions'] = dict(preprocessed_sha256=base.sha(preprocessed),
            inline_fatal_sites=preprocessed_text.count('$fatal'), required_messages=assertions)

        rc, _ = run([tools['iverilog'], '-g2012', '-DSTOP_COND=1', '-DASSERT_VERBOSE_COND=1', '-I', out, '-s', 'i1_runtime_fixed_tb',
            '-o', binary, *files, TB], out, 'compile', 600, record)
        if rc:
            raise RuntimeError('native compile failed')
        record['sim_sha256'] = base.sha(binary)
        command = [tools['vvp'], '-i', binary, '+rom=' + str(out / 'guest.hex')]
        record['clock_cases'] = [dict(name='unrelated', half_period_ns=[5,7,11,13,3,17,19,23]),
                                 dict(name='reversed', half_period_ns=[11,5,7,3,17,2,13,19])]
        record['ledgers'] = []
        for name, periods in [('unrelated', (5,7,11,13,3,17,19,23)), ('reversed', (11,5,7,3,17,2,13,19))]:
            if args.single_ratio and args.single_ratio != name:
                continue
            for scenario in (range(4) if args.single_case is None else [args.single_case]):
                case = command + [f'+{clock}-half={period}' for clock,period in zip(
                    ['cpu','fabric','aon','debug','rx','tx','ddr','timebase'],periods)] + [f'+case={scenario}']
                label = name + '-case-' + str(scenario)
                rc, log = run(case, out, label, args.timeout, record)
                if rc or PASS not in log:
                    raise RuntimeError('real eight-clock network/Home positive failed: ' + label)
                record['ledgers'] += [dict(case=label,line=line) for line in log.splitlines()
                                      if line.startswith(('I1_RUNTIME_FIXED_', 'I1_FIXED_', 'I1_PACKET_'))]
        negative_cases = [] if subset else [(1,'NETWORK_ORACLE_PAYLOAD'),(2,'NETWORK_ORACLE_DRAIN'),(3,'NETWORK_ORACLE_GUARD'),(4,'FIXED_ORACLE_STALE_IDLE')]
        for negative, marker in negative_cases:
            rc, log = run(command + [f'+negative={negative}', '+case=0'], out,
                              'negative-' + str(negative), args.timeout, record)
            if not rc or marker not in log or PASS in log:
                raise RuntimeError('independent negative monitor not rejected: ' + str(negative))
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
        record['status'] = 'PASS_SELECTED_CASES' if subset else 'PASS'
    except BaseException as error:
        record.update(status='FAIL', error=repr(error))
        raise
    finally:
        record['logs_sha256'] = {path.name: base.sha(path) for path in out.glob('*.log')}
        (out / 'receipt.json').write_text(json.dumps(record, indent=2) + '\n')
        print(record['status'] + ' receipt=' + str(out / 'receipt.json'), flush=True)


if __name__ == '__main__':
    main()
