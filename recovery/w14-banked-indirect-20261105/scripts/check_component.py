#!/usr/bin/env python3
"""Run the preserved component positive and four observation-negative tests.
An independently generated, compiled and hash-verified executable is required.
This is not the whole-CPU benchmark and is not run by verify_snapshot.py.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import subprocess

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--executable', type=Path, required=True)
p.add_argument('--executable-sha256', required=True)
p.add_argument('--output', type=Path, required=True, help='New directory; must not already exist')
args = p.parse_args()
exe = args.executable.resolve()
if hashlib.sha256(exe.read_bytes()).hexdigest() != args.executable_sha256:
    raise SystemExit('Executable hash mismatch')
args.output.mkdir(parents=True, exist_ok=False)
root = Path(__file__).resolve().parents[1]
expected = json.loads((root / 'RESULTS.json').read_text())['component']
env = os.environ.copy()
for key in ('LD_PRELOAD', 'LD_AUDIT'):
    if env.get(key):
        raise SystemExit('Unexpected runtime injection: ' + key)
env.update(ASAN_OPTIONS='detect_leaks=0', UBSAN_OPTIONS='halt_on_error=1', LANG='C', LC_ALL='C')
cases = [('positive', [], 0, None),
         ('branch-negative', ['--inject-mismatch'], 1, 'prediction training oracle mismatch'),
         ('table-hit-negative', ['--inject-table-hit'], 1, 'directed indirect table hit mismatch'),
         ('table-target-high-negative', ['--inject-table-target-high'], 1, 'directed indirect table target mismatch'),
         ('bank-stale-hit-negative', ['--inject-bank-stale-hit'], 1, 'banked indirect table hit mismatch')]
for name, flags, code, marker in cases:
    run = subprocess.run([str(exe), *flags], env=env, cwd=args.output, capture_output=True, text=True, timeout=120)
    (args.output / (name + '.stdout')).write_text(run.stdout)
    (args.output / (name + '.stderr')).write_text(run.stderr)
    if run.returncode != code or re.search(r'AddressSanitizer|UndefinedBehaviorSanitizer|runtime error:|LeakSanitizer', run.stdout + run.stderr):
        raise SystemExit('FAIL: ' + name)
    if marker and marker not in run.stderr:
        raise SystemExit('Missing expected oracle rejection: ' + name)
    if name == 'positive':
        lines = run.stdout.splitlines()
        prefixes = ['GSIM prediction training: PASS ', 'GSIM directed indirect: PASS ', 'GSIM banked indirect: PASS ']
        if run.stderr or len(lines) != 3 or not all(line.startswith(prefix) for line, prefix in zip(lines, prefixes)):
            raise SystemExit('Positive test output mismatch')
        counts = [{k: int(v) for k, v in re.findall(r'(\w+)=(\d+)', line)} for line in lines]
        if counts != [expected['positive'][k] for k in ['random', 'original_directed', 'banked_directed']]:
            raise SystemExit('Positive coverage-count mismatch')
    print(name + ': PASS')
