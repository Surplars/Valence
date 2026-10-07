#!/usr/bin/env python3
"""Audit a frozen RV64GC candidate. No simulation/CAD, no board-signoff claim."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
RUNNER = "simulator/gsim/floating_point_full.py"
OLD_LIMIT = b"F/D defaults off and misa/DT remain unadvertised."
NEW_LIMIT = (b"F/D defaults off; only explicit complete ISA profiles advertise F/D in misa/DT, "
             b"never experimental subsets.")
RUNTIME = {"fpga/firmware/rv64gc_smoke.S", "simulator/gsim/rv64gc_board.py"}


def require(condition, reason):
    if not condition:
        raise RuntimeError(reason)


def digest(path):
    with path.open("rb") as stream:
        value = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
        return value.hexdigest()


def read_json(path):
    return json.loads(path.read_text())


def metadata_only(before, current):
    return before.count(OLD_LIMIT) == 1 and current == before.replace(OLD_LIMIT, NEW_LIMIT)


def verify(root, hashes, metadata_snapshot=None):
    corrections = []
    for name, expected in hashes.items():
        path = root / name
        actual = digest(path)
        if actual == expected:
            continue
        if name == RUNNER and metadata_snapshot is not None:
            saved = metadata_snapshot / name
            require(digest(saved) == expected, "Unverified metadata snapshot: " + name)
            require(metadata_only(saved.read_bytes(), path.read_bytes()),
                    "Runner changed beyond the exact qualification-text correction")
            corrections.append({"file": name, "tested_sha256": expected, "current_sha256": actual,
                                "kind": "qualification-text-only; no DUT/test/command change"})
            continue
        raise RuntimeError("Evidence hash mismatch: " + str(path))
    return corrections


def check_controls(results):
    expected = {"numerical-fd", "numerical-f", "numerical-small", "compressed", "cpu",
                "memory-direct", "memory-buffered", "integer-disabled", "integer-enabled"}
    positive = [row for row in results if "test" in row]
    negative = [row for row in results if "negative" in row]
    require({row["test"] for row in positive} == expected and len(positive) == 9,
            "Missing focused functional test")
    require(all(row["exit"] == 0 and "PASS" in row["log"] for row in positive),
            "Functional test did not pass")
    reasons = {"numerical-fd": "FP full mismatch: SoftFloat value",
               "numerical-f": "FP full mismatch: SoftFloat value",
               "numerical-small": "FP full mismatch: SoftFloat value",
               "cpu": "FP full CPU mismatch: independent integer result",
               "integer-disabled": "commit data/nextPC", "integer-enabled": "commit data/nextPC"}
    for mode in ("direct", "buffered"):
        for suffix, message in (("--inject-mismatch", "FP CPU mismatch: commit value/metadata"),
                                ("--inject-fp-memory", "FP CPU mismatch: FP architectural RF"),
                                ("--inject-memory-request", "FP CPU mismatch: FP memory request payload")):
            reasons["memory-" + mode + suffix] = message
    require({row["negative"] for row in negative} == set(reasons) and len(negative) == 12,
            "Missing strict negative control")
    require(all(row["exit"] == 1 and reasons[row["negative"]] in row["reason"] for row in negative),
            "Negative control did not fail for the intended reason")
    cpu = next(row for row in positive if row["test"] == "cpu")
    require("misa_gc=1" in cpu["log"], "Real CPU did not verify advertised RV64GC misa")


def checked_measurement(collector, reports, rtl, saved):
    measurement = collector.collect(reports, rtl)
    require(measurement == read_json(saved), "Saved measurements no longer match RTL/reports: " + str(saved))
    require(measurement["completed_modules"] == 13, "Incomplete FPU module measurements")
    return measurement


def compare(baseline, candidate):
    rows = {}
    for name, after in candidate["modules"].items():
        before = baseline["modules"][name]
        rows[name] = {
            "internal_setup": {"before": before["paths"]["internal_max"],
                               "after": after["paths"]["internal_max"]},
            "internal_hold": {"before": before["paths"]["internal_min"],
                              "after": after["paths"]["internal_min"]},
            "boundary_setup": {"before": before["paths"]["all_max"],
                               "after": after["paths"]["all_max"]},
            "boundary_hold": {"before": before["paths"]["all_min"],
                              "after": after["paths"]["all_min"]},
            "resources": {"before": before["resources"], "after": after["resources"],
                          "delta": {key: after["resources"][key] - value
                                    for key, value in before["resources"].items()}},
        }
    return rows


def check_software_config():
    builder = ROOT / "fpga/firmware/build_linux.py"
    template = ROOT / "fpga/firmware/linux-ddr50.dts"
    spec = importlib.util.spec_from_file_location("rv64gc_linux_builder", builder)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    results = {}
    for profile, hz, baud, isa in (("rv64imac", 50000000, 115200, "rv64imac_zicsr_zifencei"),
                                  ("rv64gc", 100000000, 460800, "rv64imafdc_zicsr_zifencei")):
        text = module.board_dts(profile, hz, baud)
        require(f'riscv,isa = "{isa}";' in text and f"timebase-frequency = <{hz}>;" in text
                and f"current-speed = <{baud}>;" in text and f"clock-frequency = <{baud * 16}>;" in text,
                "ISA/timebase/UART software discovery mismatch")
        dtb = subprocess.run(["dtc", "-I", "dts", "-O", "dtb", "-"],
                             input=text.encode(), capture_output=True, check=True).stdout
        require(dtb[:4] == bytes.fromhex("d00dfeed"), "DTC did not return a DTB")
        results[profile] = {"isa": isa, "cpu_hz": hz, "uart_baud": baud,
                            "dts_sha256": hashlib.sha256(text.encode()).hexdigest(),
                            "dtb_sha256": hashlib.sha256(dtb).hexdigest()}
    return {"inputs_sha256": {str(path.relative_to(ROOT)): digest(path) for path in (builder, template)},
            "parsed_profiles": results, "kernel_built": False, "linux_runtime_qualified": False}


def check_core_report(text, design="MachineCore"):
    require("| Design            : " + design + "\n" in text and "| Design State      : Routed" in text,
            "Report is not the expected routed design: " + design)
    require("xczu15eg-ffvb1156" in text and "-2  PRODUCTION" in text,
            "Wrong device or speed grade")
    require(re.search(r"module_clock\s+\{0\.000\s+5\.000\}\s+10\.000\s+100\.000", text),
            "Core report is not constrained to 10 ns")
    for field in ("no_clock", "unconstrained_internal_endpoints", "loops", "latch_loops"):
        require(re.search(r"checking " + field + r" \(0\)", text),
                "Unconstrained/invalid core timing: " + field)
    summary = text.split("| Design Timing Summary", 1)
    require(len(summary) == 2, "Missing design timing summary")
    summary = summary[1].split("| Clock Summary", 1)[0]
    rows = [line.split() for line in summary.splitlines()
            if re.fullmatch(r"\s*-?\d+\.\d+\s+.*", line)]
    require(len(rows) == 1 and len(rows[0]) == 12, "Unrecognized timing summary row")
    row = rows[0]
    return {"wns_ns": float(row[0]), "tns_ns": float(row[1]), "setup_failures": int(row[2]),
            "whs_ns": float(row[4]), "ths_ns": float(row[5]), "hold_failures": int(row[6]),
            "wpws_ns": float(row[8]), "tpws_ns": float(row[9]), "pulse_failures": int(row[10])}


def audit(batch, board_path):
    locked = read_json(batch / "candidate-inputs.json")
    require(locked["issue_width"] == 2 and locked["isa_profile"] == "rv64gc"
            and locked["period_ns"] == 10.0, "Wrong frozen CAD configuration")
    functional_path = ROOT / locked["functional_receipt"]
    fp = read_json(functional_path)
    require(fp["status"] == "PASS_FUNCTIONAL_CANDIDATE", "No complete F/D functional receipt")
    require(len(fp["source_sha256"]) == 134 and len(fp["artifact_sha256"]) == 36,
            "Unexpected functional source/model coverage")
    snapshot = batch / "pre-opt-source"
    changes = verify(ROOT, fp["source_sha256"], snapshot)
    verify(ROOT, fp["artifact_sha256"])
    require(digest(functional_path.parent / "vectors.txt") == fp["vector_sha256"], "Vector drift")
    require(fp["softfloat_revision"] == "a0c6494cdc11865811dec815d5c0049fba9d82a8"
            and fp["gsim_revision"] == "93b8cd23edd3228807c4f2a08c19c3936a463cb2",
            "Independent reference/simulator revision changed")
    archive = ROOT / ("build/fd-handoff/20261003-windows/fd-evidence/dependencies/softfloat-"
                      + fp["softfloat_revision"] + ".zip")
    require(digest(archive) == fp["softfloat_archive_sha256"], "Independent reference archive drift")
    require(digest(ROOT / "build/gsim/nemu-src/build/riscv64-nemu-interpreter-so")
            == fp["nemu_library_sha256"], "Integer-only NEMU library drift")
    verify(functional_path.parent / "softfloat", fp["softfloat_source_sha256"])
    oracle = (functional_path.parent / "oracle-test.log").read_text()
    require("anchors=21" in oracle and "vectors=27840" in oracle, "Missing numerical anchors")
    config_log = (functional_path.parent / "configuration.log").read_text()
    require("Tests: succeeded 2, failed 0" in config_log, "Missing configuration acceptance")
    check_controls(fp["results"])
    require(locked["source_sha256"] == fp["source_sha256"], "CAD sources differ from functional batch")
    verify(ROOT, locked["source_sha256"], snapshot)
    verify(ROOT, locked["tools_sha256"])
    verify(batch, locked["rtl_sha256"])
    sv_names = {str(p.relative_to(batch)) for directory in ("candidate-rtl", "candidate-core-rtl")
                for p in (batch / directory).rglob("*.sv")}
    require(sv_names == set(locked["rtl_sha256"]), "CAD RTL input set changed")

    board = read_json(board_path)
    require(board["status"] == "PASS_BOARD_FUNCTIONAL_SMOKE" and board["issue_width"] == 2
            and board["isa"] == "rv64imafdc_zicsr_zifencei" and board["clock_profile_hz"] == 100000000
            and board["uart_baud"] == 460800, "Board smoke used another ISA/profile")
    require(len(board["source_sha256"]) == 192, "Unexpected BoardSoC source coverage")
    scala = {str(p.relative_to(ROOT)) for directory in
             ("src/main/scala", "third_party/berkeley-hardfloat/src/main/scala")
             for p in (ROOT / directory).rglob("*.scala")}
    require(scala == {name for name in board["source_sha256"] if name.endswith(".scala")
                      and not name.startswith("src/test/")}, "Board hardware source set changed")
    for mapping in (board["source_sha256"], board["files"], board["gsim_models_sha256"]):
        verify(ROOT, mapping)
    for name in set(fp["source_sha256"]) & set(board["source_sha256"]):
        require(fp["source_sha256"][name] == board["source_sha256"][name],
                "Numerical and BoardSoC tested different DUTs: " + name)
    require(board["negative_control"]["exit"] == 1
            and "firmware independent anchor/context failure" in board["negative_control"]["reason"],
            "Board negative control missing")
    require((board_path.parent / "test.log").read_text() == board["log"], "Board test log drift")
    require(board["negative_control"]["reason"] in (board_path.parent / "negative.log").read_text(),
            "Board negative log drift")
    require(board["fp_virtual_context"] == {
        "mode": "Sv39", "context_va": "0x40220000", "context_pa": "0x80220000",
        "root_pa": "0x80210000", "integer_identity_view_checked": True}, "Missing nonidentity Sv39 FP context")
    if board["reused_model"]:
        previous_path = Path(board["reused_model"]["receipt"])
        require(digest(previous_path) == board["reused_model"]["receipt_sha256"], "Reused receipt drift")
        previous = read_json(previous_path)
        require(previous["status"] == "PASS_BOARD_FUNCTIONAL_SMOKE", "Reused board model did not pass")
        require(set(board["reused_model"]["allowed_runtime_changes"]) == RUNTIME, "Excessive reuse exceptions")
        require(set(previous["source_sha256"]) == set(board["source_sha256"]), "Reused source input set drift")
        for name, sha in previous["source_sha256"].items():
            require(name in RUNTIME or sha == board["source_sha256"][name], "Reused DUT/harness changed: " + name)
        require(previous["gsim_models_sha256"] == board["gsim_models_sha256"], "Reused model differs")
        verify(ROOT, {name: sha for name, sha in previous["files"].items() if name not in RUNTIME})

    spec = importlib.util.spec_from_file_location("fp_module_results", ROOT / "fpga/collect-fp-module-results.py")
    collector = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(collector)
    baseline = checked_measurement(collector, batch / "baseline-reports", batch / "baseline-rtl",
                                   batch / "baseline-measurements.json")
    candidate = checked_measurement(collector, batch / "candidate-reports", batch / "candidate-rtl",
                                    batch / "candidate-measurements.json")
    for stage, measurement in (("baseline", baseline), ("candidate", candidate)):
        for design in measurement["modules"]:
            check_core_report((batch / (stage + "-reports") / design / "post_route_timing.rpt").read_text(), design)
    # The collector's FP top list deliberately does not include the integrated CPU.
    saved_tops = collector.TOPS
    collector.TOPS = ["MachineCore"]
    try:
        core = collector.collect(batch / "candidate-reports", batch / "candidate-core-rtl")["modules"]["MachineCore"]
    finally:
        collector.TOPS = saved_tops
    if core["status"] != "PENDING":
        core_report = batch / "candidate-reports/MachineCore/post_route_timing.rpt"
        core["timing_summary"] = check_core_report(core_report.read_text())
        require("\nRV64GC_CORE_COMPLETE\n" in (batch / "candidate-vivado.log").read_text(),
                "CAD batch did not finish the integrated core")
    pending = core["status"] == "PENDING"
    passed = (not pending and core["status"] == "INTERNAL_SETUP_HOLD_MET"
              and core["paths"]["all_max"]["slack_ns"] >= 0
              and core["timing_summary"]["tns_ns"] == 0 and core["timing_summary"]["setup_failures"] == 0
              and core["timing_summary"]["wpws_ns"] >= 0 and core["timing_summary"]["pulse_failures"] == 0
              and candidate["status"] == "INTERNAL_SETUP_HOLD_MET_BOUNDARY_UNQUALIFIED")
    return {
        "schema_version": 1,
        "status": "PENDING_CORE_ROUTE" if pending else
                  "FUNCTIONAL_AND_INTERNAL_10NS_MET_BOUNDARY_UNQUALIFIED" if passed else "INTERNAL_TIMING_FAILED",
        "isa": board["isa"], "issue_width": 2, "period_ns": 10.0,
        "proofs": {str(path.relative_to(ROOT)): digest(path) for path in
                   (functional_path, board_path, batch / "candidate-inputs.json",
                    batch / "baseline-measurements.json", batch / "candidate-measurements.json")},
        "audit_tool_sha256": digest(Path(__file__)), "metadata_corrections": changes,
        "functional_results": fp["results"], "board_context": board["fp_virtual_context"],
        "software_discovery": check_software_config(),
        "board_log": board["log"], "fpu_comparison": compare(baseline, candidate), "core": core,
        "whole_board_qualified": False, "bit_generated": False, "linux_fp_context_qualified": False,
        "limitations": ["Bounded independent tests, not exhaustive RISC-V conformance certification.",
                        "FP port remains serialized at ROB head; integer issue width is two.",
                        "OOC zero I/O delays and excluded reset are not real board budgets; boundary hold is recorded.",
                        "Integrated MachineCore excludes cache/fabric, DDR PHY, Clock Wizard and board XDC.",
                        "No new bit, FPGA F/D board test, Linux FP scheduling/signal test or independent RTL backend."],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", type=Path, default=ROOT / "build/fpga/fpu-rv64gc-20261004")
    parser.add_argument("--board", type=Path, default=ROOT / "build/gsim/rv64gc-board-20261004-sv39-context-r1/receipt.json")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    require(not args.out.exists(), "Evidence exists; choose a fresh output")
    result = audit(args.batch.resolve(), args.board.resolve())
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    print(result["status"])
    return 2 if result["status"] == "PENDING_CORE_ROUTE" else 0 if result["status"].startswith("FUNCTIONAL_") else 1


if __name__ == "__main__":
    raise SystemExit(main())
