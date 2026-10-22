#!/usr/bin/env python3
"""Source-bound native Icarus ordering witness for the real control epoch sequencer.

The bench models parked/released. It does not prove real MAC/PHY/MDIO lifecycle,
clock-gate ACK, CDC or physical timing. Mill emission requires --emit-only and an
explicitly allocated shared compile slot; normal runs reuse a verified manifest.
Every child is bounded and its process group is killed/reaped on interruption.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import shlex
import signal
import subprocess
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
TB = HERE / 'control_park_epoch_sequencer_tb.sv'
EMITTER = ROOT / 'src/test/scala/platform/CommonControlParkEpochSequencerMain.scala'
MANIFEST = 'control_park_epoch_emission.json'
PASS = 'CONTROL_PARK_EPOCH_SEQUENCER_PASS'
FLOOR = 4 * 1024 ** 3


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_hashes():
    paths = sorted((ROOT / 'src/main/scala').rglob('*.scala'))
    paths += sorted((ROOT / 'src/main/resources').rglob('*'))
    paths += [EMITTER, ROOT / 'build.mill', ROOT / 'scripts/cloud/env.sh']
    return {str(path.relative_to(ROOT)): sha(path) for path in paths if path.is_file()}


def rtl_hashes(rtl):
    paths = sorted(list(rtl.rglob('*.sv')) + list(rtl.rglob('*.v')))
    if not paths or not (rtl / 'CommonControlParkEpochSequencer.sv').is_file():
        raise RuntimeError('missing emitted production sequencer RTL')
    return {str(path.relative_to(rtl)): sha(path) for path in paths}


def tool(name):
    path = shutil.which(name)
    if not path:
        raise RuntimeError('missing tool: ' + name)
    path = Path(path).resolve()
    return str(path), dict(path=str(path), sha256=sha(path))


def compiler_chain(compiler):
    """Bind the installed wrapper's real engine and explicit -B backend path.

    This is the same local Icarus wrapper convention used by the existing r19
    native runners. No downloaded tool or guessed alternate backend is used.
    """
    result = {}
    compiler = Path(compiler)
    if compiler.read_bytes()[:2] == b'#!':
        for line in compiler.read_text().splitlines():
            if line.startswith('exec '):
                words = shlex.split(line)
                if len(words) > 1:
                    engine = Path(words[1]).resolve()
                    result['iverilog_engine'] = dict(path=str(engine), sha256=sha(engine))
                if '-B' in words:
                    directory = Path(words[words.index('-B') + 1])
                    for name in ['ivl', 'ivlpp', 'vvp.tgt', 'vvp.conf']:
                        path = (directory / name).resolve()
                        result[name] = dict(path=str(path), sha256=sha(path))
    return result


def run(command, output, name, timeout, record):
    command = list(map(str, command))
    started = time.monotonic()
    minimum_free = shutil.disk_usage(output).free
    if minimum_free < FLOOR:
        raise RuntimeError('4 GiB disk floor before ' + name)
    child = None
    killed = timed_out = interrupted = False
    try:
        with (output / (name + '.log')).open('w') as log:
            child = subprocess.Popen(command, cwd=ROOT, stdout=log,
                                     stderr=subprocess.STDOUT, start_new_session=True)
            while child.poll() is None:
                minimum_free = min(minimum_free, shutil.disk_usage(output).free)
                timed_out = time.monotonic() - started > timeout
                if timed_out or minimum_free < FLOOR:
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
            record['cases'].append(dict(name=name, command=command,
                returncode=child.returncode, elapsed_seconds=time.monotonic() - started,
                minimum_free_bytes=minimum_free, timed_out=timed_out,
                process_group_killed=killed, interrupted=interrupted, child_reaped=True))
    if killed:
        raise RuntimeError('wall-clock or disk resource bound: ' + name)
    return child.returncode, (output / (name + '.log')).read_text()


def main():
    def interrupt(signum, _frame):
        raise KeyboardInterrupt('signal ' + str(signum))
    signal.signal(signal.SIGTERM, interrupt)
    signal.signal(signal.SIGINT, interrupt)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path, help='fresh log/artifact directory')
    parser.add_argument('--rtl', type=Path, help='source-bound previously emitted RTL directory')
    parser.add_argument('--emit-only', action='store_true', help='requires allocated shared Mill slot')
    parser.add_argument('--timeout', type=float, default=180)
    parser.add_argument('--iverilog', default=os.environ.get('IVERILOG', 'iverilog'))
    parser.add_argument('--vvp', default=os.environ.get('VVP', 'vvp'))
    args = parser.parse_args()
    if args.timeout <= 0 or args.timeout > 180:
        parser.error('timeout must be in (0, 180] seconds')
    if args.emit_only == bool(args.rtl):
        parser.error('choose exactly one of --emit-only or --rtl')
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=False)
    record = dict(scope='sequencer ordering only; modeled parked/released, not real MAC lifecycle',
                  cases=[], tools={}, passed=False)
    original = source_hashes()
    record['elaboration_sources'] = original
    record['test_sources'] = {str(path.relative_to(ROOT)): sha(path)
                              for path in [TB, Path(__file__).resolve()]}
    try:
        if args.emit_only:
            mill, record['tools']['mill'] = tool('mill')
            rtl = output / 'rtl'
            rc, _ = run([mill, '-i', 'IonSoC.test.runMain',
                'platform.CommonControlParkEpochSequencerMain', rtl], output,
                'emit', args.timeout, record)
            if rc:
                raise RuntimeError('Mill emission failed; see emit.log')
            if source_hashes() != original:
                raise RuntimeError('elaboration sources changed during emission')
            manifest = dict(elaboration_sources=original, rtl=rtl_hashes(rtl),
                            command=record['cases'][0]['command'], tools=record['tools'])
            (rtl / MANIFEST).write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
            record['rtl'] = manifest['rtl']
            record['emitted'] = True
        else:
            rtl = args.rtl.resolve()
            manifest = json.loads((rtl / MANIFEST).read_text())
            if manifest['elaboration_sources'] != original or manifest['rtl'] != rtl_hashes(rtl):
                raise RuntimeError('reused RTL/source manifest mismatch; fresh shared-slot emission required')
            record['emission_manifest'] = str(rtl / MANIFEST)
            record['emission_manifest_sha256'] = sha(rtl / MANIFEST)
            record['rtl'] = manifest['rtl']
            iverilog, record['tools']['iverilog'] = tool(args.iverilog)
            vvp, record['tools']['vvp'] = tool(args.vvp)
            record['tools'].update(compiler_chain(iverilog))
            source_files = [rtl / name for name in manifest['rtl']]
            executable = output / 'sequencer.vvp'
            rc, _ = run([iverilog, '-g2012', '-s', 'control_park_epoch_sequencer_tb',
                '-o', executable, TB, *source_files], output, 'compile', args.timeout, record)
            if rc:
                raise RuntimeError('native Icarus compile failed; see compile.log')
            rc, log = run([vvp, '-i', executable], output, 'positive', args.timeout, record)
            if rc or PASS not in log or 'scope=ordering-only' not in log:
                raise RuntimeError('ordering witness failed; see positive.log')
            rc, log = run([vvp, '-i', executable, '+negative=1'], output,
                          'oracle-negative', args.timeout, record)
            if rc == 0 or PASS in log or 'independent retired-epoch count' not in log:
                raise RuntimeError('independent oracle negative did not fail precisely')
            record['artifacts'] = {name: sha(output / name) for name in
                                   ['sequencer.vvp', 'compile.log', 'positive.log', 'oracle-negative.log']}
            record['passed'] = True
        if source_hashes() != original:
            raise RuntimeError('elaboration sources changed during native verification')
        if any(sha(item['path']) != item['sha256'] for item in record['tools'].values()):
            raise RuntimeError('toolchain changed during verification')
        if any(sha(ROOT / path) != digest for path, digest in record['test_sources'].items()):
            raise RuntimeError('test sources changed during verification')
    except BaseException as error:
        record['error'] = repr(error)
        record['passed'] = False
        raise
    finally:
        (output / 'record.json').write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
    print(json.dumps(dict(output=str(output), emitted=record.get('emitted', False),
                          passed=record['passed'], scope=record['scope']), sort_keys=True))


if __name__ == '__main__':
    main()
