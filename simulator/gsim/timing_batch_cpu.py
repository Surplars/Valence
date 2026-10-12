#!/usr/bin/env python3
"""Fresh pristine-1e90 maxperf versus explicit A+C / A+B+C timing candidates.

Default is a source/command plan. --execute builds one source at a time with one
compiler job. Guest, hosts, independent oracles and service laws are inherited
unchanged from memory_schedule_overlap.py. Historical cycle totals are never
accepted as a fresh baseline. Run pristine baseline before either candidate.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import sys

# Resolve helpers from the selected source, not from the runner's storage path.
bootstrap = argparse.ArgumentParser(add_help=False)
bootstrap.add_argument('--source-root', type=Path, required=True)
selected, _ = bootstrap.parse_known_args()
SOURCE_ROOT = selected.source_root.resolve()
RUNNER = Path(__file__).resolve()
sys.path.insert(0, str(SOURCE_ROOT / 'simulator/gsim'))
import bound_store_replay_common as portable
import run as common
import tagged_store_return_board as published
from result_contract import capture_result

ROOT = common.ROOT
PACKAGE = ROOT / 'simulator/gsim/memory_schedule_overlap'
BASE_COMMIT = '1e90af966c15d871d2544469174acba78473113b'
MODES = {'baseline': (False, False, False), 'ac': (True, False, True), 'abc': (True, True, True)}
MEMORY_FLAGS = ['--internal-line-grant', '--concurrent-read-store-prefetch', '--memory-schedule-overlap']
STAGE_FLAGS = ['--registered-pending-store-query', '--aligned-fetch-permission-stage', '--registered-canonical-store-event']
STAGE_FIELDS = ['registeredPendingStoreQuery', 'alignedFetchPermissionStage', 'registeredCanonicalStoreEvent']


def inputs():
    extra = list(common.HERE.rglob('*.h')) + list(common.HERE.rglob('*.cpp'))
    extra += list(common.HERE.glob('*.py')) + list((common.HERE / 'tagged_store_return_board').glob('*.json'))
    extra += list((common.HERE / 'payloads').glob('cpu_*')) + list((common.HERE / 'config').glob('*.json'))
    result = portable.source_inputs(ROOT, extra)
    result["runner:" + str(RUNNER)] = portable.sha(RUNNER)
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    ap.add_argument('--source-root', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--profiles', nargs='+', choices=tuple(MODES), required=True)
    ap.add_argument('--baseline-receipt', type=Path)
    ap.add_argument('--jobs', type=int, choices=(1,), default=1)
    ap.add_argument('--execute', action='store_true')
    args = ap.parse_args()
    assert ROOT == SOURCE_ROOT and len(set(args.profiles)) == len(args.profiles)
    baseline_run = args.profiles == ['baseline']
    assert baseline_run or 'baseline' not in args.profiles, 'pristine baseline is a separate source run'
    source_head = portable.source_revision(ROOT)
    assert source_head == BASE_COMMIT, 'runner requires the pinned 1e90 base; changes belong in frozen working tree'
    if baseline_run:
        assert not subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=ROOT, text=True), \
            'baseline must be pristine tracked 1e90 source'
    spec = published.load(published.PACKAGE / 'contract.json')
    assert len(spec['native_options']) == 40 and len(set(spec['native_options'])) == 40
    selected_options = {label: spec['native_options'] + MEMORY_FLAGS +
        [flag for flag, enabled in zip(STAGE_FLAGS, MODES[label]) if enabled]
        for label in args.profiles}
    out = args.output.resolve()
    assert out.is_relative_to(common.BUILD.resolve()), 'evidence must stay under selected source build/gsim'
    baseline = None
    if args.baseline_receipt:
        baseline = published.load(args.baseline_receipt)
        assert baseline['status'] == 'PASS_TIMING_BATCH_CPU' and baseline['profiles'] == ['baseline']
        assert baseline['source_head'] == BASE_COMMIT and baseline['pristine_source'] is True
        assert set(baseline['cases']['baseline']) == {'sv39', 'bare'}
        baseline_root = Path(baseline['source_root'])
        assert (baseline_root / 'simulator/gsim/memory_schedule_overlap.py').is_file()
        for rel, digest in baseline['artifacts'].items():
            assert portable.sha(args.baseline_receipt.parent / rel) == digest, 'baseline artifact drift'
    plan = {'schema': 'timing-batch-cpu-plan-v1', 'status': 'PLAN_ONLY',
        'source_root': str(ROOT), 'source_head': source_head, 'profiles': args.profiles,
        'options': selected_options, 'compiler_jobs': 1, 'fresh_models_required': True,
        'baseline_receipt': str(args.baseline_receipt) if args.baseline_receipt else None,
        'host_guest_service_source': 'simulator/gsim/memory_schedule_overlap.py',
        'run_arguments': ['guest.bin', 'mode', '2', '65536', '2'],
        'old_cycle_totals_used_for_acceptance': False,
        'physical_qualification': False}
    if not args.execute:
        print(json.dumps(plan, indent=2))
        return
    assert baseline_run or baseline is not None, 'candidate execution requires a verified fresh baseline receipt'
    out.mkdir(parents=True, exist_ok=False)
    frozen = inputs()
    r = {'schema': 'timing-batch-cpu-v1', 'status': 'RUNNING', 'source_head': source_head,
         'source_root': str(ROOT), 'pristine_source': baseline_run,
         'inputs': frozen, 'profiles': args.profiles, 'commands': [], 'cases': {}, 'models': {},
         'physical_qualification': False, 'preset_promoted': False, 'compiler_jobs': 1,
         'dependencies': {}, 'native_options': selected_options,
         'baseline_receipt': {'path': str(args.baseline_receipt), 'sha256': portable.sha(args.baseline_receipt)}
             if args.baseline_receipt else None,
         'oracle_reference_contract_sha256': portable.sha(published.PACKAGE / 'contract.json'),
         'runner_sha256': portable.sha(RUNNER),
         'host_guest_service_source_sha256': portable.sha(ROOT / 'simulator/gsim/memory_schedule_overlap.py')}

    def save():
        (out / 'receipt.json').write_text(json.dumps(r, indent=2) + '\n')

    def guard():
        assert inputs() == frozen, 'source changed during matched experiment'

    def step(name, cmd, *, expected=0, anchor=None, cwd=ROOT, timeout=900):
        cmd = list(map(str, cmd))
        print('+ ' + name + ' ' + ' '.join(cmd), flush=True)
        log = out / (name + '.log')
        start = time.monotonic()
        with log.open('x') as stream:
            p = subprocess.run(cmd, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT, timeout=timeout,
                env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0', 'PYTHONDONTWRITEBYTECODE': '1'})
        text = log.read_text()
        r['commands'].append({'name': name, 'argv': cmd, 'exit': p.returncode, 'expected': expected,
            'seconds': time.monotonic() - start, 'log_sha256': portable.sha(log)})
        if p.returncode != expected or (anchor and anchor not in text):
            raise RuntimeError(name + '\n' + text[-6000:])
        assert not re.search(r'ERROR: AddressSanitizer|runtime error:|UndefinedBehaviorSanitizer', text), name
        return text

    def build(label, top, emitter, arguments, flags, host):
        guard()
        model = out / label
        model.mkdir()
        step(label + '-emit', ['mill', '-i', '-j', '1', 'IonSoC.test.runMain', emitter, model, *arguments])
        step(label + '-generate', [gsim, '--threads=1', '--cpp-max-size-KB=1024', '--dir=' + str(model), model / (top + '.fir')])
        units = sorted(model.glob(top + '[0-9]*.cpp'))
        assert units, 'no official GSIM units'
        def compile_unit(item):
            i, unit = item
            step(label + '-compile-' + str(i), [cxx, *flags, '-I' + str(model), '-MD', '-MF', unit.with_suffix('.d'),
                '-c', unit, '-o', unit.with_suffix('.o')])
        for item in enumerate(units):
            compile_unit(item)
        for unit in units:
            portable.record_dependencies(unit.with_suffix('.d'), ROOT, r['dependencies'])
        binary = model / 'run'
        step(label + '-link', [cxx, *flags, '-I' + str(model), host,
            *[u.with_suffix('.o') for u in units], '-o', binary])
        r['models'][label] = {p.name: portable.sha(p) for p in model.iterdir() if p.is_file()}
        save()
        guard()
        return model, binary

    save()
    try:
        gsim, cxx = common.setup(False)
        r['tools'] = {'gsim': portable.sha(gsim), 'gsim_lock': common.LOCK,
                      'compiler': common.compiler()[1], 'cxx': portable.sha(shutil.which(cxx))}
        # Component gates are separate and coordinator-owned; this runner retains only
        # the identical full CPU guest, hosts, independent oracles and service laws.
        guard()
        fw = out / 'guest'
        fw.mkdir()
        step('guest', ['riscv64-unknown-elf-gcc', '-march=rv64im_zicsr_zifencei', '-mabi=lp64', '-mno-relax',
            '-nostdlib', '-nostartfiles', '-Wl,--no-relax', '-Wl,--build-id=none', '-T', common.HERE / 'payloads/cpu_hot_bandwidth.ld',
            common.HERE / 'payloads/cpu_sv39_bandwidth.S', '-o', fw / 'guest.elf'])
        step('guest-bin', ['riscv64-unknown-elf-objcopy', '-O', 'binary', fw / 'guest.elf', fw / 'guest.bin'])
        symbols = {}
        for line in step('guest-symbols', ['riscv64-unknown-elf-nm', '-n', fw / 'guest.elf']).splitlines():
            words = line.split()
            if len(words) == 3 and words[2] in ('bw_begin', 'bw_end', 'bw_drain', 'bw_done'):
                symbols[words[2]] = int(words[0], 16)
        assert len(symbols) == 4
        (fw / 'cpu_sv39_symbols.h').write_text(''.join(f'#define {k.upper()} {v}ULL\n' for k, v in symbols.items()))
        for name in ('guest.bin', 'cpu_sv39_symbols.h'):
            assert portable.sha(fw / name) == spec['guest'][name], 'published guest bytes/markers changed'
        r['guest'] = {p.name: portable.sha(p) for p in fw.iterdir()}
        hostspec = copy.deepcopy(spec)
        for name in ('production_probe.h', 'supply_ledger.h', 'passive_supply.h'):
            hostspec['host_sources'][name] = {'source': str((PACKAGE / name).relative_to(ROOT)), 'sha256': portable.sha(PACKAGE / name)}
        host = out / 'host'
        published.host_materialize(ROOT, host, hostspec)
        for label in args.profiles:
            query, fetch, canonical = MODES[label]
            wide = coexist = overlap = True
            options = selected_options[label]
            flags = spec['cxx_flags'] + spec['host_defines'] + ['-DCONCURRENT_READ_STORE_PREFETCH=' + str(int(coexist)),
                '-DMEMORY_SCHEDULE_OVERLAP=' + str(int(overlap)),
                '-I' + str(fw), '-I' + str(host), '-I' + str(host / 'harness')]
            model, binary = build(label, 'BoardSocGsim', 'ooo.CpuMatchingBoardProfileGsimMain', options,
                flags, host / 'cpu_passive_bandwidth.cpp')
            profile = published.load(model / 'profile.json')
            actual = published.load(model / 'actual-fabric.json')
            expected = copy.deepcopy(spec['profile'])
            for section in ('profile', 'cache'):
                expected[section].update(internalLineGrant=wide, concurrentReadStorePrefetch=coexist, memoryScheduleOverlap=overlap)
            if label != 'baseline':
                for section in ('profile', 'core'):
                    expected[section].update(dict(zip(STAGE_FIELDS, MODES[label])))
            assert profile == expected, 'complete actual constructor profile changed outside exact stage fields'
            expected_actual = copy.deepcopy(spec['actual_fabric'])
            expected_actual['cache'].update(internalLineGrant=True, concurrentReadStorePrefetch=True, memoryScheduleOverlap=True)
            if label != 'baseline':
                expected_actual['cpu'].update(dict(zip(STAGE_FIELDS, MODES[label])))
                expected_actual['timingStages'] = {
                    'schema': 'timing-batch-actual-stage-parameters-v1',
                    'registeredPendingStoreQuery': query, 'proofBankPresent': True,
                    'canonicalBackendRegistered': canonical, 'canonicalAdapterRegistered': canonical,
                    'fetchPacketAlignedStage': fetch, 'fetchFrontendBoundedRequest': fetch,
                    'coreFaultOffsetBits': 5 if fetch else 0, 'proofRows': 2, 'earlyLoadCredits': 2,
                    'taggedStoreReturns': True, 'coreFields': 154, 'profileFields': 64}
            assert actual == expected_actual, 'complete actual board fabric differs'
            assert portable.sha(model / 'assembly-contract.json') == spec['assembly_contract_sha256']
            r['cases'][label] = {}
            for name, mode in (('sv39', 1), ('bare', 0)):
                guard()
                work = out / (label + '-' + name)
                work.mkdir()
                text = step(label + '-' + name, [binary, fw / 'guest.bin', mode, 2, 65536, 2], cwd=work, anchor='CPU_SV39_PASS')
                row = capture_result(text, work, spec['baseline_cases'][name], actual)
                row['tagged'] = published.parse(text, 'TAGGED_RETURN_PASS')
                assert row['tagged']['physical'] == row['tagged']['physical_replies'] == row['tagged']['cache_replies']
                row['inclusive_MiBps'] = 12500000 / row['inclusive_cycles']
                # capture_result preserves historical independent architectural oracles;
                # discard its old performance deltas before comparing this fresh pair.
                for key in ('baseline_inclusive_cycles', 'inclusive_delta', 'roi_delta', 'tail_delta'):
                    row.pop(key)
                row['baseline_kind'] = 'FRESH_PRISTINE_1E90_MAXPERF' if baseline_run else 'FRESH_PRISTINE_1E90_PAIRED'
                if baseline is not None:
                    fresh = baseline['cases']['baseline'][name]
                    row['baseline_inclusive_cycles'] = fresh['inclusive_cycles']
                    row['inclusive_delta'] = row['inclusive_cycles'] - fresh['inclusive_cycles']
                    row['roi_delta'] = int(row['result']['cycles']) - int(fresh['result']['cycles'])
                    row['tail_delta'] = int(row['result']['clean_tail']) - int(fresh['result']['clean_tail'])
                    row['vs_fresh_baseline_percent'] = 100 * (fresh['inclusive_cycles'] / row['inclusive_cycles'] - 1)
                r['cases'][label][name] = row
                save()
                print('MEASURED', label, name, row['inclusive_cycles'], row['inclusive_MiBps'], flush=True)
            for mutation, anchor in published.NEGATIVES:
                work = out / (label + '-negative-' + mutation)
                work.mkdir()
                step(label + '-negative-' + mutation, [binary, fw / 'guest.bin', 1, 2, 4096, 1, '--inject-' + mutation],
                     cwd=work, expected=1, anchor=anchor)
            save()
        guard()
        r['artifacts'] = {str(p.relative_to(out)): portable.sha(p) for p in out.rglob('*') if p.is_file() and p.name != 'receipt.json'}
        r['status'] = 'PASS_TIMING_BATCH_CPU'
        save()
    except BaseException as error:
        r['status'] = 'FAIL'
        r['error'] = repr(error)
        save()
        raise


if __name__ == '__main__':
    main()
