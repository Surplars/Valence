#!/usr/bin/env python3
"""Prepare or run explicit independent-edge media tests using existing Icarus.

No installer, download, Verilator or Vivado invocation is performed. The pad
bench uses declared behavioral primitives, not AMD UNISIM or analog delay data.
Export first: mill -i IonSoC.test.runMain ip.TriSpeedNativeRtlMain <rtl-dir>
A --prepare-only receipt must never be presented as executed proof.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rtl", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    here = Path(__file__).resolve().parent
    rtl, output = args.rtl.resolve(), args.output.resolve()
    if output.exists():
        parser.error("use a fresh result directory")
    tools = {name: shutil.which(name) for name in ("iverilog", "vvp")}
    if not args.prepare_only and not all(tools.values()):
        parser.error("existing iverilog/vvp required; this script cannot install tools")
    extra = [root / "fpga/zu15eg/native_rgmii_trispeed_quarter.sv",
             root / "fpga/zu15eg/native_tx_word_reset_boundary.sv",
             here / "tests/rgmii_behavioral_primitives.sv"]
    cases = (
        ("ingress", "physical_ingress_cdc_tb", [], "+bad_payload", "INGRESS_CDC_BYTE_ORACLE",
         "PHYSICAL_INGRESS_NATIVE_CDC_PASS"),
        ("tx", "trispeed_quarter_pad_tb", extra, "+bad_phase", "QUARTER_CLOCK_",
         "TRISPEED_QUARTER_PAD_BEHAVIOR_PASS"),
        ("watchdog", "rx_clock_watchdog_tb", [], "+bad_timeout", "WATCHDOG_INDEPENDENT_TIMEOUT_ORACLE",
         "RX_CLOCK_WATCHDOG_NATIVE_PASS"),
    )
    inputs = {Path(__file__).resolve(), *extra}
    for directory, top, _, _, _, _ in cases:
        files = sorted((rtl / directory).glob("*.sv"))
        if not files:
            parser.error("missing standalone export directory " + directory)
        inputs.update(files)
        inputs.add(here / "tests" / (top + ".sv"))
    missing = [str(p) for p in inputs if not p.is_file()]
    if missing:
        parser.error("missing inputs: " + ", ".join(missing))
    output.mkdir(parents=True)
    before = {str(p): sha(p) for p in sorted(inputs)}
    sources = sorted((root / "src/main/scala").rglob("*.scala"))
    sources += sorted((root / "src/test/scala").rglob("*.scala"))
    source_hashes = {str(p.relative_to(root)): sha(p) for p in sources}
    for p in inputs:
        destination = output / "inputs" / (p.relative_to(rtl) if p.is_relative_to(rtl)
                        else Path("repo") / p.relative_to(root))
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, destination)
    report = {"status": "PREPARED_NOT_RUN" if args.prepare_only else "RUNNING",
              "input_sha256": before, "source_sha256": source_hashes,
              "scope": "independent-edge ingress/epoch/watchdog and behavioral quarter-pad adapter",
              "tools": tools, "cases": {}, "independent_clock_runtime_verified": False,
              "vendor_primitive_models": False, "metastability_proven": False,
              "physical_constraints_verified": False, "on_board_verified": False,
              "synthesis_run": False, "route_run": False, "bit_generated": False,
              "export_source_binding": "requires paired source-bound RTL export receipt"}
    try:
        if not args.prepare_only:
            for name, top, additions, injection, reject, marker in cases:
                files = sorted((rtl / name).glob("*.sv")) + additions + [here / "tests" / (top + ".sv")]
                binary = output / (name + ".vvp")
                command = [tools["iverilog"], "-g2012", "-s", top, "-o", str(binary), *map(str, files)]
                result = subprocess.run(command, capture_output=True, text=True, timeout=120)
                (output / (name + "-compile.log")).write_text(result.stdout + result.stderr)
                if result.returncode:
                    raise RuntimeError(name + " compile failed")
                row = {"compile_command": command, "binary_sha256": sha(binary)}
                for label, arguments in (("positive", []), ("negative", [injection])):
                    result = subprocess.run([tools["vvp"], str(binary), *arguments],
                                            capture_output=True, text=True, timeout=180)
                    text = result.stdout + result.stderr
                    (output / (name + "-" + label + ".log")).write_text(text)
                    if label == "positive":
                        if result.returncode or marker not in text:
                            raise RuntimeError(name + " positive failed")
                        row["summary"] = [line for line in text.splitlines() if marker in line]
                    elif not result.returncode or reject not in text or marker in text:
                        raise RuntimeError(name + " negative failed to reject")
                    row[label] = "passed"
                report["cases"][name] = row
            report.update(status="PASS_BEHAVIORAL_NATIVE_MEDIA_ONLY", independent_clock_runtime_verified=True)
    except BaseException as error:
        report.update(status="FAILED", failure=str(error))
        raise
    finally:
        if before != {str(p): sha(p) for p in sorted(inputs)} or source_hashes != {
                str(p.relative_to(root)): sha(p) for p in sources}:
            report.update(status="FAILED", failure="source/RTL/bench input drift")
        report["output_sha256"] = {p.name: sha(p) for p in sorted(output.glob("*.log"))}
        (output / "receipt.json").write_text(json.dumps(report, indent=2) + "\n")
    if report["status"] == "FAILED":
        raise RuntimeError(report["failure"])
    print(report["status"] + " receipt=" + str(output / "receipt.json"))


if __name__ == "__main__":
    main()
