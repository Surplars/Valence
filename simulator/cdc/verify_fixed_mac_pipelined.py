#!/usr/bin/env python3
"""Rehash r22 opt-in FIFO/MAC evidence and independently check its narrow claims.

Read only. No build, simulation, normalization of the default RTL, or upload.
"""
import argparse
import json
from pathlib import Path
import re
from verify_fixed_mac import sha, check_hashes, emission

ROOT = Path(__file__).resolve().parents[2]


def native(directory, status, positives, negatives, pass_marker):
    path = directory/'receipt.json'
    record = json.loads(path.read_text())
    assert record['status'] == status
    assert set(record['cases']) == set(positives) | set(negatives)
    check_hashes(record['source_sha256'])
    check_hashes(record['input_sha256'])
    for name, tool in record['tools'].items():
        assert sha(tool) == record['tool_sha256'][name]
    assert sha(directory/'test.vvp') == record['binary_sha256']
    resources = {r['label']: r for r in record['resources']}
    assert resources['compile']['returncode'] == 0
    assert not resources['compile']['timed_out'] and not resources['compile']['disk_floor_breached']
    assert '-DSTOP_COND=1' in record['commands'][0] and '-DASSERT_VERBOSE_COND=1' in record['commands'][0]
    logs = {}
    for name, case in record['cases'].items():
        log = directory/(name+'.log')
        content = log.read_text()
        result = resources[name]
        assert sha(log) == case['log_sha256'] and case['passed']
        assert not result['timed_out'] and not result['disk_floor_breached']
        assert bool(case['expected_failure']) == (name in negatives)
        assert (result['returncode'] != 0) == case['expected_failure']
        expected_marker = negatives[name] if name in negatives else pass_marker
        assert case['marker'] == expected_marker and expected_marker in content
        if case['expected_failure']:
            assert pass_marker not in content and 'TIMEOUT' not in content
        else:
            assert pass_marker in content
        logs[name] = content
    return dict(receipt_sha256=sha(path), positive=len(positives), ordinary_oracle_negatives=len(negatives),
        sources=len(record['source_sha256']), tools=len(record['tools']),
        seconds={r['label']: r['seconds'] for r in record['resources']}), logs


def fields(line):
    return dict(re.findall(r'(\w+)=([^ ]+)', line))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out-root', type=Path, required=True)
    p.add_argument('--transport', type=Path, required=True)
    p.add_argument('--burst', type=Path, required=True)
    p.add_argument('--reference', type=Path, required=True)
    p.add_argument('--lifecycle', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    assert not a.output.exists()
    result = dict(status='PASS_SCOPED_FIXED_MAC_PIPELINED', verifier_sha256=sha(__file__),
        verifier_dependency_sha256=sha(Path(__file__).with_name('verify_fixed_mac.py')))
    result['transport'], logs = native(a.transport, 'PASS_PIPELINED_MATRIX',
        ['fabric50', 'fabric250', 'fabric71'], {'negative1': 'BOUNDARY_ORACLE_PAYLOAD',
            'negative2': 'BOUNDARY_ORACLE_OWNER', 'negative3': 'BOUNDARY_ORACLE_RECEIPT',
            'negative4': 'BOUNDARY_ORACLE_PAYLOAD'},
        'FIXED_MAC_PIPELINED_PASS')
    transport_rates = {}
    for case, rate in [('fabric50', 200000000), ('fabric250', 500000000), ('fabric71', 285714286)]:
        found = [fields(line) for line in logs[case].splitlines() if line.startswith('BOUNDARY_THROUGHPUT')]
        assert len(found) == 4 and {int(row['channel']) for row in found} == set(range(4))
        for row in found:
            assert int(row['bytes_per_second']) == rate
            assert int(row['keep_counted_bytes']) == 7680 and int(row['measured_words']) == 1920
        assert 'capacity=17,17,17,17 contiguous_words=16,16,16,16' in logs[case]
        assert 'ram_index_wraps_per_lane=384 full_pointer_wraps_per_lane=192' in logs[case]
        assert logs[case].count('reset_discard=17,17,17,17') == 2
        assert 'postreset=64,64,64,64' in logs[case] and 'postreset=96,96,96,96' in logs[case]
        stress = fields(next(l for l in logs[case].splitlines() if l.startswith('BOUNDARY_STRESS')))
        assert all(int(n) >= 100 for n in stress['random_stalls'].split(','))
        transport_rates[case] = [rate]*4
    result['transport']['valid_payload_bytes_per_second'] = transport_rates
    result['burst'], burst = native(a.burst, 'PASS_REAL_MAC_BURST_MATRIX',
        ['always_ready', 'random_ready'], {'negative1': 'BURST_ORACLE_RX payload',
            'negative2': 'BURST_ORACLE_STATUS', 'negative3': 'BURST_ORACLE_COUNTER',
            'negative4': 'BURST_ORACLE_TRANSPORT_DATA'},
        'FIXED_MAC_RX_BURST_PASS')
    result['reference'], reference = native(a.reference, 'PASS_REFERENCE_BURST',
        ['always_ready'], [], 'FIXED_MAC_RX_BURST_PASS')
    measurements = {}
    for name, content in [('candidate_'+k, v) for k, v in burst.items() if not k.startswith('negative')]+[
            ('reference_always_ready', reference['always_ready'])]:
        row = fields(next(l for l in content.splitlines() if l.startswith('FIXED_MAC_RX_BURST_PASS')))
        measured = fields(next(l for l in content.splitlines() if l.startswith('BURST_MEASURE')))
        delivered, drops = int(row['delivered']), int(row['bank_full_drops'])
        assert int(row['offered_frames']) == 64 and delivered+drops == 64
        assert int(row['body_bytes']) == delivered*1514
        assert int(row['data_words']) == delivered*379 and int(row['status_words']) == delivered*6
        assert row['ifg_slots'] == '12' and row['checked_gaps'] == '63'
        assert int(measured['offered_body_bytes']) == int(measured['wire_body_bytes']) == 96896
        assert float(measured['wire_span_ns']) == 787360.0
        if name.startswith('candidate'):
            assert delivered == 64 and drops == 0 and row['ids'] == 'ffffffffffffffff'
            assert row['reference'] == '0'
            assert row['random_sink'] == ('1' if name == 'candidate_random_ready' else '0')
            if name == 'candidate_random_ready':
                assert int(row['held_data']) >= 100 and int(row['held_status']) >= 10
        else:
            assert drops > 0 and row['reference'] == '1' and row['random_sink'] == '0'
            assert int(row['ids'], 16).bit_count() == delivered
        measurements[name] = dict(summary=row, measured=measured)
    result['finite_rx_burst'] = measurements
    result['lifecycle'], _ = native(a.lifecycle, 'PASS_SELECTED_REAL_MAC', ['fabric50'], [],
        'FIXED_SOURCE_MAC_PASS')
    result['emissions'] = {name: emission(a.out_root, name) for name in
        ['boundary-r1', 'test-r1', 'reference-r1', 'production-r1', 'balanced-r1']}
    # Cross-bind behavioral binaries to the exact emissions inspected below.
    for native_dir, emitted in [(a.transport, 'boundary-r1'), (a.burst, 'test-r1'),
            (a.reference, 'reference-r1'), (a.lifecycle, 'test-r1')]:
        record = json.loads((native_dir/'receipt.json').read_text())
        receipt_path = (a.out_root/(emitted+'-emission.json')).resolve()
        emitted_record = json.loads(receipt_path.read_text())
        expected = {str((a.out_root/(emitted+'-rtl')/name).resolve()): digest
            for name, digest in emitted_record['rtl_sha256'].items()}
        observed = {name: digest for name, digest in record['input_sha256'].items()
            if name.endswith('.sv')}
        assert observed == expected
        assert record['input_sha256'][str(receipt_path)] == sha(receipt_path)

    held = ROOT/'src/main/scala/ip/bus/HeldResponseCdcDataFifo.scala'
    assert sha(held) == '2302decf7392cfd64fdec49a4c2b76470f45c98f736644c2ddb64d0cef21d126'
    result['reused_fifo_sha256'] = sha(held)
    assertion_path = a.out_root/'enabled-assertions-verification.json'
    assertions = json.loads(assertion_path.read_text())
    for name, sites in [('real', 23), ('boundary', 6)]:
        row = assertions[name]
        check_hashes(row['source_sha256'])
        content_path = a.out_root/(name+'-enabled-assertions.sv')
        assert sha(content_path) == row['preprocessed_sha256']
        content = content_path.read_text()
        assert row['inline_fatal_sites'] == content.count('$fatal') == sites
        assert row['result']['returncode'] == 0
        for message in row['required_assertions']:
            assert message in content
        assert 'Pending RAM response must retain source-visible slot ownership' in content
        assert 'Stalled response must re-read its still-owned RAM address' in content
    result['enabled_assertions'] = dict(receipt_sha256=sha(assertion_path), real_sites=23, boundary_sites=6)
    topology = {}
    for name, continuous_count in [('production-r1', 0), ('balanced-r1', 1)]:
        directory = a.out_root/(name+'-rtl')
        top = (directory/'FixedSourceManagedGmac.sv').read_text()
        mac = (directory/'TriSpeedManagedGmac.sv').read_text()
        boundary = (directory/'FixedMacBoundary.sv').read_text()
        assert re.search(r'\.sourceClock\s*\(_mac_continuousClock\)', top)
        assert re.search(r'\.fixedClock\s*\(_mac_continuousClock\)', top)
        assert re.search(r'\.rawTxClock\s*\(rawTxClock\)', top)
        assert len(re.findall(r'^\s+ContinuousClockBuffer \w+ \(', mac, re.M)) == continuous_count
        assert len(re.findall(r'^\s+ManagedClockBuffer \w+ \(', mac, re.M)) == 2
        assert len(re.findall(r'^\s+HeldResponseCdcDataFifo(?:_\d+)? \w+ \(', boundary, re.M)) == 4
        assert len(re.findall(r'^\s+CdcMailbox(?:_\d+)? \w+ \(', boundary, re.M)) == 3
        assert len(re.findall(r'^\s+RegisterClockDomainBridge \w+ \(', boundary, re.M)) == 1
        assert "remaining == 6'h31" in (directory/'MdioClause22.sv').read_text()
        topology[name] = dict(existing_continuous_buffers=continuous_count, existing_managed_buffers=2,
            new_mmcm=0, outer_held_fifos=4, payload_bits=37, csr_bridges=1, mailboxes=3)
    result['topology'] = topology
    ref = a.out_root/'reference-r1-rtl'
    candidate = a.out_root/'test-r1-rtl'
    old = ROOT/'out/cmu-frequency-r21/test-r2-rtl'
    hashes = lambda d: {p.name: sha(p) for p in d.glob('*.sv')}
    assert hashes(ref) == hashes(old) and len(hashes(ref)) == 50
    rh, ch = hashes(ref), hashes(candidate)
    assert ch.keys()-rh.keys() == {'HeldResponseCdcDataFifo.sv'}
    assert rh.keys()-ch.keys() == {'CdcDataFifo_3.sv'}
    assert [n for n in rh if n in ch and rh[n] != ch[n]] == ['FixedMacBoundary.sv']
    # This is an exact textual description of the intentional enabled change,
    # not normalization used to claim byte-identical candidate RTL.
    assert (ref/'FixedMacBoundary.sv').read_text().replace('CdcDataFifo_3 ', 'HeldResponseCdcDataFifo ') == (
        candidate/'FixedMacBoundary.sv').read_text()
    result['standalone_off'] = dict(byte_identical_to_r21=50, normalized=False)
    result['enabled_difference'] = dict(byte_identical=48, replaced_module=['CdcDataFifo_3.sv',
        'HeldResponseCdcDataFifo.sv'], changed_module='FixedMacBoundary.sv', change='four instance type names only')
    default_path = a.out_root/'default-r1-comparison.json'
    default = json.loads(default_path.read_text())
    check_hashes(default['source_sha256'])
    assert default['status'] == 'PASS_EMIT_ONLY' and default['source_unchanged']
    assert hashes(Path(default['reference'])) == hashes(a.out_root/'default-r1') == default['reference_sha256']
    assert len(default['reference_sha256']) == 248 and default['changed'] == []
    result['default_off'] = dict(byte_identical=248, normalized=False, comparison_sha256=sha(default_path))
    result['scope'] = dict(runtime_platform_selected=False, full_system_ack=False, board=False,
        physical_cdc=False, routed_timing=False, drp=False, line_rate_qualification=False,
        default_clock_changed=False, cpu_dma_home=False, reset_contract='common cold discard only',
        transport_clock_pause='digital low-phase pause only, not gate qualification',
        burst='64 standard1518-byte frames includingFCS;1514 body bytes,1G byte cadence,12-byte IFG',
        fixture_producer_closed=True, unilateral_reset=False)
    a.output.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
