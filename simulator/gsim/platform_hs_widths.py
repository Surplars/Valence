#!/usr/bin/env python3
"""Link a focused HS-width driver against an already-built platform GSIM model."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--platform-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True,
                        help='New output directory; existing evidence is never overwritten')
    parser.add_argument('--cxx', type=Path, required=True)
    parser.add_argument('--assembler', type=Path, required=True)
    parser.add_argument('--objdump', type=Path,
                        help='Defaults to assembler sibling with -as replaced by -objdump')
    parser.add_argument('--library-path', type=Path,
                        help='Compiler runtime libraries; defaults to CXX parent/../lib/x86_64-linux-gnu')
    args = parser.parse_args()
    platform = args.platform_root.resolve()
    output = args.output.resolve()
    cxx = args.cxx.absolute()
    assembler = args.assembler.absolute()
    objdump = (args.objdump or assembler.with_name(
        assembler.name.removesuffix('-as') + '-objdump')).absolute()
    script = Path(__file__).resolve()
    source = script.parent / 'harness/hypervisor_hs_widths.cpp'
    model = platform / 'final-native/model.o'
    include = platform / 'platform-build4'
    harness = platform / 'simulator/gsim/harness'
    paths = [script, source, cxx, assembler, objdump, model,
             include / 'HypervisorPlatformGsim.h',
             include / 'HypervisorPlatformGsim0.cpp',
             include / 'HypervisorPlatformGsim.fir',
             harness / 'hypervisor_platform.cpp',
             platform / 'SOURCE_MANIFEST.json', platform / 'EVIDENCE_MANIFEST.json']
    # Capture every input before any execution, then compare after all commands.
    before = {str(path): digest(path) for path in paths}
    output.mkdir(parents=True, exist_ok=False)
    (output / 'pins-before.json').write_text(json.dumps(before, indent=2) + '\n')
    env = os.environ.copy()
    library = (args.library_path or cxx.parent.parent / 'lib/x86_64-linux-gnu').resolve()
    env['LD_LIBRARY_PATH'] = str(library)
    env['ASAN_OPTIONS'] = 'detect_leaks=0'
    commands = []

    def run(argv, log):
        start = time.monotonic()
        result = subprocess.run([str(arg) for arg in argv], env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (output / log).write_bytes(result.stdout)
        commands.append({'argv': [str(arg) for arg in argv], 'exit': result.returncode,
                         'seconds': time.monotonic() - start, 'log': log})
        return result

    status = 'FAIL'
    failure = None
    try:
        assembly = output / 'encodings.s'
        names = ['hlv.b', 'hlv.bu', 'hlv.h', 'hlv.hu', 'hlv.w', 'hlv.wu',
                 'hlv.d', 'hlvx.hu', 'hlvx.wu', 'hsv.b', 'hsv.h', 'hsv.w', 'hsv.d']
        assembly.write_text('.option norvc\n' + ''.join(
            f'{name} {"gp" if name.startswith("hsv") else "a0"},(sp)\n'
            for name in names))
        result = run([assembler, '-march=rv64ih', '-mabi=lp64', assembly,
                      '-o', output / 'encodings.o'], 'assembler.log')
        if result.returncode:
            raise RuntimeError('assembler failed')
        result = run([objdump, '-d', output / 'encodings.o'], 'encodings.log')
        expected = ['60014573', '60114573', '64014573', '64114573', '68014573',
                    '68114573', '6c014573', '64314573', '68314573', '62314073',
                    '66314073', '6a314073', '6e314073']
        if result.returncode or any(word.encode() not in result.stdout for word in expected):
            raise RuntimeError('independent GNU encoding check failed')
        result = run([cxx, '-std=c++20', '-O1', '-fbracket-depth=4096',
                      '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                      '-I' + str(include), '-I' + str(harness), source, model,
                      '-ldl', '-o', output / 'hs_widths'], 'link.log')
        if result.returncode:
            raise RuntimeError('small driver compilation/link failed')
        negative = run([output / 'hs_widths', output, 'wrong-data'], 'negative.log')
        if negative.returncode != 1 or b'FAIL independent architectural data' not in negative.stdout:
            raise RuntimeError('wrong-data negative was not rejected at expected comparison')
        positive = run([output / 'hs_widths', output], 'positive.log')
        if positive.returncode or positive.stdout.count(b'HS_WIDTH_PASS') != 2:
            raise RuntimeError('both HS-positive modes did not pass')
        status = 'PASS_HS_POSITIVE_WIDTHS_AND_REJECTED_WRONG_DATA'
        print(positive.stdout.decode(), end='')
    except Exception as error:
        failure = str(error)
    after = {str(path): digest(path) for path in paths}
    unchanged = before == after
    if not unchanged:
        status = 'FAIL_INPUTS_CHANGED_DURING_RUN'
        failure = 'Source, model, helper or tool inputs changed during execution'
    outputs = {str(path.relative_to(output)): digest(path)
               for path in sorted(output.iterdir()) if path.is_file()}
    receipt = {'status': status, 'failure': failure, 'pins_before': before,
               'pins_after': after, 'inputs_unchanged': unchanged,
               'outputs': outputs, 'commands': commands,
               'environment': {'LD_LIBRARY_PATH': env['LD_LIBRARY_PATH'],
                               'ASAN_OPTIONS': env['ASAN_OPTIONS']},
               'scope': 'HS positive H-memory only; M-mode config then MRET. '
                        'Reused sealed ASan/UBSan model. CPU enabled continuously after start. '
                        'Finite sentinel, no idle claim. No hardware rebuild or fault-path review.'}
    (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    if failure:
        raise SystemExit(failure)


if __name__ == '__main__':
    main()
