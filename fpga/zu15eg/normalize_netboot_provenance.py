#!/usr/bin/env python3
"""Normalize Windows path aliases using only the recorded two tool revisions."""
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
    require(data.get("calibration_recovery_r2_sealed") and not data.get("path_aliases_normalized"), "Only recorded pre-release tool revision")
    require(not (root / "release-rv64gc100-u460800-r4").exists(), "Never alter released input identity")
    revisions = data["recovery_tool_revision"]["changes"]
    require(set(revisions) == {"restore_network_calibration_route.tcl", "prepare_netboot_release.py"}, "Unexpected revised inputs")
    canonical = {}
    corrections = []
    for name, digest in data["candidate_sha256"].items():
        normalized = name.replace("\\", "/")
        leaf = normalized.removeprefix("scripts/")
        if normalized.startswith("scripts/") and leaf in revisions:
            change = revisions[leaf]
            require(digest in {change["before_sha256"], change["after_sha256"]}, "Unrecorded tool identity")
            require(sha(root / normalized) == change["after_sha256"], "Revised staged bytes drift")
            require(sha(root / "evidence/pre-signoff-tool-revisions" / leaf) == change["before_sha256"], "Original tool bytes lost")
            actual = change["after_sha256"]
            if digest != actual:
                corrections.append(dict(old_key=name, canonical_key=normalized, superseded_sha256=digest, recorded_revision_sha256=actual))
        else:
            require(sha(root / name) == digest, "Unrelated input drift: " + name)
            actual = digest
        require(normalized not in canonical or canonical[normalized] == actual, "Unresolved path identity collision")
        canonical[normalized] = actual
    require(len(corrections) == 2, "Expected exactly two stale Windows aliases")
    data["candidate_sha256"] = canonical
    for name, digest in checked_source_map(data).items():
        require(sha(repo / name) == digest, "Current normalized source identity drift: " + name)
    previous = sha(manifest)
    backup = root / "inputs-before-path-normalization.json"
    require(not backup.exists(), "Preserve previous ledger")
    shutil.copy2(manifest, backup)
    helper = root / "scripts/normalize_netboot_provenance.py"
    require(not helper.exists(), "Preserve existing tool")
    shutil.copy2(repo / "fpga/zu15eg/normalize_netboot_provenance.py", helper)
    data["candidate_sha256"]["scripts/normalize_netboot_provenance.py"] = sha(helper)
    data["previous_candidate_manifest_sha256"] = previous
    data["path_aliases_normalized"] = True
    data["path_alias_corrections"] = corrections
    manifest.write_text(json.dumps(data, indent=2) + "\n")
    print("PASS_TWO_RECORDED_WINDOWS_PATH_ALIASES_NORMALIZED", sha(manifest))


if __name__ == "__main__":
    main()
