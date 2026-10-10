#!/usr/bin/env python3
"""Frozen, serial OFF/ON GSIM component gate using existing hash-pinned tools only.

This gate checks the local two-credit response boundary, not CPU execution,
permission production, whole-system speedup, or FPGA frequency. No tool setup,
fetch, installation, broad regression, or legacy hardware simulator is invoked.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
TOP = 'TranslatedResponseFlowGsim'
NEGATIVES = {
    'data': 'response_data_mismatch',
    'error': 'response_error_mismatch',
    'pagefault': 'response_pagefault_mismatch',
    'order': 'response_order_mismatch',
    'credit': 'response_credit_mismatch',
    'drop': 'response_valid_missing',
    'duplicate': 'response_unowned_duplicate',
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def inventory():
    return {name: sha(ROOT / name) for name in git('ls-files').splitlines() if (ROOT / name).is_file()}


def module(text, name):
    found = re.search(r'^  (?:public )?module ' + re.escape(name) + r' :.*?(?=^  (?:public )?(?:module|extmodule) |\Z)', text, re.M | re.S)
    if not found:
        raise RuntimeError('module missing: ' + name)
    return found.group()


def normalized(text):
    # The saved board's observational taps cannot affect queue behavior. Remove
    # their port/connect declarations only; retain every functional statement.
    lines = [line for line in text.splitlines() if '_bore' not in line]
    result = re.sub(r' @\[[^\]]*\]', '', '\n'.join(lines))
    result = re.sub(r'TwoEntryRegisterQueue(?:_\d+)?', 'TwoEntryRegisterQueue', result)
    return '\n'.join(line.rstrip() for line in result.splitlines() if line.strip())


def parse_cases(log):
    cases = {}
    for line in log.splitlines():
        if line.startswith('TRANSLATED_RESPONSE_CASE '):
            fields = dict(item.split('=', 1) for item in line.split()[1:])
            name = fields.pop('name')
            if name in cases:
                raise RuntimeError('duplicate component case: ' + name)
            cases[name] = {key: int(value) for key, value in fields.items()}
    if not cases:
        raise RuntimeError('component case observations missing')
    return cases


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, required=True, help='fresh evidence directory')
    ap.add_argument('--tool-receipt', type=Path, required=True, help='existing receipt containing tools with path/sha256')
    ap.add_argument('--baseline-fir', type=Path, required=True, help='immutable final9483 model-C FIR for default-off equality')
    ap.add_argument('--freeze-only', action='store_true', help='freeze inputs and precise serial commands; no compilation or runtime')
    ap.add_argument('--run-frozen', action='store_true', help='run an existing unchanged freeze')
    args = ap.parse_args()
    if args.freeze_only and args.run_frozen:
        ap.error('choose freeze-only or run-frozen')
    if git('status', '--porcelain'):
        ap.error('commit the complete source checkpoint before freezing')
    out = args.output.resolve()
    tool_receipt = args.tool_receipt.resolve()
    baseline = args.baseline_fir.resolve()
    tools = json.loads(tool_receipt.read_text())['tools']
    for item in tools.values():
        if sha(item['path']) != item['sha256']:
            raise RuntimeError('tool hash drift: ' + item['path'])
    frozen = {
        'schema': 'valence-local-translated-response-flow-component-v1',
        'commit': git('rev-parse', 'HEAD'), 'tree': git('rev-parse', 'HEAD^{tree}'),
        'base': '9483b274e6d9a32df60255c1dc1d1a884b8260c4',
        'sources': inventory(), 'tools': tools,
        'tool_receipt': str(tool_receipt), 'tool_receipt_sha256': sha(tool_receipt),
        'baseline_fir': str(baseline), 'baseline_fir_sha256': sha(baseline),
        'java_tool_options': os.environ.get('JAVA_TOOL_OPTIONS'),
        'limits': {'parallel_jobs': 1, 'gsim_threads': 1, 'max_runtime_seconds_each': 30,
                   'max_command_seconds': 600},
        'scope': 'ordinary synthetic all-payload two-credit response component only; no CPU, Sv39 late-cancel/ROB-reuse, native timing, or speedup claim',
    }
    flags = ['-std=c++20', '-O1', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=all']
    frozen['commands'] = [
        [tools['mill_wrapper']['path'], '-i', '-j', '1', 'IonSoC.test.testOnly',
         'ooo.FpgaNextConfigSpec', 'ooo.TranslatedResponseFlowSpec'],
        [sys.executable, '-B', str(ROOT / 'simulator/gsim/test_translated_response_flow_cli.py')],
    ]
    for mode in (0, 1):
        target = out / str(mode)
        frozen['commands'] += [
            [tools['mill_wrapper']['path'], '-i', '-j', '1', 'IonSoC.test.runMain',
             'ooo.TranslatedResponseFlowGsimMain', str(target), str(mode)],
            [tools['gsim']['path'], '--threads=1', '--dir=' + str(target), str(target / (TOP + '.fir'))],
            [tools['clang']['path'], *flags, '-I' + str(target), '-c', '<each generated TU serially>', '-o', '<matching object>'],
            [tools['clang']['path'], *flags, '-I' + str(target), '-DRESPONSE_FLOW_ENABLED=' + str(mode),
             str(ROOT / 'simulator/gsim/harness/translated_response_flow.cpp'), '<generated objects>', '-ldl', '-o', str(target / 'run')],
            [str(target / 'run')],
            *[[str(target / 'run'), '--inject-' + name] for name in NEGATIVES],
        ]
    if args.run_frozen:
        if json.loads((out / 'freeze.json').read_text()) != frozen:
            raise RuntimeError('frozen inputs/commands/environment changed; preserve evidence and use new output')
    else:
        out.mkdir(parents=True, exist_ok=False)
        (out / 'freeze.json').write_text(json.dumps(frozen, indent=2) + '\n')
    if args.freeze_only:
        print(json.dumps({'status': 'FROZEN_NO_BUILD', 'commit': frozen['commit'],
                          'freeze_sha256': sha(out / 'freeze.json'), 'output': str(out)}))
        return
    state = {'status': 'RUNNING', 'freeze_sha256': sha(out / 'freeze.json'), 'steps': [], 'models': {},
             'started': datetime.datetime.now(datetime.timezone.utc).isoformat()}

    def save():
        (out / 'receipt.json').write_text(json.dumps(state, indent=2) + '\n')

    def guard():
        if inventory() != frozen['sources'] or git('rev-parse', 'HEAD') != frozen['commit']:
            raise RuntimeError('source checkpoint changed')
        for item in tools.values():
            if sha(item['path']) != item['sha256']:
                raise RuntimeError('tool drift')
        if sha(baseline) != frozen['baseline_fir_sha256']:
            raise RuntimeError('baseline FIR drift')
        if shutil.disk_usage(out).free < 700 * 1024 * 1024:
            raise RuntimeError('less than 700 MiB free')

    def step(name, command, timeout=600, expected=0, reason=None):
        guard()
        log = out / (name + '.log')
        if log.exists():
            raise RuntimeError('refusing to overwrite existing step: ' + name)
        record = {'name': name, 'command': list(map(str, command)), 'timeout': timeout, 'status': 'RUNNING'}
        state['steps'].append(record)
        save()
        print(name, flush=True)
        started = time.monotonic()
        with log.open('w') as stream:
            result = subprocess.run(list(map(str, command)), cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                                    timeout=timeout, env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'})
        record.update(exit_code=result.returncode, seconds=time.monotonic() - started,
                      max_child_rss_kib=resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss, log_sha256=sha(log))
        text = log.read_text()
        ok = result.returncode == expected and (reason is None or reason in text)
        record['status'] = 'PASS' if ok else 'FAIL'
        save()
        if not ok:
            raise RuntimeError(name + ' failed: ' + text[-6000:])
        return text

    try:
        step('configuration-cli', frozen['commands'][1], timeout=30)
        step('configuration', frozen['commands'][0])
        baseline_text = baseline.read_text()
        baseline_buffer = module(baseline_text, 'DataResponseBuffer')
        original_queue_name = re.search(r'inst responses_responses of (\w+)', baseline_buffer).group(1)
        for mode in (0, 1):
            target = out / str(mode)
            target.mkdir()
            step(str(mode) + '-elaborate', [tools['mill_wrapper']['path'], '-i', '-j', '1', 'IonSoC.test.runMain',
                 'ooo.TranslatedResponseFlowGsimMain', target, str(mode)])
            fir = target / (TOP + '.fir')
            if mode == 0:
                emitted = fir.read_text()
                off_buffer = module(emitted, 'DataResponseBuffer')
                off_queue_name = re.search(r'inst responses_responses of (\w+)', off_buffer).group(1)
                if normalized(off_buffer) != normalized(baseline_buffer):
                    raise RuntimeError('default-off buffer functional FIR differs from frozen9483')
                if normalized(module(emitted, off_queue_name)) != normalized(module(baseline_text, original_queue_name)):
                    raise RuntimeError('default-off response queue functional FIR differs from frozen9483')
                state['default_off_buffer_queue_fir_equality'] = 'PASS excluding only locations, module disambiguation suffixes and passive taps'
                save()
            step(str(mode) + '-generate', [tools['gsim']['path'], '--threads=1', '--dir=' + str(target), fir])
            units = sorted(target.glob(TOP + '[0-9]*.cpp'))
            if not units:
                raise RuntimeError('GSIM produced no translation units')
            objects = []
            for unit in units:
                obj = unit.with_suffix('.o')
                step(str(mode) + '-compile-' + unit.stem, [tools['clang']['path'], *flags,
                     '-I' + str(target), '-c', unit, '-o', obj])
                objects.append(obj)
            binary = target / 'run'
            step(str(mode) + '-link', [tools['clang']['path'], *flags, '-I' + str(target),
                 '-DRESPONSE_FLOW_ENABLED=' + str(mode), ROOT / 'simulator/gsim/harness/translated_response_flow.cpp',
                 *objects, '-ldl', '-o', binary])
            log = step(str(mode) + '-positive', [binary], timeout=30, reason='TRANSLATED_RESPONSE_FLOW_PASS')
            cases = parse_cases(log)
            negatives = {}
            for name, reason in NEGATIVES.items():
                step(str(mode) + '-negative-' + name, [binary, '--inject-' + name], timeout=30,
                     expected=1, reason='TRANSLATED_RESPONSE_FLOW_FAIL reason=' + reason)
                negatives[name] = reason
            files = [fir, target / (TOP + '.h'), *units, *objects, binary]
            state['models'][str(mode)] = {'cases': cases, 'negative_controls': negatives,
                'artifacts': {str(p.relative_to(out)): sha(p) for p in files}}
            save()
        off, on = state['models']['0']['cases'], state['models']['1']['cases']
        if off.keys() != on.keys():
            raise RuntimeError('paired case sets differ')
        for name in off:
            for key in ('issued', 'accepted', 'returned', 'semantic_digest', 'request_digest'):
                if off[name][key] != on[name][key]:
                    raise RuntimeError('paired semantic mismatch: ' + name + '/' + key)
        guard()
        state.update(status='PASS_COMPONENT_ONLY', paired_semantics='PASS',
                     finished=datetime.datetime.now(datetime.timezone.utc).isoformat())
    except BaseException as error:
        state.update(status='FAIL', error=repr(error))
        raise
    finally:
        save()
    print(json.dumps({'status': state['status'], 'receipt_sha256': sha(out / 'receipt.json')}))


if __name__ == '__main__':
    main()
