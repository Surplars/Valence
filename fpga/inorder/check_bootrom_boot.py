#!/usr/bin/env python3
"""Bounded real-CPU ROM/UART GSIM proof; no physical multi-clock simulation claim."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "simulator/gsim"))
import run as common


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def simulation_flags(board_flags):
    return [x for x in board_flags if x != "--soc-managed-uart" and
            not x.startswith(("--soc-user-chain=", "--soc-jtag-scan-bits="))]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--board-manifest", type=Path, required=True)
    ap.add_argument("--short-receipt", type=Path,
        help="fresh completed CPU short proof; preserve the board clock/BootROM flags")
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    board = json.loads(args.board_manifest.read_text())
    flags = simulation_flags(board["flags"])
    required = {"--soc-clock-hz=300000000", "--icache=32768", "--dcache=32768", "--soc-jtag"}
    if not required.issubset(flags) or "--soc-no-bootrom" in flags:
        ap.error("exact CPU300 I/D32KiB JTAG-wait BootROM configuration required")
    frozen = dict(board["source_sha256"])
    if args.short_receipt:
        from board_short_proof import (BANDWIDTH42, BANDWIDTH43, BANDWIDTH44, validate_bandwidth41,
            validate_bandwidth42, validate_bandwidth43, validate_bandwidth44)
        short = json.loads(args.short_receipt.read_text())
        validate = {BANDWIDTH42: validate_bandwidth42, BANDWIDTH43: validate_bandwidth43,
                    BANDWIDTH44: validate_bandwidth44}.get(
            short.get("status"), validate_bandwidth41)
        selected, _ = validate(short, args.short_receipt, ROOT)
        selected = [x for x in selected if x != "--soc-no-bootrom"] + [
            "--soc-managed-uart", "--soc-jtag", "--soc-user-chain=2", "--soc-jtag-scan-bits=65"]
        if selected != board["flags"]:
            ap.error("new short proof must preserve exact board flags")
        frozen = dict(short["source_sha256"])
    for p in (Path(__file__), HERE / "tests/bootrom_uart.cpp", HERE / "bootrom/build.py",
              HERE / "bootrom/start.S", HERE / "bootrom/link.ld"):
        frozen[str(p.relative_to(ROOT))] = sha(p)
    def audit_sources():
        for name, digest in frozen.items():
            if sha(ROOT / name) != digest:
                raise RuntimeError("source/oracle changed: " + name)
    audit_sources()
    out = args.output.resolve(); out.mkdir(parents=True, exist_ok=False)
    receipt = {"status": "RUNNING", "source_sha256": frozen, "board_flags": board["flags"],
        "simulation_flags": flags, "checks": {}, "physical_qualified": False,
        "scope": "Real CPU+ROM+TL/MMIO+UART TX decode, single CPU300 clock; physical UART50 CDC not simulated",
        "base_board_manifest": str(args.board_manifest.resolve()), "base_board_manifest_sha256": sha(args.board_manifest)}
    if args.short_receipt:
        receipt["short_receipt"] = str(args.short_receipt.resolve())
        receipt["short_receipt_sha256"] = sha(args.short_receipt)
    def save():
        (out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    save()
    try:
        common.run([sys.executable, HERE / "bootrom/build.py", "--output", out / "firmware"], log=out / "rom-build.log")
        golden = ROOT / "src/main/resources/inorder/bootrom.hex"
        if (out / "firmware/bootrom.hex").read_bytes() != golden.read_bytes():
            raise RuntimeError("source BootROM differs from fresh assembled firmware")
        receipt["rom_sha256"] = sha(golden)
        gs = Path("/home/openion/Valence/simulator/build/gsim-src")
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=gs, text=True).strip()
        if revision != common.LOCK["revision"] or subprocess.check_output(
                ["git", "status", "--porcelain", "--untracked-files=no"], cwd=gs, text=True):
            raise RuntimeError("pinned GSIM source mismatch")
        gsim = gs / "build/gsim/gsim"
        cxx, version = common.compiler()
        receipt["tools"] = {"gsim_revision": revision, "gsim_sha256": sha(gsim), "cxx": version}
        directory = out / "cpu"; directory.mkdir()
        common.run(["mill", "-i", "OrbitalI1.test.runMain", "inorder.FiveStageSocGsimMain",
            directory, "64", *flags], log=directory / "elaborate.log")
        original = (directory / "FiveStageSoc.fir").read_text()
        normalized, count = re.subn(r"(?m)^(\s*smem dataWays_\S+ : [^\n,]+), old(?= @\[[^\n]*$)", r"\1 old", original)
        parser = directory / "FiveStageSoc.gsim-input.fir"; parser.write_text(normalized + "\n")
        receipt["parser_compat"] = {"only_old_delimiter_count": count, "read_under_write": "old"}
        common.run([gsim, "--threads=1", "--dir=" + str(directory), parser], log=directory / "generate.log", timeout=900)
        options = [cxx, "-std=c++20", "-O1", "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                   "-I" + str(directory)]
        def compile_one(source):
            common.run([*options, "-c", source, "-o", source.with_suffix(".o")],
                log=directory / (source.stem + "-compile.log"), timeout=900)
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(compile_one, sorted(directory.glob("FiveStageSoc[0-9]*.cpp"))))
        binary = directory / "bootrom-uart"
        common.run([*options, "-DDUT_XLEN=64", "-I" + str(ROOT / "simulator/gsim/harness"),
            *sorted(directory.glob("FiveStageSoc[0-9]*.o")), HERE / "tests/bootrom_uart.cpp", "-o", binary],
            log=directory / "link.log", timeout=900)
        env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}
        common.run([binary, golden], log=out / "boot.log", env=env, timeout=300)
        if "I1_BOOTROM_UART_PASS" not in (out / "boot.log").read_text():
            raise RuntimeError("positive boot marker missing")
        receipt["checks"]["real_cpu_uart"] = (out / "boot.log").read_text().strip()
        empty = out / "empty-rom.hex"; empty.write_text("0000000000000000\n" * 512)
        for name, argv, error in (
                ("wrong-banner", [golden, "--wrong-banner"], "independent UART banner mismatch"),
                ("empty-rom", [empty], "BootROM execution trap")):
            result = subprocess.run([str(binary), *map(str, argv)], cwd=ROOT, env=env,
                capture_output=True, text=True, timeout=300)
            log = result.stdout + result.stderr; (out / (name + ".log")).write_text(log)
            if result.returncode != 1 or error not in log:
                raise RuntimeError("expected negative control rejection missing: " + name)
            receipt["checks"][name] = "PASS_EXPECTED_REJECTION"
        audit_sources()
        receipt["artifact_sha256"] = {str(p.relative_to(out)): sha(p) for p in out.rglob("*")
            if p.is_file() and p.name != "receipt.json"}
        receipt["status"] = "PASS_I1_BOOTROM_UART_SHORT"
        save(); print(receipt["checks"]["real_cpu_uart"], flush=True)
    except Exception as exc:
        receipt.update(status="FAIL", error=str(exc)); save(); raise


if __name__ == "__main__":
    main()
