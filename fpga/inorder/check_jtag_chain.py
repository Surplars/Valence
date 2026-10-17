#!/usr/bin/env python3
"""Short source-bound I1 USER2/DAP serial-chain xsim acceptance; no board access."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCES = ("src/main/resources/inorder/ValenceI1BscanDebugPort.sv",
           "src/main/resources/inorder/ValenceI1DmiCdc.sv",
           "simulator/jtag/i1_dual_tap_tb.sv")
LEGACY = "build/checkpoints/i1-batch34-before-jtag65-20261017/" + SOURCES[0]

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def matrix():
    rows = []
    for upstream in (1, 0):
        for index, (half, phase, low, high) in enumerate(
                ((1667, 333, 19, 23), (10000, 5000, 11, 17), (2300, 719, 29, 31))):
            rows.append(dict(name=f"dual_order{upstream}_phase{index}", parameters=dict(
                DAP_UPSTREAM=upstream, SYS_HALF_PS=half, START_PHASE_PS=phase,
                TCK_LOW=low, TCK_HIGH=high), reject=None))
    rows.append(dict(name="single_tap_64_compatibility",
                     parameters=dict(WITH_DAP=0, DUT_SCAN_BITS=64), reject=None))
    for name, params, reject, mutation in (
        ("legacy_actual_rtl_reproduces", dict(LEGACY_DUT=1),
         "CHAIN_CAPABILITY_ORACLE", None),
        ("misconfigured_64_rejected", dict(DUT_SCAN_BITS=64),
         "CHAIN_CAPABILITY_ORACLE", None),
        ("weak_length_guard_detected", {}, "CHAIN_LONG_REJECTION_ORACLE", "length"),
        ("saturating_at_valid_detected", {}, "CHAIN_COUNT_SATURATION_ORACLE", "counter"),
        ("wrong_payload_oracle_detected", dict(BAD_EXPECTED=1),
         "CHAIN_READBACK_ORACLE", None)):
        rows.append(dict(name=name, parameters=params, reject=reject, mutation=mutation))
    return rows

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--vivado", type=Path, required=True)
    ap.add_argument("--case", choices=[row["name"] for row in matrix()])
    args = ap.parse_args()
    output = args.output.resolve()
    if output.exists():
        ap.error("fresh evidence directory required")
    tools = {name: args.vivado / "bin" / (name + ".bat") for name in ("xvlog", "xelab", "xsim")}
    if any(not p.is_file() for p in tools.values()):
        ap.error("explicit installed Windows Vivado xsim tools required")
    sys.path.insert(0, str(ROOT / "simulator/jtag"))
    import run_xsim as independent
    profile = independent.select_model("vivado-2025.1-xczu15eg")
    vendor = args.vivado / "data/verilog/src"
    vendor_hashes = {name: sha(vendor / name) for name in profile["source_sha256"]}
    independent.validate_vendor_hashes(profile, vendor_hashes)
    inputs = [*SOURCES, LEGACY, str(Path(__file__).relative_to(ROOT)), "simulator/jtag/run_xsim.py"]
    output.mkdir(parents=True)
    receipt = dict(schema="i1-serial-tap-v1", status="RUNNING",
        source_sha256={name: sha(ROOT / name) for name in inputs},
        installed_vendor_sha256=vendor_hashes,
        profile_simulation_only_not_physical_bsdl=profile,
        board_scan_bits=65, default_scan_bits=64, length_guard_disabled=False,
        old_unrelated_vendor_phase_failure_waived=False,
        actual_board_verified=False, physical_qualified=False, cases={})
    def save():
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    save()
    try:
        selected = [row for row in matrix() if args.case in (None, row["name"])]
        for row in selected:
            name = row["name"]
            folder = output / name
            folder.mkdir()
            paths = []
            for source in SOURCES:
                original = ROOT / (LEGACY if row["parameters"].get("LEGACY_DUT") and source == SOURCES[0] else source)
                text = original.read_text()
                if source == SOURCES[0] and row.get("mutation"):
                    before, after = (
                        ("scan_captured && shift_count == SCAN_BITS", "scan_captured")
                        if row["mutation"] == "length" else
                        ("COUNT_LIMIT = SCAN_BITS + 1", "COUNT_LIMIT = SCAN_BITS"))
                    if text.count(before) != 1:
                        raise RuntimeError("exact one-point mutation missing")
                    text = text.replace(before, after)
                target = folder / Path(source).name
                target.write_text(text)
                paths.append(target.name)
            commands = [
                [str(tools["xvlog"]), "-sv", "-work", "xil_defaultlib",
                 *paths, str(vendor / "glbl.v")],
                [str(tools["xelab"]), "-debug", "all", "-mt", "off", "-timescale", "1ns/1ps",
                 "xil_defaultlib.i1_dual_tap_tb", "xil_defaultlib.glbl", "-L", "unisims_ver"],
                [str(tools["xsim"]), "i1_chain", "-runall", "-onerror", "quit"]]
            for key, value in sorted(row["parameters"].items()):
                commands[1] += ["-generic_top", key + "=" + str(value)]
            commands[1] += ["-s", "i1_chain"]
            for index, command in enumerate(commands):
                if any('"' in token or "\n" in token for token in command):
                    raise RuntimeError("unsafe tool argument")
                actual = " ".join('"' + token + '"' for token in command)
                result = subprocess.run(actual, cwd=folder, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, text=True, timeout=120)
                (folder / f"{index}.log").write_text(result.stdout)
                if result.returncode and index != 2:
                    raise RuntimeError(f"{name} tool phase{index} failed")
            log = (folder / "2.log").read_text()
            check = dict(name=name, marker="PASS I1_DUAL_TAP", reject=row["reject"])
            status = independent.classify_run(check, result.returncode, log)
            receipt["cases"][name] = dict(status=status, parameters=row["parameters"],
                mutation=row.get("mutation"), expected_rejection=row["reject"],
                marker_lines=[line for line in log.splitlines()
                              if line.startswith("PASS I1_DUAL_TAP") or re.match(r"^\s*(Fatal:|FATAL:|ERROR:)", line)],
                source_sha256={path.name: sha(path) for path in folder.glob("*.sv")})
            save()
            print(name + " " + status, flush=True)
        for name, digest in receipt["source_sha256"].items():
            if sha(ROOT / name) != digest:
                raise RuntimeError("source drift during serial-TAP test: " + name)
        receipt["status"] = ("PASS_I1_JTAG_SERIAL_CHAIN_SELECTED_ONLY" if args.case else
                             "PASS_I1_JTAG_SERIAL_CHAIN_XSIM")
    except BaseException as error:
        receipt["status"] = "FAIL"
        receipt["error"] = repr(error)
        raise
    finally:
        receipt["artifact_sha256"] = {str(p.relative_to(output)): sha(p)
            for p in output.rglob("*") if p.is_file() and p.name != "receipt.json"}
        save()
    print(receipt["status"], flush=True)

if __name__ == "__main__":
    main()

