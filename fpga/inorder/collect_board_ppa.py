#!/usr/bin/env python3
"""Collect actual full-board reports; no port-fixture resources are subtracted."""
import argparse, csv, hashlib, json, re
from pathlib import Path
p = argparse.ArgumentParser()
p.add_argument('--run', type=Path, required=True)
p.add_argument('--label', required=True)
a = p.parse_args(); root = a.run.resolve(); reports = root / 'implementation'
text = (reports / 'utilization_routed.rpt').read_text()
row = next(line for line in text.splitlines() if re.match(r'\|\s*i1_board_wrapper\s*\|', line))
fields = [part.strip() for part in row.split('|')[1:-1]]
values = list(map(int, fields[2:]))
resources = dict(zip(['LUT', 'logic_LUT', 'LUTRAM', 'SRL', 'FF', 'BRAM36', 'BRAM18', 'URAM', 'DSP'], values, strict=True))
with (reports / 'clock_results.tsv').open() as f:
    clocks = list(csv.DictReader(f, delimiter='\t'))
for row in clocks:
    for key in ['period_ns', 'setup_wns_ns', 'hold_wns_ns']: row[key] = float(row[key])
    row['negative_endpoints'] = int(row['negative_endpoints'])
summary = (reports / 'timing_summary.rpt').read_text().split('Design Timing Summary', 1)[1]
line = next(line for line in summary.splitlines() if re.match(r'^\s*-?\d+\.\d+\s+-?\d+\.\d+\s+\d+', line))
nums = list(map(float, line.split())); assert len(nums) == 12
names = ['setup_WNS_ns','setup_TNS_ns','setup_failing_endpoints','setup_endpoints',
         'hold_WNS_ns','hold_TNS_ns','hold_failing_endpoints','hold_endpoints',
         'pulse_WNS_ns','pulse_TNS_ns','pulse_failing_endpoints','pulse_endpoints']
global_timing = dict(zip(names, nums, strict=True))
checks = {name: int(count) for name, count in re.findall(r'checking ([a-z_]+) \((\d+)\)', (reports / 'check_timing.rpt').read_text())}
bus = (reports / 'bus_skew.rpt').read_text()
log = next(f for f in sorted(root.glob('implement-board*.log'), reverse=True) if 'BOARD_GLOBAL_SIGNOFF' in f.read_text())
flags = re.findall(r'BOARD_GLOBAL_SIGNOFF setup_fail=(\d+) hold_fail=(\d+) drc_errors=(\d+)', log.read_text())[-1]
required_zero = ['no_clock', 'constant_clock', 'pulse_width_clock',
    'unconstrained_internal_endpoints', 'no_input_delay', 'no_output_delay',
    'multiple_clock', 'generated_clocks', 'loops', 'latch_loops']
passed = (all(int(x) == 0 for x in flags)
    and global_timing['pulse_failing_endpoints'] == 0
    and 'Slack (VIOLATED)' not in bus
    and all(checks[name] == 0 for name in required_zero))
record = {'status': 'PASS_ROUTED_BOARD_TIMING_DRC' if passed else 'FAIL_ROUTED_BOARD_TIMING',
    'label': a.label, 'resources': resources, 'clocks': clocks, 'global_timing': global_timing,
    'check_timing': checks, 'bus_skew_violations_present': 'Slack (VIOLATED)' in bus,
    'drc_errors': int(flags[2]), 'port_fixture_subtracted': False,
    'board_tested': False, 'vivado_threads': 8,
    'UART_output_constraint_under_review': 'UART_TX_ASYNC_BAUD' not in (root / 'board_cdc.tcl').read_text(),
    'UART_output_contract': ('asynchronous_16x_baud_tick_max_propagation' if 'UART_TX_ASYNC_BAUD' in (root / 'board_cdc.tcl').read_text() else 'legacy_system_clocked_output_under_review'),
    'checkpoint_sha256': {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in reports.glob('*.dcp')},
    'constraint_sha256': {n: hashlib.sha256((root / n).read_bytes()).hexdigest() for n in ['board_cdc.tcl', 'system_cdc.tcl', 'board-pins.xdc']},
    'cdc_structure_summary': {code: {'severity': severity, 'count': int(count)} for code, severity, count in re.findall(r'^(CDC-[0-9]+)\s+(Info|Warning|Critical)\s+(\d+)\s', (reports / 'cdc.rpt').read_text(), re.M)},
    'artifact_sha256': {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in reports.glob('*.rpt')}}
(root / 'physical-summary.json').write_text(json.dumps(record, indent=2) + '\n')
print(record['status'], resources)
for row in clocks: print(row['role'], row['setup_wns_ns'], row['negative_endpoints'], row['hold_wns_ns'])
