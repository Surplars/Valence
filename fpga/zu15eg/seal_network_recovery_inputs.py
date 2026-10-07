#!/usr/bin/env python3
"""Add the supported UltraScale+ recovery tool flow before bit signoff."""
import argparse
import json
from pathlib import Path
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
    require(data.get("eco_flow_r2_sealed") and not data.get("calibration_recovery_sealed"), "Only unreleased pre-signoff recovery")
    require(not (root / "release-rv64gc100-u460800-r4").exists(), "Do not change released inputs")
    for name, digest in data["candidate_sha256"].items():
        require(sha(root / name) == digest, "Existing frozen input drift: " + name)
    for name, digest in checked_source_map(data).items():
        require(sha(repo / name) == digest, "Existing source drift: " + name)
    backup = root / "inputs-before-calibration-recovery.json"
    require(not backup.exists(), "Preserve prior recovery ledger")
    previous = sha(manifest)
    shutil.copy2(manifest, backup)
    for name in ("restore_network_calibration_route.tcl", "seal_network_recovery_inputs.py"):
        target = root / "scripts" / name
        require(not target.exists(), "Preserve previous source")
        shutil.copy2(repo / "fpga/zu15eg" / name, target)
        data["candidate_sha256"][str(target.relative_to(root))] = sha(target)
    data["previous_candidate_manifest_sha256"] = previous
    data["calibration_recovery_sealed"] = True
    data["limits"].append("Vivado 2025.1 ECO placer unsupported on UltraScale+: recover two exact removed calibration AND LUTs from own pre-place checkpoint at original LOC/BEL, reuse own placed leaves, Explore router may reroute blocking nets. No READY bypass or timing relaxation.")
    manifest.write_text(json.dumps(data, indent=2) + "\n")
    print("PASS_ULTRASCALE_CALIBRATION_RECOVERY_INPUTS_SEALED", sha(manifest))


if __name__ == "__main__":
    main()
