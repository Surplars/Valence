#!/usr/bin/env python3
"""Prepare exact measured passive CPU observer sources and flags, without running a model.

Requires the complete constructor and fabric emitted with the optional durable
entry. Existing historical host sources stay frozen. An existing output is refused.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent / "durable_read_prefetch"
CONTRACT = HERE / "host-contract-v1.json"
CONTRACT_SHA256 = "c29b6f7d679d8ad011e39a781f7a5cd47c8c684071a9c0cc7236f9145e8ebad9"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_contract():
    if digest(CONTRACT) != CONTRACT_SHA256:
        raise ValueError("durable observer source contract changed")
    return json.loads(CONTRACT.read_text())


def prepare(profile_path, fabric_path, output, law="original"):
    contract = load_contract()
    sys.path.insert(0, str(ROOT / "fpga/next"))
    import board_durable_read_prefetch as entry
    profile = json.loads(profile_path.read_text())
    fabric = json.loads(fabric_path.read_text())
    entry.compare_constructor(profile)
    if fabric != entry.load_manifest()["executed_fabric"]:
        raise ValueError("full emitted fabric differs from measured candidate")
    if fabric["cpu"] != profile["core"] or fabric["cache"] != profile["cache"]:
        raise ValueError("constructor/fabric mismatch")
    if {k: fabric["cache"][k] for k in contract["actual_cache_flags"]} != contract["actual_cache_flags"]:
        raise ValueError("observer macros are not bound to actual cache policies")
    if law not in ("original", "burst-locked"):
        raise ValueError("unknown DDR service law")
    original = ROOT / "simulator/gsim/prefetch_demand_adoption/cpu_snapshot"
    sources = {name: original / name for name in contract["original_host17"]}
    for name, expected in contract["original_host17"].items():
        if digest(sources[name]) != expected:
            raise ValueError("historical observer changed: " + name)
    for name in contract["changed_positive_headers"]:
        sources[name] = HERE / "host" / name
    expected = contract["positive_host17"]
    if law == "burst-locked":
        sources["harness/board_ddr_benchmark.h"] = ROOT / contract["fixed_law_header"]
        expected = contract["fixed_host17"]
    for name, path in sources.items():
        if digest(path) != expected[name]:
            raise ValueError("measured host identity mismatch: " + name)
    output.mkdir(parents=True, exist_ok=False)
    for name, path in sources.items():
        destination = output / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
    receipt = {
        "status": "PREPARED_EXACT_HOST_NOT_NEW_MODEL_QUALIFICATION",
        "law": law,
        "constructor_sha256": digest(profile_path),
        "fabric_sha256": digest(fabric_path),
        "contract_sha256": CONTRACT_SHA256,
        "host17": {name: digest(output / name) for name in expected},
        "model_cxx_flags": contract["model_cxx_flags"],
        "host_defines": contract["host_defines"],
        "guest3": contract["guest3"],
        "source_writes": False,
        "new_model_qualification": False,
    }
    (output / "prepared-host.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--fabric", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--law", choices=("original", "burst-locked"), default="original")
    args = parser.parse_args(argv)
    print(json.dumps(prepare(args.profile, args.fabric, args.output, args.law), indent=2))


if __name__ == "__main__":
    main()
