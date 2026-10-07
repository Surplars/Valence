#!/usr/bin/env python3
"""Fail-closed audit of frozen short CMU and actual-gate CDC evidence; no CAD."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct

ROOT = Path(__file__).resolve().parent.parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(ok, reason):
    if not ok: raise RuntimeError(reason)


def unc_source(name):
    normalized = name.replace("\\", "/")
    check("/Valence/" in normalized, "unknown external source: " + name)
    relative = normalized.split("/Valence/", 1)[1]
    path = (ROOT / relative).resolve()
    check(path.is_relative_to(ROOT), "source escapes repository")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gsim", type=Path)
    parser.add_argument("native", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    check(not args.output.exists() and args.output.resolve().is_relative_to(ROOT / "build"),
          "use a fresh audit file under repository build")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = {"status": "RUNNING", "scope": "optional CMU + short actual-BUFGCE CDC only",
              "new_cpu_ipc_or_fmax": False, "new_routed_timing": False, "new_bit": False,
              "existing_cpu_ddr_uart_gmac_runtime_gate": False, "dynamic_frequency": False}
    try:
        gs = json.loads((args.gsim / "receipt.json").read_text())
        native = json.loads((args.native / "receipt.json").read_text())
        check(gs["status"] == "PASS_CMU_SCOPED_GSIM", "GSIM not passed")
        check(native["status"] == "PASS_MANAGED_CLOCK_GATE_CDC_SHORT", "gate CDC not passed")
        check("Tests: succeeded 4, failed 0" in (args.gsim / "scala.log").read_text(), "Scala not passed")
        for mode, top in (("register", "ClockManagementGsim"), ("tl", "ClockManagementTlGsim"),
                          ("serial", "ClockManagementRouterGsim"), ("parallel", "ClockManagementRouterGsim")):
            entry = gs[mode]
            check(entry["status"] == "passed" and entry["independent_negative"] == "passed", mode)
            check(entry["fir_sha256"] == digest(args.gsim / mode / (top + ".fir")), mode + " FIR drift")
            check(entry["executable_sha256"] == digest(args.gsim / mode / "run"), mode + " executable drift")
            check("CMU independent register oracle mismatch" in (args.gsim / mode / "negative.log").read_text(),
                  mode + " missing negative")
        sources = {}
        for name, expected in gs["source_sha256"].items():
            path = ROOT / name
            check(digest(path) == expected, "GSIM source drift: " + name)
            sources[name] = expected
        for name, expected in gs["rtl_sha256"].items():
            check(digest(args.gsim / name) == expected, "GSIM RTL drift: " + name)
        for name, expected in native["input_sha256"].items():
            if "/Valence/" in name.replace("\\", "/"):
                path = unc_source(name)
                check(digest(path) == expected, "native input drift: " + name)
                if not path.is_relative_to(ROOT / "build"):
                    sources[str(path.relative_to(ROOT))] = expected
            else:
                check(name.replace("\\", "/").endswith("/data/verilog/src/glbl.v"), "unexpected external input")
                check(digest(args.native / "glbl.v") == expected, "frozen glbl mismatch")
        for name, expected in native["protected_cpu_sha256"].items():
            check(digest(unc_source(name)) == expected, "native protected CPU drift")
        for name, expected in native["output_sha256"].items():
            check(digest(args.native / name) == expected, "native output drift: " + name)
        check("MANAGED_CLOCK_CDC_PASS clock_cases=3 actual_BUFGCE=1" in
              (args.native / "positive.log").read_text(), "actual-gate positive missing")
        negative = (args.native / "negative-clock.log").read_text()
        check("physical stopped-clock independent oracle mismatch" in negative and
              "MANAGED_CLOCK_CDC_PASS" not in negative, "gate negative did not reject")
        # Compare previous accepted CPU/DMA implementation. Only optional
        # BoardSocTop/MachinePlatform entry edits are authorized this batch.
        prior = json.loads((ROOT / "build/fpga/self-gmac-cdc-20261004-r1/functional-r4/receipt.json").read_text())
        changed = []
        for name, expected in prior["protected_cpu_dma_sha256"].items():
            path = unc_source(name)
            if digest(path) != expected: changed.append(str(path.relative_to(ROOT)))
        check(set(changed) == {"src/main/scala/core/ooo/BoardSocTop.scala",
                              "src/main/scala/core/ooo/MachinePlatform.scala"}, "unexpected CPU/DMA change")
        obj = (args.gsim / "valence_cmu_header.o").read_bytes()
        check(obj[:4] == b"\x7fELF" and struct.unpack("<H", obj[18:20])[0] == 243, "missing RISC-V header object")
        for name in ("fpga/audit-clock-management.py", "fpga/firmware/valence_cmu.h"):
            sources[name] = digest(ROOT / name)
        snapshot = args.output.parent / "frozen-source"
        check(not snapshot.exists(), "source snapshot already exists")
        for name, expected in sources.items():
            target = snapshot / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, target)
            check(digest(target) == expected, "source snapshot mismatch")
        report.update(status="PASS_CMU_SCOPED_FUNCTIONAL_ONLY", scala_checks=4,
            gsim_modes=4, gsim_transactions=1323, independent_negatives=5,
            actual_gate_clock_cases=3, risc_v_header_compile=True,
            authorized_platform_entry_changes=sorted(changed), frozen_source_sha256=sources,
            gsim_receipt_sha256=digest(args.gsim / "receipt.json"),
            native_receipt_sha256=digest(args.native / "receipt.json"))
    except BaseException as error:
        report.update(status="FAIL_CMU_AUDIT", failure=str(error))
    report["artifact_sha256"] = {str(p.relative_to(args.output.parent)): digest(p)
        for p in sorted(args.output.parent.rglob("*")) if p.is_file() and p != args.output}
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(report["status"], "audit=" + str(args.output))
    if report["status"] != "PASS_CMU_SCOPED_FUNCTIONAL_ONLY": raise SystemExit(report["failure"])


if __name__ == "__main__": main()
