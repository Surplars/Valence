#!/usr/bin/env python3
"""Freeze the already checked full-DDR2G export and a private board build.

Does not claim CPU/Linux runtime, routed signoff, or equivalence to an old bit.
The routed donor is ONLY an incremental placement/routing reference.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path
import sys


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(value, reason):
    if not value:
        raise ValueError(reason)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--repo', type=Path, required=True)
    ap.add_argument('--root', type=Path, required=True)
    ap.add_argument('--firmware', type=Path, required=True)
    ap.add_argument('--donor', type=Path, required=True)
    ap.add_argument('--ddr-receipt', type=Path)
    ap.add_argument('--network-receipt', type=Path)
    ap.add_argument('--cpu-receipt', type=Path)
    args = ap.parse_args()
    target = args.root / 'inputs.json'
    require(not target.exists(), 'Preserve frozen build inputs')
    proof_path = args.ddr_receipt or args.repo / 'build/gsim/ddr2g-20261006-r8/receipt.json'
    network_path = args.network_receipt or args.repo / 'build/gsim/network-packet-pressure-20261006-2g-r6/receipt.json'
    proof = json.loads(proof_path.read_text())
    network = json.loads(network_path.read_text())
    require(proof['status'] == network['status'] == 'passed', 'Affected tests did not pass')
    require(proof['capacity_bytes'] == 0x80000000, 'Wrong DDR capacity')
    require(proof['end_exclusive'] == '0x100200000', 'Wrong physical end address')
    sources = {}
    receipts = [proof, network]
    if args.cpu_receipt:
        cpu = json.loads(args.cpu_receipt.read_text())
        require(cpu['status'] == 'PASS_SOC_UART_MARGIN_AFFECTED_SHORT', 'Current CPU batch did not pass')
        native_path = Path(cpu['native_receipt'])
        # Linux evidence uses Linux absolute paths; map into the same UNC repository.
        native_path = args.repo / native_path.relative_to('/home/openion/Valence')
        require(sha(native_path) == cpu['native_receipt_sha256'], 'Actual RV64GC proof changed')
        require(json.loads(native_path.read_text())['status'] == 'PASS_RV64GC_NATIVE_AFFECTED_SHORT', 'Missing native CPU proof')
        receipts.append(cpu)
    for receipt in receipts:
        for name, digest in receipt['source_sha256'].items():
            require(sha(args.repo / name) == digest, 'Verified source drift: ' + name)
            require(name not in sources or sources[name] == digest, 'Conflicting source evidence')
            sources[name] = digest
    rtl = args.root / 'rtl'
    require(set(proof['production_rtl']) == {p.name for p in rtl.glob('*.sv')}, 'Incomplete production RTL')
    for name, digest in proof['production_rtl'].items():
        require(sha(rtl / name) == digest, 'RTL export drift: ' + name)
    audit = json.loads((args.firmware / 'bsp-audit.json').read_text())
    require((audit['status'], audit['memory_bytes'], audit['cpu_hz'], audit['uart_baud']) ==
            ('software_and_affected_short_checks_passed', 0x80000000, 100000000, 460800), 'Wrong BSP')
    if not args.cpu_receipt:
        for name, item in audit['rom'].items():
            if (args.root / 'firmware' / name).exists():
                digest = item['sha256'] if isinstance(item, dict) else item
                require(sha(args.root / 'firmware' / name) == digest, 'Wrong BootROM: ' + name)
    uart = None
    if args.cpu_receipt:
        uart_path = args.root / 'firmware/uart-machine-code-audit.json'
        uart = json.loads(uart_path.read_text())
        require((uart['status'], uart['reference_hz'], uart['baud'], uart['divisor'], uart['lcr'], uart['ier'], uart['fcr']) ==
                ('PASS_COMPILED_BOOTROM_UART_CONTRACT', 7372800, 460800, 1, 3, 0, 7), 'Compiled ROM UART mismatch')
        require(sha(args.root / 'firmware/bootrom.bin') == uart['binary_sha256'] and
                sha(args.root / 'firmware/bootrom.elf') == uart['elf_sha256'] and
                sha(args.repo / 'fpga/firmware/audit_uart_contract.py') == uart['auditor_sha256'], 'UART machine-code evidence drift')
        text = (rtl / 'UartConsole.sv').read_text()
        reference = re.search(r"referenceTick_advance\s*=.*\+\s*\d+'h([0-9A-Fa-f]+)", text)
        threshold = re.search(r"referenceTick_advance\s*>\s*\d+'h([0-9A-Fa-f]+)", text)
        require(reference and threshold and int(reference[1], 16) == uart['reference_hz'] and
                int(threshold[1], 16) + 1 == 50000000, 'Actual UART RTL clock/reference mismatch')
        dts = (args.firmware / 'valence-vl100.dts').read_text()
        serial = re.search(r'serial@10000000\s*\{(.*?)\};', dts, re.S)
        require(serial and re.search(r'clock-frequency\s*=\s*<7372800>', serial[1]) and
                re.search(r'current-speed\s*=\s*<460800>', serial[1]), 'BSP UART reference mismatch')
        for name in ('fpga/firmware/build.py', 'fpga/firmware/audit_uart_contract.py', 'fpga/firmware/bootrom.c'):
            sources[name] = sha(args.repo / name)
    sys.path.insert(0, str(args.repo / 'fpga/firmware'))
    from audit_bootrom import audit as audit_rom
    ip = args.root / 'ip-build/board_ip.gen/sources_1/ip/blk_mem_gen_0'
    rom = audit_rom(args.root / 'firmware/bootrom.bin', ip / 'blk_mem_gen_0.mif', ip / 'blk_mem_gen_0.dcp')
    require(rom['mifWordsMatched'] == 32768, 'Wrong generated ROM contents')
    files = {}
    for folder in ('rtl', 'board', 'scripts', 'firmware', 'mig', 'ip-build/board_ip.srcs', 'ip-build/board_ip.gen'):
        for path in sorted((args.root / folder).rglob('*')):
            if path.is_file():
                files[path.relative_to(args.root).as_posix()] = sha(path)
    manifest = dict(status='STAGED_DDR2G_RV64GC_CHECKED_EXPORT_NOT_ROUTED',
                    vendor='OpenIon', soc='VL100', cpu='Orbital-A1', isa='rv64gc',
                    f_d_enabled=True, issue_width=2, cpu_hz=100000000,
                    aon_uart_hz=50000000, uart_baud=460800, ddr_bytes=0x80000000,
                    ram_base='0x80200000', end_exclusive='0x100200000',
                    monitor_reserved=['0xffff8000', '0xffffc000'], netboot_enabled=True,
                    tx_clock_architecture='common_clk250_dedicated_oddr',
                    checked_source_sha256=sources, candidate_sha256=files,
                    incremental_routed_reference=str(args.donor),
                    incremental_routed_reference_sha256=sha(args.donor),
                    cpu_checkpoint_reused=False, bit_generated=False, board_verified=False,
                    affected_short_receipt_sha256=sha(proof_path),
                    network_pressure_receipt_sha256=sha(network_path),
                    bsp_audit_sha256=sha(args.firmware / 'bsp-audit.json'),
                    rom_word_audit=rom,
                    limits=['Fresh SoC synthesis, old route is only an implementation reference.',
                            'Affected GSIM checks are not CPU/Linux board execution.',
                            'Complete-board static signoff and physical board retest still required.'])
    if args.cpu_receipt:
        manifest.update(cpu_affected_receipt=str(args.cpu_receipt), cpu_affected_receipt_sha256=sha(args.cpu_receipt),
                        uart_machine_code_audit=uart, uart_machine_code_audit_sha256=sha(uart_path),
                        bsp_rom_override_reason='Correct r5 DLL=7 UART erratum; unchanged matched Debian payload/DTS')
    target.write_text(json.dumps(manifest, indent=2) + '\n')
    print('PASS_DDR2G_INPUTS_FROZEN', 'rtl=', len(proof['production_rtl']),
          'sources=', len(sources), 'files=', len(files), 'ROM_WORDS=', rom['mifWordsMatched'])


if __name__ == '__main__':
    main()
