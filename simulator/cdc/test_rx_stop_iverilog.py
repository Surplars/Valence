#!/usr/bin/env python3
"""Run the existing independent RX-stop ledger against fresh emitted RTL in Icarus.

Real mailbox/barrier/FIFO; frame/status owners are surrogates. No physical signoff.
"""
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
    p.error('use a fresh output directory')
a.output.mkdir(parents=True)
root = Path(__file__).resolve().parents[2]
tb = root / 'fpga/zu15eg/rx_admission_stop_cdc_tb.sv'
files = sorted(a.rtl.resolve().glob('*.sv'))
assert files, 'missing emitted RTL'
exe = a.output.resolve() / 'simulation'
sources = [root / name for name in (
    'src/main/scala/ip/bus/CdcDataChannels.scala',
    'src/main/scala/ip/bus/ClockDomainCrossing.scala',
    'src/main/scala/ip/ethernet/EthernetClockCrossing.scala',
    'src/main/scala/ip/ethernet/EthernetPort.scala',
    'src/main/scala/ip/ethernet/EthernetRxAdmissionStop.scala',
    'src/test/scala/ip/GmacRxAdmissionStopCdc.scala',
    'src/test/scala/ip/RegisteredStatusBoundaryMain.scala',
    'simulator/cdc/test_rx_stop_iverilog.py',
    'simulator/cdc/test_tilelink_boundary.py',
    'build.mill')]
receipt = {'scope': __doc__, 'inputs': {str(f): sha(f) for f in files + [tb]},
           'sources': {str(f.relative_to(root)): sha(f) for f in sources},
           'tools': {str(Path(f).resolve()): sha(Path(f)) for f in (a.iverilog, a.vvp)},
           'runs': {}}
result = run_logged([a.iverilog, '-g2012', '-s', 'rx_admission_stop_cdc_tb', '-o', str(exe),
                     *map(str, files), str(tb)], a.output / 'compile.log')
receipt['compile'] = result
assert result['returncode'] == 0, 'compile failed; inspect compile.log'
for injection, marker in (('', 'RX_ADMISSION_STOP_CDC_PASS'),
                          ('payload', 'RX stop independent payload scoreboard mismatch'),
                          ('drain', 'RX stop independent drain')):
    log = a.output / (injection or 'baseline')
    command = [a.vvp, str(exe)] + ([f'+inject_{injection}'] if injection else [])
    result = run_logged(command, log)
    receipt['runs'][injection or 'baseline'] = result
    contents = log.read_text()
    assert not result['timed_out'] and not result['disk_floor_breached']
    assert marker in contents, contents[-4000:]
    assert (result['returncode'] != 0) == bool(injection), contents[-4000:]
assert receipt['sources'] == {str(f.relative_to(root)): sha(f) for f in sources}, 'source drift'
assert receipt['inputs'] == {str(f): sha(f) for f in files + [tb]}, 'input drift'
receipt['status'] = 'PASS_RX_STOP_ICARUS_WITH_TWO_MONITOR_NEGATIVE_CONTROLS'
(a.output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(receipt['status'])
