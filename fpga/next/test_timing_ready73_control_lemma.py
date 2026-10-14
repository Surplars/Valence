#!/usr/bin/env python3
"""25 exact-triple admission controls; optional fresh-export source-equation proof.

Hash-admission fixtures are not RTL execution. --export also checks complete
native bytes, direct parent connections and reset-based control induction.
Neither mode is a mapped-chain or timing qualification.
"""
import argparse
import hashlib
import importlib.util
import itertools
import json
from pathlib import Path
import re
import tempfile
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OLD = {
    'rtl/TriSpeedRgmiiTx.sv': '6374714496e0b23b174ac542027eefc59370c13cd5a0eb85de9af58e77af79a7',
    'rtl/TriSpeedManagedGmac.sv': '4d1f5c7f520f1cff5fe2a45bc510a9d269448f7e9e285450c2c8936cc7bf043e',
    'board/native_rgmii_trispeed_quarter.sv': '32b96761f2019806b6e03d9d885595449d2b057a30b6bb9ca204a34162ce96fc',
}
NEW = {**OLD, 'rtl/TriSpeedManagedGmac.sv': '5be26d593e5462db4028983ab63e7ffe3b0e58bc1e133242629b2e945c1c3d9b'}
BANK_ENCODER = '26715434594bbbc15f1d30e5a4bfc92bdc3cc1b0b81499ac36d55d3d890780ab'
BANK_PARENT = 'b754d2a417c569c32867322bb26816bcebca88a56e098b7fb6eab659770c03ec'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load():
    spec = importlib.util.spec_from_file_location('ready73_control_board', HERE / 'board_t1.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def admission_tests(board):
    rows = []
    def check(name, hashes, admitted):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for filename in hashes:
                path = root / filename
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('HASH-ADMISSION FIXTURE ONLY; NOT RTL\n')
            with mock.patch.object(board, 'sha', side_effect=lambda p: hashes[p.relative_to(root).as_posix()]):
                result = board.source_control_lemma(root)
            assert result['proved'] is admitted, name
            assert result['reset_phase_induction_vectors'] == (16 if admitted else 0), name
            assert result['mapped_chain_checked'] is False and result['physical_qualification'] is False
            rows.append({'case': name, 'admitted': admitted})
    check('old-whole-triple', OLD, True)
    check('new-whole-triple', NEW, True)
    for label, original in [('old', OLD), ('new', NEW)]:
        for name in original:
            values = dict(original)
            values[name] = hashlib.sha256((values[name] + 'unknown').encode()).hexdigest()
            check(label + '-mutated-' + name, values, False)
            values = dict(original)
            del values[name]
            check(label + '-missing-' + name, values, False)
    distinct = set()
    for bits in itertools.product((0, 1), repeat=3):
        values = {name: (NEW if bit else OLD)[name] for name, bit in zip(OLD, bits)}
        distinct.add(tuple(values.values()))
        check('cross-combination-' + ''.join(map(str, bits)), values, values in (OLD, NEW))
    assert len(distinct) == 2  # Identical encoder/adapter bytes, not eight distinct forms.
    for label, original in [('old', OLD), ('new', NEW)]:
        check(label + '-unreviewed-bank-encoder', {**original, 'rtl/TriSpeedRgmiiTx.sv': BANK_ENCODER}, False)
    check('unreviewed-bank-parent', {**NEW, 'rtl/TriSpeedManagedGmac.sv': BANK_PARENT}, False)
    assert len(rows) == 25
    return rows


def source_proof(export):
    actual = {name: sha(export / name) for name in NEW}
    assert actual == NEW, 'fresh complete native triple differs'
    fixture = HERE / 'native_mac_tests/fixtures'
    assert sha(fixture / 'TriSpeedRgmiiTx.sv') == NEW['rtl/TriSpeedRgmiiTx.sv']
    assert sha(fixture / 'TriSpeedManagedGmac.sv') == OLD['rtl/TriSpeedManagedGmac.sv']
    assert sha(ROOT / 'fpga/zu15eg/native_rgmii_trispeed_quarter.sv') == NEW['board/native_rgmii_trispeed_quarter.sv']
    encoder = (export / 'rtl/TriSpeedRgmiiTx.sv').read_text()
    parent = (export / 'rtl/TriSpeedManagedGmac.sv').read_text()
    old_parent = (fixture / 'TriSpeedManagedGmac.sv').read_text()
    block = lambda text: re.findall(r'TriSpeedRgmiiTx encode \((.*?)\n  \);', text, re.S)
    assert len(block(parent)) == 1 and block(parent) == block(old_parent)
    for port, net in [('clock', 'rawTxClock'), ('reset', '_rawTxRelease_resetOut'),
                      ('io_rise', 'rgmiiTxRise'), ('io_fall', 'rgmiiTxFall')]:
        assert re.search(r'\.' + port + r'\s*\(' + net + r'\)', block(parent)[0])
    assert len(re.findall(r'\brgmiiTxRise\b', parent)) == len(re.findall(r'\brgmiiTxFall\b', parent)) == 2
    assert encoder.count('always @(posedge clock or posedge reset) begin') == 1
    assert encoder.count('io_rise_REG <=') == encoder.count('io_fall_REG <=') == 2
    for text in ["io_rise_REG <= 5'h0;", "io_fall_REG <= 5'h0;",
                 'enable = byteStart ? io_gmiiEnable & ~(|rateGap) : heldEnable;',
                 'io_rise_REG <= {enable, gigabit | ~highNibble ? data[3:0] : data[7:4]};',
                 'io_fall_REG <= {enable, gigabit | highNibble ? data[7:4] : data[3:0]};',
                 'assign io_rise = io_rise_REG;', 'assign io_fall = io_fall_REG;']:
        assert text in encoder
    # Complete encoder bytes are already reviewed, and both control bits have
    # the same unconditional non-reset update in the same clock/reset process.
    adapter = (export / 'board/native_rgmii_trispeed_quarter.sv').read_text()
    for text in ['always @(negedge tx_pad_clock or posedge serializer_reset)',
                 'low_symbol<=0; high_symbol<=0;', 'low_symbol<=tx_rise; high_symbol<=tx_fall;',
                 'end else if(REGISTER_SELECTED_HALF) begin', 'low_symbol<=high_symbol;']:
        assert text in adapter
    chain = {}
    connections = [
        ('rtl/ManagedPeripheralBank.sv', [('rgmiiTxRise', 'triSpeedRgmii_txRise'), ('rgmiiTxFall', 'triSpeedRgmii_txFall')]),
        ('rtl/BoardSocTop.sv', [('triSpeedRgmii_txRise', 'io_nativeGmac_triSpeedRgmii_txRise'), ('triSpeedRgmii_txFall', 'io_nativeGmac_triSpeedRgmii_txFall')]),
        ('rtl/FpgaNextSocTop.sv', [('io_nativeGmac_triSpeedRgmii_txRise', 'io_nativeGmac_triSpeedRgmii_txRise'), ('io_nativeGmac_triSpeedRgmii_txFall', 'io_nativeGmac_triSpeedRgmii_txFall')]),
        ('board/soc_top_fpga_next_ddr.sv', [('io_nativeGmac_triSpeedRgmii_txRise', 'rgmii_tx_rise'), ('io_nativeGmac_triSpeedRgmii_txFall', 'rgmii_tx_fall'), ('tx_rise', 'rgmii_tx_rise'), ('tx_fall', 'rgmii_tx_fall')]),
    ]
    for filename, ports in connections:
        text = (export / filename).read_text()
        for port, net in ports:
            assert len(re.findall(r'\.' + port + r'\s*\(' + net + r'\)', text)) == 1
        chain[filename] = sha(export / filename)
    return {'complete_triple': actual, 'encode_instance_identical': True,
            'control_D_clock_reset_enable_equal': True, 'forwarding_chain_sha256': chain}


def induction():
    cases = 0
    for selected, reset, phase, source, prior in itertools.product((0, 1), repeat=5):
        low = high = prior  # Invariant established by common zero reset.
        if reset:
            next_low = next_high = 0
        elif not phase:
            next_low = next_high = source
        else:
            next_low = high if selected else low
            next_high = high
        assert next_low == next_high
        cases += 1
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--export', type=Path)
    args = parser.parse_args()
    board = load()
    result = {'status': 'PASS_EXACT_TRIPLE_HOST_ADMISSION_ONLY', 'cases': admission_tests(board),
              'induction_vectors_both_modes': induction(), 'mapped_chain_checked': False,
              'physical_qualification': False}
    if args.export:
        result['native_source_proof'] = source_proof(args.export)
        assert board.source_control_lemma(args.export)['proved'] is True
        result['status'] = 'PASS_EXACT_TRIPLE_NATIVE_SOURCE_AND_HOST_ADMISSION_ONLY'
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
