#!/usr/bin/env python3
"""One short I1 prediction batch: full-PC oracle, ISA/bus, IPC, pinned CoreMark, and paired RTL."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[3]
BASE = 'e2039094f3665af5e9ab73876f94e041a3319179'
sys.path.insert(0, str(ROOT / 'simulator/gsim'))
import run as common


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--coremark-reference', type=Path, required=True)
    parser.add_argument('--rtl-output', type=Path, required=True)
    args = parser.parse_args()
    output, rtl = args.output.resolve(), args.rtl_output.resolve()
    if output.exists() or not output.is_relative_to(ROOT / 'build'):
        parser.error('fresh output below repository build/ required')
    if rtl.exists() or not rtl.is_relative_to(Path('/mnt/e/VM/Share/Valence-rtl/Valence-InOrder')):
        parser.error('fresh RTL output below the designated Windows work root required')
    if os.environ.get('VALENCE_WORK_ROOT') != str(ROOT):
        parser.error('source .local-dev/env.sh so caches and temporary files stay inside the clone')
    reference_path = args.reference.resolve()
    coremark_path = args.coremark_reference.resolve()
    if any(not path.is_relative_to(ROOT / 'build') for path in [reference_path, coremark_path]):
        parser.error('reference evidence must stay below repository build/')
    reference = json.loads(reference_path.read_text())
    frozen_cm = json.loads(coremark_path.read_text())
    ref_classes = Path(reference['reference_classes']).resolve()
    if reference['head'] != BASE or not ref_classes.is_relative_to(ROOT / 'build'):
        raise RuntimeError('unexpected prediction reference')
    for name, digest in reference['class_sha256'].items():
        if sha(ref_classes / name) != digest:
            raise RuntimeError('reference class drift')
    if frozen_cm['status'] != 'PASS_I1_OFFICIAL_COREMARK_O3_SHORT_ONLY':
        raise RuntimeError('expected first-batch official CoreMark evidence')
    source = ROOT / 'simulator/build/coremark-src'
    if subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source, text=True).strip() != frozen_cm['coremark_revision']:
        raise RuntimeError('CoreMark source pin mismatch')
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=source, text=True).strip():
        raise RuntimeError('official CoreMark source must remain pristine')
    for name, digest in frozen_cm['coremark_algorithm_sha256'].items():
        if sha(source / name) != digest:
            raise RuntimeError('CoreMark algorithm drift')
    payload = coremark_path.parent / 'payload/coremark.bin'
    if sha(payload) != frozen_cm['payload']['binary_sha256']:
        raise RuntimeError('frozen official CoreMark binary drift')
    output.mkdir(parents=True)
    gsim, cxx = common.setup(False)
    values = json.loads((ROOT / 'out/OrbitalI1/test/runClasspath.json').read_text())['value']
    paths = [Path(value.split(':', 3)[3]) for value in values]
    if any(not path.exists() and 'resources' not in str(path) for path in paths):
        raise RuntimeError('incomplete Scala runtime classpath')
    runtime = os.pathsep.join(str(path) for path in paths if path.exists())
    files = [ROOT / 'build.mill', Path(__file__).resolve(), ROOT / 'simulator/gsim/run.py']
    files += sorted((ROOT / 'src/main/scala/core/inorder').glob('*.scala'))
    files += sorted((ROOT / 'src/test/scala/inorder').glob('*.scala'))
    files += [ROOT / ('simulator/gsim/harness/' + name) for name in
              ['i1_predictor_banks.cpp', 'i1_performance.cpp', 'i1_prediction_metrics.h',
               'five_stage.cpp', 'five_stage_coremark.cpp']]
    frozen = {str(path.relative_to(ROOT)): sha(path) for path in files}
    receipt = {'status': 'RUNNING', 'scope': 'I1 prediction affected short batch; no full regression or board claim',
               'baseline_commit': BASE, 'reference_manifest_sha256': sha(reference_path),
               'source_sha256': frozen, 'gsim_sha256': sha(gsim), 'commands': [], 'components': {}, 'profiles': {},
               'coremark_reference': {'path': str(coremark_path), 'sha256': sha(coremark_path)},
               'payload': frozen_cm['payload'], 'cpu': frozen_cm['cpu'], 'memory_service': frozen_cm['memory_service'],
               'formal_score': False, 'physical_qualified': False, 'full_regression': False}

    def save():
        (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')

    def run(argv, folder, log, negative=None):
        argv = [str(value) for value in argv]
        receipt['commands'].append({'argv': argv, 'log': str(folder / log)})
        save()
        with (folder / log).open('w') as stream:
            result = subprocess.run(argv, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                                    env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'})
        text = (folder / log).read_text()
        if negative:
            if result.returncode == 0 or negative not in text:
                raise RuntimeError('negative control not independently rejected: ' + str(folder / log))
        elif result.returncode:
            raise RuntimeError('failed: ' + str(folder / log))
        return text

    def emit(role, entry, folder, flags):
        classpath = (str(ref_classes) + os.pathsep if role == 'reference' else '') + runtime
        origin_log = folder / 'class-load.log'
        run(['java', '-Xlog:class+load=info:file=' + str(origin_log), '-cp', classpath,
             'inorder.' + entry, folder, *flags], folder, 'elaborate.log')
        marker = 'soc.core.inorder.FiveStageBranchPredictor source: '
        origins = [Path(unquote(urlparse(line.split(marker, 1)[1].strip()).path)).resolve()
                   for line in origin_log.read_text().splitlines() if marker in line]
        expected = ref_classes if role == 'reference' else ROOT / 'out/OrbitalI1/compile.dest/classes'
        if origins != [expected]:
            raise RuntimeError('unexpected predictor class origin: ' + repr(origins))

    def model(role, name, entry, top, flags, driver, defines=()):
        folder = output / name
        folder.mkdir()
        emit(role, entry, folder, flags)
        run([gsim, '--threads=1', '--dir=' + str(folder), folder / (top + '.fir')], folder, 'generate.log')
        cpp = sorted(folder.glob(top + '[0-9]*.cpp'))
        if not cpp:
            raise RuntimeError('missing GSIM model')
        run([cxx, '-std=c++20', '-O1', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
             *defines, '-I' + str(folder), *cpp, ROOT / 'simulator/gsim/harness' / driver,
             '-o', folder / 'run'], folder, 'compile.log')
        return folder

    def json_line(text, prefix):
        rows = [json.loads(line[len(prefix):]) for line in text.splitlines() if line.startswith(prefix)]
        if len(rows) != 1:
            raise RuntimeError('missing single result ' + prefix)
        return rows[0]

    try:
        cases = [('reference-128', 'reference', 128, 64, False, True, False),
                 ('local-128', 'local', 128, 64, False, True, False),
                 ('hashed-128', 'hashed', 128, 64, False, True, True),
                 ('hashed-c-128', 'hashed', 128, 64, True, True, True),
                 ('hashed-min-2', 'hashed', 2, 32, False, False, True),
                 ('hashed-max-1024', 'hashed', 1024, 32, False, True, True),
                 ('local-compact-64', 'local', 64, 64, False, False, False)]
        for name, role, entries, width, compressed, timing, hashed in cases:
            flags = [width, '--predictor=' + str(entries)]
            if compressed:
                flags += ['--c']
            if timing:
                flags += ['--pipeline=fpga8', '--timing-cuts']
            if hashed:
                flags += ['--hashed-branch-index']
            defines = [f'-DDUT_ENTRIES={entries}', f'-DDUT_XLEN={width}', f'-DDUT_C={int(compressed)}',
                       f'-DDUT_TIMING={int(timing)}', f'-DDUT_HASHED={int(hashed)}']
            folder = model(role, name, 'FiveStagePredictorMain', 'FiveStageBranchPredictor', flags,
                           'i1_predictor_banks.cpp', defines)
            text = run([folder / 'run'], folder, 'positive.log')
            if 'I1_BANKED_PREDICTOR_PASS' not in text:
                raise RuntimeError('predictor coverage incomplete')
            run([folder / 'run', '--inject-target'], folder, 'negative.log', 'independent banked predictor')
            receipt['components'][name] = {'summary': text.strip(), 'negative_rejected': True}
            print(text.strip(), flush=True)

        symbols = frozen_cm['payload']['symbols']
        for role in ['reference', 'local', 'hashed']:
            flags = [64, '--pipeline=fpga8', '--timing-cuts', '--dsp-tiled', '--predictor=128']
            if role == 'hashed':
                flags += ['--hashed-branch-index']
            bare = model(role, role + '-bare', 'I1PerformanceCoreMain', 'I1PerformanceCore', flags,
                         'i1_performance.cpp', ['-DDUT_XLEN=64', '-DDUT_PIPELINE_STAGES=8'])
            isa = run([bare / 'run', '--isa-smoke'], bare, 'isa.log')
            if 'FIVE_STAGE_PASS' not in isa:
                raise RuntimeError('missing original independent ISA/bus gate')
            run([bare / 'run', '--isa-smoke', '--inject-register-mismatch'], bare, 'negative-register.log',
                'independent register oracle mismatch')
            run([bare / 'run', '--isa-smoke', '--inject-store-mismatch'], bare, 'negative-store.log',
                'independent store intent data mismatch')
            text = run([bare / 'run'], bare, 'performance.log')
            if 'I1_PERFORMANCE_PASS' not in text:
                raise RuntimeError('missing performance ledger gate')
            rows = []
            per_pc = []
            for line in text.splitlines():
                if line.startswith(('I1_PERF ', 'I1_PRED_PC ')):
                    values = dict(token.split('=', 1) for token in line.split()[1:])
                    row = {key: value if key == 'name' else int(value) for key, value in values.items()}
                    if line.startswith('I1_PERF '):
                        row['whole_workload_ipc'] = row['retired'] / row['cycles']
                        row['retirement_window_ipc'] = row['retired'] / row['retirement_window']
                        row['next_pc_accuracy'] = row['correct'] / row['branches'] if row['branches'] else None
                        rows.append(row)
                    else:
                        per_pc.append(row)
            if len(rows) != 18:
                raise RuntimeError('expected nine workloads x two fixed service latencies')
            run([bare / 'run', '--inject-observation'], bare, 'negative-observation.log', 'prediction observation mismatch')
            cached_flags = [*flags, '--icache=32768', '--dcache=32768']
            cached = model(role, role + '-cached', 'I1PerformanceCachedMain', 'I1PerformanceCachedCore',
                           cached_flags, 'five_stage_coremark.cpp', ['-DI1_COREMARK_PREDICTION=1'])
            cm_rows = []
            for latency in [1, 12]:
                argv = [cached / 'run', payload, symbols['coremark_validation_errors'],
                        symbols['coremark_elapsed_ticks'], symbols['coremark_crcs'], latency]
                text = run(argv, cached, 'coremark-l' + str(latency) + '.log')
                row = json_line(text, 'MATCHED_COREMARK_PASS ')
                row.update(json_line(text, 'I1_COREMARK_PREDICTION '))
                row['memory_latency'] = latency
                row['roi_ipc'] = row['roi_instructions'] / row['roi_ticks']
                row['roi_branch_accuracy'] = row['roi_correct'] / row['roi_branches']
                row['roi_branch_mpki'] = 1000 * (row['roi_branches'] - row['roi_correct']) / row['roi_instructions']
                row['per_static_pc'] = [dict((key, int(value)) for key, value in
                    (token.split('=', 1) for token in line.split()[1:]))
                    for line in text.splitlines() if line.startswith('I1_COREMARK_PC ')]
                if sum(pc['count'] for pc in row['per_static_pc']) != row['roi_branches']:
                    raise RuntimeError('CoreMark per-PC denominator mismatch')
                cm_rows.append(row)
                print(role, 'CoreMark', latency, 'ROI', row['roi_ticks'], 'IPC', round(row['roi_ipc'], 6),
                      'prediction', round(row['roi_branch_accuracy'], 6), flush=True)
            run([*argv, '--inject'], cached, 'negative-register.log', 'CoreMark independent register oracle mismatch')
            run([*argv, '--inject-prediction-observer'], cached, 'negative-prediction.log', 'prediction observation mismatch')
            receipt['profiles'][role] = {'flags': flags, 'isa_summary': isa.strip().splitlines()[-1],
                'performance': rows, 'performance_per_static_pc': per_pc, 'coremark': cm_rows,
                'negative_register_store_prediction_rejected': True}
            save()

        for before, after in zip(frozen_cm['profiles']['default']['rows'], receipt['profiles']['reference']['coremark']):
            for key in ['cycles', 'roi_ticks', 'roi_instructions', 'retired', 'trace_fnv64', 'crcfinal',
                        'roi_branches', 'roi_correct', 'roi_returns_correct', 'roi_indirect_correct']:
                if before[key] != after[key]:
                    raise RuntimeError('first-batch frozen CoreMark baseline differs: ' + key)
        for field in ['performance', 'performance_per_static_pc', 'coremark', 'isa_summary']:
            if receipt['profiles']['reference'][field] != receipt['profiles']['local'][field]:
                raise RuntimeError('bank-local structural change altered identical prediction behavior: ' + field)
        for before, after in zip(receipt['profiles']['reference']['coremark'], receipt['profiles']['hashed']['coremark']):
            for key in ['roi_instructions', 'retired', 'trace_fnv64', 'crcfinal', 'roi_branches']:
                if before[key] != after[key]:
                    raise RuntimeError('hashed CoreMark architectural workload mismatch: ' + key)
            if after['roi_ticks'] > before['roi_ticks']:
                raise RuntimeError('hashed CoreMark ROI regressed')
        for name, digest in frozen.items():
            if sha(ROOT / name) != digest:
                raise RuntimeError('source drift during acceptance: ' + name)
        rtl.mkdir(parents=True)
        for role in ['reference', 'local', 'hashed']:
            folder = rtl / role
            folder.mkdir()
            flags = [64, '--pipeline=fpga8', '--timing-cuts', '--predictor=128']
            if role == 'hashed':
                flags += ['--hashed-branch-index']
            emit(role, 'I1PredictionTimingMain', folder, flags)
        receipt['rtl_sha256'] = {str(path.relative_to(rtl)): sha(path) for path in sorted(rtl.rglob('*.sv'))}
        receipt['rtl_root'] = str(rtl)
        receipt['status'] = 'PASS_I1_PREDICTION_BATCH_SHORT_COREMARK_ONLY'
    except BaseException as error:
        receipt.update(status='FAIL', error=repr(error))
        raise
    finally:
        save()
    print(json.dumps({'status': receipt['status'], 'receipt': str(output / 'receipt.json')}, indent=2))


if __name__ == '__main__':
    main()
