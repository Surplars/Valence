#!/usr/bin/env python3
"""Lightweight C++ observer tests only. Never runs Mill, GSIM, or RTL simulation."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

SOURCE = Path(__file__).resolve().parent
ROOT = SOURCE.parents[3]
HERE = ROOT / "build/mlp4-ledger-preparation"
HERE.mkdir(parents=True, exist_ok=True)
HARNESS = ROOT / 'simulator/gsim/harness'
CXX = os.environ.get('CXX', 'c++')
FLAGS = ['-std=c++20', '-O0', '-g', '-Wall', '-Wextra', '-Wno-misleading-indentation',
         '-D_GLIBCXX_ASSERTIONS', '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
         '-I' + str(HARNESS)]
ENV = {**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'}
HEADERS = ['backend_observer.h', 'backend_ownership_ledger.h', 'cpu_flow_bandwidth.h',
           'performance_observer.h', 'data_path_sample.h', 'data_path_ownership_ledger.h']
SOURCES = [HARNESS / p for p in HEADERS] + [
    HARNESS / 'backend_ownership_test.cpp', HARNESS / 'data_path_ownership_test.cpp',
    SOURCE / 'four_owner_test.cpp', SOURCE / 'probe_reader_test.cpp', SOURCE / 'mock_board.h', Path(__file__).resolve()]

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def hashes():
    return {str(p.relative_to(ROOT)): sha(p) for p in SOURCES}

def run(command, name, expected_failure=False, contains=None):
    result = subprocess.run([str(x) for x in command], cwd=ROOT, env=ENV,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    (HERE / (name + '.log')).write_text(result.stdout)
    if expected_failure:
        assert result.returncode != 0 and contains in result.stdout, (name, result.stdout)
    else:
        assert result.returncode == 0, (name, result.stdout)
    return {'command': [str(x) for x in command], 'exit_code': result.returncode,
            'log': name + '.log', 'log_sha256': sha(HERE / (name + '.log'))}

report = {'status': 'RUNNING', 'baseline': '66c06d7', 'scope': 'Source-only passive observer preparation; pure host fixtures, no RTL build/run',
          'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
          'compiler': subprocess.check_output([CXX, '--version'], text=True).splitlines()[0],
          'source_sha256_before': hashes(), 'checks': {},
          'capacities': {'two_owner_backend_fifo': 2, 'four_owner_backend_fifo': 4,
                         'two_owner_response_queue': 2, 'four_owner_response_queue': 4,
                         'adapter_ingress': 2, 'adapter_checked': 2, 'relocated_response': 2},
          'limitations': ['Not RTL, firmware, NEMU, performance, synthesis or timing evidence.',
                         'Four-owner strict slot lineage requires observation from reset/start.',
                         'Legacy two-owner ownership/report semantics retained; existing tests are run unchanged.',
                         'Start without a request or forwarding can be request-arbitration stalled or an immediate fault; both preserve exact token.',
                         'Physical port valid/ready are not separate probes: held checked-head fingerprints and accepted physical payloads are checked.']}
try:
    tests = [('legacy_backend_two', HARNESS / 'backend_ownership_test.cpp', []),
             ('legacy_datapath_two', HARNESS / 'data_path_ownership_test.cpp', []),
             ('four_owner', SOURCE / 'four_owner_test.cpp', ['-DBACKEND_OWNER_COUNT=4']),
             ('reader_legacy_two', SOURCE / 'probe_reader_test.cpp', ['-DBACKEND_OWNER_COUNT=2', '-DMOCK_LEGACY']),
             ('reader_new_two', SOURCE / 'probe_reader_test.cpp', ['-DBACKEND_OWNER_COUNT=2']),
             ('reader_new_four', SOURCE / 'probe_reader_test.cpp', ['-DBACKEND_OWNER_COUNT=4'])]
    for name, source, definitions in tests:
        binary = HERE / name
        report['checks'][name + '_compile'] = run([CXX, *FLAGS, *definitions, source, '-o', binary], name + '_compile')
        report['checks'][name] = run([binary], name)
    for name, definitions, message in [
        ('reject_four_legacy_schema', ['-DBACKEND_OWNER_COUNT=4', '-DMOCK_LEGACY'], 'four-owner observation requires backendSlotCount'),
        ('reject_three_owner_build', ['-DBACKEND_OWNER_COUNT=3'], 'backend owner probes support exactly two or four owners'),
        ('reject_wrong_fifo_capacity', ['-DBACKEND_OWNER_COUNT=4', '-DBACKEND_REQUEST_CAPACITY=2'], 'observed IntegerBackend FIFO is sized by memoryEntries')]:
        report['checks'][name] = run([CXX, '-std=c++20', '-fsyntax-only', '-I' + str(HARNESS), *definitions,
                                    SOURCE / 'probe_reader_test.cpp'], name, True, message)
    report['four_owner_negative_rejections'] = sum(line.startswith('REJECT ') for line in (HERE / 'four_owner.log').read_text().splitlines())
    assert report['four_owner_negative_rejections'] >= 54
    frozen = HARNESS / 'board_hot_nemu'
    frozen_files = [p for p in frozen.rglob('*') if p.is_file()]
    report['frozen_hot_copy_sha256'] = {str(p.relative_to(ROOT)): sha(p) for p in frozen_files}
    frozen_diff = subprocess.check_output(['git', 'diff', '66c06d7', '--', 'simulator/gsim/harness/board_hot_nemu'], cwd=ROOT, text=True)
    assert not frozen_diff, 'Frozen board_hot_nemu changed'
    report['frozen_hot_copy_unchanged_vs_baseline'] = True
    report['checks']['diff_whitespace'] = run(['git', 'diff', '--check'], 'diff_whitespace')
    report['status'] = 'PASS_HOST_ONLY'
except Exception as error:
    report['status'] = 'FAIL_HOST_ONLY'
    report['error'] = str(error)
    raise
finally:
    report['source_sha256_after'] = hashes()
    report['source_unchanged_during_tests'] = report['source_sha256_before'] == report['source_sha256_after']
    if not report['source_unchanged_during_tests']:
        report['status'] = 'FAIL_SOURCE_DRIFT'
    report['finished_utc'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    (HERE / 'host-test-receipt.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({'status': report['status'], 'four_owner_negative_rejections': report['four_owner_negative_rejections'],
                  'source_unchanged_during_tests': report['source_unchanged_during_tests']}))
