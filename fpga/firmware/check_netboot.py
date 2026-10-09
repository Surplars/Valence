#!/usr/bin/env python3
"""Short local firmware acceptance; no sockets, board execution or Vivado."""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path(__file__).resolve().parent

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def command(argv, log):
    with log.open("w") as stream:
        result = subprocess.run(list(map(str, argv)), stdout=stream, stderr=subprocess.STDOUT,
                                env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}, timeout=180)
    if result.returncode:
        raise RuntimeError(f"failed ({result.returncode}): {log}")

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--crc-mode", choices=("nibble","byte"), default="byte")
    args = parser.parse_args()
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=False)
    sources = [SOURCE / p for p in ("crc32.c", "crc32.h", "test_crc32.py", "audit_crc32.py", "netboot.c", "netboot.h", "ram_verify.h", "netboot_board.c", "netboot_host.py",
               "test_netboot.cpp", "test_netboot_host.py", "test_netboot_capacities.py", "test_netboot_interop.py", "bootrom.c", "boot_tui.h", "bootrom.ld",
               "start.S", "build.py", "check_netboot.py", "valence_gmac.h", "board_memory.h",
               "test_netboot_board.c", "test_bootrom_recovery.c", "uart_load.py", "test_uart_load.py",
               "audit_uart_contract.py", "test_uart_contract.py", "ethernet_dma.h")]
    before = {str(p.relative_to(ROOT)): sha(p) for p in sources}
    report = {"status": "running", "source_sha256": before,
              "scope": "portable protocol + scripted MMIO/monitor + host tools + bare-metal builds; NOT PHY/CDC/board/timing",
              "ddr_bytes": 0x80000000, "cpu_hz": 100000000, "timebase_hz": 100000000,
              "uart_baud": 460800, "netboot_rx_stop_abi": 2,
              "posted_rx_depth": 4, "requested_tftp_block_size": 1024, "requested_tftp_window": 4,
              "full_wire_length_tested": 76564204, "additional_wire_length_tested": 66348776,
              "current_payload_length_tested": 76564168,
              "on_board_verified": False, "routed_timing_verified": False,
              "boot_policy": "SoC pulls TFTP; static IPv4; UART recovery",
              "ip": "192.168.137.30", "server": "192.168.137.1", "filename": "valence.vld"}
    try:
        command([sys.executable, SOURCE / "test_crc32.py", "--mode", args.crc_mode], output / "crc-equivalence.log")
        command(["clang-19", "-std=c11", "-O1", "-g", "-fsanitize=address,undefined",
                 "-fno-sanitize-recover=all", f"-DFIRMWARE_CRC_MODE={0 if args.crc_mode=='nibble' else 1}", "-Wall", "-Wextra", "-Werror", "-c",
                 SOURCE / "netboot.c", "-o", output / "netboot.o"], output / "compile-c.log")
        command(["clang-19", "-std=c11", "-O1", "-g", "-fsanitize=address,undefined",
                 "-fno-sanitize-recover=all", f"-DFIRMWARE_CRC_MODE={0 if args.crc_mode=='nibble' else 1}", "-Wall", "-Wextra", "-Werror", "-c",
                 SOURCE / "crc32.c", "-o", output / "crc32.o"], output / "compile-crc.log")
        command(["clang++-19", "-std=c++20", "-O1", "-g", "-fsanitize=address,undefined",
                 "-fno-sanitize-recover=all", f"-DFIRMWARE_CRC_MODE={0 if args.crc_mode=='nibble' else 1}", "-Wall", "-Wextra", "-Werror",
                 SOURCE / "test_netboot.cpp", output / "netboot.o", output / "crc32.o", "-o", output / "test-netboot"],
                output / "compile-tests.log")
        command([output / "test-netboot"], output / "protocol-tests.log")
        if "BOOTROM_TFTP_HOST_PASS cases=34" not in (output / "protocol-tests.log").read_text():
            raise RuntimeError("protocol success witness missing")
        window_result = re.search(r"BOOTROM_TFTP_WINDOW_PASS cases=(\d+) window4=1 block1024=1 oack=1 "
                                  r"crc_exactly_once=1 final_ack_deadline=1 wrap=1 fallback=1",
                                  (output / "protocol-tests.log").read_text())
        if not window_result or int(window_result[1]) < 84:
            raise RuntimeError("window protocol success witness missing")
        for test, witness, extra in (("test_netboot_board", "BOOTROM_MMIO_ORDER_PASS cases=32", [SOURCE / "netboot.c"]),
                                     ("test_bootrom_recovery", "BOOTROM_UART_RECOVERY_PASS cases=27", [])):
            command(["clang-19", "-std=c11", "-O1", "-g", "-fsanitize=address,undefined",
                     "-fno-sanitize-recover=all", f"-DFIRMWARE_CRC_MODE={0 if args.crc_mode=='nibble' else 1}", "-Wall", "-Wextra", "-Werror",
                     SOURCE / (test + ".c"), *extra, output / "crc32.o", "-o", output / test], output / (test + "-compile.log"))
            command([output / test], output / (test + ".log"))
            if witness not in (output / (test + ".log")).read_text():
                raise RuntimeError("firmware state-machine witness missing: " + test)
        board_log = (output / "test_netboot_board.log").read_text()
        if "BOOTROM_POSTED_RX_ORDER_PASS cases=22" not in board_log or \
           "BOOTROM_STORE_ALIGN_PASS cases=4162" not in board_log:
            raise RuntimeError("posted queue/store oracle witness missing")
        command([sys.executable, SOURCE / "test_netboot_capacities.py", "--cc", "clang-19", "--out", output / "capacity-matrix"],
                output / "capacity-matrix.log")
        command([sys.executable, SOURCE / "test_netboot_host.py"], output / "host-tool-tests.log")
        command([sys.executable, SOURCE / "test_netboot_interop.py", "--cc", "clang-19"],
                output / "interop-tests.log")
        if "BOOTROM_TFTP_INTEROP_PASS cases=8 real_sockets=0 python_sender=1 c_receiver=1" not in \
                (output / "interop-tests.log").read_text():
            raise RuntimeError("actual Python/C interoperability witness missing")
        command([sys.executable, SOURCE / "test_uart_load.py"], output / "uart-tool-tests.log")
        uart_result = re.search(r"Ran (\d+) tests? in", (output / "uart-tool-tests.log").read_text())
        if not uart_result or int(uart_result[1]) == 0:
            raise RuntimeError("UART tool test count missing")
        host_result = re.search(r"Ran (\d+) tests? in", (output / "host-tool-tests.log").read_text())
        if not host_result or int(host_result[1]) == 0:
            raise RuntimeError("host tool test count missing")
        for kind, flags in (("netboot", ["--netboot", "--netboot-posted-rx"]),
                            ("netboot-legacy", ["--netboot"]), ("uart-only", [])):
            command([sys.executable, SOURCE / "build.py", "--crc-mode", args.crc_mode, "--out", output / kind, "--ddr",
                     "--ddr-bytes", "0x80000000", "--cpu-hz", "100000000", "--uart-divisor", "1",
                     "--uart-reference-hz", "7372800", "--uart-baud", "460800", *flags], output / (kind + "-build.log"))
            command([sys.executable, SOURCE / "audit_crc32.py", "--rom", output / kind],
                    output / (kind + "-crc-audit.log"))
            command([sys.executable, SOURCE / "audit_uart_contract.py", "--rom", output / kind,
                     "--reference-hz", "7372800", "--baud", "460800", "--out",
                     output / kind / "uart-machine-code-audit.json"], output / (kind + "-uart-audit.log"))
        command([sys.executable, SOURCE / "test_uart_contract.py"], output / "uart-contract-tests.log")
        elf = output / "netboot/bootrom.elf"
        command(["riscv64-unknown-elf-nm", "-n", elf], output / "symbols.log")
        symbols = {}
        for line in (output / "symbols.log").read_text().splitlines():
            fields = line.split()
            if len(fields) == 3:
                symbols[fields[2]] = int(fields[0], 16)
        if symbols["__bss_end"] > symbols["__boot_stack_top"] - 8192:
            raise RuntimeError("less than 8 KiB boot stack")
        contract = json.loads((output / "netboot/bootrom-contract.json").read_text())
        if not contract.get("netboot_posted_rx") or contract.get("netboot_request_windowsize") != 4:
            raise RuntimeError("acceptance built legacy-only image instead of posted RX candidate")
        report.update(status="passed", protocol_cases=34, window_protocol_cases=int(window_result[1]),
                      capacity_matrix_cases=10, invalid_capacity_cli_cases=3, mmio_order_cases=32, posted_mmio_cases=22, store_alignment_cases=4162, monitor_recovery_cases=27,
                      host_tool_tests=int(host_result[1]), python_c_interop_cases=8, uart_tool_tests=int(uart_result[1]), compiled_uart_contract_verified=True,
                      rx_dma_buffers_and_globals_bytes=symbols["__bss_end"] - symbols["__app_stack_top"],
                      boot_stack_reserved_bytes=8192, rom_capacity_bytes=131072,
                      netboot_rom_bytes=(output / "netboot/bootrom.bin").stat().st_size,
                      netboot_rom_sha256=sha(output / "netboot/bootrom.bin"),
                      uart_rom_sha256=sha(output / "uart-only/bootrom.bin"))
        if before != {str(p.relative_to(ROOT)): sha(p) for p in sources}:
            raise RuntimeError("source drift")
    except BaseException as error:
        report.update(status="failed", failure=str(error))
        raise
    finally:
        (output / "receipt.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("status", "netboot_rom_bytes", "protocol_cases", "host_tool_tests")}))

if __name__ == "__main__":
    main()
