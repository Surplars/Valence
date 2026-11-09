#!/usr/bin/env python3
"""Collect a frozen dual-clock implementation; never run or change the CAD flow."""
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import re

ROOT = Path('/home/openion/Valence-InOrder')
WINDOWS = Path('/mnt/e/VM/Share/Valence-rtl/Valence-InOrder')
RESOURCES = ['lut', 'logic_lut', 'lutram', 'srl', 'ff', 'bram36', 'bram18', 'uram', 'dsp']


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def field(pattern, text):
    found = re.search(pattern, text, re.M)
    require(found is not None, 'Report field missing: ' + pattern)
    return found.group(1)


def critical(text):
    text = text[text.index('Slack ('):]
    result = {'slack_ns': float(field(r'^Slack \([A-Z]+\)\s*:\s*([-+.0-9]+)ns', text))}
    for key in ['Source', 'Destination', 'Path Group', 'Path Type', 'Requirement',
                'Data Path Delay', 'Logic Levels']:
        result[key] = field(r'^\s*' + re.escape(key) + r':\s*(.*)$', text)
    # Datapath-only CDC reports intentionally omit clock skew/uncertainty.
    for key in ['Clock Path Skew', 'Clock Uncertainty']:
        value = re.search(r'^\s*' + re.escape(key) + r':\s*(.*)$', text, re.M)
        if value:
            result[key] = value.group(1)
    return result


def hierarchy(text):
    rows = []
    for line in text.splitlines():
        cells = [v.strip() for v in line.split('|')[1:-1]]
        if len(cells) == 11 and cells[2].isdigit():
            rows.append({'instance': cells[0], 'module': cells[1], **dict(zip(RESOURCES, map(int, cells[2:])))})
    def one(instance, module=None):
        found = [r for r in rows if r['instance'] == instance and (module is None or r['module'] == module)]
        require(len(found) == 1, 'Ambiguous hierarchy row: ' + instance)
        return {k: found[0][k] for k in RESOURCES}
    result = {name: one(instance, module) for name, instance, module in [
        ('total', 'I1Spinor300Context', None), ('dut', 'dut', 'I1SpinorDualClockCore'),
        ('capture_fixture', '(I1Spinor300Context)', None), ('cpu', 'cpu', 'FiveStageCachedCore'),
        ('vpu', 'vector', 'SpinorIsolated'), ('cdc_boundary', 'boundary', 'I1SpinorClockBoundary')]}
    require(all(result['total'][k] == result['dut'][k] + result['capture_fixture'][k] for k in RESOURCES),
            'DUT plus capture fixture does not equal total')
    # Vivado flattens the small memory bridge into DUT glue; do not invent a zero-sized module.
    result['memory_bridge_and_dut_glue'] = {k: result['dut'][k] - sum(result[n][k] for n in
        ['cpu', 'vpu', 'cdc_boundary']) for k in RESOURCES}
    result['hierarchy'] = rows
    return result


def collect(build, version):
    inputs = {}
    def record(path):
        inputs[str(path)] = {'sha256': sha(path), 'bytes': path.stat().st_size}
        return path
    def read(path):
        return record(path).read_text()
    frozen = json.loads(read(build / 'implementation-inputs.json'))
    require(sha(build / 'implementation-inputs.json') == sha(record(version / 'implementation-inputs.json')),
            'WSL/Windows implementation freeze differs')
    generation = json.loads(read(version / 'generation.json'))
    require(generation == frozen['generation'], 'Generation differs from frozen inputs')
    require(sha(record(build / 'generation.json')) == sha(version / 'generation.json'), 'Generation copies differ')
    locations = {'generation.json': version / 'generation.json',
                 'synthesized.dcp': version / 'synth/synthesized.dcp',
                 'context.xdc': version / 'synth/context.xdc',
                 'spinor_cdc.tcl': version / 'spinor_cdc.tcl',
                 'spinor300_implement.tcl': version / 'spinor300_implement.tcl'}
    for name, expected in frozen['inputs_sha256'].items():
        require(sha(record(locations[name])) == expected, 'Frozen input changed: ' + name)
    rtl = {p.relative_to(version / 'rtl').as_posix(): sha(record(p))
           for p in sorted((version / 'rtl').rglob('*.sv'))}
    require(rtl == generation['rtl_sha256'], 'Frozen RTL differs from export receipt')
    snapshot = build / 'source-at-export'
    for name, expected in generation['source_sha256'].items():
        require(sha(record(snapshot / name)) == expected, 'Export source snapshot changed: ' + name)
        require(sha(record(version / 'source-at-export' / name)) == expected, 'Windows source snapshot changed: ' + name)
    functional_path = ROOT / frozen['functional_receipt']
    functional = json.loads(read(functional_path))
    require(sha(functional_path) == frozen['functional_sha256'] == generation['functional_receipt_sha256'],
            'Functional receipt does not match physical inputs')
    require(functional['status'] == 'PASS_REAL_CPU_SPINOR_DUAL_CLOCK_DIRECTED_PROGRAM_FOUR_CASES_TWO_NEGATIVES',
            'Functional check did not pass')
    for name in generation['functional_dependency_match']:
        require(generation['source_sha256'][name] == functional['sources'][name], 'Functional dependency differs: ' + name)
    for name, expected in functional['artifact_sha256'].items():
        require(sha(record(functional_path.parent / name)) == expected, 'Functional artifact changed: ' + name)
    tool_receipt = ROOT / functional['qualified_tool_receipt']
    require(sha(record(tool_receipt)) == functional['qualified_tool_receipt_sha256'], 'Tool qualification receipt changed')
    require(sha(record(version / 'spinor300_synth.tcl')) == generation['source_sha256']['fpga/inorder/spinor300_synth.tcl'],
            'Synthesis flow differs from exported source')
    journal = read(version / 'vivado-implementation.jou')
    command = field(r'^# Command line\s*:\s*(.*)$', journal)
    win_version = str(version).replace('/mnt/e/', 'E:/')
    require('-source ' + win_version + '/spinor300_implement.tcl -tclargs ' + win_version +
            '/synth/synthesized.dcp ' + win_version + '/physical' in command, 'Unexpected implementation invocation')
    log = read(version / 'vivado-implementation.log')
    require('I1_SPINOR300_ROUTED_DONE NO_BIT NO_BOARD_SIGNOFF' in log, 'Implementation did not finish')
    require(not re.search(r'^ERROR:', log, re.M), 'Vivado implementation contains errors')
    physical = version / 'physical'
    artifacts = {p.name: {'sha256': sha(record(p)), 'bytes': p.stat().st_size}
                 for p in sorted(physical.iterdir()) if p.suffix in {'.rpt', '.dcp', '.xdc', '.tsv'}}
    domains = {}
    periods = {name: float(field(r'create_clock -name i1_' + name + r'300 -period ([0-9.]+)',
                               read(version / 'synth/context.xdc'))) for name in ['cpu', 'vpu']}
    tabular = list(csv.DictReader(io.StringIO(read(physical / 'internal_result.tsv')), delimiter='\t'))
    for row in tabular:
        name = row['domain']
        setup = critical(read(physical / (name + '_setup.rpt')))
        hold = critical(read(physical / (name + '_hold.rpt')))
        require(abs(setup['slack_ns'] - float(row['setup_ns'])) < .0011, 'Setup TSV/report mismatch')
        require(abs(hold['slack_ns'] - float(row['hold_ns'])) < .0011, 'Hold TSV/report mismatch')
        domains[name] = {'period_ns': periods[name], 'setup': setup, 'hold': hold,
                         'closed_300mhz': setup['slack_ns'] >= 0 and hold['slack_ns'] >= 0,
                         'linear_period_estimate_mhz': 1000 / (periods[name] - setup['slack_ns'])}
    require(set(domains) == {'cpu', 'vpu'}, 'Both clock domains must be reported')
    coverage = list(csv.DictReader(io.StringIO(read(physical / 'cdc_coverage.tsv')), delimiter='\t'))
    scopes = list(csv.DictReader(io.StringIO(read(physical / 'cdc_scopes.tsv')), delimiter='\t'))
    require(len(coverage) == sum(int(s['ends']) for s in scopes), 'CDC endpoint coverage differs from scoped constraints')
    require(len({r['end'] for r in coverage}) == len(coverage), 'Duplicate CDC endpoint')
    cdc_slack = min(float(r['slack_ns']) for r in coverage)
    cdc_text = read(physical / 'cdc_routed.rpt')
    cdc_rules = [{'id': a, 'severity': b, 'count': int(c), 'description': d.strip()}
                 for a,b,c,d in re.findall(r'^(CDC-\d+)\s+(\w+)\s+(\d+)\s+(.+)$', cdc_text, re.M)]
    reset_warning_rows = [l.strip() for l in cdc_text.splitlines() if re.match(r'\s*\d+\s+CDC-26\s', l)]
    skew_text = read(physical / 'bus_skew.rpt')
    skew_slacks = [float(x) for x in re.findall(r'Slack\s*\([A-Z]+\)\s*:\s*([-+.0-9]+)ns', skew_text)]
    require(skew_slacks, 'Bus-skew paths missing')
    route_text = read(physical / 'route_status.rpt')
    route = {name: int(field(r'# of ' + label + r'\.+\s*:\s*(\d+)', route_text)) for name, label in [
        ('logical_nets', 'logical nets'), ('routable_nets', 'routable nets'),
        ('fully_routed_nets', 'fully routed nets'), ('explicit_gap_nets', 'nets with explicit gaps'),
        ('routing_error_nets', 'nets with routing errors'), ('implicitly_routed_ports', 'implicitly routed ports')]}
    check = read(physical / 'check_timing.rpt')
    checks = {name: int(count) for name,count in re.findall(r'checking (\w+) \((\d+)\)', check)}
    require(len(checks) == 12, 'Expected all 12 check_timing categories')
    # Explicit exclusions must not be introduced while collecting negative results.
    constraints = read(physical / 'routed.xdc')
    broad_cuts = re.findall(r'^\s*(set_false_path|set_multicycle_path|set_clock_groups)\b.*$', constraints, re.M)
    require(not broad_cuts, 'Unexpected explicit false/multicycle/clock-group constraint')
    audit = version / 'audit'
    audit_log = read(version / 'vivado-audit.log')
    require('I1_SPINOR300_READ_ONLY_RESET_AUDIT_DONE registers=' in audit_log and not re.search(r'^ERROR:', audit_log, re.M), 'Read-only audit did not finish')
    for path in sorted(audit.iterdir()):
        artifacts['audit/' + path.name] = {'sha256': sha(record(path)), 'bytes': path.stat().st_size}
    record(version / 'spinor300_audit.tcl')
    resets = list(csv.DictReader(io.StringIO(read(audit / 'reset_registers.tsv')), delimiter='\t'))
    gap_names = read(audit / 'route_gap_names.txt').splitlines()
    require(len(gap_names) == route['explicit_gap_nets'], 'Route gap inspection count differs')
    ignored = read(physical / 'exceptions_ignored.rpt')
    overwritten = re.findall(r'Totally overridden path by DPO (\d+)', ignored)
    summary_text = read(physical / 'timing_routed.rpt')
    summary_part = summary_text[summary_text.index('| Design Timing Summary'):]
    number = r'[-+]?\d+(?:\.\d+)?'
    summary_values = field(r'^\s*(' + number + r'(?:\s+' + number + r'){11})\s*$', summary_part).split()
    overall = dict(zip(['setup_wns_ns','setup_tns_ns','setup_failing_endpoints','setup_total_endpoints',
                       'hold_whs_ns','hold_ths_ns','hold_failing_endpoints','hold_total_endpoints',
                       'pulse_width_slack_ns','pulse_width_total_slack_ns','pulse_width_failing_endpoints','pulse_width_total_endpoints'], map(float, summary_values)))
    modules = {n: critical(read(audit / (n + '_module_setup.rpt')))
               for n in ['cpu', 'spinor', 'boundary', 'mdu', 'icache', 'dcache']}
    live_changed = {n: sha(ROOT / n) for n,v in generation['source_sha256'].items()
                    if (n.startswith('src/main/') or n.startswith('integration/spinor/src/main/') or n.startswith('integration/spinor/overrides/')) and sha(ROOT / n) != v}
    baseline_path = WINDOWS / 'c-fix-20261104-r12/physical-summary.json'
    baseline = json.loads(read(baseline_path))
    require(sha(baseline_path) == 'a6a08a34c9bf80d8b9de37f1b15475a8faef66a5b14823caedea3a8569d598c7',
            'Selected R12 baseline receipt changed')
    resources = hierarchy(read(physical / 'utilization_hierarchical.rpt'))
    baseline_comparison = {'receipt': str(baseline_path), 'sha256': sha(baseline_path),
        'resources': {k:v for k,v in baseline['resources'].items() if k != 'hierarchy'},
        'setup_ns': baseline['internal_synchronous_timing']['setup_slack_ns'],
        'hold_ns': baseline['internal_synchronous_timing']['hold_slack_ns'],
        'integrated_total_delta': {k: resources['total'][k] - baseline['resources']['total'][k] for k in RESOURCES},
        'cpu_hierarchy_delta': {k: resources['cpu'][k] - baseline['resources']['cpu'][k] for k in RESOURCES}}
    batch_evidence = {}
    if generation.get('vivado_max_threads') == 8:
        require('VIVADO_THREADS 8' in log, 'Implementation thread limit was not logged as 8')
        require('VIVADO_THREADS 8' in read(version / 'vivado-synthesis.log'), 'Synthesis thread limit differs')
        for name, expected in generation['batch_gate_sha256'].items():
            require(sha(record(build / name)) == expected, 'Batch functional gate changed: ' + name)
        counts = list(csv.DictReader(io.StringIO(read(audit / 'counts.tsv')), delimiter='\t'))
        for row in counts:
            row['negative_endpoints'] = int(row['negative_endpoints'])
        for domain in ['cpu','vpu']:
            for kind in ['setup','hold']:
                paths = list(csv.DictReader(io.StringIO(read(audit / (domain + '_' + kind + '_negative.tsv'))), delimiter='\t'))
                require(len(paths) == next(x['negative_endpoints'] for x in counts if x['domain'] == domain and x['type'] == kind), 'Negative endpoint inventory differs')
        for domain in ['cpu','vpu']:
            # Report text rounds slack; the complete endpoint inventory decides closure.
            domains[domain]['closed_300mhz'] &= all(x['negative_endpoints'] == 0 for x in counts if x['domain'] == domain)
        previous_path = WINDOWS / generation.get('comparison_baseline', 'spinor-ppa-20261104-r2') / 'physical-summary.json'
        previous = json.loads(read(previous_path))
        batch_evidence = {'vivado_max_threads': 8, 'negative_endpoints': counts,
            'previous_combined': {'receipt': str(previous_path), 'sha256': sha(previous_path),
                'domains': previous['internal_domains'], 'resources': previous['resources']},
            'gate_sha256': generation['batch_gate_sha256'],
            'compiled_spinor_source_sha256': generation['compiled_spinor_source_sha256']}
    return {'status': 'COLLECTED_ROUTED_DUAL_CLOCK_PPA', 'scope': generation['scope'], 'part': generation['part'],
            'vivado_command': command, 'internal_domains': domains,
            'internal_300mhz_closed': all(d['closed_300mhz'] for d in domains.values()),
            'batch_evidence': batch_evidence,
            'board_qualified': False, 'resources': resources, 'r12_comparison': baseline_comparison,
            'module_endpoint_setup': modules,
            'cross_domain_timing': {d: critical(read(physical / (d + '_setup.rpt'))) for d in ['cpu_to_vpu','vpu_to_cpu']},
            'cdc': {'timed_endpoints': len(coverage),
                    'direction_counts': {d: sum(r['direction'] == d for r in coverage) for d in ['cpu_to_vpu','vpu_to_cpu']}, 'minimum_max_delay_slack_ns': cdc_slack,
                    'minimum_bus_skew_slack_ns': min(skew_slacks), 'scopes': scopes,
                    'rule_summary': cdc_rules, 'raw_reset_warning_rows': reset_warning_rows,
                    'reset_registers': resets, 'duplicate_max_delay_bounds_overridden_by_identical_refresh': len(overwritten),
                    'explicit_false_multicycle_clock_groups': broad_cuts,
                    'exception_scope': 'Scoped datapath-only max delay implicitly excludes hold only on those asynchronous paths. Same-clock synchronizer stages remain timed.',
                    'signoff': False},
            'route': {**route, 'explicit_gap_net_names': gap_names}, 'check_timing': checks,
            'whole_top_timing_summary': overall,
            'whole_top_timing_summary_report': str(physical / 'timing_routed.rpt'),
            'functional': {'receipt': str(functional_path), 'sha256': sha(functional_path), 'summary': functional['summary']},
            'provenance': {'functional_dependencies': len(generation['functional_dependency_match']), 'rtl_files': len(rtl),
                           'snapshot_sources': len(generation['source_sha256']), 'current_production_differences': live_changed,
                           'snapshot': str(snapshot), 'frozen_inputs_verified': True},
            'limits': ['OOC register-to-register characterization; external pads, cold reset and board clocking are not signed off.',
                       'Linear frequency estimates retain current paths/skew/uncertainty; they are not measured Fmax.',
                       'This directed functional program is not a vector IPC benchmark or complete H/V compliance.',
                       'R12 scalar capture fixture differs; integrated resource delta is not an isolated V flag cost.',
                       'No SoC fabric, CMU, peripheral, DDR controller, bitstream or board qualification.'],
            'artifacts': artifacts, 'inputs': inputs, 'collector_sha256': sha(Path(__file__))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision', default='20261104-r2')
    parser.add_argument('--variant', choices=['ppa','opt'], default='ppa')
    args = parser.parse_args()
    revision = args.revision
    prefix = 'spinor-' + args.variant
    require(re.fullmatch(r'\d{8}-r\d+', revision), 'Expected a dated revision')
    build = ROOT / ('build/i1-' + prefix + '-' + revision)
    version = WINDOWS / (prefix + '-' + revision)
    result = collect(build, version)
    encoded = json.dumps(result, indent=2) + '\n'
    for target in [build, version]:
        (target / 'physical-summary.json').write_text(encoded)
    print(json.dumps({k: result[k] for k in ['status', 'internal_domains', 'route', 'check_timing']}, indent=2))


if __name__ == '__main__':
    main()
