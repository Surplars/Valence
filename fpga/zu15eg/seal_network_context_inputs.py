#!/usr/bin/env python3
"""Add proven context assets before signoff; retain the previous input ledger."""
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
    require(data["derived_inputs_frozen"] and not data.get("parent_context_sealed"), "Only unsealed pre-release context")
    require(not (root / "release-rv64gc100-u460800-r4").exists(), "Do not change a released candidate")
    for name, digest in data["candidate_sha256"].items():
        require(sha(root / name) == digest, "Existing frozen input drift: " + name)
    for name, digest in checked_source_map(data).items():
        require(sha(repo / name) == digest, "Existing source drift: " + name)
    for name in ("prove_network_context.py", "specialize_network_context.tcl",
                 "route_network_context.tcl", "audit_network_imported_inputs.tcl",
                 "seal_network_context_inputs.py"):
        target = root / "scripts" / name
        require(not target.exists(), "Preserve preexisting script")
        shutil.copy2(repo / "fpga/zu15eg" / name, target)
        data["candidate_sha256"][str(target.relative_to(root))] = sha(target)
    for folder in ("context-proof", "partitions-context"):
        for item in (root / folder).rglob("*"):
            if item.is_file() and item.suffix in {".json", ".tcldict", ".edf", ".dcp", ".txt"}:
                data["candidate_sha256"][str(item.relative_to(root))] = sha(item)
    for top in ("CoherentLineCache", "EthernetPacketDma"):
        require((root / "partitions-context" / top / "leaf.edf").is_file(), "Missing specialized leaf")
    proof = root / "context-proof/receipt.json"
    review = json.loads(proof.read_text())
    require(review["status"] == "PASS_EXACT_PARENT_RTL_CONTEXT_CONSTANT_ALIAS_REVIEW_VALID_TRANSACTIONS_ONLY", "Context proof absent")
    for name, digest in review["source_sha256"].items():
        require(sha(root / "rtl" / name) == digest, "Reviewed parent RTL changed")
    before = sha(manifest)
    shutil.copy2(manifest, root / "inputs-before-context-seal.json")
    data["parent_context_sealed"] = True
    data["previous_candidate_manifest_sha256"] = before
    data["new_evidence"]["parent_context"] = dict(path=str(proof), sha256=sha(proof))
    data["limits"].append("Exact parent-RTL constants/aliases restored before routing; initial unsuccessful import/placement attempts retained.")
    manifest.write_text(json.dumps(data, indent=2) + "\n")
    print("PASS_PARENT_CONTEXT_INPUTS_SEALED", sha(manifest))


if __name__ == "__main__":
    main()
