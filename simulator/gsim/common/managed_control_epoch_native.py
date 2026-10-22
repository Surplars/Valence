#!/usr/bin/env python3
"""Native managed-control epochs using the r19 TX guest plus one real TX restart.

The real managed GMAC/control/MDIO bank extends the eight-clock I1/Home/AXI
fixture. Only original emitted RTL and native Icarus/VVP are accepted. Emission
is explicit and requires a separately coordinated shared Mill slot. This is
normal/cancel TX epoch coverage, not fullACK, clock-gate ACK, DRP/backend, physical
PHY timing, or routed/board qualification. The external AXI RAM and Clause22
pin responder are test models. Children default to hard 180s bounds; one explicitly
selected normal/unrelated case may use its separately approved wall budget:
600s for the original same-clock bootstrap or 300s for preboot acceleration.
"""

import argparse
import datetime
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time
import types


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
FIXED_RUNNER = HERE / 'i1_runtime_fixed_native.py'
spec = importlib.util.spec_from_file_location('unchanged_r19_fixed_guest', FIXED_RUNNER)
fixed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixed)
base = fixed.base
COMPARISON = HERE / 'managed_control_epoch_compare.py'
compare_spec = importlib.util.spec_from_file_location('managed_epoch_architectural_compare', COMPARISON)
comparison = importlib.util.module_from_spec(compare_spec)
compare_spec.loader.exec_module(comparison)

FIXTURE = ROOT / 'src/test/scala/platform/CommonManagedControlEpochMain.scala'
INHERITED_FIXTURES = tuple(ROOT / 'src/test/scala/platform' / name for name in (
    'CommonI1RuntimeFixedMain.scala',
    'CommonI1RuntimeNetworkMain.scala',
    'CommonI1RuntimeDebugMain.scala',
    'CommonI1RuntimeCdcMain.scala',
))
MANAGED_FIXTURE_SUPPORT = tuple(ROOT / 'src/test/scala/ip' / name for name in (
    'ManagedRuntimeControlMain.scala', 'ManagedPeripherals.scala',
))
TB = HERE / 'managed_control_epoch_tb.sv'
PHY_MODEL = ROOT / 'simulator/cdc/rtl8211f_pin_model.sv'
TOP = 'managed_control_epoch_tb'
EMITTER = 'platform.CommonManagedControlEpochNativeMain'
PASS = 'MANAGED_CONTROL_EPOCH_PASS'
MAX_CHILD_SECONDS = 180.0
SYMBOLS = tuple(fixed.SYMBOLS)
MANAGED_SYMBOLS = (*SYMBOLS, 'managed_tx_restart')
SCENARIOS = {'normal': 0, 'cancel': 1}
CLOCKS = ('cpu', 'fabric', 'aon', 'debug', 'rx', 'tx', 'ddr', 'timebase')
CLOCK_CASES = {
    'unrelated': (5, 7, 11, 13, 17, 3, 19, 23),
    'reversed': (11, 5, 7, 3, 17, 2, 13, 19),
}
NEGATIVES = {
    'tx-payload': (1, 'NETWORK_ORACLE_PAYLOAD', 'FIXED_NEGATIVE_OBSERVATION TX'),
    'control-csr-drain': (5, 'MANAGED_CONTROL_ORACLE_CSR_DRAIN',
                          'MANAGED_CONTROL_NEGATIVE_OBSERVATION CSR_DRAIN'),
    'retained-statistics': (6, 'MANAGED_CONTROL_ORACLE_STATISTICS',
                            'MANAGED_CONTROL_NEGATIVE_OBSERVATION STATISTICS'),
    'park-retention': (7, 'MANAGED_CONTROL_ORACLE_PARK_RETENTION',
                       'MANAGED_CONTROL_NEGATIVE_OBSERVATION PARK_RETENTION'),
}
REQUIRED_MODULES = (
    'CommonManagedControlEpochFixture', 'CommonCpuClockBoundary',
    'CommonRuntimeEpochBoundary', 'CommonDebugRuntimeSequencer',
    'DebugDmiAdmissionBoundary', 'JtagRamLoader', 'CommonNetworkRuntimeSequencer',
    'EthernetPacketDma', 'ManagedPeripheralBank', 'TriSpeedManagedGmac', 'RegisterGmacControl',
    'ManagedMdioArbiter', 'MdioClause22', 'Rtl8211fPhyManager',
    'GmiiFrameRx', 'QueuedGmiiFrameTx', 'TileLinkAxi4Bridge',
    'Axi4ClockDomainBoundary', 'RuntimeFixedTimebaseBoundary', 'MachineTimer',
    'CommonFixedDomainEpochQualifier', 'CommonControlParkEpochSequencer',
)
REQUIRED_ASSERTIONS = (
    'network runtime prepare changed before actual acceptance',
    'network epoch retired before actual admission release',
    'fabric epoch retired before fixed-domain consumed retirement receipt',
    'fixed fixture B before accepted WLAST',
    'PHY sequence released MDIO before command completed',
    'TX published into an owned bank',
)


def negative_selection(value):
    aliases = {str(item[0]): name for name, item in NEGATIVES.items()}
    names = [aliases.get(item, item) for item in value.split(',')]
    if len(names) != len(set(names)) or any(name not in NEGATIVES for name in names):
        raise argparse.ArgumentTypeError(
            'use distinct comma-separated names or IDs: ' + ', '.join(
                f'{name}={item[0]}' for name, item in NEGATIVES.items()))
    return names


def kill_group(child):
    try:
        os.killpg(child.pid, signal.SIGKILL)
        return True
    except ProcessLookupError:
        return False


def checkpoint(output, record):
    temporary = output / 'receipt.partial.json'
    temporary.write_text(json.dumps(record, indent=2) + '\n')
    temporary.replace(output / 'receipt.json')


def run(command, output, name, timeout, record):
    """Bound, kill leftover descendants, and reap every subprocess on all exits."""
    approved = record.get('approved_normal_wall_budget_seconds')
    matrix_budget = record.get('approved_case_wall_budgets', {}).get(name)
    ceiling = (float(matrix_budget) if matrix_budget else
               float(approved) if name == 'unrelated-tx-normal' and
               ((approved == 300 and record.get('bootstrap_accelerated')) or
                (approved == 600 and not record.get('bootstrap_accelerated'))) else MAX_CHILD_SECONDS)
    if not math.isfinite(timeout) or not 0 < timeout <= ceiling:
        raise ValueError('child timeout exceeds its explicitly selected wall budget')
    command = list(map(str, command))
    started = time.monotonic()
    minimum_free = shutil.disk_usage(output).free
    if minimum_free < base.FLOOR:
        raise RuntimeError('4 GiB disk floor before ' + name)
    child = None
    timed_out = disk_bound = interrupted = killed = stop_requested = False
    log_path = output / (name + '.log')
    try:
        with log_path.open('w') as log:
            child = subprocess.Popen(command, cwd=ROOT, stdout=log,
                                     stderr=subprocess.STDOUT, start_new_session=True)
            record['active_subprocess'] = dict(name=name, pid=child.pid, process_group=os.getpgid(child.pid),
                                               started_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                               command=command, timeout_seconds=timeout)
            checkpoint(output, record)
            deadline = started + timeout
            while child.poll() is None:
                if (output / 'stop.request').exists():
                    stop_requested = True
                    record['stop_request'] = (output / 'stop.request').read_text()
                    raise KeyboardInterrupt('controlled stop-file request')
                minimum_free = min(minimum_free, shutil.disk_usage(output).free)
                timed_out = time.monotonic() >= deadline
                disk_bound = minimum_free < base.FLOOR
                if timed_out or disk_bound:
                    killed = kill_group(child) or killed
                    break
                time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
            child.wait()
    except BaseException:
        interrupted = True
        raise
    finally:
        if child is not None:
            # Even if the leader exited, no process-group descendant may survive.
            killed = kill_group(child) or killed
            child.wait()
            record['cases'].append(dict(
                name=name, command=command, pid=child.pid, process_group=child.pid, returncode=child.returncode,
                stop_reason=record.get('stop_request') if stop_requested else None,
                elapsed_seconds=time.monotonic() - started, timeout_seconds=timeout,
                minimum_free_bytes=minimum_free, timed_out=timed_out,
                disk_bound=disk_bound, process_group_killed=killed,
                interrupted=interrupted, stop_requested=stop_requested, child_reaped=True))
            record.pop('active_subprocess', None)
            checkpoint(output, record)
    if timed_out or disk_bound:
        raise RuntimeError('wall-clock or disk resource bound: ' + name)
    return child.returncode, log_path.read_text()


def sources(guest_only=False):
    paths = [Path(__file__).resolve(), COMPARISON, FIXED_RUNNER, fixed.BASE,
             HERE / 'i1_runtime_network.S', HERE / 'i1_runtime_network.ld']
    if not guest_only:
        paths += [TB, PHY_MODEL, FIXTURE, *INHERITED_FIXTURES, *MANAGED_FIXTURE_SUPPORT,
                  ROOT / 'build.mill', ROOT / 'scripts/cloud/env.sh']
        paths += sorted((ROOT / 'src/main/scala').rglob('*.scala'))
        paths += sorted((ROOT / 'src/main/resources').rglob('*.sv'))
    return {str(path.relative_to(ROOT)): base.sha(path) for path in paths}


def emission_sources(frozen):
    fixtures = {str(path.relative_to(ROOT)) for path in
                (FIXTURE, *INHERITED_FIXTURES, *MANAGED_FIXTURE_SUPPORT)}
    return {name: digest for name, digest in frozen.items()
            if name.startswith(('src/main/scala/', 'src/main/resources/'))
            or name in fixtures or name == 'build.mill'}


def guest(output, prefix, record, timeout=MAX_CHILD_SECONDS):
    # Reuse the exact r19 generator function body in an isolated namespace.
    # Only its input copy gains a real CPU descriptor restart after the existing
    # readback checkpoint. The original files/globals remain unchanged, and nm
    # supplies every symbol, including the restart store; no PC is patched.
    original = (HERE / 'i1_runtime_network.S').read_text()
    needle = 'net_checked:\n    addi s5, zero, 1\n4:\n'
    replacement = ('net_checked:\n    addi s5, zero, 1\n    li t1, 3\n'
                   '.globl managed_tx_restart\nmanaged_tx_restart:\n'
                   '    sd t1, 32(s0)\n4:\n')
    if original.count(needle) != 1:
        raise RuntimeError('r19 TX restart insertion checkpoint changed')
    inputs = output / 'guest-inputs'
    inputs.mkdir()
    amended = inputs / 'i1_runtime_network.S'
    amended.write_text(original.replace(needle, replacement))
    linker = inputs / 'i1_runtime_network.ld'
    linker.write_bytes((HERE / 'i1_runtime_network.ld').read_bytes())
    def run_guest(command, output, name, requested_timeout, record):
        return run(command, output, name, min(requested_timeout, timeout), record)

    namespace = dict(vars(fixed), HERE=inputs, run=run_guest, SYMBOLS=MANAGED_SYMBOLS)
    generator = types.FunctionType(fixed.guest.__code__, namespace, fixed.guest.__name__,
                                   fixed.guest.__defaults__, fixed.guest.__closure__)
    generator(output, prefix, record)
    if tuple(fixed.SYMBOLS) != SYMBOLS or set(record['guest']['symbols']) != set(MANAGED_SYMBOLS):
        raise RuntimeError('managed guest symbol contract was modified')
    record['guest']['generator'] = str(FIXED_RUNNER.relative_to(ROOT))
    record['guest']['generator_sha256'] = base.sha(FIXED_RUNNER)
    record['guest']['amendment'] = 'one CPU TX completion ACK|START=3 after net_checked; original r19 body retained'
    record['guest']['artifacts'].update({str(path.relative_to(output)): base.sha(path)
                                       for path in (amended, linker)})
    record['guest']['symbols_immutable'] = True


def check_inputs(frozen, record, output, guest_only=False, files=()):
    if sources(guest_only) != frozen:
        raise RuntimeError('source drift during managed-control qualification')
    if files and record['rtl_sha256'] != {path.name: base.sha(path) for path in files}:
        raise RuntimeError('original emitted RTL drift during native test')
    for name, info in record['tools'].items():
        if base.sha(info['path']) != info['sha256']:
            raise RuntimeError('tool drift: ' + name)
    for name, digest in record['guest']['artifacts'].items():
        if base.sha(output / name) != digest:
            raise RuntimeError('immutable guest artifact drift: ' + name)


def completed_case_checkpoint(output, record, label, frozen, files, binary, status):
    """Preserve each finished case before starting another long native child."""
    check_inputs(frozen, record, output, files=files)
    if base.sha(binary) != record['sim_sha256']:
        raise RuntimeError('native simulation binary drift at case checkpoint')
    snapshot = dict(record, status=status, completed_case=label,
                    logs_sha256={path.name: base.sha(path) for path in output.glob('*.log')})
    path = output / ('case-' + label + '.json')
    if path.exists():
        raise RuntimeError('case checkpoint would overwrite an existing record')
    path.write_text(json.dumps(snapshot, indent=2) + '\n')
    record.setdefault('case_checkpoints', {})[label] = dict(path=path.name, sha256=base.sha(path))
    checkpoint(output, record)
    print(status + ' case=' + label + ' elapsed=' + str(record['cases'][-1]['elapsed_seconds']), flush=True)


def main():
    def interrupt(signum, frame):
        raise KeyboardInterrupt('signal ' + str(signum))

    signal.signal(signal.SIGTERM, interrupt)
    signal.signal(signal.SIGINT, interrupt)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--prepare-only', action='store_true', help='build the r19 guest with TX restart only')
    parser.add_argument('--emit-only', action='store_true', help='with --emit, stop after RTL emission')
    parser.add_argument('--single-ratio', choices=CLOCK_CASES)
    parser.add_argument('--scenario', choices=SCENARIOS,
                        help='run only this TX epoch scenario; default runs normal and cancel')
    parser.add_argument('--negative-only', type=negative_selection,
                        help='only named/numbered observation negatives, using normal TX')
    parser.add_argument('--timeout', type=float, default=MAX_CHILD_SECONDS,
                        help='per-child wall bound in seconds, at most 180 (default: 180)')
    parser.add_argument('--normal-wall-budget', type=int, choices=[300, 600],
                        help='separately approved wall-only budget for one normal/unrelated case; no DUT timing changes')
    parser.add_argument('--bootstrap-accelerate', action='store_true',
                        help='test-only preboot source scheduling; permanently rejoin fabric before real traffic')
    parser.add_argument('--baseline-receipt', type=Path,
                        help='preserved passing same-clock normal receipt, required for accelerated comparison')
    parser.add_argument('--remaining-matrix', action='store_true',
                        help='remaining three positives and four negatives after normal/unrelated qualification')
    parser.add_argument('--bootstrap-qualification', type=Path,
                        help='passing accelerated normal/unrelated receipt, independently re-compared before matrix')
    parser.add_argument('--cross-prefix', default='riscv64-unknown-elf-')
    parser.add_argument('--iverilog', default=os.environ.get('IVERILOG', 'iverilog'))
    parser.add_argument('--vvp', default=os.environ.get('VVP', 'vvp'))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--emit', action='store_true', help='explicitly use the coordinated Mill slot')
    mode.add_argument('--rtl-dir', type=Path)
    parser.add_argument('--emission-receipt', type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    if out.exists() or not out.parent.is_dir():
        parser.error('fresh output directory with existing parent required')
    if not math.isfinite(args.timeout) or not 0 < args.timeout <= MAX_CHILD_SECONDS:
        parser.error('--timeout must be finite and in (0, 180] seconds')
    if not args.prepare_only and not (args.emit or (args.rtl_dir and args.emission_receipt)):
        parser.error('use --emit or --rtl-dir with --emission-receipt')
    if args.emit_only and not args.emit:
        parser.error('--emit-only requires --emit')
    if args.prepare_only and (args.emit or args.rtl_dir or args.emit_only or args.emission_receipt):
        parser.error('--prepare-only cannot be combined with RTL emission/reuse')
    if args.negative_only and args.scenario is not None:
        parser.error('--negative-only selects normal TX; omit --scenario')
    if args.emission_receipt and not args.rtl_dir:
        parser.error('--emission-receipt requires --rtl-dir')
    if not os.environ.get('VALENCE_CLOUD_ENV'):
        parser.error('source scripts/cloud/env.sh before running this test')

    out.mkdir()
    if args.normal_wall_budget and (args.scenario != 'normal' or args.single_ratio != 'unrelated' or
                                   args.negative_only or args.prepare_only or args.emit):
        parser.error('--normal-wall-budget requires exactly --scenario normal --single-ratio unrelated with existing RTL')
    if args.remaining_matrix and (not args.bootstrap_accelerate or not args.bootstrap_qualification or
            not args.baseline_receipt or args.single_ratio or args.scenario or args.negative_only or
            args.normal_wall_budget or args.prepare_only or args.emit):
        parser.error('--remaining-matrix requires existing RTL, bootstrap acceleration, original baseline and qualified receipt only')
    if args.bootstrap_qualification and not args.remaining_matrix:
        parser.error('--bootstrap-qualification requires --remaining-matrix')
    if args.bootstrap_accelerate and not args.emit_only and not args.remaining_matrix and (
            args.scenario != 'normal' or args.single_ratio != 'unrelated' or args.negative_only or
            args.prepare_only or args.normal_wall_budget not in (None, 300) or not args.baseline_receipt):
        parser.error('--bootstrap-accelerate currently permits only normal/unrelated with --baseline-receipt and optional approved 300s wall budget')
    if args.normal_wall_budget == 300 and not args.bootstrap_accelerate:
        parser.error('--normal-wall-budget 300 requires --bootstrap-accelerate')
    if args.baseline_receipt and not args.bootstrap_accelerate:
        parser.error('--baseline-receipt requires --bootstrap-accelerate')
    subset = args.single_ratio is not None or args.scenario is not None or bool(args.negative_only) or args.remaining_matrix
    matrix_budgets = ({'unrelated-tx-cancel': 180, 'reversed-tx-normal': 300,
                       'reversed-tx-cancel': 180, 'negative-tx-payload': 180,
                       'negative-control-csr-drain': 180, 'negative-retained-statistics': 300,
                       'negative-park-retention': 300} if args.remaining_matrix else {})
    record = dict(
        status='RUNNING', source_sha256={}, tools={}, cases=[], ledgers=[], negative_controls=[],
        fixture=FIXTURE.name, top=TOP, emitter=EMITTER,
        native_case_timeout_seconds=args.timeout,
        maximum_child_timeout_seconds=max(MAX_CHILD_SECONDS, args.normal_wall_budget or 0, *matrix_budgets.values()),
        approved_case_wall_budgets=matrix_budgets,
        remaining_matrix_budget_scope=('measured phase cost after 229.611-second qualified normal; only named cases receive 300s wall time; no DUT/MDIO/guest/epoch timing changes' if args.remaining_matrix else None),
        default_child_timeout_seconds=MAX_CHILD_SECONDS,
        approved_normal_wall_budget_seconds=args.normal_wall_budget,
        wall_budget_reason=('accelerated 180s attempt was killed/reaped after real 51-transaction initialization and first packet; '
                           'only one normal/unrelated comparison receives 300s wall time; no DUT/MDIO/guest timeout changes'
                           if args.normal_wall_budget == 300 else
                           'original 180s fully concurrent and bootstrap-paused cases were killed/reaped; '
                           'real MDIO initialization requires at least 51 full Clause22 transactions and 261120 fabric cycles; '
                           'only normal/unrelated native wall budget is extended, no DUT/MDIO/guest timeout changes'
                           if args.normal_wall_budget else None),
        fixture_runtime_timeout_aon_cycles=dict(drain=65536, cleanup=65536,
                                               timeout_scenario_exercised=False),
        fixture_phy_policy_wait_cycles=dict(startup=256, poll=512,
                                           mdio_divider_and_transactions_unchanged=True),
        requested_subset=dict(tx_guest_case=3, scenario=args.scenario,
                              single_ratio=args.single_ratio, full_matrix=not subset,
                              remaining_qualified_matrix=args.remaining_matrix,
                              negative_only=args.negative_only or []),
        bootstrap_accelerated=args.bootstrap_accelerate,
        initialization_clock_scope=(
            'after actual reset releases and pre-owner park, fabric/CPU/UI/timer/debug pause low; '
            'real bank source and Clause22 pin model run at unchanged fabric period with rawTX/rawRX/AON; '
            'actual PHY parked/page-zero/config/MDIO idle then low-phase permanent fabric rejoin; '
            'real released receipt precedes ROM/CSR/guest; no runtime clock topology change'
            if args.bootstrap_accelerate else
            'after common reset release and ROM load, CPU/UI/timer clocks pause while start=false; '
            'fabric/MDIO/AON/rawTX/rawRX unchanged; all eight resume before guest and epochs'),
        scope='real managed GMAC/control/MDIO bank over real I1/private caches/Atomic/Home/packet DMA; '
              'eight clocks; r19 TX guest with one real CPU post-retirement TX restart; normal/cancel epochs; fixed DDR UI '
              'transport and real timer MMIO; external AXI RAM and Clause22 pin responder modeled',
        exclusions=['fullACK clock-manager transition', 'stopped-clock or clock-gate ACK proof',
                    'DRP/backend', 'MIG or physical PHY timing', 'routed/board qualification',
                    'RX payload scenarios', 'timeout scenario', 'eight-clock concurrent PHY initialization'],
        ledger_boundary='actual packet/AXI ownership, TX bytes and status tail, real control CSR '
                        'request/reply, MDIO owners, retained statistics, park retention, '
                        'AON result and fabric terminal; only stable checkpoints compare counters')
    try:
        if args.baseline_receipt:
            baseline_path = args.baseline_receipt.resolve()
            baseline = json.loads(baseline_path.read_text())
            if (baseline.get('status') != 'PASS_SELECTED_CASES' or
                    baseline.get('requested_subset', {}).get('scenario') != 'normal' or
                    baseline.get('requested_subset', {}).get('single_ratio') != 'unrelated' or
                    baseline.get('bootstrap_accelerated', False)):
                raise RuntimeError('passing original same-clock normal/unrelated baseline required')
            record['preserved_same_clock_baseline'] = dict(
                path=str(baseline_path), sha256=base.sha(baseline_path),
                source_count=len(baseline['source_sha256']),
                comparison_scope='architectural packet/control/epoch ledgers; timer/AXI phase counts may differ')
        if args.bootstrap_qualification:
            qualification_path = args.bootstrap_qualification.resolve()
            qualification = json.loads(qualification_path.read_text())
            baseline_log = baseline_path.parent / 'unrelated-tx-normal.log'
            qualified_log = qualification_path.parent / 'unrelated-tx-normal.log'
            for receipt, log in ((baseline, baseline_log), (qualification, qualified_log)):
                if base.sha(log) != receipt['logs_sha256'][log.name]:
                    raise RuntimeError('qualification log drift')
            comparison_result = comparison.compare(baseline, qualification,
                baseline_log.read_text().splitlines(), qualified_log.read_text().splitlines())
            record['bootstrap_qualification'] = dict(path=str(qualification_path),
                sha256=base.sha(qualification_path), comparison=comparison_result)
        frozen = sources(args.prepare_only)
        record['source_sha256'] = frozen
        if args.baseline_receipt:
            production = {name: digest for name, digest in frozen.items()
                          if name.startswith(('src/main/scala/', 'src/main/resources/'))}
            baseline_production = {name: digest for name, digest in baseline['source_sha256'].items()
                                   if name.startswith(('src/main/scala/', 'src/main/resources/'))}
            if baseline_production != production:
                raise RuntimeError('production-source drift from preserved same-clock baseline')
            record['preserved_same_clock_baseline']['unchanged_production_source_count'] = len(production)
        if args.bootstrap_qualification:
            bound_inputs = dict(emission_sources(frozen), **{str(TB.relative_to(ROOT)): frozen[str(TB.relative_to(ROOT))],
                                str(PHY_MODEL.relative_to(ROOT)): frozen[str(PHY_MODEL.relative_to(ROOT))]})
            if any(qualification['source_sha256'].get(name) != digest for name, digest in bound_inputs.items()):
                raise RuntimeError('current fixture/bench/production differs from qualified bootstrap')
        guest(out, args.cross_prefix, record, args.timeout)
        if args.bootstrap_qualification:
            if qualification['guest']['symbols'] != record['guest']['symbols'] or any(
                    qualification['guest']['artifacts'][name] != record['guest']['artifacts'][name]
                    for name in ('guest.bin', 'guest.hex', 'guest_symbols.svh')):
                raise RuntimeError('guest differs from qualified bootstrap')
        if args.prepare_only:
            check_inputs(frozen, record, out, guest_only=True)
            record['status'] = 'PASS_GUEST_ONLY'
            return

        for path in (TB, PHY_MODEL, FIXTURE, *INHERITED_FIXTURES, *MANAGED_FIXTURE_SUPPORT,
                     Path(__file__).resolve(), COMPARISON,
                     FIXED_RUNNER, fixed.BASE, HERE / 'i1_runtime_network.S',
                     HERE / 'i1_runtime_network.ld'):
            (out / ('source-' + path.name)).write_bytes(path.read_bytes())
        native = {name: base.tool(getattr(args, name)) for name in ('iverilog', 'vvp')}
        record['tools'].update(base.tool_hashes(native))
        if args.emit:
            mill = base.tool('mill')
            record['tools'].update(base.tool_hashes({'mill': mill}))
            rtl = out / 'rtl'
            rc, _ = run([mill, '--no-server', 'IonSoC.test.runMain', EMITTER, rtl],
                        out, 'emit', args.timeout, record)
            if rc:
                raise RuntimeError('managed-control fixture emission failed; see emit.log')
        else:
            rtl = args.rtl_dir.resolve()
        files = sorted(rtl.glob('*.sv'))
        if not files:
            raise RuntimeError('missing original emitted RTL')
        emitted = '\n'.join(path.read_text() for path in files)
        missing = [name for name in REQUIRED_MODULES if 'module ' + name not in emitted]
        if missing or '$fatal' not in emitted:
            raise RuntimeError('real managed-control RTL/assertions missing: ' + ', '.join(missing))
        record['rtl_sha256'] = {path.name: base.sha(path) for path in files}
        if args.bootstrap_qualification and qualification['rtl_sha256'] != record['rtl_sha256']:
            raise RuntimeError('RTL differs from qualified bootstrap')
        record['model_sha256'] = {str(PHY_MODEL.relative_to(ROOT)): base.sha(PHY_MODEL)}
        if not args.emit:
            receipt_path = args.emission_receipt.resolve()
            receipt = json.loads(receipt_path.read_text())
            if receipt.get('status') not in (
                    'PASS', 'PASS_EMIT_ONLY', 'PASS_SELECTED_CASES', 'PASS_SELECTED_NEGATIVES'):
                raise RuntimeError('passing original managed-control emission receipt required')
            if any(receipt.get('source_sha256', {}).get(name) != digest
                   for name, digest in emission_sources(frozen).items()):
                raise RuntimeError('emission not bound to current production and all inherited fixture sources')
            if receipt.get('rtl_sha256') != record['rtl_sha256']:
                raise RuntimeError('emitted RTL hash mismatch')
            record['emission_receipt'] = dict(path=str(receipt_path), sha256=base.sha(receipt_path))
        if args.emit_only:
            check_inputs(frozen, record, out, files=files)
            record['status'] = 'PASS_EMIT_ONLY'
            return

        defines = ['-g2012', '-DSTOP_COND=1', '-DASSERT_VERBOSE_COND=1']
        preprocessed = out / 'preprocessed.sv'
        rc, _ = run([native['iverilog'], *defines, '-E', '-o', preprocessed, *files],
                    out, 'preprocess', args.timeout, record)
        if rc:
            raise RuntimeError('native preprocessing failed; see preprocess.log')
        preprocessed_text = preprocessed.read_text()
        if '$fatal' not in preprocessed_text or any(
                message not in preprocessed_text for message in REQUIRED_ASSERTIONS):
            raise RuntimeError('inline production protocol assertions are not enabled')
        record['production_assertions'] = dict(
            preprocessed_sha256=base.sha(preprocessed),
            inline_fatal_sites=preprocessed_text.count('$fatal'),
            required_messages=list(REQUIRED_ASSERTIONS))
        binary = out / 'sim.vvp'
        rc, _ = run([native['iverilog'], *defines, '-I', out, '-s', TOP,
                     '-o', binary, *files, PHY_MODEL, TB], out, 'compile', args.timeout, record)
        if rc:
            raise RuntimeError('native Icarus compile failed; see compile.log')
        record['sim_sha256'] = base.sha(binary)
        command = [native['vvp'], '-i', binary, '+rom=' + str(out / 'guest.hex'), '+case=3',
                   '+bootstrap-accelerate=' + str(int(args.bootstrap_accelerate))]
        ratios = [args.single_ratio] if args.single_ratio else list(CLOCK_CASES)
        scenarios = [args.scenario] if args.scenario else list(SCENARIOS)
        record['clock_cases'] = [dict(name=name, half_period_ns=list(CLOCK_CASES[name]))
                                 for name in (ratios if not args.negative_only
                                              else [args.single_ratio or 'unrelated'])]
        positive_selection = ([('unrelated', 'cancel'), ('reversed', 'normal'), ('reversed', 'cancel')]
                              if args.remaining_matrix else
                              [(ratio, scenario) for ratio in ratios for scenario in scenarios])
        if not args.negative_only:
            for ratio, scenario in positive_selection:
                clock_args = [f'+{clock}-half={period}'
                              for clock, period in zip(CLOCKS, CLOCK_CASES[ratio])]
                label = f'{ratio}-tx-{scenario}'
                rc, log = run(command + clock_args + [f'+managed-scenario={SCENARIOS[scenario]}'],
                              out, label, matrix_budgets.get(label, args.normal_wall_budget or args.timeout), record)
                if rc or PASS not in log:
                    raise RuntimeError('managed-control positive failed: ' + label)
                record['ledgers'] += [dict(case=label, line=line) for line in log.splitlines()
                                      if line.startswith(('MANAGED_CONTROL_', 'I1_RUNTIME_FIXED_',
                                                          'I1_FIXED_', 'I1_PACKET_'))]
                completed_case_checkpoint(out, record, label, frozen, files, binary, 'PASS_POSITIVE_CASE')

        selected_negatives = (list(NEGATIVES) if args.remaining_matrix else
                              args.negative_only or ([] if subset else list(NEGATIVES)))
        negative_ratio = args.single_ratio or 'unrelated'
        clock_args = [f'+{clock}-half={period}'
                      for clock, period in zip(CLOCKS, CLOCK_CASES[negative_ratio])]
        for name in selected_negatives:
            number, rejection, injection = NEGATIVES[name]
            label = 'negative-' + name
            rc, log = run(command + clock_args + ['+managed-scenario=0', f'+negative={number}'],
                          out, label, matrix_budgets.get(label, args.timeout), record)
            if rc == 0 or rejection not in log or injection not in log or PASS in log:
                raise RuntimeError('independent observation negative not rejected: ' + name)
            record['negative_controls'].append(dict(
                name=name, tx_guest_case=3, scenario='normal', clock_ratio=negative_ratio,
                negative=number, expected_rejection=rejection, observation_injection=injection,
                injection_and_rejection_lines=[line for line in log.splitlines()
                                               if injection in line or rejection in line],
                result='PASS_EXPECTED_REJECTION'))
            completed_case_checkpoint(out, record, label, frozen, files, binary, 'PASS_NEGATIVE_CONTROL')

        check_inputs(frozen, record, out, files=files)
        if base.sha(binary) != record['sim_sha256']:
            raise RuntimeError('native simulation binary drift')
        if args.baseline_receipt and base.sha(args.baseline_receipt.resolve()) != record['preserved_same_clock_baseline']['sha256']:
            raise RuntimeError('preserved baseline receipt drift')
        if args.baseline_receipt:
            record['preserved_same_clock_baseline']['receipt_hash_preserved'] = True
        if args.bootstrap_qualification and base.sha(qualification_path) != record['bootstrap_qualification']['sha256']:
            raise RuntimeError('bootstrap qualification receipt drift')
        record['status'] = ('PASS_REMAINING_MATRIX' if args.remaining_matrix else
                            'PASS_SELECTED_NEGATIVES' if args.negative_only else
                            'PASS_SELECTED_CASES' if subset else 'PASS')
    except BaseException as error:
        record.update(status=('INTERRUPTED_KNOWN_TEST_STIMULUS_ERRORS' if record.get('stop_request') else 'FAIL'), error=repr(error))
        raise
    finally:
        record['logs_sha256'] = {path.name: base.sha(path) for path in out.glob('*.log')}
        (out / 'receipt.json').write_text(json.dumps(record, indent=2) + '\n')
        print(record['status'] + ' receipt=' + str(out / 'receipt.json'), flush=True)


if __name__ == '__main__':
    main()
