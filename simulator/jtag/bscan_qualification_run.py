#!/usr/bin/env python3
"""Small production-transport/CDC logical regressions, never vendor/STA proof.

Uses existing Icarus only, one process at a time, 1 GiB address-space limit and
60 second stage timeout. Binds source, exact commands, exits and peak RSS.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import resource
import shutil
import signal
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
DTM = "src/main/resources/debug/ValenceJtagDebugPort.sv"
BSCAN = "src/main/resources/debug/ValenceBscanDebugPort.sv"
ROWS = {
    "qualification": ("bscan_fault_phase_tb", "PASS BSCAN_FAULT_PHASE", [DTM, BSCAN, "simulator/jtag/bscan_fault_phase_tb.sv"]),
    "transport": ("bscan_user_tb", "PASS BSCAN_USER", [DTM, BSCAN, "simulator/jtag/bscan_user_tb.sv"]),
    "cdc": ("dmi_cdc_tb", "PASS CDC requests=101", [DTM, "simulator/jtag/dmi_cdc_tb.sv"]),
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bounded(command, log):
    def limits():
        resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))
    started = time.monotonic()
    with log.open("w") as stream:
        child = subprocess.Popen(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                                 start_new_session=True, preexec_fn=limits)
        timed_out = False
        while True:
            pid, status, usage = os.wait4(child.pid, os.WNOHANG)
            if pid:
                child.returncode = os.waitstatus_to_exitcode(status)
                break
            if time.monotonic() - started > 60:
                timed_out = True
                os.killpg(child.pid, signal.SIGKILL)
                _, status, usage = os.wait4(child.pid, 0)
                child.returncode = os.waitstatus_to_exitcode(status)
                break
            time.sleep(0.01)
    return dict(command=command, exit=child.returncode, timed_out=timed_out,
                seconds=round(time.monotonic()-started, 6), peak_rss_kib=usage.ru_maxrss,
                log=str(log), log_sha256=sha(log), memory_limit_bytes=1024**3, timeout_seconds=60)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case", choices=(*ROWS, "board_drain", "board_drain_bad_owner"), action="append")
    parser.add_argument("--board-loader-export", type=Path, help="reuse existing source-bound board export; never regenerate RTL")
    parser.add_argument("--adapt-board-loader-lifetimes", action="store_true", help="explicit exact-fixture Icarus compatibility copy, separately hashed")
    args = parser.parse_args()
    out = args.output.resolve()
    if out.exists():
        parser.error("use a fresh output directory")
    tools = {name: shutil.which(os.environ.get(name.upper(), name)) for name in ("iverilog", "vvp")}
    if not all(tools.values()):
        parser.error("existing Icarus/vvp required; no tool installation or simulator fallback")
    selected = args.case or list(ROWS)
    rows = dict(ROWS)
    external = {}
    loader_binding = None
    if any(key.startswith("board_drain") for key in selected):
        if args.board_loader_export is None:
            parser.error("board_drain requires --board-loader-export")
        directory = args.board_loader_export.resolve()
        receipt_path = directory/"receipt.json"
        binding = json.loads(receipt_path.read_text())
        rtl = directory/"rtl/JtagRamLoader.sv"
        if binding.get("status") != "PASS_RTL_EXPORT_ONLY" or binding.get("rtl_sha256", {}).get("rtl/JtagRamLoader.sv") != sha(rtl):
            parser.error("board loader RTL source binding mismatch")
        needed = ("build.mill", ".mill-version", "src/main/scala/ip/debug/JtagRamLoader.scala",
                  "src/main/scala/ip/debug/JtagDebugReservation.scala", "src/main/scala/ip/bus/RegisterPort.scala")
        for source in needed:
            if binding.get("source_sha256", {}).get(source) != sha(ROOT/source):
                parser.error("board loader source binding mismatch: " + source)
        # This runner supports only the unchanged saved board-profile fixture.
        # Verify its emitted default timeout instead of shortening production RTL.
        if "ticks == 20'hF423F" not in rtl.read_text():
            parser.error("review board loader timeout before changing the test wait")
        external = {"@board-loader/JtagRamLoader.sv": rtl, "@board-loader/receipt.json": receipt_path}
        loader_binding = dict(receipt_sha256=sha(receipt_path), rtl_sha256=sha(rtl),
                              source_sha256={source: sha(ROOT/source) for source in needed},
                              timeout_cycles=1000000, saved_board_export=True,
                              native_64_cycle_fixture=False, profile=binding.get("profile"))
        for key in ("board_drain", "board_drain_bad_owner"):
            rows[key] = ("loader_cdc_drain_tb", "LOADER_CDC_DRAIN_PASS",
                         [DTM, "@board-loader/JtagRamLoader.sv", "simulator/jtag/loader_cdc_drain_tb.sv"])
    if args.adapt_board_loader_lifetimes and loader_binding is None:
        parser.error("lifetime adapter is only valid with the reviewed board loader")
    def resolve(name):
        return external[name] if name in external else ROOT/name
    inputs = sorted({source for key in selected for source in rows[key][2]} |
                    {"simulator/jtag/bscan_qualification_run.py"} | set(external) |
                    ({"simulator/jtag/lower_board_loader_for_icarus.py"} if args.adapt_board_loader_lifetimes else set()))
    before = {name: sha(resolve(name)) for name in inputs}
    out.mkdir(parents=True)
    staged_loader = None
    if args.adapt_board_loader_lifetimes:
        spec = importlib.util.spec_from_file_location("loader_lifetime_adapter", ROOT/"simulator/jtag/lower_board_loader_for_icarus.py")
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        adapted, adaptation = adapter.lower(external["@board-loader/JtagRamLoader.sv"].read_text())
        staged_loader = out/"adapted/JtagRamLoader.sv"
        staged_loader.parent.mkdir()
        staged_loader.write_text(adapted)
        loader_binding["lifetime_adaptation"] = adaptation
        loader_binding["adapted_path"] = str(staged_loader)
    def compile_resolve(name):
        return staged_loader if name == "@board-loader/JtagRamLoader.sv" and staged_loader else resolve(name)
    report = dict(schema="valence-bscan-qualification-v1", status="RUNNING", input_sha256=before,
                  tools=tools, cases=[], loader_binding=loader_binding, logical_pin_event_model_only=True,
                  vendor_primitive_executed=False, physical_qualification=False, board_verified=False)
    code = 0
    try:
        for key in selected:
            top, marker, sources = rows[key]
            directory = out/key
            directory.mkdir()
            binary = directory/"test.vvp"
            row = dict(name=key, top=top, status="RUNNING", stages=[])
            report["cases"].append(row)
            parameters = ["-Ploader_cdc_drain_tb.TIMEOUT_CYCLES=1000000"] if key.startswith("board_drain") else []
            negative = key == "board_drain_bad_owner"
            if negative:
                parameters.append("-Ploader_cdc_drain_tb.BAD_RESET_OWNER=1")
            commands = [[tools["iverilog"], "-g2012", "-Wall", "-s", top, "-o", str(binary),
                         *parameters, *[str(compile_resolve(source)) for source in sources]], [tools["vvp"], str(binary)]]
            for name, command in zip(("compile", "run"), commands):
                result = bounded(command, directory/(name+".log"))
                row["stages"].append(dict(stage=name, **result))
                if result["timed_out"] or (result["exit"] and not (negative and name == "run")):
                    row["status"] = "FAILED"
                    raise RuntimeError(key + " " + name + " failed")
            log = (directory/"run.log").read_text()
            if negative:
                fatals = re.findall(r'^FATAL:[^\n]*', log, re.MULTILINE)
                if len(fatals) != 1 or "DRAIN_OWNER_ORACLE" not in fatals[0] or marker in log:
                    raise RuntimeError("bad-owner mutant did not reach its exact oracle")
                row["status"] = "EXPECTED_ORACLE_REJECTION"
            else:
                if marker not in log or "FATAL" in log or "ERROR" in log:
                    raise RuntimeError(key + " missing clean explicit PASS")
                row["status"] = "PASS"
            row["binary_sha256"] = sha(binary)
        if {name: sha(resolve(name)) for name in inputs} != before:
            raise RuntimeError("source changed during focused checks")
        if staged_loader:
            adapter.verify_adapted(staged_loader.read_text())
        report["status"] = "PASS_LOGICAL_TRANSPORT_ONLY"
    except Exception as error:
        report.update(status="FAILED", error=str(error))
        code = 1
    (out/"receipt.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
