"""Explicit batch37/38/39/40 short schemas; no failed/stopped or signoff override."""
import hashlib
import json
from pathlib import Path

BANDWIDTH37 = "PASS_I1_BANDWIDTH37_AFFECTED_SHORT_ONLY"
BANDWIDTH38 = "PASS_I1_BANDWIDTH38_AFFECTED_SHORT_ONLY"
BANDWIDTH39 = "PASS_I1_BANDWIDTH39_AFFECTED_SHORT_ONLY"
BANDWIDTH40 = "PASS_I1_BANDWIDTH40_AFFECTED_SHORT_ONLY"
BANDWIDTH_PROFILES = (BANDWIDTH37, BANDWIDTH38, BANDWIDTH39, BANDWIDTH40)
REQUIRED_FLAGS = {
    "--coherent-line-grants", "--coherent-miss-turnover", "--coherent-writeback-overlap",
    "--coherent-read-overlap", "--data-reply-handoff", "--coherent-ways=2",
    "--icache=32768", "--dcache=32768", "--soc-clock-hz=300000000",
    "--cache-fetch-predecode", "--indexed-data-proofs", "--overlap-data-retirement",
    "--direct-fast-data-issue",
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _bandwidth_flags(receipt, status):
    if receipt.get("status") != status:
        raise ValueError("exact complete affected-short profile required")
    flags = receipt.get("cpu_flags")
    if (not isinstance(flags, list) or any(not isinstance(x, str) for x in flags) or
            len(set(flags)) != len(flags) or not REQUIRED_FLAGS <= set(flags)):
        raise ValueError("complete unique tested batch37 flag list required")
    if (receipt.get("cache_bytes_each") != 32768 or receipt.get("ddr_slots") != 2 or
            receipt.get("write_slots") != 1 or receipt.get("components_only") is not False or
            receipt.get("physical_qualified") is not False or receipt.get("board_qualified") is not False):
        raise ValueError("exact CPU-only short scope,32KiB/two-slot capacity required")
    checks, gates = receipt.get("checks", {}), receipt.get("performance_gates", {})
    expected = {"precise-privilege", "precise-privilege-negative", "ca", "ca-boundary",
                "fd-context", "coremark-o3", "coremark-o3-negative",
                "home-read-pair", "home-read-pair-negative", "mmu-handoff", "mmu-handoff-negative"}
    for name in ("pair-256-serial", "pair-256-overlap", "pair-32768-overlap"):
        expected.update((name, name+"-negative", name+"-stream", name+"-stream-negative"))
    for mode in ("bare", "sv39"):
        expected.update(("cpu-coherent-"+mode, "cpu-coherent-64k-"+mode,
                         "cpu-coherent-64k-"+mode+"-latency80"))
    if status in (BANDWIDTH39, BANDWIDTH40):
        for name in ("predictor-c", "write-commit-256", "write-commit-32768", "mmu-shifted"):
            expected.update((name, name+"-negative"))
    if status == BANDWIDTH40:
        for width in (32, 64):
            for name in ("pmp-"+str(width)+"-direct", "pmp-"+str(width)+"-registered",
                         "execute-"+str(width)):
                expected.update((name, name+"-negative"))
    if set(checks) != expected or len(gates) != 13 or any(v is not True for v in gates.values()):
        raise ValueError("exact affected29 / performance13 proof required")
    if any(not isinstance(v, str) or "PASS" not in v for v in checks.values()):
        raise ValueError("every affected check must explicitly pass")
    return list(flags)


def bandwidth37_flags(receipt):
    return _bandwidth_flags(receipt, BANDWIDTH37)


def bandwidth38_flags(receipt):
    flags = _bandwidth_flags(receipt, BANDWIDTH38)
    expected = {"coremark"}
    for mode in ("bare", "sv39"):
        for suffix in ("", "-latency80"):
            for metric in ("read_ticks", "write_ticks", "copy_ticks"):
                expected.add("cpu-coherent-64k-"+mode+suffix+"/"+metric)
    if set(receipt["performance_gates"]) != expected:
        raise ValueError("all exact batch38 throughput/CoreMark gates required")
    return flags


def bandwidth39_flags(receipt):
    flags = _bandwidth_flags(receipt, BANDWIDTH39)
    expected = {"coremark"}
    for mode in ("bare", "sv39"):
        for suffix in ("", "-latency80"):
            for metric in ("read_ticks", "write_ticks", "copy_ticks"):
                expected.add("cpu-coherent-64k-"+mode+suffix+"/"+metric)
    if set(receipt["performance_gates"]) != expected:
        raise ValueError("all exact batch39 throughput/CoreMark gates required")
    return flags


def bandwidth39_audit(receipt, audit, receipt_digest):
    bandwidth39_flags(receipt)
    if (audit.get("status") != "PASS_BATCH39_SHORT_NO_REGRESSION_PHYSICAL_PENDING" or
            audit.get("receipt_sha256") != receipt_digest or
            audit.get("sources_rehashed") != len(receipt["source_sha256"]) or
            audit.get("artifacts_rehashed") != len(receipt["artifact_sha256"]) or
            audit.get("checks") != 37 or audit.get("performance_gates") != 13 or
            audit.get("identical_stream_cases") != 6 or audit.get("coremark_identical") is not True or
            audit.get("memory_structure_equal") is not True or
            audit.get("register_declarations_equal") is not True or
            audit.get("register_declarations_before") != 6999 or
            audit.get("register_declarations_after") != 6999 or
            audit.get("directory_write_ports") != 4 or
            audit.get("new_payload_ram_bits") != 0 or
            any(audit.get(k) is not False for k in
                ("multiclock_changed", "physical_qualified", "bit_generated"))):
        raise ValueError("exact source-bound, equal-capacity batch39 audit required")


def bandwidth40_flags(receipt):
    flags = _bandwidth_flags(receipt, BANDWIDTH40)
    expected = {"coremark"}
    for mode in ("bare", "sv39"):
        for suffix in ("", "-latency80"):
            for metric in ("read_ticks", "write_ticks", "copy_ticks"):
                expected.add("cpu-coherent-64k-"+mode+suffix+"/"+metric)
    if set(receipt["performance_gates"]) != expected:
        raise ValueError("all exact batch40 throughput/CoreMark gates required")
    return flags


def bandwidth40_audit(receipt, audit, receipt_digest):
    bandwidth40_flags(receipt)
    if (audit.get("status") != "PASS_BATCH40_SHORT_NO_REGRESSION_PHYSICAL_PENDING" or
            audit.get("receipt_sha256") != receipt_digest or
            audit.get("sources_rehashed") != len(receipt["source_sha256"]) or
            audit.get("artifacts_rehashed") != len(receipt["artifact_sha256"]) or
            audit.get("checks") != 49 or audit.get("performance_gates") != 13 or
            audit.get("identical_stream_cases") != 6 or audit.get("coremark_identical") is not True or
            audit.get("memory_structure_equal") is not True or
            audit.get("register_declarations_equal") is not True or
            audit.get("register_declarations_before") != 6999 or
            audit.get("register_declarations_after") != 6999 or
            audit.get("directory_write_ports") != 4 or
            audit.get("new_payload_ram_bits") != 0 or
            any(audit.get(k) is not False for k in
                ("multiclock_changed", "physical_qualified", "bit_generated"))):
        raise ValueError("exact source-bound, equal-capacity batch40 audit required")


def bandwidth38_audit(receipt, audit, receipt_digest):
    bandwidth38_flags(receipt)
    state = audit.get("state_structure", {})
    leaf = audit.get("directory_leaf", {})
    configuration = audit.get("configuration", {})
    if (audit.get("status") != "PASS_BATCH38_SHORT_AND_LEAF_MAPPING_CPU_STA_PENDING" or
            audit.get("receipt_sha256") != receipt_digest or
            audit.get("sources_rehashed") != len(receipt["source_sha256"]) or
            audit.get("artifacts_rehashed") != len(receipt["artifact_sha256"]) or
            audit.get("checks") != 29 or audit.get("performance_gates") != 13 or
            audit.get("identical_stream_cases") != 6 or audit.get("coremark_identical") is not True or
            any(audit.get(k) is not False for k in
                ("full_board_synthesized", "physical_qualified", "bit_generated")) or
            configuration != dict(cpu_target_hz=300000000, cache_bytes_each=32768,
                ddr_slots=2, write_slots=1, multiclock_changed=False, flags_identical_to_batch37=True) or
            state != dict(register_declarations_before=6999, register_declarations_after=6999,
                directory_banks=4, directory_write_ports_before=8, directory_write_ports_after=4,
                new_control_state_bits=0, new_payload_ram_bits=0) or
            any(leaf.get(k) != v for k, v in dict(width=20, depth=256, read_ports=6,
                write_ports=1, lut=700, lutram_lut=576, logic_lut=124, ff=0).items()) or
            audit.get("dt_address_local_cone", {}).get("new_reply_inputs") != [] or
            audit.get("independent_negative", {}).get("old_two_write_port_leaf_rejected") is not True):
        raise ValueError("exact source-bound single-writer/reply-independent batch38 audit required")


def _jtag_transport(root):
    from check_jtag_update import verify_external
    old_path = root/"build/gsim/i1-jtag-chain35-20261017-r1/receipt.json"
    old = json.loads(old_path.read_text())
    if old.get("status") != "PASS_I1_JTAG_CHAIN35_AFFECTED_SHORT_ONLY" or old.get("jtag_scan_bits") != 65:
        raise ValueError("qualified USER2 dual-TAP topology required")
    proof = {}
    for kind, status, cases in (("chain", "PASS_I1_JTAG_SERIAL_CHAIN_XSIM", 12),
                               ("protocol", "PASS_I1_HALF_CYCLE_CDC_XSIM_ONLY", 3)):
        path = Path(old[kind+"_receipt"])
        if sha(path) != old[kind+"_receipt_sha256"]:
            raise ValueError("JTAG receipt drift: "+kind)
        value = verify_external(path, status)
        if len(value["cases"]) != cases:
            raise ValueError("complete actual RTL chain/protocol coverage required")
        proof[kind] = {"receipt": str(path), "sha256": sha(path), "cases": cases}
    return proof


def validate_bandwidth37(receipt, receipt_path, root):
    flags = bandwidth37_flags(receipt)
    receipt_path, root = Path(receipt_path), Path(root)
    audit_path = receipt_path.parent/"batch37-final-audit.json"
    audit = json.loads(audit_path.read_text())
    if (audit.get("status") != "PASS_I1_BANDWIDTH37_OWNER_AUDIT_STREAMS_EQUAL_COREMARK_GAIN" or
            audit.get("receipt_sha256") != sha(receipt_path) or
            audit.get("source_files_checked") != len(receipt["source_sha256"]) or
            audit.get("artifacts_checked") != len(receipt["artifact_sha256"]) or
            audit.get("all_standard_cycles_and_retired_and_bus_bytes_equal") is not True or
            audit.get("memory_declarations_equal") is not True or audit.get("additional_control_bits") != 7 or
            audit.get("new_payload_queue_bits") != 0):
        raise ValueError("source/artifact-bound final batch37 audit required")
    # Recheck only the transport's actual independent RTL proofs, not an
    # obsolete claim that the changed whole CPU remains byte-identical.
    proof = _jtag_transport(root)
    return flags, {"audit": str(audit_path), "audit_sha256": sha(audit_path),
                   "jtag_scan_bits": 65, "jtag_transport_proofs": proof,
                   "whole_cpu_rtl_identity_claimed": False}


def validate_bandwidth38(receipt, receipt_path, root):
    flags = bandwidth38_flags(receipt)
    receipt_path, root = Path(receipt_path), Path(root)
    audit_path = receipt_path.parent/"batch38-final-audit.json"
    audit = json.loads(audit_path.read_text())
    bandwidth38_audit(receipt, audit, sha(receipt_path))
    baseline_path = Path(receipt["baseline"])
    baseline = json.loads(baseline_path.read_text())
    if (sha(baseline_path) != receipt["baseline_sha256"] or
            baseline.get("status") != BANDWIDTH37 or flags != baseline["cpu_flags"]):
        raise ValueError("exact same-configuration batch37 performance reference required")
    allowed = {"simulator/gsim/harness/five_stage_home_read_pair.cpp",
        "simulator/gsim/harness/five_stage_translation.cpp",
        "simulator/gsim/inorder/bandwidth37_acceptance.py",
        "src/main/scala/core/inorder/FiveStageAddressTranslation.scala",
        "src/main/scala/core/inorder/I1CoherentLineHome.scala"}
    changed = {n for n, h in baseline["source_sha256"].items()
               if receipt["source_sha256"].get(n) != h}
    new = set(receipt["source_sha256"]) - set(baseline["source_sha256"])
    if changed != allowed or new != {"simulator/gsim/inorder/bandwidth38_acceptance.py"}:
        raise ValueError("batch38 changed unrelated source or original OoO/shared IP")
    if (len(receipt.get("stream_comparison", {})) != 6 or
            any(item["old"] != item["new"] or item["old"] != baseline["stream_comparison"][key]["new"]
                for key, item in receipt["stream_comparison"].items()) or
            receipt["coremark_comparison"]["old"] != receipt["coremark_comparison"]["new"] or
            receipt["coremark_comparison"]["old"] != baseline["coremark_comparison"]["new"]):
        raise ValueError("exact six-stream/CoreMark non-regression proof required")
    mapping = Path(audit["mapping_evidence"])
    stage_path = mapping/"staged-proof.json"
    stage = json.loads(stage_path.read_text())
    leaf = audit["directory_leaf"]
    if (sha(stage_path) != leaf["staged_proof_sha256"] or
            sha(mapping/"utilization.rpt") != leaf["utilization_sha256"] or
            stage["short_receipt_sha256"] != sha(receipt_path) or
            stage["cpu_fir_sha256"] != receipt["artifact_sha256"]["cpu/FiveStageSoc.fir"] or
            stage["raw_leaf_sha256"] != sha(mapping/"raw/directoryBanks_256x20.sv") or
            stage["annotated_leaf_sha256"] != sha(mapping/"directoryBanks_256x20.sv") or
            stage["tcl_sha256"] != sha(mapping/"prove_directory.tcl") or
            stage["proof_tool_sha256"] != sha(root/"fpga/inorder/check_directory_writer.py") or
            "PASS_SINGLE_WRITER_LUTRAM FFs=0" not in (mapping/"primitive-counts.txt").read_text()):
        raise ValueError("actual tested CPU leaf/LUTRAM inference evidence drift")
    negative = root/audit["independent_negative"]["old_dt"]
    if "next physical payload depends on old reply admission" not in negative.read_text():
        raise ValueError("old DT must fail the independent prepared-payload negative control")
    return flags, {"audit": str(audit_path), "audit_sha256": sha(audit_path),
        "jtag_scan_bits": 65, "jtag_transport_proofs": _jtag_transport(root),
        "whole_cpu_rtl_identity_claimed": False, "directory_mapping": str(mapping),
        "directory_raw_leaf_sha256": stage["raw_leaf_sha256"], "directory_write_ports": 1}


def validate_bandwidth39(receipt, receipt_path, root):
    flags = bandwidth39_flags(receipt)
    receipt_path, root = Path(receipt_path), Path(root)
    audit_path = receipt_path.parent/"batch39-final-audit.json"
    audit = json.loads(audit_path.read_text())
    bandwidth39_audit(receipt, audit, sha(receipt_path))
    if audit.get("auditor_sha256") != sha(root/"fpga/inorder/audit_batch39_short.py"):
        raise ValueError("batch39 state/source audit tool drift")
    baseline_path = Path(receipt["baseline"])
    baseline = json.loads(baseline_path.read_text())
    if sha(baseline_path) != receipt["baseline_sha256"] or baseline.get("status") != BANDWIDTH38:
        raise ValueError("exact complete batch38 reference required")
    old_flags, old_proof = validate_bandwidth38(baseline, baseline_path, root)
    if flags != old_flags:
        raise ValueError("batch39 must preserve the exact tested board flags")
    allowed = {"simulator/gsim/inorder/bandwidth37_acceptance.py",
        "src/main/scala/core/inorder/FiveStageAddressTranslation.scala",
        "src/main/scala/core/inorder/FiveStageBranchPredictor.scala",
        "src/main/scala/core/inorder/I1CoherentLineCache.scala"}
    changed = {n for n, h in baseline["source_sha256"].items()
               if receipt["source_sha256"].get(n) != h}
    new = set(receipt["source_sha256"]) - set(baseline["source_sha256"])
    if changed != allowed or new != {"simulator/gsim/inorder/bandwidth39_acceptance.py"}:
        raise ValueError("batch39 changed unrelated source, reset RTL, OoO or shared IP")
    for name, digest in baseline["artifact_sha256"].items():
        if sha(baseline_path.parent/name) != digest:
            raise ValueError("frozen batch38 artifact drift: "+name)
    if (len(receipt.get("stream_comparison", {})) != 6 or
            any(item["old"] != item["new"] or item["old"] != baseline["stream_comparison"][key]["new"]
                for key, item in receipt["stream_comparison"].items()) or
            receipt["coremark_comparison"]["old"] != receipt["coremark_comparison"]["new"] or
            receipt["coremark_comparison"]["old"] != baseline["coremark_comparison"]["new"]):
        raise ValueError("batch39 exact six-stream/CoreMark behavioral equality required")
    # Home source and actual directory leaf are unchanged. Reuse only its
    # historical leaf mapping; export rechecks the new CPU's raw leaf bytes.
    return flags, {**old_proof, "audit": str(audit_path), "audit_sha256": sha(audit_path),
        "historical_directory_proof": old_proof["audit"],
        "historical_directory_proof_sha256": old_proof["audit_sha256"],
        "directory_mapping_reused_not_resynthesized": True}


def validate_bandwidth40(receipt, receipt_path, root):
    flags = bandwidth40_flags(receipt)
    receipt_path, root = Path(receipt_path), Path(root)
    audit_path = receipt_path.parent/"batch40-final-audit.json"
    audit = json.loads(audit_path.read_text())
    bandwidth40_audit(receipt, audit, sha(receipt_path))
    if audit.get("auditor_sha256") != sha(root/"fpga/inorder/audit_batch40_short.py"):
        raise ValueError("batch40 state/source audit tool drift")
    baseline_path = Path(receipt["baseline"])
    baseline = json.loads(baseline_path.read_text())
    if sha(baseline_path) != receipt["baseline_sha256"] or baseline.get("status") != BANDWIDTH39:
        raise ValueError("exact complete batch39 reference required")
    old_flags, old_proof = validate_bandwidth39(baseline, baseline_path, root)
    if flags != old_flags:
        raise ValueError("batch40 must preserve the exact tested board flags")
    allowed = {"simulator/gsim/inorder/bandwidth37_acceptance.py",
        "src/main/scala/core/inorder/FiveStageAddressTranslation.scala",
        "src/main/scala/core/inorder/FiveStageCachedCore.scala",
        "src/main/scala/core/inorder/FiveStageFetchWordCuts.scala",
        "src/main/scala/core/inorder/I1CoherentLineCache.scala",
        "src/main/scala/core/inorder/FiveStagePmp.scala",
        "src/main/scala/core/inorder/I1TimingMath.scala",
        "src/main/scala/core/inorder/FiveStageAlu.scala"}
    changed = {n for n, h in baseline["source_sha256"].items()
               if receipt["source_sha256"].get(n) != h}
    new = set(receipt["source_sha256"]) - set(baseline["source_sha256"])
    if changed != allowed or new != {"simulator/gsim/inorder/bandwidth40_acceptance.py"}:
        raise ValueError("batch40 changed unrelated source, reset RTL, OoO or shared IP")
    for name, digest in baseline["artifact_sha256"].items():
        if sha(baseline_path.parent/name) != digest:
            raise ValueError("frozen batch39 artifact drift: "+name)
    if (len(receipt.get("stream_comparison", {})) != 6 or
            any(item["old"] != item["new"] or item["old"] != baseline["stream_comparison"][key]["new"]
                for key, item in receipt["stream_comparison"].items()) or
            receipt["coremark_comparison"]["old"] != receipt["coremark_comparison"]["new"] or
            receipt["coremark_comparison"]["old"] != baseline["coremark_comparison"]["new"]):
        raise ValueError("batch40 exact six-stream/CoreMark behavioral equality required")
    return flags, {**old_proof, "audit": str(audit_path), "audit_sha256": sha(audit_path)}
