#!/usr/bin/env python3
"""Small native independent-clock acceptance for TileLinkClockDomainBoundary.

This follows the existing native MAC CDC exception, not a new general hardware
simulation flow. GSIM remains the supported project hardware flow. Export fresh
RTL with ip.TileLinkClockDomainBoundaryMain first. No build, install, DUT rewrite,
whole-SoC simulation, physical qualification, or fallback simulator is performed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import time


PASS = 'TILELINK_BOUNDARY_NATIVE_CDC_PASS'
FLOOR = 4 * 1024**3


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_logged(command, destination, timeout=90):
    started = time.monotonic()
    with destination.open('w') as log:
        minimum_free = disk_guard(destination.parent)
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        timed_out = False
        disk_floor_breached = False
        terminated = False
        while True:
            free = shutil.disk_usage(destination.parent).free
            minimum_free = min(minimum_free, free)
            disk_floor_breached = disk_floor_breached or free < FLOOR
            pid, status, usage = os.wait4(process.pid, os.WNOHANG)
            if pid:
                process.returncode = os.waitstatus_to_exitcode(status)
                break
            timed_out = timed_out or time.monotonic() - started > timeout
            if (timed_out or disk_floor_breached) and not terminated:
                # Kill the entire compiler/simulator tree, preserving its log.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                terminated = True
            time.sleep(0.02)
    return {'returncode': process.returncode, 'seconds': time.monotonic() - started,
            'maxrss_kib': usage.ru_maxrss, 'timed_out': timed_out,
            'disk_floor_breached': disk_floor_breached,
            'minimum_free_bytes': minimum_free,
            'process_group_killed': terminated}


def disk_guard(path):
    free = shutil.disk_usage(path).free
    if free < FLOOR:
        raise RuntimeError(f'4 GiB free-space floor reached: {free} bytes free')
    return free


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('rtl', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--iverilog', default=os.environ.get('IVERILOG', 'iverilog'))
    parser.add_argument('--vvp', default=os.environ.get('VVP', 'vvp'))
    parser.add_argument('--storage', choices=('baseline', 'held'), default='baseline')
    parser.add_argument('--baseline-receipt', type=Path,
                        help='read-only earlier baseline receipt; never rerun or rewrite it')
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    root = here.parents[1]
    rtl, output = args.rtl.resolve(), args.output.resolve()
    held = args.storage == 'held'
    depth = 16 if held else 4
    fifo = 'HeldResponseCdcDataFifo' if held else 'CdcDataFifo'
    profile_flags = [f'+fifo_depth={depth}', f'+held_response={int(held)}']
    baseline_path = args.baseline_receipt.resolve() if args.baseline_receipt else None
    baseline = json.loads(baseline_path.read_text()) if baseline_path else None
    if baseline is not None:
        if (baseline.get('status') != 'PASS_NATIVE_TILELINK_COMPONENT_ONLY' or
                'CdcDataFifo' not in baseline.get('modules', []) or
                'HeldResponseCdcDataFifo' in baseline.get('modules', [])):
            parser.error('comparison requires an existing successful baseline component receipt')
    if output.exists():
        parser.error('use a fresh output directory; existing evidence is never overwritten')
    if not output.parent.is_dir():
        parser.error('output parent must already exist')
    files = sorted(rtl.glob('*.sv'))
    modules = set()
    for file in files:
        content = file.read_text()
        modules.update(re.findall(r'^\s*module\s+(\w+)', content, re.M))
        if 'automatic logic' in content:
            parser.error('export with --lowering-options=disallowLocalVariables; no simulation rewrite is allowed')
    required = {'TileLinkClockDomainBoundary', fifo, 'CdcLevel', 'CdcResetRelease'}
    if not required.issubset(modules):
        parser.error('missing production component: ' + ', '.join(sorted(required - modules)))
    if any(not re.fullmatch(rf'TileLinkClockDomainBoundary|{fifo}(?:_\d+)?|CdcLevel|CdcResetRelease|storage_{depth}x(?:1|79|141|149)', m) for m in modules):
        parser.error('unexpected modules outside the selected five-channel storage/depth profile')
    top = (rtl/'TileLinkClockDomainBoundary.sv').read_text()
    if len(re.findall(rf'^\s*{fifo}(?:_\d+)?\s+\w+\s*\(', top, re.M)) != 5:
        parser.error('selected storage must provide exactly five independent FIFO instances')
    assertion_messages = (
        'Pending RAM response must retain source-visible slot ownership',
        'Stalled response must re-read its still-owned RAM address')
    external_binds = [str(p.relative_to(rtl)) for p in rtl.rglob('*.sv')
                      if re.search(r'^\s*bind\b', p.read_text(), re.M)]
    external_assertions = [str(p.relative_to(rtl)) for p in rtl.rglob('*.sv')
                           if p.parent != rtl and re.search(r'\$fatal\b|\bassert\s*\(', p.read_text())]
    if external_binds or external_assertions:
        parser.error('verification must be inline in root RTL; external bind/assertion layers would be omitted')
    root_assertions = {}
    if held:
        for path in files:
            if re.fullmatch(r'HeldResponseCdcDataFifo(?:_\d+)?', path.stem):
                content = path.read_text()
                count = len(re.findall(r'\$fatal\b', content))
                if count != 2 or not all(message in content for message in assertion_messages):
                    parser.error('both production assertions must be inline: '+path.name)
                root_assertions[path.stem] = {'fatal_sites': count, 'source_file': path.name}
        if not root_assertions:
            parser.error('no inline production FIFO assertions found')
    tools = {name: shutil.which(value) for name, value in (('iverilog', args.iverilog), ('vvp', args.vvp))}
    if not all(tools.values()):
        parser.error('existing explicit Icarus/VVP tools are required; no installation/fallback')
    fixtures = [here/'tilelink_boundary_tb.sv', Path(__file__).resolve()]
    sources = [root/name for name in (
        'src/main/scala/ip/tilelink/TileLinkClockDomainBoundary.scala',
        'src/main/scala/ip/bus/CdcDataChannels.scala',
        'src/main/scala/ip/bus/ClockDomainCrossing.scala',
        'src/main/scala/bus/tilelink/TileLink.scala',
        'src/test/scala/ip/TileLinkClockDomainBoundaryMain.scala')]
    if held:
        sources.append(root/'src/main/scala/ip/bus/HeldResponseCdcDataFifo.scala')
    inputs = files + fixtures + ([baseline_path] if baseline_path else [])
    hashes = {str(p): sha(p) for p in inputs}
    source_hashes = {str(p.relative_to(root)): sha(p) for p in sources}
    free_before = disk_guard(output.parent)
    output.mkdir()
    for directory, paths in (('rtl', files), ('fixture', fixtures), ('source', sources)):
        for path in paths:
            relative = path.relative_to(root) if directory == 'source' else path.name
            target = output/'inputs'/directory/relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    if baseline_path:
        (output/'inputs'/'baseline').mkdir()
        shutil.copy2(baseline_path, output/'inputs'/'baseline'/'receipt.json')
    report = {
        'storage_profile': args.storage, 'ram_depth_per_lane': depth,
        'logical_payload_ram_bits': 519 * depth,
        'protocol_owner_count': 8,
        'status': 'RUNNING',
        'scope': 'production five-channel CPU/fabric CDC component digital transport only',
        'simulator_scope': 'existing native independent-edge CDC exception; project GSIM flow unchanged',
        'input_sha256': hashes, 'source_sha256': source_hashes,
        'source_binding': 'exact input/source snapshot; pair with the central compile/export receipt',
        'modules': sorted(modules), 'tools': tools,
        'tool_sha256': {name: sha(Path(path)) for name, path in tools.items()},
        'free_before_bytes': free_before, 'disk_floor_bytes': FLOOR,
        'claims': {'independent_clock_runtime_verified': False,
                   'cold_reset_both_endpoints_only': True,
                   'per_channel_payload_hold_order_and_bit_coverage': False,
                   'global_transaction_drain': False, 'single_sided_hot_reset': False,
                   'clock_gating': False, 'soc_attachment_or_boot': False,
                   'physical_cdc_or_timing': False, 'metastability': False,
                   'synthesis_route_or_board': False, 'internal_assertions_enabled': False, 'ii_one': False,
                   'all_lanes_preloaded_ii_one_window': False},
        'internal_assertions': {'required_for_profile': held,
                                'root_module_evidence': root_assertions,
                                'external_bind_files': external_binds,
                                'external_assertion_files': external_assertions,
                                'preprocessed_module_evidence': {},
                                'assertion_instances': 10 if held else 0},
        'commands': [], 'process_resources': [], 'positive_cases': {}, 'negative_oracle_checks': {}}
    if baseline_path:
        report['baseline_comparison'] = {
            'receipt': str(baseline_path), 'receipt_sha256': sha(baseline_path),
            'baseline_ram_depth': 4, 'candidate_ram_depth': depth,
            'baseline_logical_payload_ram_bits': 519 * 4,
            'candidate_logical_payload_ram_bits': 519 * depth,
            'baseline_owner_count': 8, 'candidate_owner_count': 8,
            'baseline_exact_blocked_capacity': None,
            'baseline_blocked_capacity_evidence': 'old test required at least four accepted beats per blocked lane; exact count was not logged',
            'baseline_latency': None,
            'latency_comparison': 'baseline latency was not measured; no numerical delta claimed',
            'interpretation': 'storage depth and FIFO pipeline both change; capacity increase is not attributed to pipeline throughput, and rates are not a matched-depth area/performance result',
            'matched_clock_rates': {}}
    started = time.monotonic()
    try:
        binary = output/'tilelink-boundary.vvp'
        # Use the same assertion-enabling defines for preprocessing and compile.
        # Official Icarus preprocessing verifies no conditional/bind layer hides
        # the production assertions; generated RTL itself remains untouched.
        compile_flags = ['-g2012', '-DSTOP_COND=1', '-DASSERT_VERBOSE_COND=1']
        if held:
            preprocessed = output/'production-preprocessed.sv'
            command = [tools['iverilog'], *compile_flags, '-E', '-o', str(preprocessed), *map(str, files)]
            report['commands'].append(command)
            result = run_logged(command, output/'preprocess.log')
            report['process_resources'].append({'label': 'preprocess', **result})
            if result['returncode'] or result['timed_out'] or result['disk_floor_breached']:
                raise RuntimeError('assertion preprocessing failed; see preprocess.log')
            preprocessed_text = preprocessed.read_text()
            module_texts = dict(re.findall(r'\bmodule\s+(\w+)\b(.*?)\bendmodule\b', preprocessed_text, re.S))
            for name in root_assertions:
                body = module_texts.get(name, '')
                count = len(re.findall(r'\$fatal\b', body))
                if count != 2 or not all(message in body for message in assertion_messages):
                    raise RuntimeError('production assertions disabled or missing after preprocessing: '+name)
                report['internal_assertions']['preprocessed_module_evidence'][name] = {'fatal_sites': count}
            if re.search(r'^\s*bind\b', preprocessed_text, re.M):
                raise RuntimeError('unexpected bind remains after preprocessing')
            report['internal_assertions']['preprocessed_sha256'] = sha(preprocessed)
            report['internal_assertions']['assertion_gate_defines'] = ['STOP_COND=1', 'ASSERT_VERBOSE_COND=1']
        command = [tools['iverilog'], *compile_flags, '-s', 'tilelink_boundary_tb', '-o', str(binary),
                   *map(str, files), str(fixtures[0])]
        report['commands'].append(command)
        report['compile_resources'] = run_logged(command, output/'compile.log')
        report['process_resources'].append({'label': 'compile', **report['compile_resources']})
        if (report['compile_resources']['returncode'] or report['compile_resources']['timed_out']
                or report['compile_resources']['disk_floor_breached']):
            raise RuntimeError('Icarus compile failed; see compile.log')
        report['binary_sha256'] = sha(binary)
        ratios = [('cpu-fast', 3, 7, 1300), ('fabric-fast', 11, 2, 2700), ('near-ratio', 7, 5, 900)]
        for name, cpu, fabric, phase in ratios:
            disk_guard(output)
            command = [tools['vvp'], str(binary), f'+cpu_half={cpu}',
                       f'+fabric_half={fabric}', f'+phase_ps={phase}', *profile_flags]
            report['commands'].append(command)
            result = run_logged(command, output/(name+'.log'))
            report['process_resources'].append({'label': name, **result})
            if result['timed_out'] or result['disk_floor_breached']:
                raise RuntimeError(name+' stopped by runtime or disk guard')
            log = (output/(name+'.log')).read_text()
            if result['returncode'] or PASS not in log:
                raise RuntimeError(name+' failed: '+log[-3000:])
            measurements = {}
            for key, prefix in (('rates', 'TL_CDC_RATE '), ('capacity', 'TL_CDC_CAPACITY '),
                                ('latency', 'TL_CDC_LATENCY '), ('local_rates', 'TL_CDC_LOCAL_RATE ')):
                values_by_channel = []
                for line in log.splitlines():
                    if line.startswith(prefix):
                        values = dict(re.findall(r'(\w+)=([\d.]+)', line))
                        values_by_channel.append({k: float(v) if '.' in v else int(v) for k, v in values.items()})
                measurements[key] = values_by_channel
                required_count = 5 if key != 'local_rates' or held else 0
                if len(values_by_channel) != required_count:
                    raise RuntimeError('missing per-channel '+key+': '+name)
            if held:
                for value in measurements['rates']:
                    if value['source_half_ns'] < value['destination_half_ns'] and value['destination_cycles'] != 96:
                        raise RuntimeError('supplied held-response direction did not sustain II=1: '+name)
                if any(v['destination_cycles'] != 12 or v['measured_gaps'] != 12 for v in measurements['local_rates']):
                    raise RuntimeError('preloaded local II=1 window missing: '+name)
            report['positive_cases'][name] = {
                'resources': result, 'cpu_half_ns': cpu, 'fabric_half_ns': fabric, 'phase_ps': phase,
                **measurements,
                'summary': [line for line in log.splitlines() if line.startswith('TL_CDC_') or PASS in line]}
            if baseline_path:
                old_case = baseline['positive_cases'][name]
                if (old_case['cpu_half_ns'], old_case['fabric_half_ns'], old_case['phase_ps']) != (cpu, fabric, phase):
                    raise RuntimeError('baseline clock/phase mismatch: '+name)
                old_rates = {v['channel']: v for v in old_case['rates']}
                report['baseline_comparison']['matched_clock_rates'][name] = [
                    {'channel': v['channel'],
                     'baseline_beats_per_destination_cycle': old_rates[v['channel']]['beats_per_destination_cycle'],
                     'candidate_beats_per_destination_cycle': v['beats_per_destination_cycle'],
                     'candidate_capacity': measurements['capacity'][v['channel']]['accepted_while_blocked'],
                     'candidate_latency_ns': measurements['latency'][v['channel']]['accept_to_delivery_ns']}
                    for v in measurements['rates']]
        for name, anchor in [('payload', 'TL_CDC_PAYLOAD_ORACLE channel=0'),
                             ('source', 'TL_CDC_PAYLOAD_ORACLE channel=3'),
                             ('sink', 'TL_CDC_PAYLOAD_ORACLE channel=4'),
                             ('empty', 'TL_CDC_EMPTY_NOT_OWNER_DRAIN_ORACLE')]:
            disk_guard(output)
            command = [tools['vvp'], str(binary), '+bad_'+name, *profile_flags]
            report['commands'].append(command)
            result = run_logged(command, output/('negative-'+name+'.log'))
            report['process_resources'].append({'label': 'negative-'+name, **result})
            if result['timed_out'] or result['disk_floor_breached']:
                raise RuntimeError('negative-'+name+' stopped by runtime or disk guard')
            log = (output/('negative-'+name+'.log')).read_text()
            if result['returncode'] == 0 or anchor not in log or PASS in log:
                raise RuntimeError('oracle perturbation was not rejected: '+name)
            report['negative_oracle_checks'][name] = {
                'status': 'REJECTED', 'kind': 'test-only observed payload/metadata or invalid drain interpretation perturbation; RTL unchanged',
                'expected_anchor': anchor, 'resources': result}
        report['status'] = 'PASS_NATIVE_TILELINK_COMPONENT_ONLY'
        report['claims']['independent_clock_runtime_verified'] = True
        report['claims']['per_channel_payload_hold_order_and_bit_coverage'] = True
        report['claims']['internal_assertions_enabled'] = held
        report['claims']['ii_one'] = held
        report['claims']['all_lanes_preloaded_ii_one_window'] = held
    except BaseException as error:
        report.update(status='FAILED', failure=str(error))
    finally:
        if hashes != {str(p): sha(p) for p in inputs} or source_hashes != {str(p.relative_to(root)): sha(p) for p in sources}:
            report.update(status='FAILED', failure='source, RTL, or fixture changed during acceptance')
        report['free_after_bytes'] = shutil.disk_usage(output).free
        report['minimum_free_bytes'] = min([free_before, report['free_after_bytes']] +
                                          [r['minimum_free_bytes'] for r in report['process_resources']])
        report['elapsed_seconds'] = time.monotonic() - started
        report['output_log_sha256'] = {p.name: sha(p) for p in sorted(output.glob('*.log'))}
        (output/'receipt.json').write_text(json.dumps(report, indent=2)+'\n')
    print(report['status']+' receipt='+str(output/'receipt.json'))
    if report['status'] == 'FAILED':
        raise SystemExit(report['failure'])


if __name__ == '__main__':
    main()
