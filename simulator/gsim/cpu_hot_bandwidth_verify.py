#!/usr/bin/env python3
"""Verify a completed recovery receipt without compiling or replaying anything."""
import argparse
import json
from pathlib import Path

import cpu_hot_bandwidth_recover as recovery


def verify(receipt_path):
    hot, require, stable = recovery.hot, recovery.require, recovery.stable
    state = json.loads(receipt_path.read_text())
    require(state["schema"] == "valence-cpu-hot-bandwidth-recovery-v1", "not a hot recovery receipt")
    require(state["status"] == "PASS_CPU_HOT_BANDWIDTH_RECOVERY", "recovery did not pass")
    require(state["prior_evidence_unchanged"], "prior evidence not preserved")
    require(state["generated_models"] == state["model_objects_compiled"] == 0, "hardware model was compiled")
    require(not state["current_source_model_qualified"], "current model is not qualified by this replay")
    prior = Path(state["prior_receipt"]["path"])
    stable(prior, state["prior_receipt"]["sha256"], "original receipt")
    old, _ = recovery.validate_prior(prior.parent)
    require(recovery.tree_hashes(prior.parent) == state["prior_evidence_files"], "original evidence tree changed")
    require(state["prior_commands"] == old["commands"], "original commands changed")
    stable(Path(state["recovery_runner"]["path"]), state["recovery_runner"]["sha256"], "recovery runner")
    for field in ("inputs", "model_artifacts", "selected_model", "geometry", "baseline_commit"):
        require(state[field] == old[field], "recovery qualification changed: " + field)
    if "new_cases_receipt" in state:
        reference = state["new_cases_receipt"]
        child_path = Path(reference["path"])
        stable(child_path, reference["sha256"], "new cases receipt")
        child, _ = recovery.validate_prior(child_path.parent)
        require(child["status"] == "PASS_CPU_HOT_BANDWIDTH_REUSE", "new cases did not pass")
        for field in ("inputs", "model_artifacts", "selected_model", "geometry", "baseline_commit"):
            require(child[field] == old[field], "new case qualification changed: " + field)
    require(sorted(state["cases"]) == sorted(recovery.CASES), "incomplete case set")
    for case, data in state["cases"].items():
        provenance = state["case_provenance"][case]
        log = Path(provenance["run_log"])
        stable(log, provenance["run_log_sha256"], "case run log")
        require(hot.parse(log.read_text()) == {k: v for k, v in data.items() if k not in ("symbols", "artifacts")},
                "case result differs from run log: " + case)
        for name, expected in data["artifacts"].items():
            stable(Path(provenance["directory"]) / name, expected, "case artifact")
        if provenance["kind"] == "prior_pass":
            require(data == old["cases"][case], "historical case changed")
        elif provenance["kind"] == "new_lightweight_build":
            require(data == child["cases"][case], "new case changed")
        elif provenance["kind"] == "recovered_prebuilt":
            require(data["artifacts"] == state["prepared_artifacts"][case]["artifacts"], "prebuilt artifact changed")
            require(state["prepared_artifacts"][case]["first_hash_at_recovery"], "prebuilt provenance limitation hidden")
        else:
            raise RuntimeError("unknown case provenance: " + case)
    for command in state["commands"]:
        require(command["exit"] == 0, "recovery command failed")
        stable(receipt_path.parent / command["log"], command["log_sha256"], "recovery command log")
    return {"status": "PASS_CPU_HOT_BANDWIDTH_RECOVERY_VERIFICATION", "receipt_sha256": hot.sha(receipt_path),
            "original_receipt_sha256": hot.sha(prior), "cases": len(state["cases"]),
            "generated_models": 0, "model_objects_compiled": 0, "current_source_model_qualified": False,
            "prebuilt_artifacts_first_hashed_at_recovery": sorted(state["prepared_artifacts"])}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--receipt", type=Path, required=True)
    args = ap.parse_args()
    print(json.dumps(verify(args.receipt.resolve()), indent=2))


if __name__ == "__main__":
    main()
