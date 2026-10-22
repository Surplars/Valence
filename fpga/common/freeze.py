#!/usr/bin/env python3
"""Freeze an already populated package, requiring real emit/firmware/test/MIG inputs.

This does not compile, invent acceptance receipts, copy private candidates, or run FPGA tools.
All arguments except --root are portable paths relative to that native-copy package root.
"""
import argparse
import json
from pathlib import Path
import sys
import board_inputs
import manifest as gate


def freeze(a):
    root = a.root.absolute(); gate.no_links(root)
    destination = root / 'manifest.json'
    gate.require(not destination.exists() and not (root / 'board-generated').exists(), 'fresh package manifest/filelists required')
    for value in (a.emission, a.rom, a.coe, a.firmware_contract, a.functional_receipt, a.mig):
        gate.file_at(root, value)
    emission = gate.read(root / a.emission)
    gate.require(emission.get('cpu') in ('i1', 'a1'), 'actual selected CPU emission required')
    profile = emission.get('clockProfile', 'production')
    clocks = gate.reviewed_board_clocks(emission['cpu'], profile)
    cpu = emission['cpu']; base = gate.relative(a.emission).parent
    artifacts = emission.get('artifacts', {})
    tops = [p for p in artifacts if p.endswith('/CommonMachinePlatform.sv')]
    gate.require(len(tops) == 1, 'unique common emission top required')
    prefix = tops[0][:-len('CommonMachinePlatform.sv')]
    emitted = [(base / p[len(prefix):]).as_posix() for p in artifacts if p.startswith(prefix)]
    gate.require(len(emitted) == len(artifacts), 'emission artifact escaped output root')
    for path in emitted: gate.file_at(root, path)
    # Assertions remain in normal emitted RTL; layer bind files are simulation
    # auxiliaries, not duplicated top-level synthesis sources.
    rtl = [p for p in emitted if p.endswith(('.v', '.sv')) and '/verification/' not in p]
    rtl += list(board_inputs.BOARD_RTL)
    gate.require(len(rtl) == len(set(rtl)), 'duplicate emitted/resource RTL; resolve source owner before freezing')
    sim = [(base / 'TriSpeedRgmiiTx.sv').as_posix(), *board_inputs.SIM_RTL]
    for path in [*rtl, *sim, *board_inputs.PUBLIC_INPUTS]: gate.file_at(root, path)
    config = dict(cpu=cpu, top='soc_top_common_ddr', part='xczu15eg-ffvb1156-2-i', abi=1,
                  interrupt_abi='aia', rom_base=0x80000000, rom_bytes=131072,
                  clocks_hz=clocks,
                  features=dict(mac=True, network_dma=True))
    if profile != 'production': config['clock_profile'] = profile
    roles = dict(rtl_filelist='board-generated/rtl.f', simulation_filelist='board-generated/sim.f',
                 emission_profile=a.emission, firmware_contract=a.firmware_contract,
                 functional_receipt=a.functional_receipt, rom=a.rom, rom_coe=a.coe,
                 board_audit_script='fpga/common/board_audit.tcl',
                 post_synth_constraints='fpga/common/post_synth.tcl', post_opt_constraints='fpga/common/post_opt.tcl',
                 media_scenarios='fpga/common/media_scenarios.tcl',
                 constraints=['fpga/common/board_pins.xdc', 'fpga/zu15eg/pl_ddr4_pins.xdc'], ip=[a.mig])
    m = dict(schema=gate.SCHEMA, configuration=config, threads=a.threads, source_roots=list(gate.ROOTS),
             producer=dict(schema='common-board-producer-v1', simulation_suite='common-physical-boundaries-v1', media_rates_mbps=[10, 100, 1000]),
             roles=roles, stages={
                 'simulation': dict(script='fpga/common/simulate.tcl', outputs=['smoke-result.txt', 'jtag_upstream-run.log', 'jtag_downstream-run.log', 'jtag_bad64-run.log', 'quarter-run.log', 'dci-run.log', 'dci_short-run.log', 'xelab-invocations.txt', 'xsim-invocations.txt']),
                 'synthesis': dict(script='fpga/common/synthesize.tcl', outputs=['synthesized.dcp', 'utilization.rpt', 'bus-skew-scope.json', 'ip-synthesis.json', 'clock-output-checks.txt', 'generated-clocks.rpt']),
                 'implementation': dict(script='fpga/common/implement.tcl', outputs=['routed.dcp', 'utilization.rpt', 'bus-skew-scope.json'])},
             signoff=dict(bus_skew_checks='mapped-scope', clock_pins=dict(cpu='u_soc/cpuClock', fabric='u_soc/fabricClock',
                 timebase='u_soc/timebaseClock' if profile in ('boot50-static', 'performance300-static', 'boot50-dynamic') else 'u_soc/fabricClock', ddr_ui='u_ddr/c0_ddr4_ui_clk', uart='u_soc/rawUartClock', aon='u_soc/alwaysOnClock')))
    files = set(emitted + rtl + sim + list(board_inputs.PUBLIC_INPUTS))
    for value in roles.values(): files.update(value if isinstance(value, list) else [value])
    files.update(gate.firmware_inputs(root, gate.read(root / a.firmware_contract)))
    for name in gate.ROOTS:
        directory = root / name
        gate.require(directory.is_dir(), 'missing complete source root: ' + name)
        files.update(p.relative_to(root).as_posix() for p in directory.rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    files -= {'board-generated/rtl.f', 'board-generated/sim.f'}
    m['inputs'] = {p: gate.sha(gate.file_at(root, p)) for p in sorted(files)}
    # Refuse stale/missing functional identity before writing any manifest.
    receipt = gate.read(root / a.functional_receipt)
    gate.require(receipt.get('profile_sha256') == gate.configuration(config),
                 'functional receipt profile differs; do not manufacture acceptance (expected profile ' + gate.configuration(config) + ')')
    (root / 'board-generated').mkdir()
    for name, lines in [('rtl.f', rtl), ('sim.f', sim)]:
        path = root / 'board-generated' / name
        path.write_text('\n'.join(lines) + '\n')
        m['inputs'][path.relative_to(root).as_posix()] = gate.sha(path)
    destination.write_text(json.dumps(m, indent=2) + '\n')
    gate.preflight(destination)
    return destination


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', required=True, type=Path)
    for name in ('emission', 'rom', 'coe', 'firmware-contract', 'functional-receipt', 'mig'):
        p.add_argument('--' + name, required=True)
    p.add_argument('--threads', type=int, default=8)
    a = p.parse_args()
    try:
        print(freeze(a))
    except (ValueError, KeyError, TypeError, OSError) as e:
        print('COMMON_FREEZE_BLOCKED: ' + str(e), file=sys.stderr)
        sys.exit(1)
