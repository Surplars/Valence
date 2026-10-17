#!/usr/bin/env python3
"""Reconstruct relative paths for the byte-identical frozen test; no compiler/model build."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys

HERE = Path(__file__).resolve().parent

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--workdir', type=Path, required=True)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    manifest = json.loads((HERE / 'SOURCE_HASHES.json').read_text())
    for name, record in manifest.items():
        source = HERE / name
        assert source.is_file() and source.stat().st_size == record['bytes'], name
        assert hashlib.sha256(source.read_bytes()).hexdigest() == record['sha256'], name
    work = args.workdir.resolve()
    assert not work.exists(), 'fresh work directory required; preserve previous receipts'
    binary = args.binary.resolve()
    assert binary.is_file(), 'supply the already qualified/built component executable'
    test = work / 'case-fixture/source/full_line_cases.py'
    baseline = work / 'Valence-ethernet-cpu-line275-r1/simulator/gsim/posted_merge_rebuild'
    command = [sys.executable, '-B', str(test), '--executable', str(binary),
               '--output', str(work / 'results'), '--generation-bits', '64']
    print(json.dumps({'command': command, 'copies': 4, 'fresh_hardware_run_qualified': False}, indent=2))
    if args.dry_run:
        return
    test.parent.mkdir(parents=True)
    baseline.mkdir(parents=True)
    shutil.copy2(HERE / 'host/full_line_cases.py', test)
    for name in ['fixture.py', 'contract_oracle.py', 'ports.py']:
        shutil.copy2(HERE / 'baseline' / name, baseline / name)
    child = subprocess.Popen(command, start_new_session=True,
                             env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1',
                                  'ASAN_OPTIONS': 'detect_leaks=0'})
    try:
        code = child.wait(timeout=180)
    except subprocess.TimeoutExpired:
        os.killpg(child.pid, signal.SIGTERM)
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait()
        raise SystemExit('component timeout; process group stopped')
    raise SystemExit(code)

if __name__ == '__main__':
    main()
