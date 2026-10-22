#!/usr/bin/env python3
"""Native real Ethernet packet-chain/runtime admission proof, NOT full-system ACK.

Fresh production RX/CRC, RX-stop CDC, native frame bridges, adapter, packet DMA,
TX/CRC, and network epoch sequencer. Independent fabric/RX/TX clocks. Register
memory and prepare/AON terminal-consumed/retirement endpoints are explicit test
models. No CPU, Home, DDR, RGMII encoder, full MAC register plane, clock gating,
DRP, physical CDC or board claim. No Mill, RTL rewriting or simulator fallback.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import time
from test_runtime_epoch_boundary import sha, guard, run, tool_chain, FLOOR

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PASS = 'NETWORK_PACKET_RUNTIME_PASS'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('rtl', type=Path)
    p.add_argument('output', type=Path)
    p.add_argument('--iverilog', default=os.environ.get('IVERILOG', 'iverilog'))
    p.add_argument('--vvp', default=os.environ.get('VVP', 'vvp'))
    p.add_argument('--timeout', type=int, default=90)
    p.add_argument('--emission-receipt', type=Path, required=True)
    a = p.parse_args()
    rtl, out = a.rtl.resolve(), a.output.resolve()
    if out.exists() or not out.parent.is_dir():
        p.error('fresh output directory with existing parent required')
    tools = {name: shutil.which(value) for name, value in [('iverilog', a.iverilog), ('vvp', a.vvp)]}
    if not all(tools.values()):
        p.error('existing native Icarus and VVP required')
    files = sorted(rtl.glob('*.sv'))
    modules = set()
    for f in files:
        text = f.read_text()
        modules.update(re.findall(r'^\s*module\s+(\w+)', text, re.M))
        if 'automatic logic' in text or re.search(r'^\s*bind\b', text, re.M):
            p.error('fresh inline-assertion/disallowLocalVariables emission required; no DUT rewrite')
    required = {'CommonNetworkPacketRuntimeFixture', 'CommonNetworkRuntimeSequencer',
                'EthernetPacketDma', 'EthernetTxDescriptorQueue', 'GmiiFrameRx', 'GmiiFrameTx',
                'EthernetFrameClockBridge', 'EthernetRxAdmissionStop', 'EthernetDmaFrameAdapter',
                'CdcLevel', 'CdcResetRelease', 'CdcMailbox', 'CdcDataFifo'}
    if not required <= modules:
        p.error('missing real production modules: '+str(sorted(required-modules)))
    emission = json.loads(a.emission_receipt.read_text())
    if emission.get('status') != 'PASS_EMIT_ONLY':
        p.error('passing coordinated emission receipt required')
    emitted_sources = emission.get('source_sha256', {})
    emitted_rtl = emission.get('rtl_sha256', {})
    if not emitted_sources or not emitted_rtl:
        p.error('emission receipt must bind source and RTL hashes')
    for name, digest in emitted_sources.items():
        path = Path(name) if Path(name).is_absolute() else ROOT/name
        if not path.is_file() or sha(path) != digest:
            p.error('emitted source drift: '+name)
    if {f.name: sha(f) for f in files} != emitted_rtl:
        p.error('emitted RTL inventory/content drift')
    production = {str(f.relative_to(ROOT)) for f in (ROOT/'src/main/scala').rglob('*.scala')}
    emitter = 'src/test/scala/platform/CommonNetworkPacketRuntimeMain.scala'
    emitted_names = {str(Path(n).relative_to(ROOT)) if Path(n).is_absolute() else n for n in emitted_sources}
    if not (production | {emitter}) <= emitted_names:
        p.error('emission source inventory omits production or packet fixture')
    fixture = HERE/'network_packet_runtime_tb.sv'
    sources = sorted(set([ROOT/n for n in production | {emitter}] + [fixture, Path(__file__).resolve(),
        HERE/'test_runtime_epoch_boundary.py'] + [Path(n) if Path(n).is_absolute() else ROOT/n for n in emitted_sources]))
    inputs = files + [fixture, a.emission_receipt.resolve()]
    input_hashes = {str(f): sha(f) for f in inputs}
    source_hashes = {str(f.relative_to(ROOT)): sha(f) for f in sources}
    chain = tool_chain(tools)
    tool_hashes = {n: sha(f) for n, f in chain.items()}
    guard(out.parent)
    out.mkdir()
    for directory, paths in [('rtl', files), ('source', sources)]:
        for f in paths:
            relative = f.relative_to(ROOT) if directory == 'source' else f.name
            dest = out/'inputs'/directory/relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dest)
    shutil.copy2(a.emission_receipt, out/'inputs'/'emission-receipt.json')
    receipt = dict(status='RUNNING', scope=__doc__, real_packet_chain=True,
        real_epoch_sequencer=True, modeled_memory=True, modeled_prepare_terminal_receipts=True,
        real_cpu=False, real_home=False, real_ddr=False, real_rgmii_encoder=False,
        real_aon_terminal=False, full_system_ack=False, physical_cdc_qualified=False,
        clock_gating_qualified=False, drp_qualified=False, board_qualified=False,
        modules=sorted(modules), source_sha256=source_hashes, input_sha256=input_hashes,
        tools=chain, tool_sha256=tool_hashes, disk_floor_bytes=FLOOR,
        emission_receipt=str(a.emission_receipt.resolve()), commands=[], resources=[],
        positive_cases={}, negative_oracle_checks={})
    started = time.monotonic()
    binary = out/'network-packet-runtime.vvp'
    try:
        flags = ['-g2012', '-DSTOP_COND=1', '-DASSERT_VERBOSE_COND=1']
        preprocessed = out/'production-preprocessed.sv'
        commands = [('preprocess', [tools['iverilog'], *flags, '-E', '-o', str(preprocessed), *map(str, files)]),
                    ('compile', [tools['iverilog'], *flags, '-s', 'network_packet_runtime_tb', '-o', str(binary),
                                 *map(str, files), str(fixture)])]
        for label, command in commands:
            receipt['commands'].append(command)
            result = run(command, out/(label+'.log'), a.timeout)
            receipt['resources'].append(dict(label=label, **result))
            if result['returncode'] or result['timed_out'] or result['disk_floor_breached']:
                raise RuntimeError(label+' failed: '+(out/(label+'.log')).read_text()[-5000:])
            if label == 'preprocess':
                text = preprocessed.read_text()
                assertions = ['network runtime prepare changed before actual acceptance',
                              'network epoch retired before actual admission release',
                              'RX stop acknowledgement cannot precede native frame and FIFO drain']
                if not all(message in text for message in assertions) or not re.search(r'\$fatal\b', text):
                    raise RuntimeError('required production assertions not enabled')
                receipt['production_assertions'] = dict(inline_fatal_sites=len(re.findall(r'\$fatal\b', text)),
                    preprocessed_sha256=sha(preprocessed), definitions=flags[1:])
        receipt['compiled_sha256'] = sha(binary)
        ratios = [('rx-fast', 5, 3, 7, 1300), ('fabric-fast', 2, 7, 11, 2700),
                  ('tx-fast', 11, 7, 2, 900), ('near-ratio', 7, 11, 5, 1700)]
        cases = [(0, 'rx-status-memory-owners'), (1, 'tx-prefetch-control-data-wire'),
                 (2, 'posted-pending-completion-preservation'), (3, 'coordinated-reset-discards-active-epoch')]
        for ratio, fabric, rx, tx, phase in ratios:
            for case, name in cases:
                label = ratio+'-'+name
                command = [tools['vvp'], str(binary), f'+case={case}', f'+fabric_half={fabric}',
                           f'+rx_half={rx}', f'+tx_half={tx}', f'+phase_ps={phase}']
                receipt['commands'].append(command)
                log = out/(label+'.log')
                result = run(command, log, a.timeout)
                receipt['resources'].append(dict(label=label, **result))
                content = log.read_text()
                if result['returncode'] or result['timed_out'] or result['disk_floor_breached'] or PASS not in content:
                    raise RuntimeError(label+' failed: '+content[-5000:])
                receipt['positive_cases'][label] = dict(fabric_half_ns=fabric, rx_half_ns=rx,
                    tx_half_ns=tx, phase_ps=phase, events=[s for s in content.splitlines() if s.startswith('PACKET_')],
                    log_sha256=sha(log))
        for fault, case, marker in [(1, 1, 'PACKET_ORACLE_PAYLOAD'), (2, 0, 'PACKET_ORACLE_DRAIN'),
                                    (3, 0, 'PACKET_ORACLE_PAYLOAD')]:
            label = 'negative-'+str(fault)
            command = [tools['vvp'], str(binary), f'+case={case}', f'+negative={fault}']
            receipt['commands'].append(command)
            log = out/(label+'.log')
            result = run(command, log, a.timeout)
            receipt['resources'].append(dict(label=label, **result))
            content = log.read_text()
            if result['returncode'] == 0 or result['timed_out'] or result['disk_floor_breached'] or marker not in content or PASS in content:
                raise RuntimeError('negative oracle failed wrong check: '+label+' '+content[-3000:])
            receipt['negative_oracle_checks'][label] = dict(expected_failure=marker,
                mutation='test oracle only; production RTL is unchanged', log_sha256=sha(log))
        receipt['status'] = 'PASS_NATIVE_REAL_NETWORK_PACKET_CHAIN_SCOPED'
    except BaseException as error:
        receipt.update(status='FAILED', failure=str(error))
        raise
    finally:
        receipt['seconds'] = time.monotonic()-started
        receipt['source_sha256_after'] = {str(f.relative_to(ROOT)): sha(f) for f in sources}
        receipt['input_sha256_after'] = {str(f): sha(f) for f in inputs}
        receipt['tool_sha256_after'] = {n: sha(f) for n, f in chain.items()}
        receipt['compiled_sha256_after'] = sha(binary) if binary.exists() else None
        receipt['production_inventory_unchanged'] = production == {str(f.relative_to(ROOT)) for f in (ROOT/'src/main/scala').rglob('*.scala')}
        receipt['rtl_inventory_unchanged'] = sorted(f.name for f in files) == sorted(f.name for f in rtl.glob('*.sv'))
        if not receipt['production_inventory_unchanged'] or not receipt['rtl_inventory_unchanged']:
            receipt['status'] = 'FAILED_INPUT_INVENTORY_DRIFT'
        if source_hashes != receipt['source_sha256_after'] or input_hashes != receipt['input_sha256_after'] or tool_hashes != receipt['tool_sha256_after']:
            receipt['status'] = 'FAILED_INPUT_DRIFT'
        (out/'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
    if receipt['status'] != 'PASS_NATIVE_REAL_NETWORK_PACKET_CHAIN_SCOPED':
        raise RuntimeError(receipt['status'])
    print(receipt['status'])


if __name__ == '__main__':
    main()
