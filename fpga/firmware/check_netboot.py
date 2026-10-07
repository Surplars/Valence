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
    args = parser.parse_args()
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=False)
    sources = [SOURCE / p for p in ("crc32.c", "crc32.h", "test_crc32.py", "audit_crc32.py", "netboot.c", "netboot.h", "netboot_board.c", "netboot_host.py",
               "test_netboot.cpp", "test_netboot_host.py", "bootrom.c", "bootrom.ld",
               "start.S", "build.py", "check_netboot.py", "valence_gmac.h", "board_memory.h",
               "test_netboot_board.c", "test_bootrom_recovery.c", "uart_load.py", "test_uart_load.py",
               "audit_uart_contract.py", "test_uart_contract.py")]
    before = {str(p.relative_to(ROOT)): sha(p) for p in sources}
    report = {"status": "running", "source_sha256": before,
              "scope": "portable protocol + scripted MMIO/monitor + host tools + bare-metal builds; NOT PHY/CDC/board/timing",
              "ddr_bytes": 0x80000000, "cpu_hz": 100000000, "timebase_hz": 100000000,
              "uart_baud": 460800, "netboot_rx_stop_abi": 2,
              "full_wire_length_tested": 66348776,
              "on_board_verified": False, "routed_timing_verified": False,
              "boot_policy": "SoC pulls TFTP; static IPv4; UART recovery",
              "ip": "192.168.137.30", "server": "192.168.137.1", "filename": "valence.vld"}
    try:
        command([sys.executable, SOURCE / "test_crc32.py"], output / "crc-equivalence.log")
        command(["clang-19", "-std=c11", "-O1", "-g", "-fsanitize=address,undefined",
                 "-fno-sanitize-recover=all", "-Wall", "-Wextra", "-Werror", "-c",
                 SOURCE / "netboot.c", "-o", output / "netboot.o"], output / "compile-c.log")
        command(["clang-19", "-std=c11", "-O1", "-g", "-fsanitize=address,undefined",
                 "-fno-sanitize-recover=all", "-Wall", "-Wextra", "-Werror", "-c",
                 SOURCE / "crc32.c", "-o", output / "crc32.o"], output / "compile-crc.log")
        command(["clang++-19", "-std=c++20", "-O1", "-g", "-fsanitize=address,undefined",
                 "-fno-sanitize-recover=all", "-Wall", "-Wextra", "-Werror",
                 SOURCE / "test_netboot.cpp", output / "netboot.o", output / "crc32.o", "-o", output / "test-netboot"],
                output / "compile-tests.log")
        command([output / "test-netboot"], output / "protocol-tests.log")
        if "BOOTROM_TFTP_HOST_PASS cases=34" not in (output / "protocol-tests.log").read_text():
            raise RuntimeError("protocol success witness missing")
        for test, witness, extra in (("test_netboot_board", "BOOTROM_MMIO_ORDER_PASS cases=30", [SOURCE / "netboot.c"]),
                                     ("test_bootrom_recovery", "BOOTROM_UART_RECOVERY_PASS cases=20", [])):
            command(["clang-19", "-std=c11", "-O1", "-g", "-fsanitize=address,undefined",
                     "-fno-sanitize-recover=all", "-Wall", "-Wextra", "-Werror",
                     SOURCE / (test + ".c"), *extra, output / "crc32.o", "-o", output / test], output / (test + "-compile.log"))
            command([output / test], output / (test + ".log"))
            if witness not in (output / (test + ".log")).read_text():
                raise RuntimeError("firmware state-machine witness missing: " + test)
        command([sys.executable, SOURCE / "test_netboot_host.py"], output / "host-tool-tests.log")
        command([sys.executable, SOURCE / "test_uart_load.py"], output / "uart-tool-tests.log")
        uart_result = re.search(r"Ran (\d+) tests? in", (output / "uart-tool-tests.log").read_text())
        if not uart_result or int(uart_result[1]) == 0:
            raise RuntimeError("UART tool test count missing")
        host_result = re.search(r"Ran (\d+) tests? in", (output / "host-tool-tests.log").read_text())
        if not host_result or int(host_result[1]) == 0:
            raise RuntimeError("host tool test count missing")
        for kind, flags in (("netboot", ["--netboot"]), ("uart-only", [])):
            command([sys.executable, SOURCE / "build.py", "--out", output / kind, "--ddr",
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
        report.update(status="passed", protocol_cases=34, mmio_order_cases=30, monitor_recovery_cases=20,
                      host_tool_tests=int(host_result[1]), uart_tool_tests=int(uart_result[1]), compiled_uart_contract_verified=True,
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
