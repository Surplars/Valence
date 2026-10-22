#!/usr/bin/env python3
"""Real ClockRateControl timeout cleanup with real I1 three-clock epoch owners.

Reuses the unchanged r9 architectural guest, not its single-clock DUT. Native
Icarus only. Mill emission requires an explicitly allocated shared compile slot.
Actual opt-in ClockRateControl and lease adapter; boot lock/gate are test-only models. Full drain ACKs stay zero. No runtime gate/PLL/backend/DDR/physical claim.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASE = HERE / 'i1_msi_epoch_native.py'
spec = importlib.util.spec_from_file_location('unchanged_i1_epoch_guest', BASE)
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
FIXTURE = ROOT / 'src/test/scala/platform/CommonClockRateCleanupMain.scala'
REAL_FIXTURE = ROOT / 'src/test/scala/platform/CommonI1RuntimeCdcMain.scala'
TB = HERE / 'clock_rate_cleanup_tb.sv'
PASS = 'CLOCK_RATE_CLEANUP_PASS'


def sources(guest_only=False):
    paths = [BASE, HERE / 'i1_msi_epoch.S', HERE / 'i1_msi_epoch.ld', Path(__file__).resolve()]
    if not guest_only:
        paths += [TB, FIXTURE, REAL_FIXTURE, ROOT / 'build.mill', ROOT / 'scripts/cloud/env.sh']
        paths += sorted((ROOT / 'src/main/scala').rglob('*.scala'))
        paths += sorted((ROOT / 'src/main/resources').rglob('*.sv'))
    return {str(path.relative_to(ROOT)): base.sha(path) for path in paths}


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
    record = dict(status='RUNNING', source_sha256=frozen, tools={}, cases=[],
        scope='actual opt-in ClockRateControl and shared epoch adapter plus real I1/Home/APLIC/IMSIC; r10 initial drain watchdog plus controller first-held full-qualification watchdog; synthetic boot gate/lock model only, full drainAcks zero, no runtime gate or rate-program action; terminal plus fabric retirement required; no physical qualification',
        ledger_boundary='MSI delivery counted at CPU IMSIC request.fire; reply counted at fabric APLIC response.fire; independent guest retirement PCs and physical source transitions; asynchronous counters compared only at stable checkpoints')
    try:
        base.guest(out, args.cross_prefix, record)
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
                'platform.CommonClockRateCleanupNativeMain', rtl], out, 'emit', 600, record)
            if rc:
                raise RuntimeError('real three-clock fixture emission failed')
        else:
            rtl = args.rtl_dir.resolve()
        files = sorted(rtl.glob('*.sv'))
        if not files:
            raise RuntimeError('missing original emitted RTL')
        text = '\n'.join(path.read_text() for path in files)
        required = ['module CommonClockRateCleanupFixture', 'module CommonI1RuntimeCleanupFixture', 'module ClockRateControl', 'module CommonClockRateEpochAdapter', 'module CommonCpuClockBoundary',
                    'module CommonRuntimeEpochBoundary', '$fatal', 'io_msiAccepted11', 'io_msiReplied']
        if any(name not in text for name in required):
            raise RuntimeError('real three-clock RTL or inline production assertions missing')
        rtl_hashes = {path.name: base.sha(path) for path in files}
        record['rtl_sha256'] = rtl_hashes
        if not args.emit:
            receipt = json.loads(args.emission_receipt.read_text())
            if receipt.get('status') not in ('PASS', 'PASS_EMIT_ONLY'):
                raise RuntimeError('passing emission receipt required')
            required_sources = {name: digest for name, digest in frozen.items()
                if name.startswith(('src/main/scala/', 'src/main/resources/')) or name in (str(FIXTURE.relative_to(ROOT)), str(REAL_FIXTURE.relative_to(ROOT)))}
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
        rc, _ = base.run([tools['iverilog'], '-g2012', '-I', out, '-s', 'clock_rate_cleanup_tb',
            '-o', binary, *files, TB], out, 'compile', 600, record)
        if rc:
            raise RuntimeError('native compile failed')
        record['sim_sha256'] = base.sha(binary)
        command = [tools['vvp'], binary, '+rom=' + str(out / 'guest.hex')]
        record['clock_cases'] = [dict(name='unrelated', half_period_ns=[5, 7, 11], phase_ns=[0, 2, 3]),
                                 dict(name='reversed', half_period_ns=[11, 5, 7], phase_ns=[0, 2, 3])]
        record['clock_cases'] += [dict(name='qualification-' + name, half_period_ns=periods, phase_ns=[0, 2, 3], qualification_timeout_aon_edges=64)
                                  for name, periods in [('unrelated', [5, 7, 11]), ('reversed', [11, 5, 7])]]
        record['ledgers'] = []
        for name, periods in [('unrelated', (5, 7, 11)), ('reversed', (11, 5, 7))]:
            case = command + [f'+cpu-half={periods[0]}', f'+fabric-half={periods[1]}', f'+aon-half={periods[2]}']
            rc, log = base.run(case, out, name, 1200, record)
            if rc or PASS not in log:
                raise RuntimeError('real three-clock positive failed: ' + name)
            record['ledgers'] += [dict(case=name, line=line) for line in log.splitlines()
                                  if line.startswith('CLOCK_RATE_CLEANUP_')]
        for name, periods in [('qualification-unrelated', (5, 7, 11)), ('qualification-reversed', (11, 5, 7))]:
            case = command + ['+qualification', f'+cpu-half={periods[0]}', f'+fabric-half={periods[1]}', f'+aon-half={periods[2]}']
            rc, log = base.run(case, out, name, 300, record)
            if rc or 'CLOCK_RATE_QUALIFICATION_PASS' not in log:
                raise RuntimeError('real held-to-qualification cancellation failed: ' + name)
            record['ledgers'] += [dict(case=name, line=line) for line in log.splitlines()
                                  if line.startswith(('CLOCK_RATE_CLEANUP_', 'CLOCK_RATE_QUALIFICATION_'))]
        for negative, marker in [('wrong-data', 'independent load data oracle'),
                                 ('wrong-store', 'independent previous-store persistence oracle'),
                                 ('wrong-irq', 'independent IMSIC pending oracle')]:
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
