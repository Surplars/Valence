#!/usr/bin/env python3
"""Freeze derived ECO inputs once, before routed evidence and release."""
import argparse
import json
from pathlib import Path
import shutil
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_native_release_contract import sha, require


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("candidate", type=Path)
    p.add_argument("--repo", type=Path, required=True)
    a = p.parse_args()
    root, repo = a.candidate.resolve(), a.repo.resolve()
    path = root / "inputs.json"
    inputs = json.loads(path.read_text(encoding="utf-8"))
    require(root.name == "native-rv64gc-netboot-20261006-r4" and
            not inputs.get("derived_inputs_frozen"), "Only the unfrozen private r4 candidate")
    require(sha(Path(inputs["donor_checkpoint"])) == inputs["donor_checkpoint_sha256"], "Donor changed")
    for name, expected in inputs["candidate_sha256"].items():
        if name.replace("\\", "/") == "scripts/release_native_rv64gc.tcl":
            continue
        require(sha(root / name) == expected, "Previously staged input changed: " + name)
    scripts = ("release_native_rv64gc.tcl", "replace_network_candidate.tcl",
               "review_network_eco_boundaries.tcl", "prepare_netboot_release.py",
               "audit_netboot_linux.py", "freeze_netboot_inputs.py", "adapt_network_edif_inputs.py")
    for name in scripts:
        shutil.copy2(repo / "fpga/zu15eg" / name, root / "scripts" / name)
    selected = {name: sha(root / name) for name in inputs["candidate_sha256"]
                if not name.replace("\\", "/").startswith("scripts/")}
    for folder in ("scripts", "partitions"):
        for item in (root / folder).rglob("*"):
            if item.is_file() and item.suffix in {".tcl", ".py", ".edf", ".dcp", ".xdc"}:
                selected[str(item.relative_to(root))] = sha(item)
    rom = root / "ip-build/board_ip.gen/sources_1/ip/blk_mem_gen_0"
    for suffix in (".dcp", ".mif", ".veo"):
        item = rom / ("blk_mem_gen_0" + suffix)
        selected[str(item.relative_to(root))] = sha(item)
    for name in ("donor-alias-boundaries.txt", "edif-input-alias-review.json"):
        selected[name] = sha(root / name)
    inputs["candidate_sha256"] = selected
    inputs["derived_inputs_frozen"] = True
    backup = root / "inputs-before-derived-freeze.json"
    require(not backup.exists(), "Preserve previous manifest")
    shutil.copy2(path, backup)
    path.write_text(json.dumps(inputs, indent=2) + "\n", encoding="utf-8")
    print("PASS_NETBOOT_DERIVED_INPUTS_FROZEN", sha(path), "inputs", len(selected))


if __name__ == "__main__":
    main()
