#!/usr/bin/env python3
"""Freeze exact board inputs and reuse unchanged, previously passed GSIM proof.

This does not certify timing, a working PHY, Linux network driver or a bitstream.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('candidate', type=Path)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--pins', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--short', type=Path)
    parser.add_argument('--boundary-dir', default='boundary')
    args = parser.parse_args()
    assert not args.out.exists(), 'Preserve previous receipt'
    receipt_path = args.repo / 'build/gsim/managed-peripherals-20261004-r4/receipt.json'
    old = json.loads(receipt_path.read_text(encoding='utf-8'))
    assert old['status'] == 'PASS_MANAGED_PERIPHERALS_SINGLE_CLOCK'
    short = json.loads(args.short.read_text()) if args.short else None
    if short:
        assert short['status'] == 'PASS_NATIVE_TIMING_SHORT'
        for relative, expected in short['source_sha256'].items():
            assert sha(args.repo / relative) == expected, 'Fresh short proof drift: ' + relative
    changed_allowed = {'src/main/scala/core/ooo/OooParams.scala',
        'src/main/scala/core/ooo/BoardSocTop.scala', 'src/main/scala/core/ooo/PipelinedMultiply.scala',
        'src/main/scala/core/ooo/MultiplyDivide.scala', 'src/main/scala/core/ooo/RegisteredFetchPacket.scala',
        'src/main/scala/ip/ethernet/MdioClause22.scala'}
    checked = {}
    rechecked = {}
    for relative, expected in old['source_sha256'].items():
        if relative.startswith('src/main/'):
            actual = sha(args.repo / relative)
            if actual != expected:
                assert short and relative in changed_allowed, 'Unverified main source changed: ' + relative
                assert short['source_sha256'][relative] == actual
                rechecked[relative] = actual
            else:
                checked[relative] = actual
    workbook = json.loads(args.pins.read_text(encoding='utf-8'))
    table = next(sheet['cells'] for sheet in workbook['sheets'] if sheet['sheet'] == 'MIPI & PL ETH')
    manifest = json.loads((args.repo / 'fpga/zu15eg/self-gmac-board.json').read_text(encoding='utf-8'))['pl_phy']
    pins = {'PHY2_MDC': ('eth_mdc', manifest['mdc']['ball']),
            'PHY2_MDIO': ('eth_mdio', manifest['mdio']['ball']),
            'PHY2_RST': ('eth_reset_gate', manifest['reset_gate']['ball']),
            'PHY2_RXCK': ('eth_rxc', manifest['rgmii']['rx_clock']),
            'PHY2_RXCTL': ('eth_rx_ctl', manifest['rgmii']['rx_control']),
            'PHY2_TXCK': ('eth_txc', manifest['rgmii']['tx_clock']),
            'PHY2_TXCTL': ('eth_tx_ctl', manifest['rgmii']['tx_control'])}
    for direction in ('RX', 'TX'):
        for lane, ball in enumerate(manifest['rgmii'][direction.lower() + '_data_lsb_first']):
            pins['PHY2_%sD%d' % (direction, lane)] = ('eth_%sd[%d]' % (direction.lower(), lane), ball)
    xdc = (args.candidate / 'board/native_gmac_pins.xdc').read_text(encoding='utf-8')
    evidence = []
    for row in range(17, 32):
        signal, ball = table['C%d' % row], table['A%d' % row]
        port, expected = pins[signal]
        assert ball == expected, 'Pin source conflict: ' + signal
        assert ('set_property PACKAGE_PIN %s [get_ports {%s}]' % (ball, port)) in xdc
        evidence.append({'signal': signal, 'ball': ball, 'port': port,
                         'source_cells': "'MIPI & PL ETH'!A%d:C%d" % (row, row)})
    logs = args.candidate / args.boundary_dir
    assert sha(logs / 'native_rgmii.sv') == sha(args.candidate / 'board/native_rgmii.sv')
    assert 'PASS_RGMII_DDR_BOUNDARY' in (logs / 'positive.log').read_text(encoding='utf-8')
    for direction in ('tx', 'rx'):
        text = (logs / ('negative-%s.log' % direction)).read_text(encoding='utf-8')
        assert 'Fatal: %s ordered byte' % direction.upper() in text
        assert 'PASS_RGMII_DDR_BOUNDARY' not in text
    files = {}
    for dirname in ('rtl', 'board', 'scripts', 'firmware'):
        for path in sorted((args.candidate / dirname).rglob('*')):
            if path.is_file():
                files[str(path.relative_to(args.candidate))] = sha(path)
    result = {'status': 'PASS_INPUTS_AND_SHORT_BOUNDARY_NOT_BOARD_SIGNOFF',
              'cpu_hz': 100000000, 'uart_hz': 50000000, 'uart_baud': 460800,
              'issue_width': 2, 'isa': 'rv64imac', 'f_d_enabled': False,
              'pin_workbook_sha256': workbook['sha256'], 'pin_evidence': evidence,
              'reused_gsim_receipt_sha256': sha(receipt_path),
              'fresh_short_receipt_sha256': sha(args.short) if args.short else None,
              'rechecked_main_sha256': rechecked,
              'physical_boundary_directory': args.boundary_dir,
              'unchanged_gsim_main_sha256': checked, 'candidate_sha256': files,
              'boundary': '16 TX/16 RX bytes, error control, in-band speed, common reset, 2 negative cases',
              'limitations': ['PHY25MHz reference and delay straps need board verification',
                              'PCB relative skew assumption +/-0.25ns, not measured',
                              'no new CPU IPC claim, no long Linux/whole-board RTL simulation',
                              'routed STA/DRC/CDC review required before bit release']}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(result['status'], 'main_hashes=', len(checked), 'pin_rows=', len(evidence))


if __name__ == '__main__':
    main()
