#!/usr/bin/env python3
"""Frozen canonical-store source gate, using the existing pinned tools and one explicitly granted serial slot."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import time

ROOT = Path(__file__).resolve().parents[3]
HARNESS = ROOT / 'simulator/gsim/harness'
MIB = 1024 ** 2


def require(ok, why):
    if not ok:
        raise RuntimeError(why)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inputs():
    names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    return {name: sha(ROOT / name) for name in names if name and (ROOT / name).is_file()}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--slot-granted', action='store_true')
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--tool-receipt', type=Path, required=True)
    ap.add_argument('--models', nargs='*', default=['tracker', 'adapter', 'lsu2', 'lsu4'],
                    choices=['tracker', 'adapter', 'lsu2', 'lsu4', 'backendoff', 'backendon'])
    ap.add_argument('--skip-config', action='store_true')
    args = ap.parse_args()
    require(args.slot_granted, 'explicit parent-granted heavy slot required')
    require(not subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT), 'source must be clean and frozen')
    tools_receipt = json.loads(args.tool_receipt.read_text())
    tools = tools_receipt['files']
    for item in tools.values():
        require(sha(item['path']) == item['sha256'], 'pinned installed tool drift')
    mill, gsim, cxx = [tools[key]['path'] for key in ['mill_wrapper', 'gsim', 'clang']]
    require(shutil.which('mill') == mill and os.environ.get('COURSIER_CACHE') and
            os.environ.get('JAVA_TOOL_OPTIONS') and os.environ.get('CHISEL_FIRTOOL_PATH'),
            'source the recovered activate.sh in this same shell')
    out = args.output.resolve()
    require(not out.exists(), 'fresh attempt output required')
    require(shutil.disk_usage(ROOT).free > 2048 * MIB, '2GiB free floor required')
    out.mkdir(parents=True)
    frozen = inputs()
    receipt = {'schema': 'canonical-virtual-store-components-v1', 'status': 'RUNNING',
               'scope': 'configuration and selected focused GSIM fixtures; no cache/board/performance/timing claim',
               'head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
               'tree': subprocess.check_output(['git', 'rev-parse', 'HEAD^{tree}'], cwd=ROOT, text=True).strip(),
               'inputs': frozen, 'tool_receipt': tools_receipt, 'tool_receipt_sha256': sha(args.tool_receipt),
               'models': {}, 'steps': [], 'historical_runtime_pass_inherited': False}

    def save():
        (out / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')

    def step(name, command, timeout=900, anchor=None, negative=False):
        require(inputs() == frozen, 'source drift before ' + name)
        log = out / (name + '.log')
        begin = time.monotonic()
        guard = None
        with log.open('x') as stream:
            child = subprocess.Popen(list(map(str, command)), cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                                     start_new_session=True, env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0',
                                                                  'PYTHONDONTWRITEBYTECODE': '1'})
            while child.poll() is None:
                if time.monotonic() - begin > timeout: guard = 'timeout'
                if shutil.disk_usage(ROOT).free < 1536 * MIB: guard = 'disk-floor'
                if sum(p.stat().st_size for p in out.rglob('*') if p.is_file()) > 650 * MIB: guard = 'output-budget'
                if guard:
                    os.killpg(child.pid, signal.SIGTERM)
                    try: child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(child.pid, signal.SIGKILL); child.wait()
                    break
                time.sleep(0.25)
        content = log.read_text()
        receipt['steps'].append({'name': name, 'command': list(map(str, command)), 'exit': child.returncode,
                                 'negative_control': negative, 'guard': guard,
                                 'seconds': time.monotonic() - begin, 'log_sha256': sha(log)})
        save()
        require(guard is None and ((child.returncode != 0) if negative else (child.returncode == 0)) and
                (anchor is None or anchor in content), 'step failed: ' + name)
        require(not re.search(r'AddressSanitizer|UndefinedBehaviorSanitizer|runtime error:|LeakSanitizer', content),
                'sanitizer diagnostic: ' + name)
        require(inputs() == frozen, 'source changed during ' + name)

    try:
        save()
        if not args.skip_config:
            step('config', [mill, '-i', '-j', '1', 'IonSoC.test.testOnly', 'ooo.CanonicalVirtualStoreConfigSpec'],
                 anchor='All tests passed')
        for name in args.models:
            backend = name.startswith('backend')
            if name == 'tracker': top, driver, extra = 'CanonicalStoreTrackerGsim', 'canonical_store_tracker.cpp', []
            elif name == 'adapter': top, driver, extra = 'CanonicalStoreAdapterGsim', 'canonical_store_adapter.cpp', []
            elif name.startswith('lsu'): top, driver, extra = 'CanonicalStoreLsuGsim', 'canonical_store_lsu.cpp', [name[-1]]
            else: top, driver, extra = 'CanonicalVirtualStoreBackendGsim', 'canonical_virtual_store_backend.cpp', ['1' if name == 'backendon' else '0', '4']
            model = out / name; model.mkdir()
            step(name + '-emit', [mill, '-i', '-j', '1', 'IonSoC.test.runMain', 'ooo.' + top + 'Main', model, *extra])
            if backend:
                params = json.loads((model / 'parameters.json').read_text())
                require(params['core']['canonicalVirtualStoreOverlap'] == (name == 'backendon'),
                        'actual emitter option disagrees with host macro')
                require(params['core']['virtualRamLoadPrecheck'] and params['core']['memoryEntries'] == 4,
                        'focused backend lost precheck or requested owner capacity')
                if name == 'backendon' and (out / 'backendoff/parameters.json').exists():
                    control = json.loads((out / 'backendoff/parameters.json').read_text())
                    params['core']['canonicalVirtualStoreOverlap'] = False
                    require(params == control, 'backend OFF/ON differs outside the single option')
            step(name + '-generate', [gsim, '--threads=1', '--dir=' + str(model), model / (top + '.fir')])
            flags = ['-std=c++20', '-O1', '-g', '-gz=zlib', '-fsanitize=address,undefined',
                     '-fno-sanitize-recover=all', '-I' + str(model), '-I' + str(HARNESS)]
            if backend: flags += ['-DPRECHECK_ENABLED=1', '-DCANONICAL_STORE_OVERLAP=' + ('1' if name == 'backendon' else '0')]
            objects = []
            for source in sorted(model.glob(top + '[0-9]*.cpp')):
                obj = source.with_suffix('.o')
                step(name + '-compile-' + source.stem, [cxx, *flags, '-c', source, '-o', obj])
                objects.append(obj)
            require(objects, 'no generated model sources')
            executable = model / 'run'
            step(name + '-link', [cxx, *flags, HARNESS / driver, *objects, '-ldl', '-o', executable])
            marker = 'CANONICAL_BACKEND_PASS' if backend else 'CANONICAL_STORE_' + ('LSU' if name.startswith('lsu') else name.upper()) + '_PASS'
            step(name + '-cases', [executable], timeout=300, anchor=marker)
            injection = '--inject-result' if backend else {'tracker': '--inject-valid', 'adapter': '--inject-pa'}.get(name, '--inject-payload')
            fail_marker = 'CANONICAL_BACKEND_FAIL' if backend else marker.replace('_PASS', '_FAIL')
            step(name + '-negative', [executable, injection], timeout=60, anchor=fail_marker, negative=True)
            receipt['models'][name] = {'top': top, 'driver_sha256': sha(HARNESS / driver),
                                      'artifacts': {str(p.relative_to(out)): sha(p) for p in model.rglob('*') if p.is_file()}}
            save()
        require(inputs() == frozen, 'final source drift')
        receipt['status'] = 'PASS_SELECTED_CONFIG_AND_FOCUSED_COMPONENTS_ONLY'
    except BaseException as error:
        receipt['status'] = 'FAIL'; receipt['error'] = str(error)
        raise
    finally:
        save()
    print(receipt['status'], out / 'receipt.json')


if __name__ == '__main__':
    main()
