#!/usr/bin/env python3
"""One serial, source-bound OFF/ON component gate; no CPU or native export."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
MIB = 1024**2
CAP = 250*MIB
FLOOR = 700*MIB
TOP = 'CoherentCacheHomeGsim'


def require(ok, why):
    if not ok:
        raise RuntimeError(why)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source():
    require(not subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT), 'freeze source before the gate')
    names = subprocess.check_output(['git', 'ls-files'], cwd=ROOT, text=True).splitlines()
    return {'head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            'tree': subprocess.check_output(['git', 'rev-parse', 'HEAD^{tree}'], cwd=ROOT, text=True).strip(),
            'files': {name: sha(ROOT/name) for name in names if (ROOT/name).is_file()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tool-receipt', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--slot-granted', action='store_true')
    parser.add_argument('--reuse-off-from', type=Path, help='prior failed run with frozen generated-only OFF manifest')
    args = parser.parse_args()
    require(args.slot_granted, 'parent must grant one serial small-model slot and disk budget')
    require(shutil.disk_usage(ROOT).free >= CAP+FLOOR, '250 MiB new output plus 700 MiB free required')
    out = args.output.resolve()
    require(not out.exists(), 'fresh output directory required')
    bound = source()
    tools = json.loads(args.tool_receipt.read_text())
    pins = tools['files']
    for entry in pins.values():
        require(sha(entry['path']) == entry['sha256'], 'tool pin drift: '+entry['path'])
    envroot = Path(pins['mill_wrapper']['path']).parents[1]
    java = list((envroot/'cache/coursier/arc').glob('**/bin/java'))
    require(len(java) == 1, 'one existing pinned JDK required; do not install a new tool')
    env = dict(os.environ)
    # Reuse the existing cache/JDK without changing HOME or installing software.
    env.update(JAVA_HOME=str(java[0].parents[1]),
               PATH=os.pathsep.join(map(str, [envroot/'bin', envroot/'sysroot/usr/bin', java[0].parent]))+os.pathsep+env['PATH'],
               JAVA_TOOL_OPTIONS=f'-Duser.home={envroot / "home"} -Xmx4g -XX:ActiveProcessorCount=2 -Djavax.net.ssl.trustStore=/etc/ssl/certs/java/cacerts',
               XDG_CACHE_HOME=str(envroot/'cache'), COURSIER_CACHE=str(envroot/'cache/coursier'),
               COURSIER_REPOSITORIES='https://repo.maven.apache.org/maven2',
               CHISEL_FIRTOOL_PATH=str(Path(pins['firtool']['path']).parent), FIRTOOL=pins['firtool']['path'],
               LD_LIBRARY_PATH=str(envroot/'sysroot/usr/lib/x86_64-linux-gnu'),
               CPATH=str(envroot/'sysroot/usr/include'), ASAN_OPTIONS='detect_leaks=0', PYTHONDONTWRITEBYTECODE='1')
    out.mkdir(parents=True)
    receipt = {'schema': 'distinct-way-release-focused-v1', 'status': 'RUNNING', 'source': bound,
               'tool_receipt_sha256': sha(args.tool_receipt), 'tools': tools, 'output_cap_bytes': CAP,
               'disk_floor_bytes': FLOOR, 'steps': [], 'models': {}, 'historical_pass_inherited': False,
               'posted_component_covered': False, 'executing_cpu': False, 'performance_qualification': False,
               'java': {'path': str(java[0]), 'sha256': sha(java[0])},
               'cached_jars': {str(p): sha(p) for p in sorted((envroot/'cache/coursier').rglob('*.jar'))}}
    def save():
        (out/'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
    def guard():
        require(sha(java[0]) == receipt['java']['sha256'], 'JDK binary drift')
        require(source() == bound, 'source drift during gate')
        for entry in pins.values():
            require(sha(entry['path']) == entry['sha256'], 'tool drift during gate')
    def size():
        return sum(p.stat().st_size for root in [ROOT/'out', out] if root.exists()
                   for p in root.rglob('*') if p.is_file())
    def step(name, command, expected=0, anchor=None, timeout=1200):
        guard(); log = out/(name+'.log'); began = time.monotonic(); stop = None
        with log.open('x') as stream:
            child = subprocess.Popen(list(map(str, command)), cwd=ROOT, env=env, stdout=stream,
                                     stderr=subprocess.STDOUT, start_new_session=True)
            while child.poll() is None:
                if shutil.disk_usage(ROOT).free < FLOOR: stop = 'disk-floor'
                elif size() > CAP: stop = 'combined-out-model-cap'
                elif time.monotonic()-began > timeout: stop = 'timeout'
                if stop:
                    os.killpg(child.pid, signal.SIGTERM)
                    try: child.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        os.killpg(child.pid, signal.SIGKILL); child.wait()
                    break
                time.sleep(.25)
        text = log.read_text()
        receipt['steps'].append({'name': name, 'argv': list(map(str, command)), 'exit': child.returncode,
                                 'expected': expected, 'stop': stop, 'seconds': time.monotonic()-began,
                                 'log_sha256': sha(log), 'combined_output_bytes': size()})
        save()
        require(not stop and child.returncode == expected and (anchor is None or anchor in text), 'failed: '+name)
        require(not re.search(r'ERROR: AddressSanitizer|runtime error:|Sanitizer:DEADLYSIGNAL|LeakSanitizer', text), 'sanitizer: '+name)
        guard()
    try:
        save()
        mill = pins['mill_wrapper']['path']; cxx = pins['clang']['path']
        step('cli', [sys.executable, '-B', HERE/'test_cli.py'], anchor='DISTINCT_WAY_RELEASE_CLI_PASS')
        step('config', [mill, '-i', '-j', '1', 'IonSoC.test.testOnly', 'ooo.DistinctWayReleaseConfigSpec',
                        'ooo.CanonicalVirtualStoreBoardConfigSpec', 'ooo.StorePrefetchLruVictimConfigSpec',
                        'ooo.PostedPreparationPriorityConfigSpec'])
        for mode in (0, 1):
            directory = out/('on' if mode else 'off'); directory.mkdir()
            reused = False
            if mode == 0 and args.reuse_off_from:
                previous = args.reuse_off_from.resolve()
                prior = json.loads((previous/'receipt.json').read_text())
                manifest = json.loads((previous/'off-artifacts.json').read_text())
                require(manifest['source_head'] == prior['source']['head'], 'reused OFF source mismatch')
                metadata_only = {'src/test/scala/ooo/'+name for name in [
                    'PostedPrefetchBoardProfiles.scala', 'CanonicalVirtualStoreActualParamsMain.scala',
                    'CanonicalVirtualStoreBoardConfigSpec.scala']}
                def rtl_input(name):
                    return name.endswith(('.scala', '.sc')) or name == 'build.mill' or '/resources/' in name
                current_rtl = {n: h for n, h in bound['files'].items() if rtl_input(n) and n not in metadata_only}
                prior_rtl = {n: h for n, h in prior['source']['files'].items() if rtl_input(n) and n not in metadata_only}
                require(current_rtl == prior_rtl, 'reuse changed a model-generating source outside reviewed metadata-only audits')
                require(prior['tool_receipt_sha256'] == receipt['tool_receipt_sha256'], 'reused OFF tool pins differ')
                for name, digest in manifest['files'].items():
                    require(sha(previous/'off'/name) == digest, 'original OFF generated byte drift')
                    shutil.copy2(previous/'off'/name, directory/name)
                    require(sha(directory/name) == digest, 'copied OFF generated byte drift')
                receipt['off_generation_reuse'] = {'source_head': prior['source']['head'],
                    'host_source_head': bound['head'], 'manifest_sha256': sha(previous/'off-artifacts.json'),
                    'files': manifest['files'], 'reviewed_metadata_only_changes': sorted(metadata_only),
                    'large_objects_reused': False}
                reused = True
            else:
                step(f'emit-{mode}', [mill, '-i', '-j', '1', 'IonSoC.test.runMain',
                                    'ooo.DistinctWayReleaseGsimMain', directory, mode])
            actual = json.loads((directory/'actual-parameters.json').read_text())
            require(actual['cacheConcurrency']['distinctWayRelease'] == bool(mode) and
                    actual['homeDistinctWayRelease'] == bool(mode) and actual['issuedBits'] == 2*mode and
                    actual['postedConfigPresent'] is False, 'actual component flags/state differ')
            if not reused:
                step(f'generate-{mode}', [pins['gsim']['path'], '--threads=1', '--dir='+str(directory), directory/(TOP+'.fir')])
            flags = ['-std=c++20', '-O1', '-g', '-gz=zlib', '-fsanitize=address,undefined',
                     '-fno-sanitize-recover=all', '-I'+str(directory), '-I'+str(ROOT/'simulator/gsim/harness'),
                     '-DDISTINCT_WAY_RELEASE_ON='+str(mode), '-DCACHE_BASE=0x1000080010000ULL',
                     '-DCACHE_LINES=512', '-DREAD_MSHRS=2', '-DRESPONSE_ENTRIES=2', '-DAXI_SLOTS=4']
            step(f'header-{mode}', [cxx, *flags, '-fsyntax-only', HERE/'cache.cpp'])
            objects = []
            for cpp in sorted(directory.glob(TOP+'[0-9]*.cpp')):
                obj = cpp.with_suffix('.o'); objects.append(obj)
                step(f'compile-{mode}-{cpp.stem}', [cxx, *flags, '-c', cpp, '-o', obj])
            require(objects, 'missing generated model')
            receipt['models'][str(mode)] = {'actual': actual, 'compiler_sha256': sha(cxx), 'flags': flags,
                'artifacts': {p.name: sha(p) for p in directory.iterdir() if p.is_file()}}
            save()
            exe = directory/'gate'
            step(f'link-{mode}', [cxx, *flags, HERE/'cache.cpp', *objects, '-ldl', '-o', exe])
            step(f'positive-{mode}', [exe], anchor=f'DISTINCT_WAY_RELEASE_PASS on={mode}', timeout=180)
            step(f'negative-{mode}', [exe, '--mutate-directory'], expected=1,
                 anchor='home directory full-line identity mismatch', timeout=180)
            receipt['models'][str(mode)] = {'actual': actual,
                'artifacts': {p.name: sha(p) for p in directory.iterdir() if p.is_file()}}
            save()
        receipt['status'] = 'PASS_FRESH_REAL_CACHE_MIXED_HOME_C_BEFORE_E'
    except BaseException as error:
        receipt['status'] = 'FAIL'; receipt['error'] = str(error); raise
    finally:
        save()
    print(receipt['status'])


if __name__ == '__main__':
    main()
