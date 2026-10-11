#!/usr/bin/env python3
"""Actual MAC boundary, independent-edge Icarus proof. No CAD or tool install.

Export with ip.TriSpeedManagedBoundaryCdcMain first. --prepare-only stages a
source-bound input packet and is never runtime proof. All normal and deliberate
negative cases use the same emitted production boundary and input hashes.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_logged(command, destination, timeout, cwd=None):
    """Use wait4 for this process's real RSS; no external time binary."""
    begin = time.monotonic()
    with destination.open('w') as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, cwd=cwd)
        timed_out = False
        while True:
            pid, status, usage = os.wait4(process.pid, os.WNOHANG)
            if pid:
                process.returncode = os.waitstatus_to_exitcode(status)
                break
            if time.monotonic()-begin > timeout and not timed_out:
                process.kill()
                timed_out = True
            time.sleep(0.05)
    return {'returncode': process.returncode, 'seconds': time.monotonic()-begin,
            'maxrss_kib': usage.ru_maxrss, 'user_seconds': usage.ru_utime,
            'system_seconds': usage.ru_stime, 'timed_out': timed_out}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('rtl', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--positive-only', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    here = Path(__file__).resolve().parent
    rtl, output = args.rtl.resolve(), args.output.resolve()
    if output.exists():
        parser.error('use a fresh result directory')
    files = sorted(rtl.glob('*.sv'))
    required = {'TriSpeedManagedBoundaryCdcTop', 'TriSpeedManagedGmac', 'EthernetMediaTransition',
                'EthernetPhysicalIngress', 'EthernetDmaFrameAdapter', 'GmiiFrameRx',
                'EthernetRxAdmissionStop', 'PeripheralClockControl', 'ManagedClockBuffer',
                'CdcMailbox', 'CdcDataFifo', 'CdcLevel', 'CdcCounterBank', 'PeripheralWakeDelay'}
    modules = set()
    for file in files:
        modules.update(re.findall(r'^\s*module\s+([A-Za-z_][A-Za-z0-9_$]*)', file.read_text(), re.M))
    if not required.issubset(modules):
        parser.error('missing actual production boundary: '+', '.join(sorted(required-modules)))
    if not {'GmiiFrameTx', 'QueuedGmiiFrameTx'} & modules:
        parser.error('missing production TX owner')
    if any(re.search(r'MachineCore|EthernetPacketDma|soc_top', m) for m in modules):
        parser.error('unexpected whole-SoC/DMA scope')
    extras = [here/'tests/mac_cdc_clock_model.sv', here/'tests/mac_boundary_cdc_tb.sv']
    inputs = [*files, *extras, Path(__file__).resolve()]
    sources = sorted((root/'src/main/scala').rglob('*.scala'))
    sources += [root/'src/test/scala/ip/TriSpeedManagedBoundaryCdc.scala', root/'build.mill']
    before = {str(p): sha(p) for p in inputs}
    source_hashes = {str(p.relative_to(root)): sha(p) for p in sources}
    tools = {name: shutil.which(name) for name in ('iverilog', 'vvp')}
    if not args.prepare_only and not all(tools.values()):
        parser.error('existing official Icarus/VVP required; no fallback simulator is allowed')
    output.mkdir(parents=True)
    for path in inputs:
        destination = output/'inputs'/('rtl' if path.is_relative_to(rtl) else 'fixture')/path.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
    report = {'status': 'PREPARED_NOT_RUN' if args.prepare_only else 'RUNNING',
              'scope': 'actual production MAC owner/CDC boundary; PHY discovery bypass and digital BUFGCE model',
              'input_sha256': before, 'source_sha256': source_hashes, 'modules': sorted(modules), 'tools': tools,
              'independent_clock_runtime_verified': False, 'negative_checks': {},
              'vendor_primitive_models': False, 'metastability_proven': False,
              'physical_constraints_verified': False, 'synthesis_run': False, 'route_run': False,
              'bit_generated': False, 'board_verified': False,
              'export_source_binding': 'requires paired exact-source export receipt', 'commands': []}
    started = time.monotonic()
    try:
        if not args.prepare_only:
            binary = output/'mac-boundary.vvp'
            command = [tools['iverilog'], '-g2012', '-s', 'mac_boundary_cdc_tb', '-o', str(binary),
                       *map(str, files+extras)]
            report['commands'].append(command)
            result = run_logged(command, output/'compile.log', 180)
            report['compile_resources'] = result
            if result['returncode']:
                raise RuntimeError('Icarus compile failed; see compile.log')
            report['binary_sha256'] = sha(binary)
            cases = [('positive', [], 'MAC_BOUNDARY_NATIVE_CDC_PASS')]
            if not args.positive_only:
                cases += [('negative-'+name, ['+bad_'+name], anchor) for name, anchor in (
                    ('payload', 'MAC_CDC_PAYLOAD_ORACLE'), ('event', 'MAC_CDC_TX_EVENT_ORACLE'),
                    ('drain', 'MAC_CDC_RX_STOP_OWNER_ORACLE'))]
            for label, flags, anchor in cases:
                command = [tools['vvp'], str(binary), '+tx_slots='+('2' if 'QueuedGmiiFrameTx' in modules else '1'), *flags]
                report['commands'].append(command)
                result = run_logged(command, output/(label+'.log'), 180)
                log = (output/(label+'.log')).read_text()
                if label=='positive':
                    if result['returncode'] or anchor not in log:
                        raise RuntimeError('positive failed: '+log[-3000:])
                    report['positive_resources'] = result
                    report['summary'] = [line for line in log.splitlines() if anchor in line]
                else:
                    if not result['returncode'] or anchor not in log or 'MAC_BOUNDARY_NATIVE_CDC_PASS' in log:
                        raise RuntimeError('negative failed to reject: '+label+': '+log[-1000:])
                    report['negative_checks'][label] = {'status': 'REJECTED', 'resources': result}
            report.update(status='PASS_NATIVE_MAC_BOUNDARY_ONLY', independent_clock_runtime_verified=True)
    except BaseException as error:
        report.update(status='FAILED', failure=str(error))
    finally:
        if before!={str(p):sha(p) for p in inputs} or source_hashes!={str(p.relative_to(root)):sha(p) for p in sources}:
            report.update(status='FAILED', failure='source/RTL/fixture input drift')
        report['elapsed_seconds'] = time.monotonic()-started
        report['output_sha256'] = {p.name:sha(p) for p in sorted(output.glob('*.log'))}
        (output/'receipt.json').write_text(json.dumps(report,indent=2)+'\n')
    print(report['status']+' receipt='+str(output/'receipt.json'))
    if report['status']=='FAILED':
        raise SystemExit(report['failure'])


if __name__=='__main__':
    main()
