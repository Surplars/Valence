#!/usr/bin/env python3
"""Finite real I1+IMSIC commit regression, using an existing qualified GSIM toolchain.

No downloads, Verilator, Vivado, broad regression or board/timing claims. Each command
has a 1200-second cap and a monitored 4 GiB disk floor. Profiles run sequentially.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import shlex
import shutil
import signal
import subprocess
import time

ROOT = Path(__file__).resolve().parents[3]
FLOOR = 4 * 1024**3
TOP = 'I1AiaCommitHarness'

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--mill', default='mill -i -j2')
    ap.add_argument('--gsim', type=Path, required=True)
    ap.add_argument('--cxx', type=Path, required=True)
    ap.add_argument('--profiles', nargs='+', choices=('compact5', 'balanced7', 'fpga8'), default=['compact5', 'fpga8'])
    ap.add_argument('--skip-config', action='store_true')
    args = ap.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    paths = sorted((ROOT/'src/main/scala/core/inorder').glob('*.scala')) + [
        ROOT/'src/main/scala/ip/interrupt/Imsic.scala', ROOT/'src/main/scala/ip/bus/RegisterPort.scala',
        ROOT/'src/test/scala/inorder/I1AiaCommitMain.scala',
        ROOT/'simulator/gsim/harness/i1_aia_commit.cpp', Path(__file__).resolve(), ROOT/'build.mill']
    frozen = {str(p.relative_to(ROOT)): sha(p) for p in paths}
    record = dict(status='RUNNING', scope='finite real core+IMSIC commit/backpressure/privilege RTL regression',
        profiles=args.profiles, source_sha256=frozen, commands=[], results=[],
        tools={str(p): sha(p) for p in (args.gsim, args.cxx)},
        tool_note='Caller-provided restored patched GSIM; this does not claim pristine upstream simulation.',
        physical_timing_qualified=False, board_qualified=False)
    def save():
        (out/'receipt.json').write_text(json.dumps(record, indent=2)+'\n')
    def run(command, log, expected_error=None):
        if shutil.disk_usage(out).free < FLOOR:
            raise RuntimeError('4 GiB free disk floor before command')
        command = list(map(str, command))
        record['commands'].append(command)
        started, minimum, error = time.monotonic(), shutil.disk_usage(out).free, None
        def no_core():
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        with log.open('w') as stream:
            process = subprocess.Popen(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'}, start_new_session=True, preexec_fn=no_core)
            while process.poll() is None:
                minimum = min(minimum, shutil.disk_usage(out).free)
                if minimum < FLOOR or time.monotonic()-started > 1200:
                    error = 'disk floor' if minimum < FLOOR else 'bounded timeout'
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                    break
                time.sleep(0.2)
        record['results'].append(dict(command=command, returncode=process.returncode,
            seconds=time.monotonic()-started, minimum_free_bytes=minimum, error=error,
            log=str(log.relative_to(out))))
        save()
        text = log.read_text()
        if expected_error:
            if error or process.returncode == 0 or expected_error not in text:
                raise RuntimeError('negative control failed: '+str(log))
        elif error or process.returncode:
            raise RuntimeError('command failed: '+str(log))
        return text
    try:
        save()
        if not args.skip_config:
            run([*shlex.split(args.mill), 'OrbitalI1.test.testOnly', 'inorder.FiveStageConfigSpec'], out/'config.log')
        for profile in args.profiles:
            folder = out/profile
            folder.mkdir()
            run([*shlex.split(args.mill), 'OrbitalI1.test.runMain', 'inorder.I1AiaCommitMain', folder, profile],
                folder/'emit.log')
            fir = folder/(TOP+'.fir')
            parser = fir
            if fir.stat().st_size % 4096 == 0:
                parser = folder/(TOP+'.parser.fir')
                parser.write_bytes(fir.read_bytes()+b'\n')
            run([args.gsim, '--threads=1', '--dir='+str(folder), parser], folder/'generate.log')
            sources = sorted(folder.glob(TOP+'[0-9]*.cpp'))
            if not sources:
                raise RuntimeError('no generated model sources')
            objects = []
            flags = ['-std=c++20', '-O1', '-fsanitize=address,undefined', '-fno-sanitize-recover=all']
            for source in sources:
                obj = source.with_suffix('.o')
                run([args.cxx, *flags, '-I'+str(folder), '-c', source, '-o', obj], obj.with_suffix('.compile.log'))
                objects.append(obj)
            binary = folder/'run'
            run([args.cxx, *flags, '-I'+str(folder), '-DI1_AIA_FPGA8='+str(int(profile == 'fpga8')),
                *objects, ROOT/'simulator/gsim/harness/i1_aia_commit.cpp', '-o', binary], folder/'link.log')
            text = run([binary], folder/'run.log')
            if 'I1_AIA_COMMIT_PASS' not in text:
                raise RuntimeError('missing positive completion marker')
            run([binary, '--wrong-retire'], folder/'negative-retire.log',
                expected_error='independent AIA/register retirement oracle')
            print(profile+': PASS', flush=True)
        if frozen != {str(p.relative_to(ROOT)): sha(p) for p in paths}:
            raise RuntimeError('source drift during regression')
        record['status'] = 'PASS_FINITE_I1_AIA_COMMIT'
    except BaseException as error:
        record['status'] = 'FAIL'
        record['error'] = repr(error)
        raise
    finally:
        record['artifact_sha256'] = {str(p.relative_to(out)): sha(p) for p in out.rglob('*')
            if p.is_file() and p.name != 'receipt.json'}
        save()

if __name__ == '__main__':
    main()
