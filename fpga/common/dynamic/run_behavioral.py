#!/usr/bin/env python3
"""Icarus transaction/clock-observer evidence, deliberately not vendor evidence."""
import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--iverilog', type=Path, required=True)
    parser.add_argument('--vvp', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    source_dir = root/'fpga/common/dynamic'
    sources = sorted(p for p in (root/'fpga/common').rglob('*')
                     if p.is_file() and p.suffix in ('.sv', '.tcl', '.py', '.xdc') and '__pycache__' not in p.parts)
    frozen = {p.relative_to(root).as_posix(): sha(p) for p in sources}
    receipt = dict(schema=1, stage='dynamic-clock-behavioral-only', vendorPrimitivesValidated=False,
                   fullSocValidated=False, timingValidated=False, boardValidated=False,
                   softwareQualifiedPoints=[], sourceHashes=frozen, tools={}, runs=[],
                   createdUtc=datetime.now(timezone.utc).isoformat())
    receipt['baseCommit'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    for name in ('iverilog', 'vvp'):
        p = getattr(args, name).resolve(strict=True)
        receipt['tools'][name] = dict(path=str(p), sha256=sha(p))
    def run(label, command, marker=None, negative=False):
        result = subprocess.run([str(x) for x in command], cwd=root, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=90)
        log = out/(label+'.log'); log.write_text(result.stdout)
        good = (result.returncode != 0 if negative else result.returncode == 0)
        if marker is not None:
            good = good and marker in result.stdout
        receipt['runs'].append(dict(label=label, command=[str(x) for x in command], exitCode=result.returncode,
                                    expectedFailure=negative, marker=marker, passed=good,
                                    log=log.name, logSha256=sha(log)))
        if not good:
            raise RuntimeError(f'{label} failed expected outcome; inspect {log}')
    try:
        for tool in ('iverilog', 'vvp'):
            run(tool+'-version', [getattr(args, tool), '-V'])
        base = ['behavioral_primitives', 'native_clock_gate', 'native_clock_drp', 'native_dynamic_clock_domain']
        tests = [
            ('dynamic_clock_tb', base, 'DYNAMIC_CLOCK_BEHAVIORAL_PASS'),
            ('gate_witness_tb', ['behavioral_primitives', 'native_clock_gate'], 'GATE_WITNESS_BEHAVIORAL_PASS'),
            ('drp_reset_tb', ['native_clock_drp'], 'DRP_RESET_BEHAVIORAL_PASS'),
            ('drp_stuck_ready_tb', ['native_clock_drp'], 'DRP_READY_FAULT_BEHAVIORAL_PASS'),
            ('dynamic_clock_unisim_tb', base, 'DYNAMIC_CLOCK_VENDOR_TB_MODEL_SMOKE_PASS'),
        ]
        for top, rtl, marker in tests:
            exe = out/(top+'.vvp')
            run(top+'-compile', [args.iverilog, '-g2012', '-s', top, '-o', exe,
                                *[source_dir/(p+'.sv') for p in rtl+[top]]])
            run(top, [args.vvp, exe], marker)
        for mode, marker in [('negative_fake_closed', 'CPU_EDGE_AFTER_CLOSE_ACK'),
                             ('negative_fake_resumed', 'STALE_OPEN_EDGE_WITNESS'),
                             ('negative_wrong_rate', 'CLOCK_RATE_OR_INDEPENDENCE')]:
            run(mode, [args.vvp, out/'dynamic_clock_tb.vvp', '+'+mode], marker, negative=True)
        run('board-python-tests', ['python3', '-m', 'unittest', 'discover', '-s', 'fpga/common', '-p', 'test_*.py'], 'OK')
        run('clock-target-contracts', ['python3', '-m', 'unittest', 'discover', '-s', 'fpga/common', '-p', 'test_dynamic_clock_targets.py', '-v'], 'OK')
        after = {p.relative_to(root).as_posix(): sha(p) for p in sources}
        if frozen != after:
            raise RuntimeError('Source drift during tests')
        receipt['status'] = 'PASS_BEHAVIORAL_ONLY_NATIVE_QUALIFICATION_PENDING'
    except Exception as exc:
        receipt['status'] = 'FAILED'
        receipt['error'] = str(exc)
        raise
    finally:
        (out/'receipt.json').write_text(json.dumps(receipt, indent=2, sort_keys=True)+'\n')
    print(receipt['status'])
    print(out/'receipt.json')


if __name__ == '__main__':
    main()
