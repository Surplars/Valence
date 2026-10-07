#!/usr/bin/env python3
"""Append the actual ready-cone checker revision before candidate signoff."""
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
    require(data.get("eco_flow_sealed") and not data.get("eco_flow_r2_sealed"), "Only pre-signoff ECO ledger")
    require(not (root / "release-rv64gc100-u460800-r4").exists(), "Do not modify a released candidate")
    for name, digest in data["candidate_sha256"].items():
        require(sha(root / name) == digest, "Existing input drift: " + name)
    for name, digest in checked_source_map(data).items():
        require(sha(repo / name) == digest, "Existing source drift: " + name)
    previous = sha(manifest)
    backup = root / "inputs-before-eco-r2-seal.json"
    require(not backup.exists(), "Preserve previous ledger")
    shutil.copy2(manifest, backup)
    for name in ("route_network_eco_r2.tcl", "review_delay_ready_truth.tcl", "seal_network_eco_r2_inputs.py"):
        target = root / "scripts" / name
        require(not target.exists(), "Preserve existing script")
        shutil.copy2(repo / "fpga/zu15eg" / name, target)
        data["candidate_sha256"][str(target.relative_to(root))] = sha(target)
    data["candidate_sha256"]["ready-truth-review.txt"] = sha(root / "ready-truth-review.txt")
    data["previous_candidate_manifest_sha256"] = previous
    data["eco_flow_r2_sealed"] = True
    data["limits"].append("Actual readiness is two LUT2 AND levels; checker recursively requires exact AND truth tables and all three real RDY inputs. No netlist modification or tie-off.")
    manifest.write_text(json.dumps(data, indent=2) + "\n")
    print("PASS_ACTUAL_READY_CONE_ECO_INPUTS_SEALED", sha(manifest))


if __name__ == "__main__":
    main()
