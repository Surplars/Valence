#!/usr/bin/env python3
"""Retain the superseded pre-signoff recovery script and seal its correction."""
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
    require(data.get("calibration_recovery_sealed") and not data.get("calibration_recovery_r2_sealed"), "Only pre-release recovery revision")
    require(not (root / "release-rv64gc100-u460800-r4").exists(), "Do not modify released inputs")
    for name, digest in data["candidate_sha256"].items():
        require(sha(root / name) == digest, "Previously sealed input drift: " + name)
    revisions = ("restore_network_calibration_route.tcl", "prepare_netboot_release.py")
    revision_sources = {"fpga/zu15eg/" + name for name in revisions}
    for name, digest in checked_source_map(data).items():
        if name in revision_sources:
            staged = root / "scripts" / Path(name).name
            require(sha(staged) == digest, "Prior revision identity lost: " + name)
        else:
            require(sha(repo / name) == digest, "Unrelated source drift: " + name)
    previous = sha(manifest)
    backup = root / "inputs-before-calibration-recovery-r2.json"
    require(not backup.exists(), "Preserve prior revision")
    shutil.copy2(manifest, backup)
    changes = {}
    archive_dir = root / "evidence/pre-signoff-tool-revisions"
    archive_dir.mkdir(parents=True, exist_ok=True)
    for name in revisions:
        key = "scripts/" + name
        target = root / key
        archived = archive_dir / name
        require(not archived.exists(), "Preserve superseded tool source")
        old = sha(target)
        shutil.copy2(target, archived)
        shutil.copy2(repo / "fpga/zu15eg" / name, target)
        require(sha(target) != old, "Tool revision must differ")
        data["candidate_sha256"][key] = sha(target)
        data["candidate_sha256"][str(archived.relative_to(root))] = old
        data["checked_source_sha256"]["fpga/zu15eg/" + name] = sha(target)
        changes[name] = dict(before_sha256=old, after_sha256=sha(target))
    helper = root / "scripts/revise_network_recovery_inputs.py"
    shutil.copy2(repo / "fpga/zu15eg/revise_network_recovery_inputs.py", helper)
    data["candidate_sha256"][str(helper.relative_to(root))] = sha(helper)
    data["previous_candidate_manifest_sha256"] = previous
    data["calibration_recovery_r2_sealed"] = True
    data["recovery_tool_revision"] = dict(changes=changes, reason="Retain identical surviving calibration LUTs; restore original disconnected nets only; refuse different truth, driver or occupied placement. Correct release description to permit blocking-net rerouting.")
    manifest.write_text(json.dumps(data, indent=2) + "\n")
    print("PASS_PRE_SIGNOFF_RECOVERY_REVISION_SEALED", sha(manifest))


if __name__ == "__main__":
    main()
