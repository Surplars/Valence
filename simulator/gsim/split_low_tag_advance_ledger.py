#!/usr/bin/env python3
"""Qualified-epoch guarded-natural control/split tag-advance actual ROB ledger replay."""
import argparse
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from datetime import datetime, timezone

sys.dont_write_bytecode = True
import run as common


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inputs():
    paths = sorted((common.ROOT / 'src/main/scala').rglob('*.scala'))
    paths += sorted((common.ROOT / 'third_party/berkeley-hardfloat').rglob('*.scala'))
    paths += [common.ROOT / p for p in (
        'build.mill', '.mill-jvm-opts', 'src/test/scala/ooo/RenameRobGsim.scala',
        'src/test/scala/ooo/SplitLowTagAdvanceLedgerGsim.scala', 'simulator/gsim/run.py',
        'simulator/gsim/split_low_tag_advance_ledger.py', 'simulator/gsim/rob_ledger_qualification.py', 'simulator/gsim/gsim_initialization_epoch.py', 'simulator/gsim/harness/backend.cpp',
        'simulator/gsim/harness/rob_ledger_qualification.cpp', 'simulator/gsim/config/toolchain.json')]
    return {str(p.relative_to(common.ROOT)): sha(p) for p in paths}


def adapter(destination):
    original = (common.HERE / 'harness/backend.cpp').read_text()
    changes = {
        '#include "RenameRobGsim.h"': '#include "RenameRobGsim.h"\nstruct Output; struct Input;\n'
            'static void mutateObservation(Output &, const Input &);\n'
            'static bool observeRecovery(bool, const Input &);\nstatic bool observeHeadException(bool);',
        'Output out = sample(dut);': 'Output out = sample(dut);\n        mutateObservation(out, in);',
        'check(bool(dut.get_io$$recoveryAccepted()) == acceptRecovery,':
            'check(observeRecovery(bool(dut.get_io$$recoveryAccepted()), in) == acceptRecovery,',
        'check(bool(dut.get_io$$headException$$valid()) == headFault,':
            'check(observeHeadException(bool(dut.get_io$$headException$$valid())) == headFault,',
        '<< " rejectedCompletions=" << model.rejected << " seeds=3 randomCycles=18000\\n";\n}':
            '<< " rejectedCompletions=" << model.rejected << " seeds=3 randomCycles=18000\\n";\n    return 0;\n}'
    }
    for old, new in changes.items():
        if original.count(old) != 1:
            raise RuntimeError('oracle observer adapter anchor is not unique: ' + old)
        original = original.replace(old, new)
    destination.write_text(original)
    return ['declare three observation-only adapter hooks', 'mutate sampled Output before unchanged deque oracle',
            'observe sampled recovery/head-exception booleans before unchanged oracle',
            'explicit success return required after renaming inherited main']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-run', action='store_true')
    parser.add_argument('--tag', default='split-low-tag-advance-ledger-r1')
    parser.add_argument('--compile-receipt', type=Path)
    parser.add_argument('--tool-receipt', type=Path)
    a = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', a.tag):
        parser.error('tag must contain only letters, numbers, underscore or hyphen')
    before = inputs()
    if not a.build_run:
        print(json.dumps({'status': 'PREFLIGHT_ONLY', 'input_files': len(before), 'models': 2,
            'geometry': 'ROB16/PRF48/rename2/complete2/commit2/recovery4/tag64',
            'source': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=common.ROOT, text=True).strip()}))
        return
    if not a.compile_receipt or not a.tool_receipt:
        parser.error('bound compile and corrected tool receipts required')
    import gsim_initialization_epoch as epoch
    if sha(a.tool_receipt) != '128c4853a6584cd1181cff863fc727a824fe132ad3c60f3ba323d46ea3b135fa':
        raise RuntimeError('expected qualified deterministic corrected epoch receipt')
    binding = epoch.tool_binding(a.tool_receipt)
    spec = importlib.util.spec_from_file_location('compile_gate', common.ROOT/'fpga/common/scala_compile_receipt.py')
    gate = importlib.util.module_from_spec(spec); spec.loader.exec_module(gate)
    compiled = gate.verify_receipt(a.compile_receipt, common.ROOT)
    classpath = os.pathsep.join(compiled["runClasspathEntries"])
    out = common.BUILD / a.tag
    out.mkdir(parents=True, exist_ok=False)
    receipt = {'schema': 'valence-split-low-tag-advance-ledger-v1', 'status': 'RUNNING',
        'started_utc': datetime.now(timezone.utc).isoformat(), 'inputs': before,
        'base_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=common.ROOT, text=True).strip(),
        'source_changes': subprocess.check_output(['git', 'status', '--short'], cwd=common.ROOT, text=True),
        'profile': 'guarded-natural coreParams; only splitLowTagAdvance differs',
        'tool_epoch': binding, 'compile_receipt_sha256': sha(a.compile_receipt),
        'cases': {}, 'negatives': {}, 'fresh_model_generation': True,
        'limits': ['Module-level ledger proof, not whole-core/ISA/system proof.',
            'All 64 generation bits challenged with stale-owner mismatches. Live allocations start at zero;'
            ' 2^64 generation exhaustion cannot be traversed by this bounded replay.',
            'Retirement bypass qualifiers are true in this existing focused wrapper; fastHeadRetire is disabled.'
            ' Current core/board tests own those integrated producer contracts.',
            'Reset requires external producers reset/drained; cross-reset stale completions are not allowed by the RTL contract.',
            'No synthesis, implementation, mapping, timing, CDC, FPGA-board or performance qualification.']}
    try:
        gsim = Path(binding['gsim']['path'])
        revision = binding['gsim'].get('revision', epoch.REVISION)
        cxx, version = common.compiler()
        receipt['tools'] = {'gsim_revision': revision, 'gsim_sha256': sha(gsim), 'compiler': version,
            'compiler_sha256': sha(cxx), 'sanitizers': ['address', 'undefined'], 'leak_sanitizer': False,
            'build_parallelism': 'one model/one translation unit at a time; jobs <= 2'}
        env = {**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'}
        negative_modes = {
            '--mutate=pc': 'commit record', '--mutate=instruction': 'commit record',
            '--mutate=data': 'commit record', '--mutate=token': 'commit record',
            '--mutate=completion-owner': 'stale/duplicate/wrong-path completion filter',
            '--mutate=high-tag-completion': 'stale/duplicate/wrong-path completion filter',
            '--mutate=source': 'same-packet source mapping', '--mutate=retire-prefix': 'ordered commit prefix',
            '--mutate=recovery-owner': 'recovery acceptance/age', '--mutate=exception': 'precise head exception',
            '--inject-head-trap-mismatch': 'head trap acceptance oracle mismatch',
            '--inject-head-system-mismatch': 'head system acceptance oracle mismatch',
            '--inject-tentative-source-mismatch': 'same-packet source mapping'}
        for name in ('control', 'split'):
            model = out / name
            model.mkdir()
            receipt['oracle_adapter_changes'] = adapter(model / 'backend_qualification_adapter.h')
            common.run(['java', '-cp', classpath, 'ooo.SplitLowTagAdvanceLedgerGsimMain', model, name],
                log=model / 'elaborate.log', timeout=1800)
            params = json.loads((model / 'effective-params.json').read_text())
            receipt.setdefault('effective_params', {})[name] = params
            common.run([gsim, '--threads=1', '--dir=' + str(model), model / 'RenameRobGsim.fir'],
                log=model / 'generate.log', timeout=1200)
            flags = ['-std=c++20', '-O1', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                '-DROB_ENTRIES=16', '-DPHYSICAL_REGS=48', '-DTAG_BITS=64', '-DRECOVERY_WIDTH=4',
                '-DFAST_HEAD_TRAP=1', '-DFAST_HEAD_SYSTEM=1', '-I' + str(model)]
            objects = []
            for source in sorted(model.glob('RenameRobGsim[0-9]*.cpp')):
                obj = source.with_suffix('.o')
                common.run([cxx, *flags, '-c', source, '-o', obj], log=obj.with_suffix('.compile.log'), timeout=1200)
                objects.append(obj)
            harness = common.HERE / 'harness/rob_ledger_qualification.cpp'
            harness_obj = model / 'qualification-harness.o'
            common.run([cxx, *flags, '-c', harness, '-o', harness_obj], log=model / 'harness-compile.log', timeout=600)
            common.run([cxx, *flags, *objects, harness_obj, '-ldl', '-o', model / 'run'], log=model / 'link.log')
            receipt['cases'][name] = {}
            for label, args in (('ledger', []), ('trusted-head-trap', ['--head-trap-short']),
                                ('trusted-head-system', ['--authorization-short'])):
                log = model / (label + '.log')
                common.run([model / 'run', *args], env=env, log=log, timeout=180)
                receipt['cases'][name][label] = log.read_text()
            receipt['negatives'][name] = {}
            for mode, anchor in negative_modes.items():
                result = subprocess.run([model / 'run', mode], capture_output=True, text=True, env=env, timeout=180)
                log = model / ('negative-' + mode.lstrip('-').replace('=', '-') + '.log')
                log.write_text(result.stdout + result.stderr)
                text = log.read_text()
                if result.returncode == 0 or anchor not in text or ('--mutate=' in mode and 'fired=1' not in text):
                    raise RuntimeError('negative control failed to reject for expected reason: ' + mode)
                receipt['negatives'][name][mode] = {'status': 'EXPECTED_REJECTION', 'exit_code': result.returncode,
                    'anchor': anchor, 'log': str(log.relative_to(out)), 'sha256': sha(log)}
        if receipt['cases']['control'] != receipt['cases']['split']:
            raise RuntimeError('paired control/split deterministic ledger results differ')
        left, right = receipt['effective_params']['control'].copy(), receipt['effective_params']['split'].copy()
        if left.pop('splitLowTagAdvance') != 'false' or right.pop('splitLowTagAdvance') != 'true' or left != right:
            raise RuntimeError('unapproved paired profile differences')
        receipt['paired_result'] = 'IDENTICAL_POSITIVE_LOGS_AND_PARAMS_EXCEPT_TAG_ADVANCE'
        gate.verify_receipt(a.compile_receipt, common.ROOT)
        if epoch.tool_binding(a.tool_receipt) != binding:
            raise RuntimeError('corrected tool epoch drift')
        receipt['status'] = 'PASS_FOCUSED_FULL64_LEDGER'
    except Exception as error:
        receipt['status'] = 'FAIL'
        receipt['error'] = str(error)
        raise
    finally:
        receipt['finished_utc'] = datetime.now(timezone.utc).isoformat()
        if before != inputs():
            receipt['status'] = 'FAIL_SOURCE_CHANGED'
        # Save actual model/header/objects/executables plus all raw logs; never omit negatives.
        receipt['artifacts'] = {str(p.relative_to(out)): {'sha256': sha(p), 'bytes': p.stat().st_size}
            for p in sorted(out.rglob('*')) if p.is_file() and p.name != 'receipt.json'}
        (out / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
        if before != inputs():
            raise RuntimeError('source changed during qualification')
    print(json.dumps({'status': receipt['status'], 'receipt': str(out / 'receipt.json'),
        'receipt_sha256': sha(out / 'receipt.json'), 'negative_controls': sum(map(len, receipt['negatives'].values()))}))


if __name__ == '__main__':
    main()
