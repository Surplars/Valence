#!/usr/bin/env python3
"""Opt-in focused storage proof; default is source-only preflight, no tool installation."""
import argparse
import json
from pathlib import Path
import hashlib
import os
import subprocess
import shutil
import re
import run as common


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tag', default='fpga-storage')
    ap.add_argument('--build-run', action='store_true')
    ap.add_argument('--core', action='store_true', help='Also compile the explicit short core A/B pair')
    ap.add_argument('--prf', action='store_true', help='Core-only pair: existing storage options on both sides; candidate adds owner-banked PRF')
    ap.add_argument('--reference-root', type=Path, help='Existing build/gsim directory containing pinned NEMU and reference-used.json')
    ap.add_argument('--core-only', action='store_true', help='Run the core pair after a separately recorded ledger phase')
    ap.add_argument('--baseline-model', type=Path, help='Reuse exact emitted baseline FIR/header/C++ after a test-only fix')
    a = ap.parse_args()
    if a.prf:
        a.core_only = True
    if a.core_only:
        a.core = True
    if not a.tag.replace('-', '').replace('_', '').isalnum():
        ap.error('tag must contain only letters, digits, hyphens and underscores')
    inputs = sorted((common.ROOT/'src/main/scala').rglob('*.scala')) + [Path(__file__),
        common.ROOT/'src/test/scala/ooo/RenameRobGsim.scala',
        common.ROOT/'src/test/scala/ooo/ThroughputPerfGsim.scala',
        common.HERE/'harness/backend.cpp', common.HERE/'harness/core.cpp']
    hashes = lambda: {str(p.relative_to(common.ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    before = hashes()
    if not a.build_run:
        print(json.dumps({'status': 'PREFLIGHT_ONLY', 'source_files': len(before),
            'planned_models': 2 if a.core_only else (4 if a.core else 2), 'synthesis': False, 'cycle_equivalence': 'unverified'}))
        return
    out = common.BUILD/a.tag
    out.mkdir(parents=True, exist_ok=False)
    report = {'status': 'RUNNING', 'inputs': before, 'cases': {}, 'synthesis': False}
    try:
        gsim, cxx = common.setup(False)
        for enabled in (() if a.core_only else (False, True)):
            name = 'banked' if enabled else 'registers'
            flags = ('banked-payload',) if enabled else ()
            model = common.test(gsim, cxx, f'{a.tag}/ledger-{name}', 'ooo.RenameRobGsimMain',
                'RenameRobGsim', 'backend.cpp', parameters=('16', '48', '8', '4', *flags),
                defines={'ROB_ENTRIES': 16, 'PHYSICAL_REGS': 48, 'TAG_BITS': 8, 'RECOVERY_WIDTH': 4})
            report['cases']['ledger-'+name] = (model/'test.log').read_text()
            result = subprocess.run([model/'run', '--inject-rob-payload-mismatch'],
                capture_output=True, text=True, timeout=120,
                env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'})
            (model/'negative-payload.log').write_text(result.stdout + result.stderr)
            if result.returncode == 0 or 'commit record' not in result.stdout + result.stderr:
                raise RuntimeError('valid ROB payload corruption was not rejected')
        if not a.core_only and report['cases']['ledger-banked'] != report['cases']['ledger-registers']:
            raise RuntimeError('paired deterministic ledger outcomes differ')
        if a.core:
            from control_stage import core_payloads
            from throughput_perf import DEFINES, parse_measurements
            reference_root = a.reference_root.resolve() if a.reference_root else common.BUILD
            ref = reference_root/'nemu-src/build/riscv64-nemu-interpreter-so'
            used_path = reference_root/'reference-used.json'
            if not ref.is_file() or not used_path.is_file():
                raise RuntimeError('Pinned NEMU reference is missing; no automatic download/build is allowed')
            lock = json.loads((common.HERE/'config/reference-lock.json').read_text())
            used = json.loads(used_path.read_text())
            config_sha = hashlib.sha256((common.HERE/'config/rv64-integer-ref_defconfig').read_bytes()).hexdigest()
            if any(used.get(k) != v for k, v in lock.items()) or used.get('config_sha256') != config_sha or \
                    used.get('library_sha256') != hashlib.sha256(ref.read_bytes()).hexdigest():
                raise RuntimeError('Pinned NEMU reference provenance/hash check failed')
            payloads = core_payloads(out)
            report['reference_sha256'] = hashlib.sha256(ref.read_bytes()).hexdigest()
            report['payload_sha256'] = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in payloads}
            measurements = []
            for enabled in (False, True):
                name = 'mapped' if enabled else 'baseline'
                flags = (('banked-rob', 'shared-store-reads') + (('lvt-prf',) if enabled else ())) if a.prf else (('banked-rob', 'shared-store-reads') if enabled else ())
                model = out/('core-'+name)
                model.mkdir()
                reused_objects = False
                if not enabled and a.baseline_model:
                    previous = a.baseline_model.resolve()
                    previous_receipt = json.loads((previous.parent/'receipt.json').read_text())
                    if a.prf:
                        common.run(['mill', '-i', 'IonSoC.test.runMain', 'ooo.ThroughputPerfGsimMain',
                            model, 'staged-fetch-turnover', *flags], log=model/'elaborate.log')
                        def canonical(path):
                            text = re.sub(r'@\[[^\n]*?\]', '', path.read_text())
                            # Only automatic diagnostic source line numbers differ;
                            # retain every assertion condition, label and message text.
                            return re.sub(r'(Assertion failed at [A-Za-z0-9_]+\.scala:)\d+(\\n)', r'\g<1>LINE\2', text)
                        if canonical(model/'IntegerCoreGsim.fir') != canonical(previous/'IntegerCoreGsim.fir'):
                            raise RuntimeError('default PRF FIR differs after source-location stripping; do not reuse old object without further equivalence proof')
                        expected = previous_receipt['model_sha256']['mapped']
                        for source in [previous/'IntegerCoreGsim.h', *sorted(previous.glob('IntegerCoreGsim[0-9]*.cpp')),
                                       *sorted(previous.glob('IntegerCoreGsim[0-9]*.o'))]:
                            if expected.get(source.name) != hashlib.sha256(source.read_bytes()).hexdigest():
                                raise RuntimeError('previous passed model artifact changed: '+source.name)
                        reused_objects = True
                        report['legacy_default_canonical_fir_equal'] = True
                        report['canonical_rules'] = ['strip source-location annotations', 'normalize automatic assertion diagnostic Scala line numbers only']
                    else:
                        for rel, sha in before.items():
                            if rel.startswith('src/') and previous_receipt['inputs'].get(rel) != sha:
                                raise RuntimeError('baseline model production/wrapper source mismatch: '+rel)
                    reused = {}
                    for source in [previous/'IntegerCoreGsim.fir', previous/'IntegerCoreGsim.h',
                                   *sorted(previous.glob('IntegerCoreGsim[0-9]*.cpp')),
                                   *(sorted(previous.glob('IntegerCoreGsim[0-9]*.o')) if reused_objects else [])]:
                        reused[source.name] = hashlib.sha256(source.read_bytes()).hexdigest()
                        shutil.copy2(source, model/source.name)
                        assert hashlib.sha256((model/source.name).read_bytes()).hexdigest() == reused[source.name]
                    report['baseline_emitted_model_reuse'] = reused
                else:
                    common.run(['mill', '-i', 'IonSoC.test.runMain', 'ooo.ThroughputPerfGsimMain',
                        model, 'staged-fetch-turnover', *flags], log=model/'elaborate.log')
                    common.run([gsim, '--threads=1', '--dir='+str(model), model/'IntegerCoreGsim.fir'],
                        log=model/'generate.log')
                compile_flags = ['-std=c++20', '-O1', '-g', '-fsanitize=address,undefined',
                    '-fno-sanitize-recover=all', '-I'+str(model)]
                objects = []
                for source in sorted(model.glob('IntegerCoreGsim[0-9]*.cpp')):
                    obj = source.with_suffix('.o')
                    if not reused_objects:
                        common.run([cxx, *compile_flags, '-c', source, '-o', obj], log=obj.with_suffix('.compile.log'))
                    elif not obj.is_file():
                        raise RuntimeError('verified model object missing: '+str(obj))
                    objects.append(obj)
                defines = {**DEFINES, 'REGISTERED_FETCH_PACKET': 1, 'FPGA_STORAGE_OBSERVE': 1}
                common.run([cxx, *compile_flags, *[f'-D{k}={v}' for k,v in defines.items()],
                    common.HERE/'harness/core.cpp', *objects, '-ldl', '-o', model/'run'],
                    log=model/'harness-compile.log')
                report.setdefault('model_sha256', {})[name] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in [model/'IntegerCoreGsim.fir', model/'IntegerCoreGsim.h', *objects,
                              *sorted(model.glob('IntegerCoreGsim[0-9]*.cpp'))]}
                common.run([model/'run', ref, *payloads, '--throughput-short'],
                    env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'}, log=model/'test.log', timeout=180)
                rows = parse_measurements((model/'test.log').read_text())
                measurements.append(rows)
                common.run([model/'run', ref, *payloads, '--pipeline-recovery'],
                    env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'},
                    log=model/'pipeline-recovery.log', timeout=180)
                from control_stage import negative
                negative(model/'run', (ref, *payloads), 'NEMU register mismatch', model/'negative-register.log')
                report['cases']['core-'+name] = rows
            if measurements[0] != measurements[1]:
                raise RuntimeError('short core cycle/retirement/counter comparison changed')
        report['comparison'] = 'legacy PRF versus owner-banked PRF, existing storage options enabled on both sides' if a.prf else 'legacy versus banked ROB/shared store reads'
        report['status'] = 'PASS_CORE_ONLY' if a.core_only else ('PASS_FOCUSED' if a.core else 'PASS_LEDGER_ONLY')
    except Exception as error:
        report['status'] = 'FAIL'
        report['error'] = str(error)
        raise
    finally:
        if before != hashes():
            report['status'] = 'FAIL_SOURCE_CHANGED'
        (out/'receipt.json').write_text(json.dumps(report, indent=2)+'\n')
        if before != hashes():
            raise RuntimeError('source changed during proof')


if __name__ == '__main__':
    main()
