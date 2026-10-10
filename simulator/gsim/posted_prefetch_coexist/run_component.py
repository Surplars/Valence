#!/usr/bin/env python3
"""One frozen posted/PF policy OFF/ON actual-cache gate using installed pinned tools only.

Requires an explicitly granted heavy slot. No generic setup, tool rebuild,
full GSIM, executing CPU, real home qualification or synthesis is performed.
"""
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

from ports import emit_driver

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
TOOLS = ROOT.parent / 'toolchain-recovery/tool-files.json'
MIB = 1024 ** 2


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def inputs():
    names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    return {name: sha(ROOT / name) for name in names if name and (ROOT / name).is_file()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--slot-granted', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--tool-files', type=Path, default=TOOLS)
    args = parser.parse_args()
    require(args.slot_granted, 'parent-granted serial heavy slot required')
    require(not subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT), 'source must be frozen and clean')
    require(os.environ.get('COURSIER_CACHE') and os.environ.get('JAVA_TOOL_OPTIONS') and
            os.environ.get('CHISEL_FIRTOOL_PATH'), 'source the recovered activate.sh first')
    source = inputs()
    tool_receipt = json.loads(args.tool_files.read_text())
    tools = tool_receipt['files']
    for item in tools.values():
        require(sha(item['path']) == item['sha256'], 'installed pinned tool drift')
    mill, gsim, cxx = (tools[name]['path'] for name in ['mill_wrapper', 'gsim', 'clang'])
    require(shutil.which('mill') == mill, 'activated Mill path mismatch')
    out = args.output.resolve()
    require(not out.exists(), 'fresh attempt directory required; never overwrite a failed receipt')
    require(shutil.disk_usage(ROOT).free >= 900 * MIB, '200MiB output budget plus 700MiB free floor required')
    out.mkdir(parents=True)
    receipt = {'schema': 'posted-prefetch-coexist-component-gate-v1', 'status': 'RUNNING',
               'scope': 'real posted cache/engine/SRAM, coexistence policy OFF/ON; synthetic manager and authority premises; no CPU/home qualification',
               'source_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
               'source_tree': subprocess.check_output(['git', 'rev-parse', 'HEAD^{tree}'], cwd=ROOT, text=True).strip(),
               'inputs': source, 'tool_files': tool_receipt, 'tool_receipt_sha256': sha(args.tool_files),
               'historical_pass_inherited': False, 'steps': [], 'models': {}}

    def save():
        (out / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')

    def step(name, command, timeout=600, anchor=None):
        require(inputs() == source, 'source changed before ' + name)
        log = out / (name + '.log')
        started = time.monotonic()
        guard = None
        with log.open('x') as stream:
            child = subprocess.Popen(list(map(str, command)), cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                                     start_new_session=True, env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0',
                                                                  'PYTHONDONTWRITEBYTECODE': '1'})
            while child.poll() is None:
                if time.monotonic() - started > timeout: guard = 'bounded-timeout'
                if shutil.disk_usage(ROOT).free < 700 * MIB: guard = 'disk-floor'
                if sum(p.stat().st_size for p in out.rglob('*') if p.is_file()) > 200 * MIB: guard = 'output-budget'
                if guard:
                    os.killpg(child.pid, signal.SIGTERM)
                    try: child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(child.pid, signal.SIGKILL); child.wait()
                    break
                time.sleep(0.25)
        text = log.read_text()
        receipt['steps'].append({'name': name, 'command': list(map(str, command)), 'exit': child.returncode,
                                 'guard': guard, 'seconds': time.monotonic() - started, 'log_sha256': sha(log)})
        save()
        require(guard is None and child.returncode == 0 and (anchor is None or anchor in text), 'step failed: ' + name)
        require(not re.search(r'AddressSanitizer|UndefinedBehaviorSanitizer|runtime error:|LeakSanitizer', text),
                'sanitizer failure: ' + name)
        require(inputs() == source, 'source changed during ' + name)

    try:
        save()
        step('host-contract', [sys.executable, HERE.parent / 'posted_merge_rebuild/run_host_checks.py', '--output', out / 'host-results.json'], 120,
             '"passed": true')
        step('transport-preflight', [sys.executable, '-m', 'unittest', 'discover', '-s', HERE, '-p', 'test_*.py', '-v'], 120,
             'OK')
        step('production-selection-host', [sys.executable, '-m', 'unittest', 'discover',
             '-s', HERE.parent / 'posted_prefetch_selection', '-p', 'test_*.py', '-v'], 120, 'OK')
        step('scala-config-coexistence-elaboration', [mill, '-i', '-j', '1', 'IonSoC.test.testOnly',
                                                'ooo.PostedPrefetchCoexistConfigSpec'], 900, 'All tests passed')
        for policy, generation, wb in [(0, 64, 2), (1, 64, 2), (0, 2, 2), (1, 2, 2)]:
            name = f'policy{policy}-generation{generation}-wb{wb}'
            model = out / name
            model.mkdir()
            top = 'PostedPrefetchCoexistGsim'
            step(name + '-emit', [mill, '-i', '-j', '1', 'IonSoC.test.runMain',
                                  'ooo.PostedPrefetchCoexistGsimMain', model, policy, generation, wb], 300)
            step(name + '-generate', [gsim, '--threads=1', '--dir=' + str(model), model / (top + '.fir')], 300)
            driver = model / 'driver.cpp'
            emit_driver(driver)
            flags = ['-std=c++20', '-O1', '-g', '-gz=zlib', '-fsanitize=address,undefined',
                     '-fno-sanitize-recover=all', '-I' + str(model)]
            objects = []
            for generated in sorted(model.glob(top + '[0-9]*.cpp')):
                obj = generated.with_suffix('.o')
                step(name + '-compile-' + generated.stem, [cxx, *flags, '-c', generated, '-o', obj], 600)
                objects.append(obj)
            require(objects, 'no generated native model')
            executable = model / 'run'
            step(name + '-link', [cxx, *flags, driver, *objects, '-ldl', '-o', executable], 300)
            step(name + '-cases', [sys.executable, HERE / 'fixture.py', '--executable', executable,
                                  '--output', model / 'cases', '--policy', policy, '--generation-bits', generation, '--wb-entries', wb], 180,
                 'POSTED_PREFETCH_COEXIST_PASS policy=' + str(policy))
            receipt['models'][name] = {'posted_enabled': True, 'policy': policy, 'generation_bits': generation, 'wb_entries': wb,
                                      'artifacts': {str(p.relative_to(out)): sha(p) for p in model.rglob('*') if p.is_file()}}
            save()
        require(inputs() == source, 'final source drift')
        require(not subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT), 'source no longer clean')
        for item in tools.values(): require(sha(item['path']) == item['sha256'], 'final tool drift')
        receipt['status'] = 'PASS_POSTED_PREFETCH_CACHE_SYNTHETIC_MANAGER_ONLY'
    except BaseException as error:
        receipt['status'] = 'FAIL'
        receipt['error'] = str(error)
        raise
    finally:
        save()
    print(receipt['status'], out / 'receipt.json')


if __name__ == '__main__':
    main()
