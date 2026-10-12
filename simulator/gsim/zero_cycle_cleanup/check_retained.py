#!/usr/bin/env python3
"""Verify the minimal public receipt and source/config subset; never rerun hardware."""
import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path, PurePosixPath
import re
import tempfile

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[2]
RECEIPT_PATH = "simulator/gsim/zero_cycle_cleanup/evidence/public-receipt.json"
RECEIPT_SHA256 = "7c15b261bc5709123d150c4ce4c2b1afe24d43a5d50fe3f374b104d7e553f9e6"
BASE = "611ab7a602d66aaa5435a9f2a4699e31146e65be"
QUALIFIED_TREE = "b2dfb60cfb55f227d2860160c42c841e57bf8610"
FIELDS = {"schema", "baseline_commit", "qualified_candidate_tree", "verification_scope", "recorded_qualification", "configuration", "source_fingerprints", "production_source_closure", "qualified_input_closure", "full_receipt_sha256", "external_evidence_sha256", "prior_failures"}
CLOSURE_SCOPES = ["src/main/scala", "src/main/resources", "third_party/berkeley-hardfloat/src/main/scala", "fpga/next/rtl"]
EXTERNAL = {"complete_qualification": "21f44c06c72d1e2ad57a7b6b20ac8fd4293eae170563faf639380762cfcbfdf3", "qualified_model": "06a82d2d1d276d5068ddf6c655d60cb4e2e9f5b8573376d37b6fcccf2112fd3c", "full_r3_source": "c709e703a1ee57576ddedb282efbc06f85ae007d1c63184ddff0a8bc6001826e"}


def need(value, message):
    if not value:
        raise RuntimeError(message)


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def safe_file(root, name):
    path = PurePosixPath(name)
    need(str(path) == name and not path.is_absolute() and ".." not in path.parts, "invalid relative source path")
    target = root / name
    need(target.is_file() and all(not p.is_symlink() for p in [target, *target.parents] if p != root.parent), "missing or symlink source: " + name)
    need(target.resolve().is_relative_to(root.resolve()), "source escapes root")
    return target


def read_receipt(source):
    path = safe_file(source, RECEIPT_PATH)
    need(sha(path) == RECEIPT_SHA256, "minimal receipt identity changed")
    value = json.loads(path.read_text())
    need(set(value) == FIELDS and value["schema"] == "valence-minimal-public-qualification-v1", "minimal receipt schema changed")
    need(value["baseline_commit"] == BASE and value["qualified_candidate_tree"] == QUALIFIED_TREE, "qualified source identity changed")
    need(value["external_evidence_sha256"] == EXTERNAL, "external evidence references changed")
    return value


def check(source, external=None):
    source = source.resolve()
    value = read_receipt(source)
    fingerprints = value["source_fingerprints"]
    need(len(fingerprints) == 45 and digest(sorted(fingerprints)) == "fc8a7e26b5b3231929e769badb31cf94ebc26b340b4fcc686387f888aeaabe61", "necessary source set changed")
    for name, expected in fingerprints.items():
        need(re.fullmatch(r"[0-9a-f]{64}", expected) is not None and sha(safe_file(source, name)) == expected, "necessary source fingerprint changed: " + name)
    closure = value["production_source_closure"]
    need(closure["scope"] == CLOSURE_SCOPES, "production source scope changed")
    actual = {p.relative_to(source).as_posix(): sha(safe_file(source, p.relative_to(source).as_posix()))
              for folder in CLOSURE_SCOPES for p in sorted((source / folder).rglob("*")) if p.is_file()}
    need(len(actual) == closure["file_count"] == 220 and digest(actual) == closure["canonical_sha256"], "aggregate production source closure changed")
    record = value["recorded_qualification"]
    need(record["status"] == "PASS_COMBINED_ZERO_CYCLE_QUALIFICATION" and record["physical_qualification"] is False and record["physical_timing"] == "UNMEASURED" and record["network_concurrency_qualification"] is False, "recorded qualification scope changed")
    cpu, native, nemu = (record[k] for k in ("cpu", "native", "nemu"))
    need(cpu["inclusive_cycles"] == {"sv39": 191618, "bare": 194153} and cpu["functional_fields_per_case"] == 105 and cpu["equal_result_sections_per_case"] == 12 and cpu["inclusive_roi_tail_deltas"] == [0, 0, 0] and cpu["raw_axi_supply_exact"] is True, "recorded CPU result changed")
    need(cpu["negative_controls"] == ["read", "memory", "trap"] and (cpu["fresh_on_models"], cpu["off_models"], cpu["model_translation_units"], cpu["compiler_jobs"]) == (1, 0, 36, 1), "recorded CPU run scope changed")
    need(native["module_count"] == 239 and native["changed_modules"] == ["IntegerBackend.sv", "TileLinkAxi4BurstBridge.sv"] and native["all_module_ports_identical"] is True and native["all_declared_state_identical"] is True, "recorded native result changed")
    need(nemu["same_cpu_object_count"] == 36 and nemu["case_cycles"] == {"hot": 1847, "compressed": 958} and nemu["negative_control_exits"] == {"pc": 1, "gpr": 1, "memory": 1} and nemu["zero_work"] == {"dut_generations": 0, "dut_object_compiles": 0, "reference_builds": 0, "state_resynchronizations": 0}, "recorded NEMU result changed")
    config = value["configuration"]
    old = json.loads(safe_file(source, "fpga/next/timing-batch-abc-lane1-prf-profile.json").read_text())["native_options"]
    options = config["native_options"]
    need(len(old) == 48 and options == old + ["--direct-registered-execution-operands", "--local-payload-write-enable"] and len(set(options)) == 50, "exact original48 option extension changed")
    need(config["constructor_counts"] == {"OooParams": 157, "FpgaNextConfig": 68, "DdrBridgeConfig": 8, "CoherentCacheConcurrency": 22} and config["fixture_overrides"] == {} and config["native_mac_t1"] is True and config["jtag_user_chain"] == 2, "recorded product constructor changed")
    # These are source/configuration checks, not elaboration or simulation.
    for name, pattern in [("OooParams.scala", r"directRegisteredExecutionOperands:\s*Boolean\s*=\s*false"), ("DdrBridgeConfig.scala", r"localPayloadWriteEnable:\s*Boolean\s*=\s*false")]:
        need(re.search(pattern, safe_file(source, "src/main/scala/core/ooo/" + name).read_text()) is not None, "generic option default changed")
    params = safe_file(source, "src/main/scala/core/ooo/OooParams.scala").read_text()
    bridge = safe_file(source, "src/main/scala/core/ooo/TileLinkAxi4BurstBridge.scala").read_text()
    need("require(!directRegisteredExecutionOperands || registeredIssueExecute," in params and "if (lineReadChannel && localPayloadWriteEnable)" in bridge, "option prerequisite changed")
    spec = importlib.util.spec_from_file_location("checked_final_entry", source / "fpga/next/board_final.py")
    final = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(final)
    profile = final.load_profile()
    need(profile["qualification_receipt"]["sha256"] == RECEIPT_SHA256 and profile["native_options"] == options + ["--native-mac-local-pad-reset-release"], "final entry receipt/options changed")
    with tempfile.TemporaryDirectory(prefix="valence-source-check-") as directory:
        absent = Path(directory) / "must-remain-absent"
        with contextlib.redirect_stdout(io.StringIO()) as stream:
            final.main(["--output", str(absent)])
        preflight = json.loads(stream.getvalue())
        need(not absent.exists() and preflight["status"] == "PREFLIGHT_ONLY", "preflight unexpectedly produced output")
    need(sorted(preflight["command"][5:]) == sorted(options) and preflight["native_mac_mode"] == profile["mode"] and final.digest(preflight["configuration"]) == config["export_profile_sha256"], "local option/configuration bridge changed")
    c = preflight["configuration"]
    expected = {"issue_width": 2, "rob_entries": 16, "physical_registers": 48, "lsu_entries": 4, "data_translation_entries": 16, "instruction_translation_entries": 8, "pte_cache_entries": 4, "instruction_cache_lines": 512, "data_cache_lines": 512, "cache_ways": 2, "cache_read_mshrs": 2, "cache_response_entries": 2, "cache_writeback_entries": 2, "pending_virtual_store_proof_slots": 2, "pending_store_early_load_credits": 2, "ddr_bytes": 2147483648, "bscan_chain": 2, "experimental_trispeed_ethernet": True, "direct_registered_execution_operands": True, "local_payload_write_enable": True}
    need(all(c.get(key) == expected_value for key, expected_value in expected.items()), "actual product preflight parameters changed")
    verified = []
    for role, path in (external or {}).items():
        need(role in EXTERNAL and sha(Path(path)) == EXTERNAL[role], "external bundle content hash changed: " + role)
        verified.append(role)
    return {"status": "PASS_MINIMAL_RECEIPT_AND_LOCAL_SOURCE_CONFIG_SUBSET", "receipt_sha256": RECEIPT_SHA256,
            "locally_checked_source_fingerprints": len(fingerprints), "production_source_files": len(actual), "native_option_count": len(options),
            "recorded_qualification_status": record["status"], "full_qualification_reexecuted": False,
            "external_bundles_hash_verified": sorted(verified), "external_unverified_references": sorted(set(EXTERNAL) - set(verified)),
            "synthesis_consumer_executed": False, "physical_qualification": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--evidence-bundle", type=Path, help="optional complete qualification bundle for byte-hash verification only")
    parser.add_argument("--model-bundle", type=Path)
    parser.add_argument("--full-source-bundle", type=Path)
    args = parser.parse_args()
    external = {role: path for role, path in [("complete_qualification", args.evidence_bundle), ("qualified_model", args.model_bundle), ("full_r3_source", args.full_source_bundle)] if path is not None}
    print(json.dumps(check(args.source, external), indent=2))


if __name__ == "__main__":
    main()
