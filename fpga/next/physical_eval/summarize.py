"""Read existing synthesis/placed reports. Never opens Vivado or changes a run."""
import argparse
import hashlib
import json
if not __debug__:
    raise SystemExit('Safety checks require Python without -O')

from pathlib import Path
import re
import csv


def timing(folder):
    text = (folder / 'timing_summary.rpt').read_text(encoding='utf-8')
    summary = text.split('Design Timing Summary', 1)[1]
    row = next(line for line in summary.splitlines()
               if re.match(r'^\s*-?\d+\.\d+\s+-?\d+\.\d+\s+\d+', line))
    values = re.findall(r'-?\d+(?:\.\d+)?', row)
    if len(values) != 12:
        raise ValueError('Unexpected timing summary columns')
    coverage = (folder / 'check_timing.rpt').read_text(encoding='utf-8')
    cdc = (folder / 'cdc.rpt').read_text(encoding='utf-8')
    return dict(WNS_ns=float(values[0]), TNS_ns=float(values[1]),
                WHS_ns=float(values[4]), THS_ns=float(values[5]),
                coverage={name: int(count) for name, count in
                          re.findall(r'checking\s+(\w+)\s+\((\d+)\)', coverage)},
                cdc_summary={rule: dict(severity=severity, count=int(count))
                             for rule, severity, count in re.findall(
                                 r'^(CDC-\d+)\s+(Critical|Warning|Info)\s+(\d+)\s+', cdc, re.M)})


def summarize(root, run_name):
    if not re.fullmatch(r'[A-Za-z0-9_-]+', run_name):
        raise ValueError('Invalid run basename')
    run = root / run_name
    if (run / 'failure.txt').exists():
        raise ValueError('Run has a recorded failure')
    if 'PLACED_REQUIRES_REVIEW' not in (run / 'stage-result.txt').read_text(encoding='utf-8'):
        raise ValueError('Placement completion marker missing')
    receipt = json.loads((root / 'evidence/frozen-inputs.json').read_text(encoding='utf-8'))
    def resources(folder):
        row = next(line for line in (folder / 'utilization.rpt').read_text(encoding='utf-8').splitlines()
                   if re.match(r'^\|\s*soc_top_fpga_next_ddr\s*\|', line))
        columns = [part.strip() for part in row.strip().strip('|').split('|')]
        return dict(zip(('LUT_total', 'LUT_logic', 'LUTRAM', 'SRL', 'FF',
                         'RAMB36', 'RAMB18', 'URAM', 'DSP'), map(int, columns[2:])))

    def init(path):
        result = {}
        cell = None
        for line in path.read_text(encoding='utf-8').splitlines():
            parts = line.split('\t')
            if parts[0] == 'CELL':
                cell = parts[1]
                result[cell] = {'REF_NAME': parts[2]}
            else:
                result[cell][parts[0]] = parts[1]
        return result

    baseline = init(root / 'synthesis/rom-init.tsv')
    mac_gate = (run / 'mac-raw-handoff-final.txt').read_text(encoding='utf-8')
    if 'PASS_MAC_ROLE_SEMANTICS' not in mac_gate:
        raise ValueError('Final MAC semantic gate missing')
    thread_file = run / 'threads.tsv'
    threads = list(csv.DictReader(thread_file.read_text(encoding='utf-8').splitlines(), delimiter='\t')) if thread_file.exists() else []
    result = dict(status='PLACED_ESTIMATE_REQUIRES_TIMING_CDC_RDC_REVIEW',
                  requested_threads=receipt.get('requested_threads'),
                  thread_manifest=threads,
                  thread_manifest_status='RECORDED_CONFIGURED_LIMITS_NOT_WORKER_OCCUPANCY' if threads else 'HISTORICAL_MANIFEST_UNAVAILABLE',
                  commit=receipt['commit'], tree=receipt['tree'],
                  rom=receipt['rom'],
                  timing={name: timing(run / name) for name in ('post_synth', 'post_place')},
                  resources={name: resources(run / name) for name in ('post_synth', 'post_place')},
                  rom_init_equal_synthesis={stage: init(run / ('rom-init-' + stage + '.tsv')) == baseline
                                            for stage in ('opt', 'placed')},
                  mac_final_semantic_gate=True,
                  jtag=(run / 'jtag-inventory.txt').read_text(encoding='utf-8'),
                  artifacts={p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                             for p in sorted(run.glob('*.dcp'))})
    if 'PASS_EXACT_USER2_OWNER' not in result['jtag']:
        raise ValueError('USER2 final gate missing')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('run_name')
    args = parser.parse_args()
    print(json.dumps(summarize(args.root, args.run_name), indent=2))
