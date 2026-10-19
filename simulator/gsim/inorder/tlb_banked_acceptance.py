#!/usr/bin/env python3
"""Finite I1 4/8/16/32 proof-owner regression; no full CPU, physical timing or V/H claim.

Requires already installed tools; never downloads tools or invokes Verilator/Vivado.
The same independent Sv39/PMP oracle runs for each capacity and both request owners.
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


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--mill', default='mill -i -j2', help='existing Mill command, shell-split only')
    ap.add_argument('--gsim', type=Path, required=True)
    ap.add_argument('--cxx', type=Path, required=True)
    ap.add_argument('--entries', type=int, nargs='+', choices=(4, 8, 16, 32), default=[4, 8, 16, 32])
    ap.add_argument('--owners', nargs='+', choices=('instruction', 'data'), default=['instruction', 'data'])
    ap.add_argument('--skip-config', action='store_true')
    args = ap.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    source_paths = sorted((ROOT/'src/main/scala/core/inorder').glob('*.scala'))
    source_paths += [ROOT/'src/test/scala/inorder/FiveStagePrivilegeMain.scala',
                     ROOT/'src/test/scala/inorder/FiveStageConfigSpec.scala',
                     ROOT/'src/test/scala/inorder/FiveStageMain.scala',
                     ROOT/'simulator/gsim/harness/five_stage_translation.cpp', Path(__file__).resolve()]
    frozen = {str(p.relative_to(ROOT)): sha(p) for p in source_paths}
    record = dict(status='RUNNING', scope='finite MMU module RTL regression; not full CPU or physical timing',
                  banked_default=False, owners_per_translator=1, source_sha256=frozen, commands=[], results=[],
                  tools={str(p): sha(p) for p in (args.gsim, args.cxx)},
                  tools_note='Caller supplies existing qualified toolchain; hashes bind this run, no upstream-clean claim.')

    def save():
        (output/'receipt.json').write_text(json.dumps(record, indent=2)+'\n')

    def run(command, log, timeout=600, expected_error=None):
        if shutil.disk_usage(output).free < FLOOR:
            raise RuntimeError('4 GiB free disk floor before command')
        command = list(map(str, command))
        record['commands'].append(command)
        started = time.monotonic()
        minimum = shutil.disk_usage(output).free
        error = None
        def no_core():
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        with log.open('w') as stream:
            process = subprocess.Popen(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'}, start_new_session=True, preexec_fn=no_core)
            while process.poll() is None:
                minimum = min(minimum, shutil.disk_usage(output).free)
                if minimum < FLOOR or time.monotonic()-started > timeout:
                    error = 'disk floor' if minimum < FLOOR else 'bounded timeout'
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                    break
                time.sleep(0.2)
        result = dict(command=command, returncode=process.returncode, seconds=time.monotonic()-started,
                      minimum_free_bytes=minimum, error=error, log=str(log.relative_to(output)))
        record['results'].append(result)
        save()
        text = log.read_text()
        if expected_error is not None:
            if error or process.returncode == 0 or expected_error not in text:
                raise RuntimeError('negative control failed: '+str(log))
        elif error or process.returncode:
            raise RuntimeError('command failed: '+str(log))
        return text

    try:
        save()
        if not args.skip_config:
            run([*shlex.split(args.mill), 'OrbitalI1.test.testOnly', 'inorder.FiveStageConfigSpec'],
                output/'config.log')
        for count in args.entries:
            for owner in args.owners:
                out = output/f'{owner}-{count}'
                out.mkdir()
                flags = ['--timing-cuts', '--atomic', f'--tlb={count}']
                defines = [f'-DI1_TLB_ENTRIES={count}', '-DI1_MACHINE_OFF_FAST']
                if count > 8:
                    flags += ['--banked-tlb-proofs']
                if owner == 'instruction':
                    flags += ['--instruction', '--split-candidates']
                    defines += ['-DI1_INSTRUCTION_TRANSLATION', '-DI1_INSTRUCTION_PMA',
                                '-DI1_SPLIT_INSTRUCTION_CANDIDATES']
                else:
                    flags += ['--fast-data-translation', '--direct-fast-data-issue', '--indexed-data-proofs',
                              '--split-data-candidates', '--overlap-data-retirement']
                    defines += ['-DI1_INDEXED_DATA_PROOFS', '-DI1_SPLIT_DATA_CANDIDATES',
                                '-DI1_RETIREMENT_OVERLAP=1']
                run([*shlex.split(args.mill), 'OrbitalI1.test.runMain', 'inorder.FiveStageTranslationMain',
                    out, *flags], out/'emit.log')
                fir = out/'FiveStageTranslationHarness.fir'
                parser = fir
                if fir.stat().st_size % 4096 == 0:
                    parser = out/'FiveStageTranslationHarness.parser.fir'
                    parser.write_bytes(fir.read_bytes()+b'\n')
                run([args.gsim, '--threads=1', f'--dir={out}', parser], out/'generate.log')
                generated = sorted(out.glob('FiveStageTranslationHarness[0-9]*.cpp'))
                if not generated:
                    raise RuntimeError('no generated model sources')
                run([args.cxx, '-std=c++20', '-O1', '-fsanitize=address,undefined',
                    '-fno-sanitize-recover=all', '-I'+str(out), *defines, *generated,
                    ROOT/'simulator/gsim/harness/five_stage_translation.cpp', '-o', out/'run'],
                    out/'compile.log', timeout=900)
                text = run([out/'run'], out/'run.log')
                if 'FIVE_STAGE_TRANSLATION_PASS' not in text:
                    raise RuntimeError('missing positive completion marker')
                run([out/'run', '--wrong-page'], out/'negative-page.log',
                    expected_error='independent Sv39/PMP/page-vs-access fault oracle')
                if owner == 'data':
                    run([out/'run', '--wrong-indexed-count'], out/'negative-proof-count.log',
                        expected_error='independent indexed data superpage proof reuse oracle')
                print(f'{owner}-{count}: PASS', flush=True)
        if frozen != {str(p.relative_to(ROOT)): sha(p) for p in source_paths}:
            raise RuntimeError('source drift during regression')
        record['status'] = 'PASS_FINITE_I1_TLB_PROOF_OWNERS'
    except BaseException as error:
        record['status'] = 'FAIL'
        record['error'] = repr(error)
        raise
    finally:
        record['artifact_sha256'] = {str(p.relative_to(output)): sha(p) for p in output.rglob('*')
            if p.is_file() and p.name != 'receipt.json'}
        save()


if __name__ == '__main__':
    main()
