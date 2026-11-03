#!/usr/bin/env python3
"""Bounded I1 numerical batch: independent arithmetic, cancellation, CPU cost and paired RTL."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'simulator/gsim'))
import run as common


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--rtl-output', type=Path, required=True)
    args = parser.parse_args()
    output, reference, rtl = args.output.resolve(), args.reference.resolve(), args.rtl_output.resolve()
    if not output.is_relative_to(ROOT / 'build') or output.exists():
        parser.error('fresh output below repository build/ required')
    if not reference.is_relative_to(ROOT / 'build'):
        parser.error('reference manifest must stay inside this worktree build/')
    if not rtl.is_relative_to(Path('/mnt/e/VM/Share/Valence-rtl/Valence-InOrder')) or rtl.exists():
        parser.error('fresh RTL output inside the designated Valence-rtl work root required')
    original = json.loads(reference.read_text())
    ref_classes = Path(original['reference_classes']).resolve()
    if not ref_classes.is_relative_to(ROOT / 'build'):
        parser.error('reference classes must stay inside this worktree build/')
    for name, digest in original['class_sha256'].items():
        if sha(ref_classes / name) != digest:
            raise RuntimeError('reference class drift: ' + name)
    output.mkdir(parents=True)
    rtl.mkdir(parents=True)
    gsim, cxx = common.setup(False)
    values = json.loads((ROOT / 'out/OrbitalI1/test/runClasspath.json').read_text())['value']
    paths = [Path(value.split(':', 3)[3]) for value in values]
    missing = [str(path) for path in paths if not path.exists()]
    if any('resources' not in path for path in missing):
        raise RuntimeError('missing runtime dependency: ' + repr(missing))
    runtime = os.pathsep.join(str(path) for path in paths if path.exists())
    normal_classes = ROOT / 'out/OrbitalI1/compile.dest/classes'
    files = [ROOT / 'build.mill', Path(__file__).resolve(),
             ROOT / 'simulator/gsim/harness/five_stage.cpp',
             ROOT / 'simulator/gsim/harness/five_stage_mul_div.cpp',
             ROOT / 'simulator/gsim/harness/i1_divide_step.cpp']
    files += sorted((ROOT / 'src/main/scala/core/inorder').glob('*.scala'))
    files += sorted((ROOT / 'src/test/scala/inorder').glob('*.scala'))
    frozen = {str(path.relative_to(ROOT)): sha(path) for path in files}
    receipt = {'status': 'RUNNING', 'scope': 'bounded numerical module and bare CPU comparison only',
               'source_sha256': frozen, 'reference': original, 'reference_manifest_sha256': sha(reference),
               'tools': {'gsim_sha256': sha(gsim), 'cxx': common.compiler()[1]},
               'missing_optional_resource_directories': missing, 'checks': {}, 'commands': [],
               'rtl_root': str(rtl), 'physical_qualified': False, 'full_regression': False}

    def save():
        (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')

    def execute(argv, folder, log, negative=None):
        argv = [str(value) for value in argv]
        receipt['commands'].append({'argv': argv, 'cwd': str(ROOT), 'log': str(folder / log)})
        save()
        with (folder / log).open('w') as stream:
            result = subprocess.run(argv, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'})
        text = (folder / log).read_text()
        if negative:
            if result.returncode == 0 or negative not in text:
                raise RuntimeError('negative control not independently rejected: ' + str(folder / log))
        elif result.returncode:
            raise RuntimeError('command failed: ' + str(folder / log))
        return text

    def emit(role, folder, entry, width, flags=(), is_mdu=True):
        effective = (str(ref_classes) + os.pathsep if role == 'reference' else '') + runtime
        log = folder / 'class-load.log'
        execute(['java', '-Xlog:class+load=info:file=' + str(log), '-cp', effective,
                 'inorder.' + entry, folder, width, *flags], folder, 'elaborate.log')
        if is_mdu:
            marker = 'soc.core.inorder.FiveStageMulDiv source: '
            origins = [Path(unquote(urlparse(line.split(marker, 1)[1].strip()).path)).resolve()
                       for line in log.read_text().splitlines() if marker in line]
            expected = ref_classes if role == 'reference' else normal_classes
            if origins != [expected]:
                raise RuntimeError('unexpected MDU class origin: ' + repr(origins))

    def model(name, role, entry, top, driver, width, flags=(), defines=(), negative=None, with_mdu=True):
        folder = output / name
        folder.mkdir()
        emit(role, folder, entry, width, flags, with_mdu)
        execute([gsim, '--threads=1', '--dir=' + str(folder), folder / (top + '.fir')], folder, 'generate.log')
        generated = sorted(folder.glob(top + '[0-9]*.cpp'))
        if not generated:
            raise RuntimeError('generated C++ missing: ' + name)
        execute([cxx, '-std=c++20', '-O1', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                 '-DDUT_XLEN=' + str(width), *defines, '-I' + str(folder), *generated,
                 ROOT / 'simulator/gsim/harness' / driver, '-o', folder / 'run'], folder, 'compile.log')
        positive = execute([folder / 'run'], folder, 'positive.log')
        if not re.search(r'(?:FIVE_STAGE_(?:MDU_)?PASS|I1_DIVIDE_STEP_PASS)', positive):
            raise RuntimeError('missing independent positive marker: ' + name)
        if negative:
            execute([folder / 'run', '--inject-register-mismatch'], folder, 'negative.log', negative)
        row = {'summary': positive.splitlines()[-1], 'negative_rejected': bool(negative),
               'latencies': {key: int(cycles) for key, cycles in
                   re.findall(r'I1_DIV_LATENCY name=(\w+) cycles=(\d+)', positive)}}
        match = re.search(r'matched_retires=(\d+) low_cycles=(\d+) blocked_cycles=(\d+)', positive)
        if match:
            row.update(zip(('retires', 'low_cycles', 'blocked_cycles'), map(int, match.groups())))
            row['low_ipc'] = row['retires'] / row['low_cycles']
        receipt['checks'][name] = row
        save()
        print(name, row['summary'], flush=True)

    try:
        for width in (32, 64):
            model('divide-step-' + str(width), 'candidate', 'I1DivideStepMain', 'I1DivideStepFixture',
                  'i1_divide_step.cpp', width, negative='independent wide divide-step oracle mismatch', with_mdu=False)
            for role in ('reference', 'default', 'candidate'):
                model(role + '-mdu-' + str(width), role, 'FiveStageMulDivMain', 'FiveStageMulDiv',
                      'five_stage_mul_div.cpp', width, ['--dsp-tiled', *(['--fast-division'] if role == 'candidate' else [])],
                      negative='independent MDU oracle mismatch')
        for profile, flags, stages in (
                ('compact5', ['--dsp-tiled'], 5),
                ('fpga8', ['--dsp-tiled', '--pipeline=fpga8', '--timing-cuts'], 8)):
            for role in ('reference', 'default', 'candidate'):
                model(role + '-cpu-' + profile, role, 'FiveStageMain', 'FiveStageCore', 'five_stage.cpp', 64,
                      [*flags, *(['--fast-division'] if role == 'candidate' else [])], ['-DDUT_PIPELINE_STAGES=' + str(stages)],
                      negative='independent register oracle mismatch')
            baseline = receipt['checks']['reference-cpu-' + profile]
            for role in ('default', 'candidate'):
                measured = receipt['checks'][role + '-cpu-' + profile]
                if baseline['retires'] != measured['retires']:
                    raise RuntimeError('CPU work differs: ' + profile + ' ' + role)
                if measured['low_cycles'] > baseline['low_cycles'] or measured['blocked_cycles'] > baseline['blocked_cycles']:
                    raise RuntimeError('matched CPU cycle regression: ' + profile + ' ' + role)
        for role in ('reference', 'default', 'candidate'):
            target = rtl / role
            target.mkdir()
            emit(role, target, 'I1MulDivRtlMain', 64, ['--dsp-tiled', *(['--fast-division'] if role == 'candidate' else [])])
        for name, digest in frozen.items():
            if sha(ROOT / name) != digest:
                raise RuntimeError('source drift during acceptance: ' + name)
        receipt['rtl_sha256'] = {str(path.relative_to(rtl)): sha(path) for path in sorted(rtl.rglob('*.sv'))}
        receipt['status'] = 'PASS_I1_NUMERICAL_AFFECTED_SHORT_ONLY'
    except BaseException as error:
        receipt.update(status='FAIL', error=repr(error))
        raise
    finally:
        save()
    print(json.dumps({'status': receipt['status'], 'checks': receipt['checks'], 'receipt': str(output / 'receipt.json')}, indent=2))


if __name__ == '__main__':
    main()
