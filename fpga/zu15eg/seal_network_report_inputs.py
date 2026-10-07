#!/usr/bin/env python3
"""Seal read-only report recovery after successful own route and Tcl failure."""
import argparse
import json
from pathlib import Path
import re
import shutil
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_native_release_contract import require, sha
from audit_native_rv64gc import checked_source_map


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("candidate", type=Path)
    p.add_argument("--repo", type=Path, required=True)
    a = p.parse_args()
    root, repo = a.candidate.resolve(), a.repo.resolve()
    manifest = root / "inputs.json"
    data = json.loads(manifest.read_text())
    require(data.get("calibration_recovery_r2_sealed") and not data.get("report_recovery_sealed"), "Only own unreleased completed route")
    require(not (root / "release-rv64gc100-u460800-r4").exists(), "Do not change released inputs")
    for name, digest in data["candidate_sha256"].items():
        require(sha(root / name) == digest, "Frozen input drift: " + name)
    for name, digest in checked_source_map(data).items():
        require(sha(repo / name) == digest, "Source drift: " + name)
    log = root / "build-r7.log"
    text = log.read_text()
    require("route_design completed successfully" in text and 'invalid command name "redirect"' in text, "Not the documented post-route Tcl failure")
    require(not re.search(r"^(?:ERROR:|CRITICAL WARNING:)", text, re.M), "Unexpected implementation errors")
    require("PASS_REAL_THREE_CONTROLLER_CALIBRATION_READINESS" in text.split("route_design completed successfully")[-1], "Post-route calibration review absent")
    dcp = root / "implementation-report-recovery-r1/routed.dcp"
    digest = sha(dcp)
    evidence = root / "evidence/route-report-recovery.json"
    require(not evidence.exists(), "Preserve recovery evidence")
    evidence.parent.mkdir(exist_ok=True)
    evidence.write_text(json.dumps(dict(status="OWN_ROUTE_COMPLETED_POST_ROUTE_REPORT_TCL_RECOVERY_REQUIRED", dcp_sha256=digest, implementation_log_sha256=sha(log), failure='Unsupported post-route redirect command; successful route preserved', timing_constraints_relaxed=False, physical_board_verified=False), indent=2) + "\n")
    previous = sha(manifest)
    backup = root / "inputs-before-report-recovery.json"
    require(not backup.exists(), "Preserve prior ledger")
    shutil.copy2(manifest, backup)
    for name in ("recover_netboot_reports.tcl", "seal_network_report_inputs.py"):
        target = root / "scripts" / name
        require(not target.exists(), "Preserve existing tool")
        shutil.copy2(repo / "fpga/zu15eg" / name, target)
        data["candidate_sha256"][str(target.relative_to(root))] = sha(target)
    data["candidate_sha256"][str(evidence.relative_to(root))] = sha(evidence)
    data["new_evidence"]["route_report_recovery"] = dict(path=str(evidence), sha256=sha(evidence))
    data["own_routed_checkpoint_sha256"] = digest
    data["previous_candidate_manifest_sha256"] = previous
    data["report_recovery_sealed"] = True
    data["limits"].append("Own Explore route passed; unsupported post-route redirect failed after checkpoint save. Fresh read-only reporting reopens that exact DCP; no synthesis/place/route rerun or exception change.")
    manifest.write_text(json.dumps(data, indent=2) + "\n")
    print("PASS_OWN_ROUTE_REPORT_RECOVERY_INPUTS_SEALED", sha(manifest), "DCP", digest)


if __name__ == "__main__":
    main()
