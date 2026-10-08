#!/usr/bin/env python3
"""Freeze source identity and export one FPGA-next profile; never run Vivado.

The reference source hashes bind what was actually emitted, not the historical
baseline commit label. Staging a local implementation is a separate operation.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sources():
    files = [p for folder in ("src/main/scala", "third_party/berkeley-hardfloat/src/main/scala")
             for p in (ROOT / folder).rglob("*.scala")]
    files += [ROOT / name for name in ("build.mill", ".mill-version",
        "src/test/scala/ooo/FpgaNextMain.scala", "fpga/next/baseline.json", "fpga/next/export.py")]
    # Blackbox SV/resources are functional source, never omit them from a binding.
    for folder in ("src/main/resources", "fpga/next/rtl"):
        if (ROOT / folder).exists():
            files += [p for p in (ROOT / folder).rglob("*") if p.is_file()]
    return {p.relative_to(ROOT).as_posix(): sha(p) for p in sorted(set(files))}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--experimental-jtag-stub", action="store_true",
                    help="emit unqualified TAP/DTM with fail-only endpoint; never enables CPU halt/resume")
    ap.add_argument("--experimental-trispeed-ethernet", action="store_true",
                    help="emit logic-qualified tri-speed media; native clocks/pads/CDC remain unqualified")
    choice = ap.add_mutually_exclusive_group()
    choice.add_argument("--reference", action="store_true", help="emit register-topology control with common correctness fixes")
    choice.add_argument("--storage-candidate", action="store_true", help="emit the earlier storage-only candidate for ablation")
    ap.add_argument("--emit", action="store_true", help="actually elaborate; default only validates the locked profile")
    ap.add_argument("--virtual-ram-load-precheck", action="store_true")
    ap.add_argument("--independent-fetch-payload-capture", action="store_true")
    ap.add_argument("--owner-local-issue-ready", action="store_true")
    ap.add_argument("--shared-fetch-pmp-relations", action="store_true")
    ap.add_argument("--share-protected-head-payload", action="store_true")
    ap.add_argument("--banked-instruction-data", action="store_true")
    ap.add_argument("--prefetch-break-on-store", action="store_true")
    ap.add_argument("--prefetch-candidate-cycles", type=int, choices=(1, 3, 16), default=1)
    a = ap.parse_args()
    profile = json.loads((HERE / "baseline.json").read_text())
    selected = not (a.reference or a.storage_candidate)
    features = {
        "independent_fetch_payload_capture": selected or a.independent_fetch_payload_capture,
        "owner_local_issue_ready": selected or a.owner_local_issue_ready,
        "shared_fetch_pmp_relations": selected or a.shared_fetch_pmp_relations,
        "share_protected_head_payload": selected or a.share_protected_head_payload,
        "banked_instruction_data": selected or a.banked_instruction_data}
    if a.reference and features["share_protected_head_payload"]:
        ap.error("protected head sharing requires the banked issue payload in a candidate profile")
    complete = not a.reference and all(features.values())
    profile["profile"].update(features)
    profile["profile"]["name"] = "fpga-next-selected-v2" if complete else (
        "fpga-next-reference-topology-v1" if a.reference else "fpga-next-storage-v1")
    if not complete:
        for key, suffix in (("independent_fetch_payload_capture", "fetch-capture"),
            ("owner_local_issue_ready", "owner-ready"), ("shared_fetch_pmp_relations", "shared-pmp"),
            ("share_protected_head_payload", "shared-head"), ("banked_instruction_data", "banked-idata")):
            if features[key]:
                profile["profile"]["name"] += "-" + suffix
    profile["profile"]["prefetch_candidate_cycles"] = a.prefetch_candidate_cycles
    if a.prefetch_candidate_cycles != 1:
        profile["profile"]["name"] += "-prefetch-retry" + str(a.prefetch_candidate_cycles)
    profile["profile"]["prefetch_break_on_store"] = a.prefetch_break_on_store
    if a.prefetch_break_on_store:
        profile["profile"]["name"] += "-store-break"
    profile["profile"]["virtual_ram_load_precheck"] = a.virtual_ram_load_precheck
    if a.virtual_ram_load_precheck:
        profile["profile"]["name"] += "-virtual-precheck"
    profile["profile"]["experimental_trispeed_ethernet"] = a.experimental_trispeed_ethernet
    profile["profile"]["tri_speed_tx_frame_slots"] = 2 if a.experimental_trispeed_ethernet else 1
    if a.experimental_trispeed_ethernet:
        profile["profile"]["name"] += "-experimental-trispeed"
    profile["profile"]["banked_issue_payload"] = not a.reference
    profile["profile"]["banked_fetch_hints"] = not a.reference
    profile["profile"]["fp_state_ram"] = not a.reference
    profile["profile"]["fp_shared_rounders"] = not a.reference
    profile["profile"]["banked_cache_tags"] = not a.reference
    profile["profile"]["fp_shared_product"] = not a.reference
    profile["profile"]["jtag_pins_reserved"] = True
    profile["profile"]["jtag_transport_experimental"] = a.experimental_jtag_stub
    profile["profile"]["debug_module_implemented"] = False
    before = sources()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        raise RuntimeError("unresolved source revision")
    output = a.output.resolve()
    if output.exists():
        raise RuntimeError("refusing existing export output: " + str(output))
    if not a.emit:
        print(json.dumps({"status": "PREFLIGHT_ONLY", "profile": profile["profile"]["name"],
            "git_head": head, "source_files": len(before), "output": str(output),
            "virtual_ram_load_precheck": a.virtual_ram_load_precheck,
            "physical_qualification": False}, indent=2))
        return
    output.mkdir(parents=True)
    rtl = output / "rtl"
    command = ["mill", "-i", "IonSoC.test.runMain", "ooo.FpgaNextMain", str(rtl)]
    command.append("--reference" if a.reference else "--candidate" if a.storage_candidate else "--selected")
    if a.share_protected_head_payload:
        command.append("--share-protected-head-payload")
    if a.banked_instruction_data:
        command.append("--banked-instruction-data")
    if a.owner_local_issue_ready:
        command.append("--owner-local-issue-ready")
    if a.shared_fetch_pmp_relations:
        command.append("--shared-fetch-pmp-relations")
    if a.experimental_trispeed_ethernet:
        command.append("--experimental-trispeed-ethernet")
    if a.independent_fetch_payload_capture:
        command.append("--independent-fetch-payload-capture")
    if a.experimental_jtag_stub:
        command.append("--experimental-jtag-stub")
    if a.prefetch_break_on_store:
        command.append("--prefetch-break-on-store")
    if a.prefetch_candidate_cycles != 1:
        command.append("--prefetch-candidate-cycles=" + str(a.prefetch_candidate_cycles))
    if a.virtual_ram_load_precheck:
        command.append("--virtual-ram-load-precheck")
    receipt = {"schema": "valence-fpga-next-export-v1", "status": "RUNNING",
        "baseline_source_commit": profile["source_commit"], "git_head": head,
        "source_sha256": before, "profile": profile["profile"],
        "virtual_ram_load_precheck": a.virtual_ram_load_precheck,
        "command": command, "synthesis": False, "physical_qualification": False}
    try:
        started = time.monotonic()
        with (output / "elaborate.log").open("w") as stream:
            result = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, timeout=1800)
        receipt["seconds"] = time.monotonic() - started
        receipt["exit"] = result.returncode
        if result.returncode:
            raise RuntimeError("RTL export failed; see " + str(output / "elaborate.log"))
        if before != sources():
            raise RuntimeError("source changed during export")
        inventory = {p.relative_to(output).as_posix(): sha(p) for p in sorted(rtl.rglob("*")) if p.is_file()}
        if not inventory or not any(name.endswith(".sv") for name in inventory):
            raise RuntimeError("no SystemVerilog export")
        # firtool's list can omit HasBlackBoxResource source. Add only the
        # explicitly audited debug resource; never glob verification layers.
        listed = []
        filelist = rtl / "filelist.f"
        if filelist.exists():
            listed = [line.strip() for line in filelist.read_text().splitlines()
                      if line.strip() and not line.strip().startswith("#")]
        if not listed:
            listed = ["FpgaNextSocTop.sv"]
        if a.experimental_jtag_stub:
            resource = rtl / "ValenceJtagDebugPort.sv"
            if not resource.is_file():
                raise RuntimeError("enabled debug resource missing from export")
            if resource.name not in listed:
                listed.append(resource.name)
        for name in listed:
            item = Path(name)
            if item.is_absolute() or ".." in item.parts or not (rtl / item).is_file():
                raise RuntimeError("unsafe/missing synthesis filelist item: " + name)
        (output / "synthesis-files.f").write_text("".join("rtl/" + name + "\n" for name in listed))
        receipt["synthesis_filelist_sha256"] = sha(output / "synthesis-files.f")
        receipt["rtl_sha256"] = inventory
        receipt["status"] = "PASS_RTL_EXPORT_ONLY"
        receipt["limitations"] = ["No FPGA synthesis, routed timing, CDC or board qualification",
            "External DDR, clock, UART/GMAC domain and PHY wrappers still require matched board integration",
            "No bitstream generated"]
    except BaseException as error:
        receipt["status"] = "FAIL"
        receipt["error"] = str(error)
        raise
    finally:
        if (output / "elaborate.log").exists():
            receipt["log_sha256"] = sha(output / "elaborate.log")
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print("PASS_RTL_EXPORT_ONLY " + str(output / "receipt.json"))


if __name__ == "__main__":
    main()
