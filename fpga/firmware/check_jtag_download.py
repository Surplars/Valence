#!/usr/bin/env python3
"""Focused host-native BootROM JTAG proof; no Scala, GSIM, OpenOCD or board run."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cc", default="cc")
    parser.add_argument("--no-sanitize", action="store_true")
    args = parser.parse_args()
    source = Path(__file__).resolve().parent
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=True)
    paths = [source / name for name in (
        "bootrom.c", "boot_tui.h", "jtag_download.h", "crc32.c", "crc32.h", "board_memory.h",
        "ram_verify.h", "test_bootrom_jtag.c", "test_bootrom_menu.c",
        "test_bootrom_recovery.c", "test_uart_only_pending.c", "check_jtag_download.py")]
    def hashes():
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    before = hashes()
    flags = ["-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror"]
    if not args.no_sanitize:
        flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}
    report = dict(status="running", scope="host-native software and modeled MMIO only",
                  source_sha256=before, sanitized=not args.no_sanitize,
                  hardware_verified=False, board_verified=False, profiles={})
    try:
        tests = []
        for menu in (False, True):
            for network in (False, True):
                name = ("menu" if menu else "legacy") + ("-network" if network else "-uart")
                defines = (["-DBOOT_MENU=1"] if menu else []) + (["-DBOARD_NETBOOT=1"] if network else [])
                tests.append((name, "test_bootrom_jtag", defines, "BOOTROM_JTAG_PASS"))
        tests += [(name, name, [], witness) for name, witness in (
            ("test_bootrom_menu", "BOOTROM_MENU_PASS"),
            ("test_bootrom_recovery", "BOOTROM_UART_RECOVERY_PASS"),
            ("test_uart_only_pending", "UART_ONLY_PENDING_PASS"))]
        for name, test, defines, witness in tests:
            binary = output / name
            command = [args.cc, *flags, *defines, str(source / (test + ".c")),
                       str(source / "crc32.c"), "-o", str(binary)]
            with (output / (name + "-compile.log")).open("w") as stream:
                subprocess.run(command, env=env, stdout=stream, stderr=subprocess.STDOUT,
                               check=True, timeout=120)
            result = subprocess.run([str(binary)], env=env, capture_output=True,
                                    text=True, timeout=30)
            (output / (name + ".log")).write_text(result.stdout + result.stderr)
            result.check_returncode()
            found = re.search(r"\b" + witness + r" cases=(\d+)\b", result.stdout)
            if not found:
                raise RuntimeError("missing success witness: " + name)
            report["profiles"][name] = int(found.group(1))
            print(result.stdout.strip())
        if hashes() != before:
            raise RuntimeError("source changed during test run")
        report["status"] = "passed"
    except BaseException as error:
        report.update(status="failed", failure=str(error))
        raise
    finally:
        (output / "receipt.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
