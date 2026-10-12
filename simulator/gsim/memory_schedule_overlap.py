#!/usr/bin/env python3
"""Matched ownership-overlap batch; fixed two-issue/two-MSHR, no synthesis.

Preserves the published full guest/byte/tagged lifecycle/service oracles. Two
experimental diagnostic headers change only origin admission/first-refusal rules.
Both arms are emitted and compiled fresh from one frozen source closure.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import copy
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import bound_store_replay_common as portable
import run as common
import tagged_store_return_board as published
from result_contract import capture_result

ROOT = common.ROOT
PACKAGE = ROOT / 'simulator/gsim/memory_schedule_overlap'
MODES = {'previous': (True, True, False), 'overlap': (True, True, True)}


def inputs():
    extra = list(common.HERE.rglob('*.h')) + list(common.HERE.rglob('*.cpp'))
    extra += list(common.HERE.glob('*.py')) + list((common.HERE / 'tagged_store_return_board').glob('*.json'))
    extra += list((common.HERE / 'payloads').glob('cpu_*')) + list((common.HERE / 'config').glob('*.json'))
    return portable.source_inputs(ROOT, extra)


def main():
    ap = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--profiles', nargs='+', choices=tuple(MODES), default=list(MODES))
    ap.add_argument('--jobs', type=int, choices=(1, 2, 4), default=2)
    ap.add_argument('--components-only', action='store_true')
    ap.add_argument('--skip-components', action='store_true')
    ap.add_argument('--reuse-components-from', type=Path,
                    help='host-only correction: rehash all prior model objects and forbid Scala/tool changes')
    args = ap.parse_args()
    assert len(set(args.profiles)) == len(args.profiles), 'duplicate profile'
    out = args.output.resolve()
    assert out.is_relative_to(common.BUILD.resolve()), 'evidence must stay under ignored build/gsim'
    out.mkdir(parents=True, exist_ok=False)
    frozen = inputs()
    prior = None
    if args.reuse_components_from:
        prior = json.loads((args.reuse_components_from / 'receipt.json').read_text())
        portable.check_dependencies(prior['dependencies'])
        assert prior['inputs'].keys() <= frozen.keys()
        changed = {n for n in frozen if frozen[n] != prior['inputs'].get(n)}
        assert changed <= {'simulator/gsim/memory_schedule_overlap.py',
            'simulator/gsim/harness/memory_schedule_overlap.cpp',
            'simulator/gsim/harness/memory_schedule_admission_probe.cpp',
            'simulator/gsim/memory_schedule_overlap/passive_supply.h',
            'simulator/gsim/memory_schedule_overlap/production_probe.h',
            'simulator/gsim/memory_schedule_overlap/supply_ledger.h',
            'simulator/gsim/harness/concurrent_read_store_prefetch.cpp',
            'simulator/gsim/harness/prefetch_demand_adoption_oracle.h'}, 'hardware/source drift forbids model reuse'
    spec = published.load(published.PACKAGE / 'contract.json')
    r = {'schema': 'memory-schedule-overlap-matched-v1', 'status': 'RUNNING', 'source_head': portable.source_revision(ROOT),
         'inputs': frozen, 'profiles': args.profiles, 'commands': [], 'cases': {}, 'models': {},
         'physical_qualification': False, 'preset_promoted': False, 'compiler_jobs': args.jobs,
         'published_original_law_totals': {'sv39': 236951, 'bare': 260694},
         'previous_combined_totals': {'sv39': 202290, 'bare': 215747}, 'dependencies': {}}

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
        reused = prior is not None and label in prior['models']
        if reused:
            assert r['tools'] == prior['tools'], 'reused model toolchain changed'
            old = args.reuse_components_from / label
            for name, digest in prior['models'][label].items():
                assert portable.sha(old / name) == digest, 'prior model artifact changed'
                if Path(name).suffix in ('.o', '.cpp', '.h', '.fir', '.json'):
                    shutil.copyfile(old / name, model / name)
            r.setdefault('reused_models', {})[label] = {'receipt_sha256': portable.sha(args.reuse_components_from / 'receipt.json'),
                'model_artifacts': prior['models'][label], 'host_only_changes': sorted(changed)}
        else:
            step(label + '-emit', ['mill', '-i', '-j', '1', 'IonSoC.test.runMain', emitter, model, *arguments])
            step(label + '-generate', [gsim, '--threads=1', '--cpp-max-size-KB=1024', '--dir=' + str(model), model / (top + '.fir')])
        units = sorted(model.glob(top + '[0-9]*.cpp'))
        assert units, 'no official GSIM units'
        def compile_unit(item):
            i, unit = item
            step(label + '-compile-' + str(i), [cxx, *flags, '-I' + str(model), '-MD', '-MF', unit.with_suffix('.d'),
                '-c', unit, '-o', unit.with_suffix('.o')])
        if not reused:
            with ThreadPoolExecutor(max_workers=args.jobs) as pool:
                list(pool.map(compile_unit, enumerate(units)))
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
        short_flags = ['-std=c++20', '-O1', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=all']
        # New Home policy still rejects full-PA, source and committed/transient
        # way conflicts. Old-mode assertions and original data oracles remain.
        for overlap in (0, 1):
            label = 'admission-probe-' + str(overlap)
            binary = out / label
            step(label + '-build', [cxx, *short_flags, '-DMEMORY_SCHEDULE_OVERLAP=' + str(overlap),
                '-I' + str(PACKAGE), common.HERE / 'harness/memory_schedule_admission_probe.cpp', '-o', binary])
            step(label + '-positive', [binary], anchor='MEMORY_ADMISSION_PROBE_PASS')
            for mutation in ('same-line', 'source', 'full'):
                step(label + '-negative-' + mutation, [binary, mutation], expected=1,
                    anchor='passive home accepted a known blocker')
            if overlap:
                for mutation in ('slot-alias', 'owned-slot'):
                    step(label + '-negative-' + mutation, [binary, mutation], expected=1,
                        anchor='passive transient directory reservation collision')
        save()
        if not args.skip_components:
            step('configuration', ['mill', '-i', '-j', '1', 'IonSoC.test.testOnly',
                'ooo.MemoryScheduleOverlapConfigSpec', 'ooo.LineGrantPrefetchConfigSpec', 'ooo.DurableReadPrefetchConfigSpec',
                'ooo.ReadPrefetchDemandAdoptionConfigSpec', 'ooo.PendingVirtualStoreProofConfigSpec'], anchor='All tests passed')
            save()
            # Real cache/home lifecycle suite, original compact data/ownership oracles.
            flags = short_flags + ['-I' + str(common.HERE / 'harness'), '-DSPLIT_PREFETCH_TRACKING=1',
                '-DSTORE_PF_LRU_ON=0', '-DPF_CANDIDATE_CYCLES=16', '-DCACHE_WAYS=2', '-DREAD_PF_DIRTY_RETRY=1',
                '-DREAD_PF_DEMAND_ADOPTION=1', '-DREAD_PF_STORE_HOLD=1', '-DPREFETCH_INDEPENDENT_STORE_ADMISSION=1',
                '-DDURABLE_READ_PREFETCH=1', '-DCONCURRENT_READ_STORE_PREFETCH=1',
                '-DREAD_MSHRS=2', '-DCACHE_LINES=512', '-DRESPONSE_ENTRIES=2', '-DAXI_SLOTS=4']
            for overlap in (0, 1):
                label = 'ownership-' + str(overlap)
                _, binary = build(label, 'CoherentCacheHomeGsim', 'ooo.DurableReadPrefetchGsimMain', [1, 1, overlap],
                    flags + ['-DMEMORY_SCHEDULE_OVERLAP=' + str(overlap)],
                    common.HERE / 'harness/memory_schedule_overlap.cpp')
                step(label + '-positive', [binary], anchor='MEMORY_SCHEDULE_OVERLAP_PASS')
                for mutation, anchor in (('token-address', 'resident token full PA/index'),
                        ('token-origin', 'useful event changed immutable refill origin'),
                        ('dirty-byte', 'dirty release byte oracle mismatch')):
                    step(label + '-negative-' + mutation, [binary, '--inject-' + mutation], expected=1, anchor=anchor)
                save()
        if args.components_only:
            r['status'] = 'PASS_SHORT_COMPONENTS_ONLY'
            save()
            return
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
            wide, coexist, overlap = MODES[label]
            options = spec['native_options'] + (['--internal-line-grant'] if wide else []) + (['--concurrent-read-store-prefetch'] if coexist else []) + (['--memory-schedule-overlap'] if overlap else [])
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
            assert profile == expected, 'complete profile changed outside three opt-in booleans'
            expected_actual = copy.deepcopy(spec['actual_fabric'])
            expected_actual['cache'].update(internalLineGrant=wide, concurrentReadStorePrefetch=coexist, memoryScheduleOverlap=overlap)
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
                row['vs_published_percent'] = 100 * (r['published_original_law_totals'][name] / row['inclusive_cycles'] - 1)
                row['vs_previous_percent'] = 100 * (r['previous_combined_totals'][name] / row['inclusive_cycles'] - 1)
                if label == 'previous':
                    assert row['inclusive_cycles'] == r['previous_combined_totals'][name], 'fresh OFF did not reproduce published total'
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
        r['status'] = 'PASS_MATCHED_OWNERSHIP_OVERLAP'
        save()
    except BaseException as error:
        r['status'] = 'FAIL'
        r['error'] = repr(error)
        save()
        raise


if __name__ == '__main__':
    main()
