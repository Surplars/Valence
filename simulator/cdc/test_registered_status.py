#!/usr/bin/env python3
"""Fresh emitted RTL, true independent clocks; component-only, not timing signoff."""
import argparse
import json
from pathlib import Path
from test_tilelink_boundary import run_logged, sha

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('rtl', type=Path)
p.add_argument('output', type=Path)
p.add_argument('--iverilog', required=True)
p.add_argument('--vvp', required=True)
a = p.parse_args()
if a.output.exists():
    p.error('output must be fresh')
a.output.mkdir(parents=True)
files = sorted(a.rtl.resolve().glob('*.sv'))
assert files, 'no emitted RTL'
tb = Path(__file__).with_name('registered_status_tb.sv').resolve()
root = tb.parents[2]
sources = [root / name for name in (
    'src/main/scala/ip/bus/RegisteredStatusClockBoundary.scala',
    'src/main/scala/ip/bus/ClockDomainCrossing.scala',
    'src/test/scala/ip/RegisteredStatusBoundaryMain.scala')]
exe = a.output.resolve() / 'simulation'
receipt = {'scope': 'standalone opt-in status helper only; no default integration or physical signoff',
           'inputs': {str(f): sha(f) for f in files + [tb]},
           'sources': {str(f.relative_to(root)): sha(f) for f in sources},
           'tools': {str(Path(f).resolve()): sha(Path(f)) for f in (a.iverilog, a.vvp)},
           'runs': {}}
compile_result = run_logged([a.iverilog, '-g2012', '-s', 'registered_status_tb', '-o', str(exe),
                             *map(str, files), str(tb)], a.output / 'compile.log')
receipt['compile'] = compile_result
assert compile_result['returncode'] == 0, 'compile failed; inspect compile.log'
for fault in (0, 1, 2):
    log = a.output / f'fault-{fault}.log'
    result = run_logged([a.vvp, str(exe), f'+fault={fault}'], log)
    contents = log.read_text()
    receipt['runs'][str(fault)] = result
    assert not result['timed_out'] and not result['disk_floor_breached']
    if fault == 0:
        assert result['returncode'] == 0 and 'REGISTERED_STATUS_NATIVE_PASS' in contents, contents
    else:
        assert result['returncode'] != 0 and 'STATUS_ORACLE_MISMATCH' in contents, contents
receipt['status'] = 'PASS_WITH_TWO_MONITOR_NEGATIVE_CONTROLS'
(a.output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(receipt['status'])
