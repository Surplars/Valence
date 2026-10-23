#!/usr/bin/env python3
"""Run the independent oracle against freshly emitted ClockPerformanceTelemetry RTL."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--rtl', required=True, type=Path)
    p.add_argument('--out', required=True, type=Path)
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    rtl = sorted(a.rtl.glob('*.sv'))
    assert rtl, 'No emitted RTL supplied'
    tb = ROOT / 'simulator/cdc/clock_performance_telemetry_tb.sv'
    binary = a.out / 'telemetry.vvp'
    commands = [['iverilog', '-g2012', '-s', 'clock_performance_telemetry_tb', '-o', str(binary),
                 *map(str, rtl), str(tb)], ['vvp', str(binary)]]
    receipt = {'status': 'RUNNING', 'rtl_sha256': {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in rtl},
               'testbench_sha256': hashlib.sha256(tb.read_bytes()).hexdigest(), 'cases': []}
    try:
        for index, cmd in enumerate(commands):
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            output = r.stdout + r.stderr
            (a.out / f'{index}.log').write_text(output)
            receipt['cases'].append({'command': cmd, 'exit_code': r.returncode})
            assert r.returncode == 0, output[-6000:]
            if index: assert 'CLOCK_PERFORMANCE_TELEMETRY_PASS' in output
        receipt['status'] = 'PASS'
        print('CLOCK_PERFORMANCE_TELEMETRY_PASS')
    except BaseException as error:
        receipt['status'] = 'FAIL'
        receipt['error'] = str(error)
        raise
    finally:
        (a.out / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')

if __name__ == '__main__':
    main()
