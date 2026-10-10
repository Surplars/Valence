#!/usr/bin/env python3
"""Bind new host tests to explicitly frozen, generated actual-cache models."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import resource
import shutil
import signal
import subprocess
import tarfile
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
MIB = 1024 ** 2
SANITIZER = r'AddressSanitizer|UndefinedBehaviorSanitizer|runtime error:|LeakSanitizer'
STATUS = 'PASS_CONFIG_AND_GENERATED_MODELS_NO_OBJECT_NO_DUT'
TOP = 'CoherentCacheHomeGsim'


def require(ok, why):
    if not ok:
        raise RuntimeError(why)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_inputs():
    names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    return {name: sha(ROOT / name) for name in names if name and (ROOT / name).is_file()}


def rtl_input(name):
    return (name.endswith(('.scala', '.sc')) or name in ('build.mill', '.mill-version') or
            name.startswith(('src/main/resources/', 'src/test/resources/')))


def rows(text, prefix):
    result = []
    for line in text.splitlines():
        if line.startswith(prefix + ' '):
            result.append(dict(token.split('=', 1) for token in line.split()[1:]))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--generated', type=Path, required=True,
                        help='Generated-only directory containing fixed plan.json and receipt.json')
    parser.add_argument('--tool-files', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--reuse-objects-from', type=Path,
                        help='Prior runtime receipt; only exact generated source/tool/flag objects may be reused')
    parser.add_argument('--slot-granted', action='store_true')
    args = parser.parse_args()
    require(args.slot_granted, 'coordinator must grant one serial heavy slot')
    require(not subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT), 'commit/freeze host source first')
    output = args.output.resolve()
    require(not output.exists(), 'fresh output directory required')
    require(shutil.disk_usage(ROOT).free >= 1100 * MIB, '400 MiB attempt plus 700 MiB disk floor required')
    generated = args.generated.resolve()
    prior = json.loads((generated / 'receipt.json').read_text())
    plan = json.loads((generated / 'plan.json').read_text())
    require(prior['status'] == STATUS, 'models must have completed source-bound generation/config only')
    bound = source_inputs()
    actual_rtl = {name: digest for name, digest in bound.items() if rtl_input(name)}
    expected_rtl = {name: digest for name, digest in plan['sources'].items() if rtl_input(name)}
    require(actual_rtl == expected_rtl, 'current Scala/resources/build inputs differ from generated model freeze')
    tools_path = args.tool_files.resolve()
    tools = json.loads(tools_path.read_text())
    require(sha(tools_path) == plan['tool_receipt_sha256'], 'generated model tool receipt differs')
    for entry in tools['files'].values():
        require(sha(entry['path']) == entry['sha256'], 'bound tool drift')
    for path, digest in plan['tools'].items():
        require(sha(path) == digest, 'generated model tool hash changed')
    cxx = tools['files']['clang']['path']
    previous = json.loads(args.reuse_objects_from.read_text()) if args.reuse_objects_from else None
    output.mkdir(parents=True)
    receipt = {
        'schema': 'store-prefetch-lru-victim-runtime-v1', 'status': 'RUNNING',
        'source_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'sources': bound, 'generated_directory': str(generated),
        'generated_plan_sha256': sha(generated / 'plan.json'),
        'generated_receipt_sha256': sha(generated / 'receipt.json'),
        'tools': tools, 'steps': [], 'models': {}, 'historical_pass_inherited': False,
        'executing_cpu': False, 'performance_qualification': False,
    }

    def save():
        (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')

    def guard():
        require(source_inputs() == bound, 'runtime source drift')
        require(sha(generated / 'plan.json') == receipt['generated_plan_sha256'] and
                sha(generated / 'receipt.json') == receipt['generated_receipt_sha256'], 'generation receipt drift')
        require(sha(tools_path) == plan['tool_receipt_sha256'], 'tool receipt drift')
        for path, digest in plan['tools'].items():
            require(sha(path) == digest, 'tool drift: ' + path)
        for model in prior['models'].values():
            for name, digest in model['artifacts'].items():
                require(sha(Path(model['directory']) / name) == digest, 'generated artifact drift: ' + name)

    def step(name, command, anchor=None, code=0, timeout=600):
        guard()
        require(source_inputs() == bound, 'source changed before ' + name)
        log = output / (name + '.log')
        began = time.monotonic()
        usage_before = resource.getrusage(resource.RUSAGE_CHILDREN)
        stop_reason = None
        with log.open('x') as stream:
            child = subprocess.Popen(list(map(str, command)), cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                                     start_new_session=True, env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0',
                                                                  'PYTHONDONTWRITEBYTECODE': '1'})
            while child.poll() is None:
                if shutil.disk_usage(ROOT).free < 700 * MIB:
                    stop_reason = 'disk-floor'
                if sum(p.stat().st_size for p in output.rglob('*') if p.is_file()) > 400 * MIB:
                    stop_reason = 'output-budget'
                if time.monotonic() - began > timeout:
                    stop_reason = 'bounded-timeout'
                if stop_reason:
                    os.killpg(child.pid, signal.SIGTERM)
                    try:
                        child.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        os.killpg(child.pid, signal.SIGKILL)
                        child.wait()
                    break
                time.sleep(0.5)
        usage_after = resource.getrusage(resource.RUSAGE_CHILDREN)
        text = log.read_text()
        receipt['steps'].append({'name': name, 'command': list(map(str, command)), 'exit': child.returncode,
                                 'expected_exit': code, 'guard': stop_reason, 'seconds': time.monotonic() - began,
                                 'cumulative_waited_child_maxrss_KiB_before': usage_before.ru_maxrss,
                                 'cumulative_waited_child_maxrss_KiB_after': usage_after.ru_maxrss,
                                 'cumulative_waited_child_user_seconds_before': usage_before.ru_utime,
                                 'cumulative_waited_child_user_seconds_after': usage_after.ru_utime,
                                 'cumulative_waited_child_system_seconds_before': usage_before.ru_stime,
                                 'cumulative_waited_child_system_seconds_after': usage_after.ru_stime,
                                 'step_child_user_seconds': usage_after.ru_utime - usage_before.ru_utime,
                                 'step_child_system_seconds': usage_after.ru_stime - usage_before.ru_stime,
                                 'log_sha256': sha(log)})
        save()
        require(not stop_reason and child.returncode == code and (not anchor or anchor in text), 'step failed: ' + name)
        require(not re.search(SANITIZER, text), 'sanitizer failure: ' + name)
        require(source_inputs() == bound, 'source changed during ' + name)
        guard()
        return text

    try:
        save()
        closure = {name: digest for name, digest in bound.items() if rtl_input(name) or
                   name.startswith(('simulator/gsim/store_prefetch_lru_victim/', 'simulator/gsim/harness/')) or
                   name == 'simulator/gsim/mshr_occupancy.py'}
        with tarfile.open(output / 'source-closure.tar.gz', 'w:gz') as archive:
            for name in sorted(closure):
                archive.add(ROOT / name, arcname=name, recursive=False)
        receipt['raw_source_closure'] = {'files': closure, 'sha256': sha(output / 'source-closure.tar.gz')}
        host = output / 'policy-host'
        step('policy-host-compile', [cxx, '-std=c++20', '-O1', '-Wall', '-Wextra', '-Werror',
                                    '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                                    HERE / 'test_policy.cpp', '-o', host])
        step('policy-host-positive', [host], 'STORE_PREFETCH_LRU_HOST_PASS checks=74')
        for mode, on in [('off', 0), ('on', 1)]:
            model = prior['models'][mode]
            require(model['mode'] == mode and model['top'] == TOP, 'generated mode/top mismatch')
            directory = Path(model['directory'])
            for name, digest in model['artifacts'].items():
                require(sha(directory / name) == digest, 'generated artifact changed: ' + name)
            actual = json.loads((directory / 'actual-parameters.json').read_text())
            expected_cache = dict(readMshrs=2, responseEntries=2, writebackEntries=2, overlapWritebackRefill=True,
                                  nextLinePrefetch=True, prefetchCandidateCycles=1, prefetchBreakOnStore=False,
                                  storeNextLinePrefetch=True, storePrefetchMruInsertion=True,
                                  postedPrefetchCoexistence=False, storePrefetchLruVictim=bool(on))
            require(actual['mode'] == mode and actual['constructions'] == 1 and
                    actual['cacheConcurrency'] == expected_cache, 'actual constructed cache profile mismatch')
            geometry = dict(base=0x1000080010000, bytes=131072, tagLow=14, addressWidth=64, compact=True)
            require(actual['cacheGeometry'] == geometry and actual['homeGeometry'] == geometry and
                    actual['cacheLines'] == actual['homeTrackedLines'] == 512 and
                    actual['cacheWays'] == actual['homeTrackedWays'] == 2 and
                    actual['homeAcquireEntries'] == actual['homeWritebackEntries'] == 2,
                    'actual constructed high-PA cache/home geometry mismatch')
            target = output / mode
            target.mkdir()
            definitions = ['CHECKED_STORE_PREFETCH=1', 'STORE_PF_MRU_ON=1', 'STORE_PF_LRU_ON=' + str(on),
                           'CACHE_BASE=0x1000080010000ULL', 'READ_MSHRS=2', 'CACHE_LINES=512',
                           'RESPONSE_ENTRIES=2', 'AXI_SLOTS=4', 'MIXED_MODEL=1', 'MIXED_RTL=1']
            flags = ['-std=c++20', '-O1', '-g', '-gz=zlib', '-fsanitize=address,undefined',
                     '-fno-sanitize-recover=all', '-I' + str(directory), '-I' + str(ROOT / 'simulator/gsim/harness'),
                     '-I' + str(HERE), *['-D' + definition for definition in definitions]]
            object_flags = [flag for flag in flags if flag not in ('-I' + str(ROOT / 'simulator/gsim/harness'), '-I' + str(HERE))]
            identity = {'generated_artifacts': model['artifacts'], 'clang_sha256': sha(cxx), 'flags': object_flags}
            saved = receipt['models'][mode] = {'identity': identity, 'actual_parameters': actual, 'objects': []}
            # Parse against the real generated ABI before spending a large Clang slot.
            step(mode + '-actual-header-syntax', [cxx, *flags, '-fsyntax-only', HERE / 'cache.cpp'])
            spec = importlib.util.spec_from_file_location('occupancy', ROOT / 'simulator/gsim/mshr_occupancy.py')
            occupancy = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(occupancy)
            bad = occupancy.validate(ROOT, directory / (TOP + '.h'), 2, 'cache$')
            caught = False
            try:
                occupancy.validate(ROOT, bad, 2, 'cache$')
            except AssertionError:
                caught = True
            require(caught, 'corrupt generated occupancy schema escaped')
            objects = []
            old_model = previous.get('models', {}).get(mode) if previous else None
            if old_model:
                require(old_model['identity'] == identity, 'reused object tool/flags/generated source mismatch')
                for obj in old_model['objects']:
                    path = Path(obj['path'])
                    require(sha(path) == obj['sha256'], 'reused object changed')
                    objects.append(path)
                    saved['objects'].append(obj)
            else:
                for source in sorted(directory.glob(TOP + '[0-9]*.cpp')):
                    obj = target / (source.stem + '.o')
                    step(mode + '-compile-' + source.stem, [cxx, *object_flags, '-c', source, '-o', obj])
                    objects.append(obj)
                    saved['objects'].append({'path': str(obj), 'sha256': sha(obj), 'source_sha256': sha(source)})
                    save()
            require(objects and len(objects) == len(list(directory.glob(TOP + '[0-9]*.cpp'))), 'generated objects incomplete')
            binary = target / 'run'
            step(mode + '-link', [cxx, *flags, HERE / 'cache.cpp', *objects, '-ldl', '-o', binary])
            saved['binary_sha256'] = sha(binary)
            text = step(mode + '-positive', [binary, '--images=' + str(target / 'images')],
                        'STORE_PREFETCH_LRU_VICTIM_PASS store_pf=1 store_pf_mru=1 store_pf_lru=' + str(on) + ' cases=20')
            cases = rows(text, 'STORE_PREFETCH_LRU_VICTIM_CASE')
            conflicts = rows(text, 'STORE_PREFETCH_LRU_VICTIM_CONFLICT')
            cancels = rows(text, 'STORE_PREFETCH_LRU_VICTIM_CANCEL')
            require(len(cases) == len({c['name'] for c in cases}) == 20 and len(conflicts) == 12 and len(cancels) == 4,
                    'positive coverage missing or duplicated')
            by_name = {row['name']: row for row in conflicts}
            for name in ('dirty_lru_clean_mru', 'mirror_dirty_lru_clean_mru', 'dirty_victim_pf_error'):
                row = by_name[name]
                require(int(row['later_hits']) == 6 + on and int(row['later_misses']) == 1 - on and
                        int(row['c_beats']) == (8 if on else 1) and int(row['victim_pa']) > 2**32,
                        'main/mirror/error OFF/ON retention or release predicate failed')
            require(by_name['read_origin_clean_first']['later_misses'] == '1' and
                    by_name['read_origin_both_dirty_blocked']['admitted'] == '0', 'read-origin control changed')
            snapshots = rows(text, 'STORE_PREFETCH_LRU_VICTIM_SNAPSHOT')
            require(snapshots and any(row['allocated'] == '1' for row in snapshots), 'actual LRU snapshots absent')
            images = {}
            for case in cases:
                name = case['name']
                expected_image = target / 'images' / (name + '-expected.bin')
                actual_image = target / 'images' / (name + '-actual.bin')
                require(expected_image.stat().st_size == actual_image.stat().st_size == 131072 and
                        expected_image.read_bytes() == actual_image.read_bytes(), 'full byte image differs: ' + name)
                images[name] = {'expected_sha256': sha(expected_image), 'actual_sha256': sha(actual_image)}
            saved.update(cases=cases, conflicts=conflicts, cancels=cancels, images=images)
            negatives = [
                ('--inject-mismatch', 'CPU independent byte oracle mismatch', None),
                ('--inject-wb-prefetch-aba', 'WB capture stale-PF ABA origin mismatch', 'wb-prefetch-aba'),
                ('--inject-policy-lru-bit', 'candidate LRU bit differs from independent access order', 'lru-bit'),
                ('--inject-policy-origin', 'pending candidate origin differs from original authored request', 'origin'),
                ('--inject-policy-full-pa', 'candidate full-PA ways differ from independent residency', 'full-pa'),
            ]
            for option, diagnostic, trigger in negatives:
                negative = step(mode + '-' + option[2:], [binary, option], diagnostic, code=1)
                require('STORE_PREFETCH_LRU_VICTIM_PASS ' not in negative, 'negative emitted success marker')
                if trigger:
                    require('STORE_PREFETCH_LRU_VICTIM_MUTATION_TRIGGER ' + trigger in negative, 'negative never triggered')
            save()
        require(receipt['models']['off']['images'] == receipt['models']['on']['images'],
                'OFF/ON authored or actual final images differ')
        require(source_inputs() == bound, 'final source drift')
        receipt['status'] = 'PASS_STORE_PREFETCH_LRU_VICTIM_ACTUAL_CACHE_HOME'
    except BaseException as error:
        receipt['status'] = 'FAIL'
        receipt['error'] = str(error)
        raise
    finally:
        save()
    print(receipt['status'], output / 'receipt.json')


if __name__ == '__main__':
    main()
