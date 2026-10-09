#!/usr/bin/env python3
"""Read-only archive audit with one explicitly verified historical host-HEAD field.

Never edits original fixtures/receipts. Never links, builds, or executes hardware.
"""
import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
SCHEMA = 'valence-fetch-prefix-archive-revalidation-v1'
PASS = 'PASS_FROZEN_FETCH_PREFIX_ARCHIVE_REVALIDATION'


def require(ok, why):
    if not ok:
        raise RuntimeError(why)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            digest.update(block)
    return digest.hexdigest()


def load(path):
    return json.loads(Path(path).read_text())


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def verify_hashes(files):
    require(type(files) is dict and files, 'empty required file inventory')
    for path, digest in files.items():
        require(Path(path).is_file() and sha(path) == digest, 'bound file content drift: ' + path)


def differences(before, after, path=''):
    if type(before) is not type(after):
        return [path]
    if isinstance(before, dict):
        result = []
        for key in sorted(before.keys() | after.keys()):
            result += differences(before[key], after[key], path + '.' + key) if key in before and key in after else [path + '.' + key]
        return result
    return [] if before == after else [path]


def normalize_host(current, historical, git):
    """Only host_head is historical; every other field must be exactly equal."""
    keys = {'production_commit', 'production_tree', 'qualified_host_commit', 'host_head'}
    require(set(current) == set(historical) == keys, 'source binding field inventory drift')
    require(set(differences(historical, current)) <= {'.host_head'}, 'non-head source binding difference')
    for key in ('production_commit', 'qualified_host_commit', 'host_head'):
        require(type(historical[key]) is str and re.fullmatch('[0-9a-f]{40}', historical[key]), 'invalid historical commit')
    require(git('rev-parse', historical['host_head'] + ':src/main') == current['production_tree'],
            'historical host production tree differs')
    git('merge-base', '--is-ancestor', historical['qualified_host_commit'], historical['host_head'])
    git('merge-base', '--is-ancestor', historical['host_head'], current['host_head'])
    return copy.deepcopy(historical)


class HistoricalAnchor:
    def __init__(self, original, historical, expected_current):
        self.original = original
        self.historical = historical
        self.expected_current = expected_current
        self.calls = []

    def __call__(self, repo, production, host=None, expected_tree=None):
        # Always call the unchanged validator first: full source tree, worktree
        # file inventory, resource bytes, symlinks and qualified-host ancestry.
        current = self.original(repo, production, host, expected_tree)
        require(current['host_head'] == self.expected_current, 'current audit HEAD changed during verification')
        def git(*args):
            p = subprocess.run(['git', *args], cwd=repo, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            require(p.returncode == 0, 'historical ancestry/identity check failed: git ' + ' '.join(args))
            return p.stdout.strip()
        normalized = normalize_host(current, self.historical, git)
        self.calls.append({'current': current, 'historical': normalized,
                           'differences': differences(normalized, current)})
        return normalized


def environment_for(state):
    result = dict(os.environ)
    for key, value in state.get('environment', {}).items():
        require(type(key) is str and (value is None or type(value) is str), 'malformed recorded environment')
        if value is None:
            result.pop(key, None)
        else:
            result[key] = value
    result['PYTHONDONTWRITEBYTECODE'] = '1'
    return result


def install_readonly_process_guard(tool_hashes, git_sha):
    original = subprocess.Popen
    commands = []
    def checked(command, *args, **kwargs):
        require(isinstance(command, (list, tuple)) and not kwargs.get('shell'), 'nonliteral or shell command prohibited')
        argv = list(map(str, command))
        resolved = shutil.which(argv[0])
        require(resolved, 'missing read-only tool')
        executable = str(Path(resolved).resolve())
        tail = argv[1:]
        if Path(executable).name == 'git':
            require(sha(executable) == git_sha, 'git executable changed')
            allowed = (tail[:1] == ['rev-parse'] or tail[:2] == ['diff', '--quiet'] or
                       tail[:2] == ['merge-base', '--is-ancestor'] or tail[:3] == ['ls-tree', '-r', '--name-only'])
        else:
            require(executable in tool_hashes and sha(executable) == tool_hashes[executable], 'unattested audit tool')
            allowed = (tail == ['--version'] or
                (len(tail) == 1 and tail[0] in ('-print-prog-name=as', '-print-prog-name=ld', '-print-prog-name=cc1')) or
                (Path(executable).name.endswith('nm') and len(tail) == 2 and tail[0] == '--defined-only') or
                (Path(executable).name.endswith('addr2line') and len(tail) == 5 and tail[0] == '-e' and tail[2:4] == ['-f', '-C']))
        require(allowed, 'non-read-only audit subprocess prohibited: ' + ' '.join(argv))
        commands.append({'command': argv, 'executable': executable, 'sha256': sha(executable)})
        return original(command, *args, **kwargs)
    subprocess.Popen = checked
    return commands


def frozen_inputs(lock, suite):
    record = lock['suites'][suite]
    receipt = ROOT / record['receipt']
    require(sha(receipt) == record['receipt_sha256'], 'original receipt changed: ' + suite)
    verify_hashes({str(ROOT / name): digest for name, digest in lock['original_sources'].items()})
    state = load(receipt)
    require(state['status'] == record['status'], 'original terminal status drift')
    if suite == 'nemu':
        files = state['inputs']['files']
        require(len(files) == 1252, 'original NEMU 1252 input inventory drift')
        verify_hashes(files)
    else:
        verify_hashes(state['frozen_files'])
    return record, receipt, state


def worker(suite):
    lock = load(HERE / 'source_lock.json')
    record, receipt, state = frozen_inputs(lock, suite)
    expected_environment = state.get('environment')
    if expected_environment is not None:
        require({key: os.environ.get(key) for key in expected_environment} == expected_environment,
                'recorded environment must be reproduced exactly, never normalized')
    historical = state['inputs']['source_binding'] if suite == 'nemu' else state['source_binding']
    current = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    tool_files = state['inputs']['files'] if suite == 'nemu' else state['frozen_files']
    trusted = {str(Path(path).resolve()): digest for path, digest in tool_files.items()}
    calls = install_readonly_process_guard(trusted, lock['git_sha256'])
    runner_path = ROOT / record['runner']
    sys.path.insert(0, str(runner_path.parent))
    runner = module('frozen_archive_' + suite, runner_path)
    raw_snapshot = None
    if suite == 'nemu':
        args = state['inputs']
        # Load the unchanged dependencies once, then install only their validator
        # anchor adapter. No checker, parser, guard, flag or audit is replaced.
        deps = runner.dependencies(ROOT)
        original_dependencies = runner.dependencies
        anchor = HistoricalAnchor(deps[-1].production_anchor, historical, current)
        deps[-1].production_anchor = anchor
        def dependencies(repo):
            require(Path(repo).resolve() == ROOT, 'dependency source root drift')
            return deps
        runner.dependencies = dependencies
        inputs = runner.Inputs(ROOT, args['model_receipts']['off'], args['model_receipts']['on'],
            args['guest_manifest'], args['reference_cache'], args['compiler'])
        require(inputs.snapshot == args, 'non-head NEMU snapshot difference')
        require(inputs.cxx.as_posix() == args['compiler'], 'original NEMU compiler spelling changed')
        raw_snapshot = copy.deepcopy(inputs.snapshot)
        raw_snapshot['source_binding']['host_head'] = current
        command = [str(runner_path), '--audit', '--off-receipt', args['model_receipts']['off'],
            '--on-receipt', args['model_receipts']['on'], '--guest-manifest', args['guest_manifest'],
            '--reference-cache', args['reference_cache'], '--compiler', args['compiler'], '--out', str(receipt.parent)]
        runner.audit(inputs, receipt.parent, state, terminal=True)
        identity_diffs = differences(args, raw_snapshot)
        require(set(identity_diffs) <= {'.source_binding.host_head'}, 'non-head NEMU identity difference')
        evidence = {'case_count': len(state['cases']), 'negative_count': sum('-negative-' in x for x in state['steps']),
                    'step_count': len(state['steps']), 'input_file_count': len(inputs.files)}
    else:
        anchor = HistoricalAnchor(runner.b.v.production_anchor, historical, current)
        runner.b.v.production_anchor = anchor
        models = state['model_receipts'] if suite == 'context' else state['models']
        key = 'path' if suite == 'context' else 'receipt'
        command = [str(runner_path), '--audit', '--off-receipt', models['off'][key],
            '--on-receipt', models['on'][key], '--out', str(receipt.parent), '--cxx', state['host_compiler']['driver']]
        if suite == 'context' and state['compress_debug']:
            command.append('--compress-debug')
        if suite == 'dma_pmp' and not state['fresh_guests']:
            command += ['--guests', state['guests_path']]
        # Read-only trace captures the unmodified runner's full computed identity;
        # no values, control flow, or checks are changed by the trace callback.
        captured = {}
        def trace(frame, event, arg):
            if frame.f_code is runner.main.__code__ and event == 'line' and 'identity' in frame.f_locals:
                captured['identity'] = copy.deepcopy(frame.f_locals['identity'])
            return trace
        sys.argv = command
        sys.settrace(trace)
        try:
            runner.main()  # Its original --audit path, including all guards.
        finally:
            sys.settrace(None)
        identity = captured['identity']
        require({k: state.get(k) for k in identity} == identity, 'non-head original audit identity difference')
        raw_snapshot = copy.deepcopy(identity)
        raw_snapshot['source_binding']['host_head'] = current
        identity_diffs = differences({k: state.get(k) for k in identity}, raw_snapshot)
        require(set(identity_diffs) <= {'.source_binding.host_head'}, 'non-head archive identity difference')
        evidence = {'case_count': len(state['cases']),
                    'negative_count': len(state['negative_controls'] if suite == 'context' else state['negatives']),
                    'step_count': len(state['steps']), 'frozen_file_count': len(state['frozen_files'])}
    frozen_inputs(lock, suite)
    require(anchor.calls and all(x['current']['host_head'] == current for x in anchor.calls), 'anchor checks missing')
    require(sha(receipt) == record['receipt_sha256'], 'original receipt modified during read-only audit')
    result = {'suite': suite, 'status': 'PASS_UNCHANGED_TERMINAL_AUDIT', 'receipt': str(receipt),
              'receipt_sha256': sha(receipt), 'runner': str(runner_path), 'runner_sha256': sha(runner_path),
              'original_audit_arguments': command, 'historical_host_head': historical['host_head'],
              'current_audit_head': current, 'production_tree': historical['production_tree'],
              'identity_differences': identity_diffs, 'anchor_checks': anchor.calls,
              'environment': expected_environment, 'readonly_subprocesses': calls, **evidence}
    print('ARCHIVE_RESULT ' + json.dumps(result, sort_keys=True))


def main():
    p = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    p.add_argument('--worker', choices=('nemu', 'context', 'dma_pmp'))
    p.add_argument('--out', type=Path)
    a = p.parse_args()
    if a.worker:
        worker(a.worker)
        return
    require(a.out, 'fresh --out required for separate archive receipt')
    out = a.out.resolve()
    require(out.is_relative_to(HERE) and not out.exists(), 'fresh output inside archive fixture required')
    lock = load(HERE / 'source_lock.json')
    source_files = {str(p): sha(p) for p in HERE.iterdir() if p.is_file()}
    start_head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    print('Read-only archive audit: original NEMU 12+26, context 4+8, DMA/PMP 4+14; no hardware/build execution.', flush=True)
    print('Tools: git, hash readers, original --audit metadata/symbolization commands. Estimate 10–30 seconds, <1 MB.', flush=True)
    out.mkdir()
    state = {'schema': SCHEMA, 'status': 'RUNNING', 'current_audit_head': start_head,
             'normalization': 'Only source_binding.host_head retained as explicitly validated historical metadata.',
             'source_files': source_files, 'source_lock_sha256': sha(HERE / 'source_lock.json'),
             'model_builds': 0, 'harness_links': 0, 'hardware_executions': 0, 'reference_executions': 0,
             'original_receipt_edits': 0, 'original_fixture_edits': 0, 'suites': {},
             'limits': ['Revalidates existing frozen terminal proofs; no new hardware coverage or performance claim.',
                        'Compiler --version/component queries and existing ELF symbolization are read-only.',
                        'Recorded path spelling and environment are reproduced, never normalized.']}
    try:
        for suite in lock['suites']:
            record, receipt, original = frozen_inputs(lock, suite)
            env = environment_for(original)
            cmd = [sys.executable, '-B', str(Path(__file__).resolve()), '--worker', suite]
            log = out / (suite + '.log')
            with log.open('x') as stream:
                result = subprocess.run(cmd, cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT, timeout=120)
            text = log.read_text()
            require(result.returncode == 0, suite + ' archive audit failed:\n' + text[-8000:])
            rows = [x for x in text.splitlines() if x.startswith('ARCHIVE_RESULT ')]
            require(len(rows) == 1, 'missing/duplicate child audit result')
            item = json.loads(rows[0].removeprefix('ARCHIVE_RESULT '))
            require(item['current_audit_head'] == start_head and item['status'] == 'PASS_UNCHANGED_TERMINAL_AUDIT',
                    'child audit scope/head drift')
            state['suites'][suite] = {'result': item, 'command': cmd, 'exit': result.returncode,
                                      'log': log.name, 'log_sha256': sha(log)}
            print(suite, item['status'], flush=True)
        verify_hashes(source_files)
        require(subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip() == start_head,
                'audit HEAD changed across suites')
        state['status'] = PASS
    except BaseException as error:
        state['status'] = 'FAIL'; state['error'] = str(error)
        raise
    finally:
        (out / 'receipt.json').write_text(json.dumps(state, indent=2) + '\n')
    print(PASS, out / 'receipt.json', sha(out / 'receipt.json'), flush=True)


if __name__ == '__main__':
    main()
