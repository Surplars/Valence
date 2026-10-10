#!/usr/bin/env python3
"""Relink host-only witness fixes against immutable, fully hashed backend OFF/ON model objects."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[3]
DRIVER = 'simulator/gsim/harness/canonical_virtual_store_backend.cpp'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(ok, why):
    if not ok:
        raise RuntimeError(why)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--slot-granted', action='store_true')
    ap.add_argument('--models', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--tool-receipt', type=Path, required=True)
    args = ap.parse_args()
    require(args.slot_granted, 'explicit existing serial slot required')
    require(not subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT), 'freeze source first')
    base = args.models.resolve()
    previous = json.loads((base / 'receipt.json').read_text())
    require(previous['status'] == 'PASS_SELECTED_CONFIG_AND_FOCUSED_COMPONENTS_ONLY', 'base models did not qualify')
    for path, digest in previous['inputs'].items():
        if path != DRIVER:
            require(sha(ROOT / path) == digest, 'non-host input changed: ' + path)
    tools = json.loads(args.tool_receipt.read_text())
    require(sha(args.tool_receipt) == previous['tool_receipt_sha256'], 'tool receipt changed')
    for item in tools['files'].values():
        require(sha(item['path']) == item['sha256'], 'tool binary drift')
    for model in previous['models'].values():
        for path, digest in model['artifacts'].items():
            require(sha(base / path) == digest, 'frozen model artifact changed: ' + path)
    out = args.output.resolve(); require(not out.exists(), 'fresh host replay output required'); out.mkdir()
    receipt = {'status': 'RUNNING', 'schema': 'canonical-backend-host-replay-v1',
               'scope': 'same immutable backend OFF/ON DUT models; host-only token witnesses and unresolved stall labels',
               'source_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
               'driver_sha256': sha(ROOT / DRIVER), 'base_receipt_sha256': sha(base / 'receipt.json'),
               'tool_receipt_sha256': sha(args.tool_receipt), 'script_sha256': sha(__file__),
               'no_java_emit_generate_or_model_recompile': True, 'steps': []}

    def save():
        (out / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')

    def step(name, command, anchor=None, negative=False, timeout=180):
        start = time.monotonic(); log = out / (name + '.log')
        with log.open('x') as stream:
            result = subprocess.run(list(map(str, command)), cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                                    env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'}, timeout=timeout)
        text = log.read_text()
        receipt['steps'].append({'name': name, 'command': list(map(str, command)), 'exit': result.returncode,
                                 'negative_control': negative, 'seconds': time.monotonic() - start,
                                 'log_sha256': sha(log)})
        save()
        require((result.returncode != 0 if negative else result.returncode == 0) and
                (anchor is None or anchor in text), 'host replay failure: ' + name)
        require(not any(x in text for x in ['AddressSanitizer', 'UndefinedBehaviorSanitizer', 'runtime error:']),
                'sanitizer diagnostic: ' + name)

    try:
        save()
        for name, enabled in [('backendoff', 0), ('backendon', 1)]:
            model = base / name; executable = out / name
            objects = sorted(model.glob('CanonicalVirtualStoreBackendGsim[0-9]*.o'))
            require(objects, 'missing original native model objects')
            flags = ['-std=c++20', '-O1', '-g', '-gz=zlib', '-fsanitize=address,undefined',
                     '-fno-sanitize-recover=all', '-I' + str(model), '-I' + str(ROOT / 'simulator/gsim/harness'),
                     '-DPRECHECK_ENABLED=1', '-DCANONICAL_STORE_OVERLAP=' + str(enabled)]
            step(name + '-link', [tools['files']['clang']['path'], *flags, ROOT / DRIVER, *objects, '-ldl', '-o', executable])
            step(name + '-cases', [executable], anchor='CANONICAL_BACKEND_PASS enabled=' + str(enabled))
            step(name + '-result-negative', [executable, '--inject-result'], negative=True,
                 anchor='independent architectural result mismatch')
            step(name + '-retirement-negative', [executable, '--inject-cancel-retirement'], negative=True,
                 anchor='faulted store allowed the younger load or dependent full token to retire')
        receipt['status'] = 'PASS_HOST_ONLY_EXACT_TOKEN_FAULT_CLOSURE'
        receipt['artifacts'] = {p.name: sha(p) for p in out.iterdir() if p.is_file() and p.name != 'receipt.json'}
    except BaseException as error:
        receipt['status'] = 'FAIL'; receipt['error'] = str(error); raise
    finally:
        save()
    print(receipt['status'], out / 'receipt.json')


if __name__ == '__main__':
    main()
