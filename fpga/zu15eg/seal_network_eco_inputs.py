#!/usr/bin/env python3
"""Append a pre-signoff ECO tool-flow revision without replacing old inputs."""
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
    require(data.get("parent_context_sealed") and not data.get("eco_flow_sealed"), "Only unrevised context-qualified input ledger")
    require(not (root / "release-rv64gc100-u460800-r4").exists(), "Do not change a released candidate")
    for name, digest in data["candidate_sha256"].items():
        require(sha(root / name) == digest, "Existing input drift: " + name)
    for name, digest in checked_source_map(data).items():
        require(sha(repo / name) == digest, "Existing source drift: " + name)
    previous = sha(manifest)
    backup = root / "inputs-before-eco-seal.json"
    require(not backup.exists(), "Preserve previous ECO ledger")
    shutil.copy2(manifest, backup)
    for name in ("route_network_eco.tcl", "review_eco_delay_control.tcl", "seal_network_eco_inputs.py"):
        target = root / "scripts" / name
        require(not target.exists(), "Preserve existing script: " + name)
        shutil.copy2(repo / "fpga/zu15eg" / name, target)
        data["candidate_sha256"][str(target.relative_to(root))] = sha(target)
    for name in ("delay-review-context.txt", "delay-review-placed.txt"):
        require((root / name).is_file(), "Missing tool-flow failure evidence")
        data["candidate_sha256"][name] = sha(root / name)
    data["previous_candidate_manifest_sha256"] = previous
    data["eco_flow_sealed"] = True
    data["limits"].append("Failed normal place/preserve route retained; native ECO place/route preserves actual IDELAYCTRL readiness, may reroute blocking nets, no timing constraints relaxed.")
    manifest.write_text(json.dumps(data, indent=2) + "\n")
    print("PASS_NATIVE_ECO_FLOW_INPUTS_SEALED", sha(manifest))


if __name__ == "__main__":
    main()
