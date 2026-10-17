#!/usr/bin/env python3
"""I1 scan-length-only update: short xsim + loader GSIM, not a CPU rerun."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
CHANGED = (
    "src/main/scala/core/inorder/I1BscanRamTransport.scala",
    "src/main/scala/core/inorder/FiveStageFpgaShell.scala",
    "src/main/scala/core/inorder/I1PeripheralFpgaShell.scala",
    "src/main/scala/core/inorder/I1NetworkFpgaShell.scala",
    "src/test/scala/inorder/FiveStageSocMain.scala",
    "src/test/scala/inorder/I1FloatingPointMain.scala",
    "src/test/scala/inorder/FiveStageConfigSpec.scala")
EXTRA = ("src/main/resources/inorder/ValenceI1BscanDebugPort.sv",
    "src/main/resources/inorder/ValenceI1DmiCdc.sv",
    "simulator/jtag/i1_dual_tap_tb.sv", "simulator/jtag/run_xsim.py",
    "fpga/inorder/check_jtag_chain.py", "fpga/inorder/check_cdc.py",
    "fpga/inorder/check_jtag_update.py")

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def read(path):
    return json.loads(path.read_text())

def verify_external(path, status):
    receipt = read(path)
    if receipt["status"] != status:
        raise RuntimeError("explicit complete xsim PASS required: " + str(path))
    for key, digest in receipt["source_sha256"].items():
        if sha(ROOT / key.replace("\\", "/")) != digest:
            raise RuntimeError("xsim source drift: " + key)
    for key, digest in receipt["artifact_sha256"].items():
        if sha(path.parent / key.replace("\\", "/")) != digest:
            raise RuntimeError("xsim artifact drift: " + key)
    return receipt

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--chain-receipt", type=Path, required=True)
    ap.add_argument("--protocol-receipt", type=Path, required=True)
    ap.add_argument("--base-receipt", type=Path, default=ROOT /
        "build/gsim/i1-cpu-timing34-20261017-r1/receipt.json")
    ap.add_argument("--base-board", type=Path, default=Path(
        "/mnt/e/VM/Share/Valence-rtl/orbital-i1-cpu300-board-20261017-r9"))
    args = ap.parse_args()
    base = read(args.base_receipt)
    if (base["status"] != "PASS_I1_CPU_TIMING34_AFFECTED_SHORT_ONLY" or
            len(base["checks"]) != 127 or len(base["performance_gates"]) != 18 or
            not all(base["performance_gates"].values())):
        raise RuntimeError("exact batch34 base127/18 required")
    snapshot = ROOT / "build/checkpoints/i1-batch34-before-jtag65-20261017"
    for name, digest in base["source_sha256"].items():
        if sha(snapshot / name) != digest:
            raise RuntimeError("base snapshot mismatch: " + name)
        if name not in CHANGED and sha(ROOT / name) != digest:
            raise RuntimeError("unrelated source change: " + name)
    chain = verify_external(args.chain_receipt, "PASS_I1_JTAG_SERIAL_CHAIN_XSIM")
    protocol = verify_external(args.protocol_receipt, "PASS_I1_HALF_CYCLE_CDC_XSIM_ONLY")
    if (len(chain["cases"]) != 12 or
            sum(row["status"] == "PASS" for row in chain["cases"].values()) != 7 or
            sum(row["status"] == "EXPECTED_ORACLE_REJECTION" for row in chain["cases"].values()) != 5 or
            len(protocol["cases"]) != 3):
        raise RuntimeError("complete chain/protocol cases required")
    output = args.output.resolve()
    output.mkdir(exist_ok=False)
    frozen = {name: sha(ROOT / name) for name in (*base["source_sha256"], *EXTRA)}
    receipt = dict(status="RUNNING", source_sha256=frozen, checks={},
        base_receipt=str(args.base_receipt), base_receipt_sha256=sha(args.base_receipt),
        base_board=str(args.base_board), base_board_manifest_sha256=sha(args.base_board / "board-manifest.json"),
        base_source_snapshot=str(snapshot), allowed_changed_base_sources=list(CHANGED),
        inherited_cpu_acceptance=dict(checks=127, performance_gates=18,
            cpu_tests_reexecuted=False, condition="Only listed shell/transport/test changes; export must prove identical CPU SV"),
        cpu_flags=base["cpu_flags"], performance_gates=base["performance_gates"],
        benchmarks=base["benchmarks"], stream_comparison=base["stream_comparison"],
        chain_receipt=str(args.chain_receipt), chain_receipt_sha256=sha(args.chain_receipt),
        protocol_receipt=str(args.protocol_receipt), protocol_receipt_sha256=sha(args.protocol_receipt),
        jtag_scan_bits=65, default_scan_bits=64, physical_qualified=False,
        board_qualified=False, bit_generated=False, old_vendor_phase_failure_waived=False)
    def save():
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    def run(command, log):
        result = subprocess.run([str(x) for x in command], cwd=ROOT,
            env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"},
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=300)
        (output / log).write_text(result.stdout)
        return result
    save()
    try:
        result = run(["mill", "-i", "OrbitalI1.test.testOnly", "inorder.FiveStageConfigSpec"], "scala.log")
        if result.returncode or "All tests passed." not in result.stdout or "Tests: succeeded 17, failed 0" not in result.stdout:
            raise RuntimeError("Scala configuration17 failed")
        receipt["checks"]["scala17"] = "PASS"
        for mode in ("off", "on"):
            name = "jtag-prepared-" + mode
            folder = output / name
            folder.mkdir()
            flags = ["--timing-cuts"] if mode == "on" else []
            result = run(["mill", "-i", "OrbitalI1.test.runMain", "inorder.I1JtagTimingMain",
                          folder, "64", *flags], name + "-elaborate.log")
            fir = name + "/I1JtagTimingFixture.fir"
            if result.returncode or sha(output / fir) != base["artifact_sha256"][fir]:
                raise RuntimeError("fresh GSIM fixture not identical to tested base: " + name)
            binary = args.base_receipt.parent / name / "run"
            if sha(binary) != base["artifact_sha256"][name + "/run"]:
                raise RuntimeError("verified GSIM binary drift")
            receipt.setdefault("exact_compilation_reuse", {})[name] = dict(
                binary_sha256=sha(binary), fresh_fir_sha256=sha(output / fir), pass_reused=False)
            for suffix, options, reject in (
                    ("positive", [], None), ("metadata", [], None),
                    ("readback-negative", ["--corrupt-readback"], "independent RAM readback oracle mismatch"),
                    ("metadata-negative", ["--wrong-metadata"], "independent loader metadata/free-bank oracle")):
                key = name + "-" + suffix
                result = run([binary, *options], key + ".log")
                if reject:
                    if not result.returncode or reject not in result.stdout or "I1_JTAG_PREPARED_PASS" in result.stdout:
                        raise RuntimeError("GSIM negative failed to detect intended issue: " + key)
                    receipt["checks"][key] = "PASS_EXPECTED_INDEPENDENT_ORACLE_REJECTION"
                else:
                    marker = "I1_JTAG_PREPARED_PASS paired_cycle_equivalence=1 metadata_sessions=32 requests=165 writes=84 cycles=3782"
                    if result.returncode or marker not in result.stdout:
                        raise RuntimeError("GSIM loader failed: " + key)
                    receipt["checks"][key] = marker
                save()
        for name, value in chain["cases"].items():
            receipt["checks"]["xsim-chain-" + name] = value["status"]
        for name, value in protocol["cases"].items():
            receipt["checks"]["xsim-protocol-" + name] = value
        for name, digest in frozen.items():
            if sha(ROOT / name) != digest:
                raise RuntimeError("source drift during short update: " + name)
        receipt["status"] = "PASS_I1_JTAG_CHAIN35_AFFECTED_SHORT_ONLY"
    except BaseException as error:
        receipt["status"] = "FAIL"
        receipt["error"] = repr(error)
        raise
    finally:
        receipt["artifact_sha256"] = {str(p.relative_to(output)): sha(p)
            for p in output.rglob("*") if p.is_file() and p.name != "receipt.json"}
        save()
    print(receipt["status"], "checks=" + str(len(receipt["checks"])), flush=True)

if __name__ == "__main__":
    main()
