#!/usr/bin/env python3
"""Independently rehash fixed-MAC native, emission, topology and default-OFF evidence.

No simulation, build, source/RTL rewriting, upload, or historical receipt edits.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check_hashes(entries):
    for name, digest in entries.items():
        path = Path(name)
        if not path.is_absolute():
            path = ROOT/path
        assert path.is_file() and sha(path) == digest, ('hash drift', str(path))


def native(path, expected_status, pass_marker):
    receipt_path = path/'receipt.json'
    receipt = json.loads(receipt_path.read_text())
    assert receipt['status'] == expected_status
    assert set(receipt['cases']) == {'fabric50', 'fabric250', 'fabric71',
        'negative1', 'negative2', 'negative3', 'negative4'}
    check_hashes(receipt['source_sha256'])
    check_hashes(receipt['input_sha256'])
    for name, tool in receipt['tools'].items():
        assert sha(tool) == receipt['tool_sha256'][name]
    assert sha(path/'test.vvp') == receipt['binary_sha256']
    resources = {r['label']: r for r in receipt['resources']}
    for name, case in receipt['cases'].items():
        log = path/(name+'.log')
        assert case['passed'] and sha(log) == case['log_sha256']
        content = log.read_text()
        result = resources[name]
        assert not result['timed_out'] and not result['disk_floor_breached']
        assert (result['returncode'] != 0) == case['expected_failure']
        assert case['marker'] in content
        if case['expected_failure']:
            assert pass_marker not in content and 'TIMEOUT' not in content
        else:
            assert pass_marker in content
    return dict(receipt_sha256=sha(receipt_path), sources=len(receipt['source_sha256']),
        inputs=len(receipt['input_sha256']), tools=len(receipt['tools']),
        positive=3, ordinary_oracle_negatives=4,
        seconds={r['label']: r['seconds'] for r in receipt['resources']})


def emission(root, name):
    receipt_path = root/(name+'-emission.json')
    record = json.loads(receipt_path.read_text())
    assert record['status'] == 'PASS_EMIT_ONLY' and record['returncode'] == 0
    check_hashes(record['source_sha256'])
    rtl = root/(name+'-rtl')
    assert {p.name: sha(p) for p in rtl.glob('*.sv')} == record['rtl_sha256']
    return dict(receipt_sha256=sha(receipt_path), modules=len(record['rtl_sha256']))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out-root', type=Path, required=True)
    p.add_argument('--real', type=Path, required=True)
    p.add_argument('--boundary', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    assert not a.output.exists(), 'verification result must be fresh'
    result = dict(status='PASS_SCOPED_FIXED_MAC_BOUNDARY',
        verifier_sha256=sha(__file__),
        real=native(a.real, 'PASS_REAL_MAC_MATRIX', 'FIXED_SOURCE_MAC_PASS'),
        boundary=native(a.boundary, 'PASS_BOUNDARY_MATRIX', 'FIXED_MAC_BOUNDARY_PASS'),
        emissions={name: emission(a.out_root, name) for name in
            ['test-r2', 'boundary-r2', 'production-r2', 'balanced-r2']})
    default_path = a.out_root/'default-r3-comparison.json'
    default = json.loads(default_path.read_text())
    assert default['status'] == 'PASS_EMIT_ONLY' and default['source_unchanged']
    check_hashes(default['source_sha256'])
    old = {p.name: sha(p) for p in Path(default['reference']).glob('*.sv')}
    new = {p.name: sha(p) for p in (a.out_root/'default-r3').glob('*.sv')}
    assert old == new == default['reference_sha256'] == default['current_sha256']
    assert len(old) == 248 and default['changed'] == []
    result['default_off'] = dict(byte_identical=248, normalized=False,
        comparison_sha256=sha(default_path))
    topology = {}
    for name, continuous_count in [('production-r2', 0), ('balanced-r2', 1)]:
        directory = a.out_root/(name+'-rtl')
        top = (directory/'FixedSourceManagedGmac.sv').read_text()
        mac = (directory/'TriSpeedManagedGmac.sv').read_text()
        assert re.search(r'\.sourceClock\s*\(_mac_continuousClock\)', top)
        assert re.search(r'\.fixedClock\s*\(_mac_continuousClock\)', top)
        assert re.search(r'\.rawTxClock\s*\(rawTxClock\)', top)
        assert len(re.findall(r'^\s+ContinuousClockBuffer \w+ \(', mac, re.M)) == continuous_count
        assert len(re.findall(r'^\s+ManagedClockBuffer \w+ \(', mac, re.M)) == 2
        if continuous_count:
            assert re.search(r'ContinuousClockBuffer continuousTxClock_keepRunning\s*\(\s*\.rawClock\s*\(rawTxClock\)', mac)
            assert 'assign continuousClock = _continuousTxClock_keepRunning_runningClock;' in mac
        else:
            assert 'assign continuousClock = rawTxClock;' in mac
        boundary = (directory/'FixedMacBoundary.sv').read_text()
        assert len(re.findall(r'^\s+CdcDataFifo(?:_\d+)? \w+ \(', boundary, re.M)) == 4
        assert len(re.findall(r'^\s+CdcMailbox(?:_\d+)? \w+ \(', boundary, re.M)) == 3
        assert len(re.findall(r'^\s+RegisterClockDomainBridge \w+ \(', boundary, re.M)) == 1
        assert "remaining == 6'h31" in (directory/'MdioClause22.sv').read_text()
        topology[name] = dict(existing_continuous_buffers=continuous_count, existing_managed_buffers=2,
            new_mmcm=0, stream_fifos=4, stream_payload_bits=37, command_mailboxes=3,
            csr_bridges=1, fixed_source_hz=125000000, mdio_half_period_fixed_cycles=50)
    result['static_topology'] = topology
    result['scope'] = dict(real_cpu_dma_home=False, complete_aon_epoch_retirement=False,
        runtime_platform_selected=False, full_system_ack=False, clock_gating=False,
        physical_cdc=False, drp=False, board=False, line_rate=False,
        short_external_irq_capture=False, fixture_producer_closed=True,
        fifo_only_rx_fabric50_measured_bytes_per_second=100000000)
    a.output.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
