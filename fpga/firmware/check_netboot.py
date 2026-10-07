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
    sources = [SOURCE / p for p in ("netboot.c", "netboot.h", "netboot_board.c", "netboot_host.py",
               "test_netboot.cpp", "test_netboot_host.py", "bootrom.c", "bootrom.ld",
               "start.S", "build.py", "check_netboot.py")]
    before = {str(p.relative_to(ROOT)): sha(p) for p in sources}
    report = {"status": "running", "source_sha256": before,
              "scope": "portable protocol + bare-metal builds; NOT PHY/CDC/board/timing",
              "on_board_verified": False, "routed_timing_verified": False,
              "boot_policy": "SoC pulls TFTP; static IPv4; UART recovery",
              "ip": "192.168.137.30", "server": "192.168.137.1", "filename": "valence.vld"}
    try:
        command(["clang-19", "-std=c11", "-O1", "-g", "-fsanitize=address,undefined",
                 "-fno-sanitize-recover=all", "-Wall", "-Wextra", "-Werror", "-c",
                 SOURCE / "netboot.c", "-o", output / "netboot.o"], output / "compile-c.log")
        command(["clang++-19", "-std=c++20", "-O1", "-g", "-fsanitize=address,undefined",
                 "-fno-sanitize-recover=all", "-Wall", "-Wextra", "-Werror",
                 SOURCE / "test_netboot.cpp", output / "netboot.o", "-o", output / "test-netboot"],
                output / "compile-tests.log")
        command([output / "test-netboot"], output / "protocol-tests.log")
        if "BOOTROM_TFTP_HOST_PASS cases=32" not in (output / "protocol-tests.log").read_text():
            raise RuntimeError("protocol success witness missing")
        command([sys.executable, SOURCE / "test_netboot_host.py"], output / "host-tool-tests.log")
        host_result = re.search(r"Ran (\d+) tests? in", (output / "host-tool-tests.log").read_text())
        if not host_result or int(host_result[1]) == 0:
            raise RuntimeError("host tool test count missing")
        for kind, flags in (("netboot", ["--netboot"]), ("uart-only", [])):
            command([sys.executable, SOURCE / "build.py", "--out", output / kind, "--ddr",
                     "--cpu-hz", "100000000", "--uart-divisor", "1", *flags], output / (kind + "-build.log"))
        elf = output / "netboot/bootrom.elf"
        command(["riscv64-unknown-elf-nm", "-n", elf], output / "symbols.log")
        symbols = {}
        for line in (output / "symbols.log").read_text().splitlines():
            fields = line.split()
            if len(fields) == 3:
                symbols[fields[2]] = int(fields[0], 16)
        if symbols["__bss_end"] > symbols["__boot_stack_top"] - 8192:
            raise RuntimeError("less than 8 KiB boot stack")
        report.update(status="passed", protocol_cases=32, host_tool_tests=int(host_result[1]),
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
