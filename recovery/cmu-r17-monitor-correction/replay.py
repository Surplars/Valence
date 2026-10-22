#!/usr/bin/env python3
"""Replay only three corrected observation-side negatives on immutable r17 RTL.

This is historical monitor sensitivity, never current-production qualification.
No emission, guest rebuild, broad positive run, installation, or upload occurs.
"""
import argparse
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import shutil
import signal
import subprocess
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FLOOR = 4 * 1024**3
TIMEOUT = 180
TB_NAME = 'simulator/gsim/common/i1_runtime_network_tb.sv'
PASS = 'I1_RUNTIME_NETWORK_PASS'


def require(condition, reason):
    if not condition:
        raise RuntimeError(reason)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def verify(path, digest):
    require(Path(path).is_file() and sha(path) == digest, 'hash mismatch: ' + str(path))


def guard(path):
    free = shutil.disk_usage(path).free
    require(free >= FLOOR, '4 GiB free-space floor breached: ' + str(free))
    return free


def run(command, log):
    """Bound every process; always terminate descendants and reap the child."""
    started = time.monotonic()
    minimum = guard(log.parent)
    process = None
    timed_out = breached = killed = False

    def no_core():
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    try:
        with log.open('w') as stream:
            process = subprocess.Popen(command, cwd=ROOT, stdout=stream,
                                       stderr=subprocess.STDOUT,
                                       start_new_session=True, preexec_fn=no_core)
            while process.poll() is None:
                minimum = min(minimum, shutil.disk_usage(log.parent).free)
                breached = minimum < FLOOR
                timed_out = time.monotonic() - started >= TIMEOUT
                if breached or timed_out:
                    break
                time.sleep(0.05)
    finally:
        if process is not None:
            # Even a normally exited compiler must not leave a child behind.
            try:
                os.killpg(process.pid, signal.SIGKILL)
                killed = True
            except ProcessLookupError:
                pass
            process.wait()
    return dict(returncode=process.returncode, seconds=time.monotonic()-started,
                minimum_free_bytes=minimum, timed_out=timed_out,
                disk_floor_breached=breached, process_group_killed=killed,
                process_reaped=True, timeout_seconds=TIMEOUT)


def replace_once(text, old, new):
    require(text.count(old) == 1, 'positive projection missing/ambiguous: ' + old)
    return text.replace(old, new)


def positive_projection(text, corrected):
    """Exact, explicit negative=0 specialization plus local monitor-copy folding.

    This is a narrow source equivalence proof, not a generic SV optimizer. Each
    removed assignment is exclusively negative-gated; each folded alias is a
    blocking copy immediately before its ordinary checker, with no DUT writes.
    The existing negative=2 control is unchanged on both sides.
    """
    if corrected:
        for line in (
            '  reg [7:0] observedWireByte;\n',
            '  reg [63:0] observedPacketWord;\n',
            '        observedPacketWord=packetMemoryRequestData;\n',
            "        if(negative==1 && packetWordIndex==0) observedPacketWord=observedPacketWord^64'h1;\n",
            '      observedWireByte=gmiiTxData;\n',
            "      if(negative==1 && wirePosition==23) observedWireByte=observedWireByte^8'h1;\n",
            "      if(negative==3) data[63:32]=data[63:32]^32'h1;\n",
        ):
            text = replace_once(text, line, '')
        text = text.replace('observedPacketWord', 'packetMemoryRequestData')
        text = text.replace('observedWireByte', 'gmiiTxData')
    else:
        text = replace_once(text,
            '        if(negative==1 && packetWordIndex==0) expectedPacketWord=expectedPacketWord^1;\n', '')
        text = replace_once(text,
            '      if(negative==1 && wirePosition==23) expectedWireByte=expectedWireByte^1;\n', '')
        text = replace_once(text, "(negative==3 ? GUARD_DATA^32'h1 : GUARD_DATA)", 'GUARD_DATA')
    # Remove comments without touching quoted strings, then normalize whitespace
    # only outside strings. Every remaining token, including diagnostics, agrees.
    tokens = re.findall(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*[\s\S]*?\*/|[^\s]', text)
    return '\n'.join(t for t in tokens if not t.startswith(('//', '/*'))) + '\n'


def validate_inputs():
    manifest = json.loads((HERE/'manifest.json').read_text())
    baseline = ROOT/manifest['baseline_receipt']
    verify(baseline, manifest['baseline_receipt_sha256'])
    verify(HERE/'baseline-receipt.json', manifest['baseline_receipt_sha256'])
    old = json.loads(baseline.read_text())
    require(old['status'] == 'PASS', 'historical receipt not PASS')
    historical = baseline.parent
    for name, digest in manifest['bundle_sha256'].items():
        verify(HERE/name, digest)
    verify(HERE/'baseline_tb.source.sv', old['source_sha256'][TB_NAME])
    verify(historical/'testbench.source.sv', old['source_sha256'][TB_NAME])
    require((ROOT/TB_NAME).read_bytes() == (HERE/'corrected_tb.source.sv').read_bytes(),
            'working TB differs from corrected snapshot')
    for name, digest in old['logs_sha256'].items():
        verify(historical/name, digest)
    for name, digest in old['guest']['artifacts'].items():
        verify(historical/name, digest)
    verify(historical/'sim.vvp', old['sim_sha256'])
    verify(historical/'preprocessed.sv', old['production_assertions']['preprocessed_sha256'])
    for info in old['tools'].values():
        verify(info['path'], info['sha256'])
    emission_path = Path(old['emission_receipt']['path'])
    verify(emission_path, old['emission_receipt']['sha256'])
    verify(HERE/'baseline-emission-receipt.json', old['emission_receipt']['sha256'])
    emission = json.loads(emission_path.read_text())
    require(emission['status'] == 'PASS_EMIT_ONLY', 'historical emission not PASS_EMIT_ONLY')
    require(emission['rtl_sha256'] == old['rtl_sha256'], 'emission/native RTL inventory mismatch')
    command = list(next(c['command'] for c in old['cases'] if c['name'] == 'compile'))
    require(command.count(str(ROOT/TB_NAME)) == 1, 'missing/ambiguous historical TB')
    rtl = [Path(x) for x in command if x.endswith('.sv') and x != str(ROOT/TB_NAME)]
    require(len({p.parent for p in rtl}) == 1, 'multiple historical RTL roots')
    require(set(rtl) == set(rtl[0].parent.glob('*.sv')), 'historical compile file inventory changed')
    require({p.name: sha(p) for p in rtl} == old['rtl_sha256'], 'historical RTL content drift')
    require(command[:4] == [old['tools']['iverilog']['path'], '-g2012',
                           '-DSTOP_COND=1', '-DASSERT_VERBOSE_COND=1'],
            'unexpected compile tool/production assertion flags')
    require(command[command.index('-I')+1] == str(historical), 'unexpected guest symbol include')
    baseline_text = (HERE/'baseline_tb.source.sv').read_text()
    corrected_text = (HERE/'corrected_tb.source.sv').read_text()
    require(positive_projection(baseline_text, False) == positive_projection(corrected_text, True),
            'positive-mode token projection differs')
    patch = ''.join(difflib.unified_diff(baseline_text.splitlines(True), corrected_text.splitlines(True),
                                       fromfile='baseline_tb.source.sv', tofile='corrected_tb.source.sv'))
    require(patch == (HERE/'monitor-only.patch').read_text(), 'monitor patch mismatch')
    for label in ('negative-1', 'negative-3'):
        verify(HERE/('baseline-'+label+'.log'), old['logs_sha256'][label+'.log'])
    for name, source in [('runner.source.py','simulator/gsim/common/i1_runtime_network_native.py'),
                         ('guest.source.S','simulator/gsim/common/i1_runtime_network.S'),
                         ('guest.source.ld','simulator/gsim/common/i1_runtime_network.ld'),
                         ('fixture.source.scala','src/test/scala/platform/CommonI1RuntimeNetworkMain.scala'),
                         ('parent-fixture.source.scala','src/test/scala/platform/CommonI1RuntimeCdcMain.scala')]:
        verify(historical/name, old['source_sha256'][source])
    return manifest, old, emission, historical, command, rtl


def replay(output):
    manifest, old, emission, historical, command, rtl = validate_inputs()
    require(not output.exists() and output.parent.is_dir(), 'fresh output/existing parent required')
    guard(output.parent)
    output.mkdir()
    original_inventory = {str(p): sha(p) for p in historical.iterdir() if p.is_file()}
    inputs = {str(p): sha(p) for p in rtl}
    inputs.update(original_inventory)
    inputs.update({str(p): sha(p) for p in HERE.iterdir() if p.is_file()})
    inputs[str(ROOT/TB_NAME)] = sha(ROOT/TB_NAME)
    inputs[old['emission_receipt']['path']] = old['emission_receipt']['sha256']
    inputs.update({v['path']: v['sha256'] for v in old['tools'].values()})
    drift = {}
    for name, digest in emission['source_sha256'].items():
        path = Path(name) if Path(name).is_absolute() else ROOT/name
        current = sha(path) if path.is_file() else None
        if current != digest:
            drift[name] = {'historical_sha256': digest, 'current_sha256': current}
    binary = output/'corrected-monitor.vvp'
    command[command.index('-o')+1] = str(binary)
    command[command.index(str(ROOT/TB_NAME))] = str(HERE/'corrected_tb.source.sv')
    report = dict(status='RUNNING', mode='HISTORICAL_R17_OBSERVATION_MONITOR_REPLAY',
                  scope='Three affected observation-side negatives only; eight old positives unchanged and not rerun',
                  baseline_receipt=manifest['baseline_receipt'],
                  baseline_receipt_sha256=manifest['baseline_receipt_sha256'],
                  original_emission_receipt=old['emission_receipt'],
                  original_emission_command=emission['command'],
                  original_rtl_directory=str(rtl[0].parent),
                  complete_original_rtl_inventory_sha256=old['rtl_sha256'],
                  complete_rtl_inventory_verified=True,
                  original_toolchain=old['tools'], original_guest=old['guest'],
                  original_sim_sha256=old['sim_sha256'],
                  original_production_assertions=old['production_assertions'],
                  current_production_source_qualified=False,
                  current_emission_source_differences=drift,
                  historical_classification='Old negatives 1 and 3 corrupted references in ordinary checks; not observation-side injection. Historical positives and negative 2 remain valid in their stated historical scope.',
                  positive_mode_proof=json.loads((HERE/'positive-mode-proof.json').read_text()),
                  disk_floor_bytes=FLOOR, per_process_timeout_seconds=TIMEOUT,
                  unbuffered_vvp=True, input_sha256=inputs, cases=[])
    try:
        result = run(command, output/'compile.log')
        report['compile'] = dict(command=command, **result)
        require(result['returncode'] == 0 and not result['timed_out'] and
                not result['disk_floor_breached'], 'corrected historical compile failed')
        report['compiled_sha256'] = sha(binary)
        tests = [('rx-payload-case0-negative1', 0, 1, 'NETWORK_ORACLE_PAYLOAD RX word=0 byte=0'),
                 ('rx-guard-case0-negative3', 0, 3, 'NETWORK_ORACLE_GUARD dirty same-line neighbor got=55667789 expected=55667788'),
                 ('tx-payload-case3-negative1', 3, 1, 'NETWORK_ORACLE_PAYLOAD TX byte=23 got=2e expected=2f')]
        for label, case, negative, marker in tests:
            cmd = [old['tools']['vvp']['path'], '-i', str(binary),
                   '+rom='+str(historical/'guest.hex'), f'+negative={negative}', f'+case={case}']
            log = output/(label+'.log')
            result = run(cmd, log)
            content = log.read_text()
            fatals = [line for line in content.splitlines() if line.startswith('FATAL:')]
            accepted = (result['returncode'] == 1 and not result['timed_out'] and
                        not result['disk_floor_breached'] and len(fatals) == 1 and
                        bool(re.match(r'FATAL: .*corrected_tb\.source\.sv:\d+: '+re.escape(marker)+r'$', fatals[0])) and
                        PASS not in content)
            report['cases'].append(dict(label=label, command=cmd, expected_negative=True,
                                        required_ordinary_checker_marker=marker, accepted=accepted,
                                        log_sha256=sha(log), **result))
            require(accepted, 'unexpected '+label+' outcome: '+content[-2500:])
            print(label+': expected ordinary-checker rejection', flush=True)
        for path, digest in inputs.items():
            verify(path, digest)
        require({str(p): sha(p) for p in historical.iterdir() if p.is_file()} == original_inventory,
                'historical native directory inventory/content changed')
        require({p.name: sha(p) for p in rtl[0].parent.glob('*.sv')} == old['rtl_sha256'],
                'historical RTL inventory/content changed')
        verify(binary, report['compiled_sha256'])
        report.update(status='PASS_HISTORICAL_R17_OBSERVATION_MONITOR_REPLAY',
                      original_receipt_unchanged=True, original_native_directory_unchanged=True,
                      original_rtl_unchanged=True, all_bound_inputs_unchanged=True,
                      positive_simulations_run=0, negative_simulations_run=3)
    except BaseException as error:
        report.update(status='FAIL', error=repr(error))
        raise
    finally:
        report['logs_sha256'] = {p.name: sha(p) for p in output.glob('*.log')}
        (output/'receipt.json').write_text(json.dumps(report, indent=2)+'\n')
        print(report['status']+' receipt='+str(output/'receipt.json'), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    require(os.environ.get('VALENCE_CLOUD_ENV'), 'source scripts/cloud/env.sh first')
    if args.verify_only:
        validate_inputs()
        print('PASS historical inputs, monitor patch, and positive-mode equivalence', flush=True)
    else:
        require(args.output is not None, '--output required')
        replay(args.output.resolve())


if __name__ == '__main__':
    main()
