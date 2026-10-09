#!/usr/bin/env python3
"""Source-bound, opt-in older-prefix RenameRob qualification; no simulator setup/install."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
import run as common

TOP = 'OlderPrefixRetirementGsim'
NEGATIVES = {
    'checked-load': 'strict older-prefix oracle mismatch',
    'younger-lane': 'strict older-prefix oracle mismatch',
    'stale-limit': 'strict older-prefix oracle mismatch',
    'lost-older': 'strict older-prefix oracle mismatch',
    'global-hold': 'strict older-prefix oracle mismatch',
    'branch-hold': 'strict older-prefix oracle mismatch',
    'retire-token': 'retirement identity/payload oracle mismatch',
    'retire-payload': 'retirement identity/payload oracle mismatch',
    'recovery-owner': 'recovery acceptance oracle mismatch',
    'exception': 'head exception oracle mismatch',
    'completion-owner': 'completion ownership oracle mismatch',
}
LIMITS = [
    'RenameRob component qualification, not executing-CPU replay/cancellation or ISA proof.',
    'Non-writing allocations isolate order/token/payload behavior; unchanged full-ledger tests own RAT/free-list proof.',
    'The harness tests legal trusted fast-head pulses only; caller-gated candidates remain unsent when blocked.',
    'All 64 generation bits are challenged; bounded tests do not traverse 2^64 allocations or tag exhaustion.',
    'No future response-latency assumptions or removal of registered load-load replay checks.',
    'No synthesis, routed timing, FPGA-board, Linux or performance qualification.',
]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inputs():
    paths = sorted((common.ROOT / 'src/main/scala').rglob('*.scala'))
    paths += sorted((common.ROOT / 'third_party/berkeley-hardfloat').rglob('*.scala'))
    paths += [common.ROOT / name for name in (
        'build.mill', '.mill-jvm-opts', '.mill-version',
        'src/test/scala/ooo/OlderPrefixRetirementGsim.scala',
        'simulator/gsim/older_prefix_retirement.py', 'simulator/gsim/run.py',
        'simulator/gsim/harness/older_prefix_oracle.h',
        'simulator/gsim/harness/older_prefix_retirement.cpp', 'simulator/gsim/config/toolchain.json')]
    return {str(path.relative_to(common.ROOT)): sha(path) for path in paths}


def check_params(params):
    required = {
        'robEntries': '16', 'physicalRegs': '48', 'tagBits': '64',
        'renameWidth': '2', 'commitWidth': '2', 'completionWidth': '2', 'recoveryWidth': '4',
        'memoryEntries': '4', 'loadOrderOlderRetire': 'true', 'registeredLoadReplay': 'true',
        'registeredMemoryAddress': 'true', 'registeredRobRetirement': 'true',
        'earlyRecoveryIssueBlock': 'true', 'bankedRobPayload': 'true',
        'physicalLoadIngressFlow': 'true', 'virtualRamLoadPrecheck': 'false',
        'precheckedDataRequestFlow': 'false', 'machineSystem': 'true',
        'fastHeadTrapRecovery': 'true', 'fastHeadSystemRecovery': 'true',
        'fastHeadLoadRetire': 'false', 'fastBufferedStoreRetire': 'false',
    }
    wrong = {key: {'expected': value, 'actual': params.get(key)} for key, value in required.items()
             if params.get(key) != value}
    if wrong:
        raise RuntimeError('unexpected fixture profile: ' + json.dumps(wrong, sort_keys=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--build-run', action='store_true', help='fresh one-model GSIM compile and focused tests')
    mode.add_argument('--host-only', action='store_true', help='pure C++ oracle self-check; no RTL evidence')
    parser.add_argument('--tag', default='older-prefix-retirement-r1')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.tag):
        parser.error('tag must contain only letters, numbers, underscore or hyphen')
    before = inputs()
    if not args.build_run and not args.host_only:
        print(json.dumps({'status': 'PREFLIGHT_ONLY', 'input_files': len(before), 'models': 1,
            'geometry': 'ROB16/PRF48/rename2/complete2/commit2/recovery4/tag64/LSU4',
            'profile': 'selected, physical-ingress ON, virtual/prechecked OFF; only loadOrderOlderRetire added',
            'source': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=common.ROOT, text=True).strip(),
            'negative_controls': list(NEGATIVES), 'limits': LIMITS}))
        return
    output = common.BUILD / args.tag
    output.mkdir(parents=True, exist_ok=False)
    receipt = {'schema': 'valence-older-prefix-retirement-v1', 'status': 'RUNNING',
        'started_utc': datetime.now(timezone.utc).isoformat(), 'inputs': before,
        'base_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=common.ROOT, text=True).strip(),
        'source_changes': subprocess.check_output(['git', 'status', '--short'], cwd=common.ROOT, text=True),
        'limits': LIMITS, 'mode': 'HOST_ORACLE_ONLY' if args.host_only else 'FRESH_GSIM_COMPONENT',
        'negative_controls': {}}
    try:
        harness = common.HERE / 'harness/older_prefix_retirement.cpp'
        if args.host_only:
            cxx = os.environ.get('CXX', 'c++')
            common.run([cxx, '-std=c++20', '-O0', '-Wall', '-Wextra', '-pedantic',
                '-DOLDER_PREFIX_ORACLE_ONLY', harness, '-o', output / 'host-oracle'],
                log=output / 'host-compile.log', timeout=120)
            common.run([output / 'host-oracle'], log=output / 'host-test.log', timeout=60)
            receipt['positive_log'] = (output / 'host-test.log').read_text()
            receipt['status'] = 'PASS_HOST_ORACLE_ONLY_NO_RTL_EXECUTED'
        else:
            gsim = common.SOURCE / 'build/gsim/gsim'
            revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=common.SOURCE, text=True).strip()
            if revision != common.LOCK['revision'] or not gsim.is_file():
                raise RuntimeError('prebuilt pinned GSIM unavailable; no setup or installation attempted')
            if subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no'],
                                       cwd=common.SOURCE, text=True):
                raise RuntimeError('GSIM source has tracked modifications')
            cxx, version = common.compiler()
            receipt['tools'] = {'gsim_revision': revision, 'gsim_sha256': sha(gsim),
                'compiler': version, 'compiler_sha256': sha(shutil.which(cxx) or cxx),
                'sanitizers': ['address', 'undefined'], 'leak_sanitizer': False,
                'build_parallelism': 'one model and one translation unit at a time'}
            common.run(['mill', '-i', 'IonSoC.test.runMain', 'ooo.OlderPrefixRetirementGsimMain', output],
                       log=output / 'elaborate.log', timeout=1800)
            params = json.loads((output / 'effective-params.json').read_text())
            check_params(params)
            baseline = json.loads((output / 'baseline-params.json').read_text())
            differences = {key for key in set(params) | set(baseline) if params.get(key) != baseline.get(key)}
            if differences != {'loadOrderOlderRetire'} or baseline.get('loadOrderOlderRetire') != 'false':
                raise RuntimeError('fixture changes more than the opt-in baseline parameter')
            receipt['effective_params'] = params
            receipt['baseline_params'] = baseline
            receipt['fixture_config'] = json.loads((output / 'fixture-config.json').read_text())
            common.run([gsim, '--threads=1', '--dir=' + str(output), output / (TOP + '.fir')],
                       log=output / 'generate.log', timeout=1200)
            flags = ['-std=c++20', '-O1', '-g', '-fsanitize=address,undefined',
                     '-fno-sanitize-recover=all', '-I' + str(output)]
            objects = []
            sources = sorted(output.glob(TOP + '[0-9]*.cpp'))
            if not sources:
                raise RuntimeError('GSIM emitted no model translation units')
            for source in sources + [harness]:
                obj = output / (source.stem + '.o')
                common.run([cxx, *flags, '-c', source, '-o', obj], log=obj.with_suffix('.compile.log'), timeout=1200)
                objects.append(obj)
            common.run([cxx, *flags, *objects, '-ldl', '-o', output / 'run'], log=output / 'link.log')
            env = {**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'}
            common.run([output / 'run'], env=env, log=output / 'positive.log', timeout=180)
            receipt['positive_log'] = (output / 'positive.log').read_text()
            for mutation, anchor in NEGATIVES.items():
                result = subprocess.run([output / 'run', '--mutate=' + mutation], capture_output=True,
                                        text=True, env=env, timeout=180)
                log = output / ('negative-' + mutation + '.log')
                log.write_text(result.stdout + result.stderr)
                if result.returncode != 1 or anchor not in log.read_text() or 'fired=1' not in log.read_text():
                    raise RuntimeError('observation mutation did not reject at expected check: ' + mutation)
                receipt['negative_controls'][mutation] = {'status': 'EXPECTED_REJECTION',
                    'exit_code': result.returncode, 'anchor': anchor, 'log': log.name, 'sha256': sha(log)}
            receipt['status'] = 'PASS_FOCUSED_GSIM_OLDER_PREFIX_COMPONENT'
    except Exception as error:
        receipt['status'] = 'FAIL'
        receipt['error'] = str(error)
        raise
    finally:
        receipt['finished_utc'] = datetime.now(timezone.utc).isoformat()
        after = inputs()
        changed = before != after
        if changed:
            receipt['status'] = 'FAIL_SOURCE_CHANGED'
            receipt['changed_inputs'] = [name for name in set(before) | set(after) if before.get(name) != after.get(name)]
        receipt['artifacts'] = {str(path.relative_to(output)): {'sha256': sha(path), 'bytes': path.stat().st_size}
            for path in sorted(output.rglob('*')) if path.is_file() and path.name != 'receipt.json'}
        (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
        if changed:
            raise RuntimeError('source changed during qualification; receipt is not a clean-source pass')
    print(json.dumps({'status': receipt['status'], 'receipt': str(output / 'receipt.json'),
                     'receipt_sha256': sha(output / 'receipt.json')}))


if __name__ == '__main__':
    main()
