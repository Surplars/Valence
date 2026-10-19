#!/usr/bin/env python3
"""Short installed-xsim tests of I1 opposite-edge reset transport, not board signoff."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--vivado", type=Path, required=True)
    ap.add_argument("--vendor", action="store_true", help="Also run hash-pinned installed USER2 model phases")
    ap.add_argument("--legacy-control", action="store_true", help="Read-only original transport control, not I1 qualification")
    ap.add_argument("--vendor-only", action="store_true",
                    help="Diagnose installed-model phases only; never substitutes for protocol checks")
    args = ap.parse_args()
    if args.vendor_only and not args.vendor:
        ap.error("--vendor-only requires --vendor")
    output = args.output.resolve()
    if output.exists():
        ap.error("fresh evidence directory required")
    output.mkdir(parents=True)
    tools = {n: args.vivado / "bin" / (n + ".bat") for n in ("xvlog", "xelab", "xsim")}
    if not all(p.is_file() for p in tools.values()):
        ap.error("explicit existing Windows Vivado tools required")
    resources = [ROOT / "src/main/resources/inorder" / n for n in
                 ("ValenceI1BscanDebugPort.sv", "ValenceI1DmiCdc.sv")]
    if args.legacy_control:
        resources = [ROOT / "src/main/resources/debug" / n for n in
                     ("ValenceBscanDebugPort.sv", "ValenceJtagDebugPort.sv")]
    receipt = {"status": "RUNNING", "source_sha256": {str(p.relative_to(ROOT)): sha(p) for p in resources},
               "cases": {}, "physical_qualified": False}
    def save():
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    save()
    try:
        rows = [(name, marker, name, {}, None) for name, marker in
                (("dmi_cdc", "PASS CDC requests=101"), ("bscan_user", "PASS BSCAN_USER"),
                 ("bscan_qualification", "PASS BSCAN_QUALIFICATION"))]
        if args.vendor_only:
            rows = []
        if args.vendor:
            sys.path.insert(0, str(ROOT / "simulator/jtag"))
            import run_xsim as independent
            profile = independent.select_model("vivado-2025.1-xczu15eg")
            vendor = args.vivado / "data/verilog/src"
            hashes = {name: sha(vendor / name) for name in profile["source_sha256"]}
            independent.validate_vendor_hashes(profile, hashes)
            receipt["installed_vendor_sha256"] = hashes
            receipt["simulation_profile_not_physical_bsdl"] = profile
            for row in independent.cases("unisim", profile):
                if row["name"].startswith("vendor_phase_") or row["name"] == "vendor_bad_oracle":
                    rows.append((row["name"], row["marker"], "bscan_unisim", row["parameters"], row["reject"]))
        for name, marker, fixture, parameters, reject in rows:
            folder = output / name
            folder.mkdir()
            for p in resources:
                shutil.copy2(p, folder / p.name)
            source = ROOT / "simulator/jtag" / (fixture + "_tb.sv")
            receipt["source_sha256"][str(source.relative_to(ROOT))] = sha(source)
            # Only DUT module names are adapted. Stimulus, expected payload,
            # reset-edge assertions, watchdog and qualification ledger unchanged.
            text = source.read_text()
            if not args.legacy_control:
                text = text.replace("ValenceDmiCdc", "ValenceI1DmiCdc").replace(
                    "ValenceBscanUserTransport", "ValenceI1BscanUserTransport").replace(
                    "ValenceBscanDebugPort", "ValenceI1BscanDebugPort")
            tb = folder / source.name
            tb.write_text(text)
            files = [p.name for p in resources] + [tb.name]
            extra = []
            if fixture == "bscan_unisim":
                files.append(str(vendor / "glbl.v"))
                extra = ["xil_defaultlib.glbl", "-L", "unisims_ver"]
            for key, value in sorted(parameters.items()):
                extra += ["-generic_top", key + "=" + str(value)]
            commands = [
                [str(tools["xvlog"]), "-sv", "-work", "xil_defaultlib", *files],
                [str(tools["xelab"]), "-debug", "all", "-mt", "off", "-timescale", "1ns/1ps",
                 "xil_defaultlib." + fixture + "_tb", *extra, "-s", "i1_cdc"],
                [str(tools["xsim"]), "i1_cdc", "-runall", "-onerror", "quit"]]
            for i, command in enumerate(commands):
                # Vivado's Windows batch argument collector otherwise splits
                # an unquoted KEY=VALUE into two arguments. Quote each token;
                # no shell expansion or user-supplied command is admitted.
                if any('"' in value or "\n" in value for value in command):
                    raise RuntimeError("unsafe tool argument")
                actual = " ".join('"' + value + '"' for value in command)
                run = subprocess.run(actual, cwd=folder, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, text=True, timeout=120)
                (folder / (str(i) + ".log")).write_text(run.stdout)
                if run.returncode and not (i == 2 and reject):
                    raise RuntimeError("xsim command failed: " + name + " " + str(i))
            log = (folder / "2.log").read_text()
            if reject:
                row = dict(name=name, marker=marker, reject=reject)
                independent.classify_run(row, run.returncode, log)
                receipt["cases"][name] = "PASS_EXPECTED_INDEPENDENT_ORACLE_REJECTION"
            elif re.search(r"(?m)^\s*(Fatal:|FATAL:|ERROR:)", log) or marker not in log:
                raise RuntimeError("missing clean independent PASS: " + name)
            else:
                receipt["cases"][name] = "PASS_UNCHANGED_PROTOCOL_ORACLE"
            save()
        for name, digest in receipt["source_sha256"].items():
            if sha(ROOT / name) != digest:
                raise RuntimeError("CDC source drift: " + name)
        receipt["status"] = ("PASS_LEGACY_CONTROL_ONLY" if args.legacy_control else
                             "PASS_I1_HALF_CYCLE_CDC_XSIM_ONLY")
    except BaseException as error:
        receipt["status"] = "FAIL"
        receipt["error"] = repr(error)
        raise
    finally:
        receipt["artifact_sha256"] = {str(p.relative_to(output)): sha(p) for p in output.rglob("*")
                                      if p.is_file() and p.name != "receipt.json"}
        save()
    print(json.dumps(receipt["cases"]))
if __name__ == "__main__":
    main()
