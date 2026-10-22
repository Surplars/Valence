#!/usr/bin/env python3
"""Fixed MAC serial adapter and actual CDC at independent clocks, with modeled MAC endpoints.

Fixture drives producer-closed witnesses, not actual CPU/DMA/Home or AON terminal.
No whole-system gate ACK, line-rate, physical timing, DRP or platform DFS claim.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
from test_runtime_epoch_boundary import sha, guard, run, tool_chain

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('rtl', type=Path)
    p.add_argument('output', type=Path)
    p.add_argument('--emission-receipt', type=Path, required=True)
    p.add_argument('--iverilog', required=True)
    p.add_argument('--vvp', required=True)
    p.add_argument('--timeout', type=int, default=120)
    p.add_argument('--single', action='store_true')
    a = p.parse_args()
    rtl, out = a.rtl.resolve(), a.output.resolve()
    if out.exists() or not out.parent.is_dir():
        p.error('fresh output with existing parent required')
    emission = json.loads(a.emission_receipt.read_text())
    if emission['status'] != 'PASS_EMIT_ONLY':
        p.error('source-bound passing emission required')
    emitted_sources = emission['source_sha256']
    for name, digest in emitted_sources.items():
        if sha(ROOT / name) != digest:
            p.error('source drift: ' + name)
    files = sorted(rtl.glob('*.sv'))
    if {f.name: sha(f) for f in files} != emission['rtl_sha256']:
        p.error('RTL drift')
    tools = {n: shutil.which(v) for n, v in [('iverilog', a.iverilog), ('vvp', a.vvp)]}
    if not all(tools.values()):
        p.error('existing Icarus/VVP required')
    chain = tool_chain(tools)
    sources = {str(ROOT/n): d for n, d in emitted_sources.items()}
    sources.update({str(f): sha(f) for f in [Path(__file__).resolve(), HERE/'test_runtime_epoch_boundary.py',
        HERE/'fixed_mac_epoch_adapter_tb.sv', HERE/'rtl8211f_pin_model.sv']})
    inputs = {str(f): sha(f) for f in files + [a.emission_receipt.resolve()]}
    guard(out.parent)
    out.mkdir()
    receipt = dict(status='RUNNING', scope=__doc__, source_sha256=sources, input_sha256=inputs,
        tool_sha256={n: sha(f) for n, f in chain.items()}, tools=chain, cases={},
        commands=[], resources=[], real_mac=False, real_phy_mdio=False, real_outer_cdc=True,
        fixture_producer_closed=True, fixed_source_hz=125000000, fixture_policy_waits=None,
        cpu_dma_home=False, full_epoch_retirement=False, full_system_ack=False, physical_qualified=False,
        line_rate_qualified=False, hardware_default_changed=False)
    binary = out/'test.vvp'
    try:
        compile_command = [tools['iverilog'], '-g2012', '-DSTOP_COND=1', '-DASSERT_VERBOSE_COND=1',
            '-s', 'fixed_mac_epoch_adapter_tb', '-o', str(binary), *map(str, files),
            str(HERE/'rtl8211f_pin_model.sv'), str(HERE/'fixed_mac_epoch_adapter_tb.sv')]
        receipt['commands'].append(compile_command)
        result = run(compile_command, out/'compile.log', a.timeout)
        receipt['resources'].append(dict(label='compile', **result))
        if result['returncode'] or result['timed_out']:
            raise RuntimeError('compile failed: '+(out/'compile.log').read_text()[-4000:])
        receipt['binary_sha256'] = sha(binary)
        cases = [('fabric50', 10, 0, 'FIXED_MAC_EPOCH_ADAPTER_PASS')]
        if not a.single:
            cases += [('fabric250', 2, 0, 'FIXED_MAC_EPOCH_ADAPTER_PASS'), ('fabric71', 7, 0, 'FIXED_MAC_EPOCH_ADAPTER_PASS')]
            cases += [(f'negative{n}', 10, n, marker) for n, marker in [
                (1, 'EPOCH_ORACLE_RELEASE_OWNERSHIP'), (2, 'EPOCH_ORACLE_COMMAND_SERIAL'),
                (3, 'EPOCH_ORACLE_RELEASE_OWNERSHIP'), (4, 'EPOCH_ORACLE_RELEASE_OWNERSHIP')]]
        cases = [(name, half, negative, marker, 0) for name, half, negative, marker in cases]
        if not a.single:
            cases += [(f'fault{n}', 10, 0, 'FIXED_MAC_EPOCH_ADAPTER_PASS', n) for n in (1, 2, 3)]
        for name, half, negative, marker, faultcase in cases:
            command = [tools['vvp'], '-i', str(binary), f'+fabric_half={half}', f'+negative={negative}', f'+faultcase={faultcase}']
            receipt['commands'].append(command)
            log = out/(name+'.log')
            result = run(command, log, a.timeout)
            receipt['resources'].append(dict(label=name, **result))
            content = log.read_text()
            passed = marker in content and not result['timed_out'] and not result['disk_floor_breached']
            passed &= (result['returncode'] != 0 if negative else result['returncode'] == 0)
            injections = {1: 'EPOCH_NEGATIVE_OLD_RELEASED_SNAPSHOT', 2: 'EPOCH_NEGATIVE_DUPLICATE_SERIAL',
                          3: 'EPOCH_NEGATIVE_TERMINAL_BACKPRESSURE', 4: 'EPOCH_NEGATIVE_FINAL_SNAPSHOT_BACKPRESSURE'}
            if negative:
                passed &= injections[negative] in content and 'FIXED_MAC_EPOCH_ADAPTER_PASS' not in content
            else:
                passed &= all(term in content for term in ('commands=5 receipts=5', 'release_snapshots=2',
                                                           'csr=2/2', 'early_cancel=1',
                                                           'FIXED_MAC_UNSENT_PARK_CANCEL csr_owner_retained=1 parked_commands=0 released_before_fresh_reply=1'))
            if faultcase:
                passed &= f'FIXED_MAC_EPOCH_FAULT_PASS case={faultcase} failed_closed=1' in content
            receipt['cases'][name] = dict(passed=passed, expected_failure=bool(negative), marker=marker,
                log_sha256=sha(log), events=[line for line in content.splitlines() if line.startswith(('FIXED_', 'EPOCH_'))])
            if not passed:
                raise RuntimeError(name+' failed: '+content[-4000:])
        for name, digest in {**sources, **inputs}.items():
            if sha(name) != digest:
                raise RuntimeError('input drift: '+name)
        for name, path in chain.items():
            if sha(path) != receipt['tool_sha256'][name]:
                raise RuntimeError('tool drift: '+name)
        receipt['status'] = 'PASS_SELECTED_ADAPTER' if a.single else 'PASS_ADAPTER_MATRIX'
    except BaseException as error:
        receipt['status'] = 'FAILED'
        receipt['error'] = str(error)
        raise
    finally:
        (out/'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
        print(receipt['status'], str(out), flush=True)


if __name__ == '__main__':
    main()
