#!/usr/bin/env python3
"""Qualify a current timing-met experimental bit, not a production BSP release.

All original Tcl physical/ROM/clock/DRC gates remain mandatory. This separate
contract records a complete current-netlist CDC structural review, its protocol
assumptions and unverified runtime scope. It neither fabricates historical test
receipts nor accepts their old routed CDC fingerprints.
"""
import argparse
import collections
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from release_inputs import FRESH_STATUS, load_release_inputs
from verify_native_release_contract import cdc_inventory, fingerprint, require, sha, validate_cdc_review
from prepare_native_release_contract import bridge_fields, classify
from verify_netboot_release import rx_stop_finding
from audit_native_rv64gc import routed_state, summary

STATUS = "READY_CURRENT_INTEGRATED_RV64GC100_STATIC_CANDIDATE_BIT_NOT_RUNTIME"
LIMITS = [
    "Experimental timing-qualified candidate bit for user testing, not a production platform/BSP release.",
    "CDC review is current structural/held-payload/Gray/reset and routed timing review, not complete independent CDC protocol verification.",
    "Common cold reset, stable held-data ownership and FIFO Gray-pointer protocol assumptions remain required; unilateral reset is unsupported.",
    "Only supplied evidence is claimed; no historical CPU/DDR/GMAC/interface test receipt is fabricated or inherited.",
    "Physical UART/DDR/GMAC behavior, board stability, Linux/BSP compatibility and full runtime correctness remain unverified.",
]
COVERAGE = {"no_clock", "unconstrained_internal_endpoints", "generated_clocks", "loops", "multiple_clock", "latch_loops"}
REQUIRED_REPORTS = {"timing_summary.rpt", "route_status.rpt", "check_timing.rpt", "bus_skew.rpt",
                    "tx_io.rpt", "rx_io.rpt", "divider_clear.rpt", "quarter_tx_identity.txt", "drc.rpt", "cdc.rpt"}


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def tools_map():
    directory = Path(__file__).resolve().parent
    return {str(directory / name): sha(directory / name) for name in (
        "verify_current_candidate_release.py", "release_inputs.py", "verify_native_release_contract.py",
        "prepare_native_release_contract.py", "verify_netboot_release.py", "audit_native_rv64gc.py",
        "audit_native_io_qualification.py", "release_native_rv64gc.tcl")}


def current_classification(row, facts, truth):
    """Reuse strict endpoint predicates, never their historical test claims."""
    if "/rxStop/command/held_reg/" in row["source"]:
        rx_stop_finding(row, facts, truth)
        return ("held_payload_mailbox",
                "The exact RX-stop held-command capture has current routed payload timing and an exhaustive "
                "32-state actual-netlist next-state check. Synchronized request/ACK ownership and common "
                "reset remain protocol assumptions; independent-clock runtime is not established by this review.",
                ["cdc_facts", "mailbox_truth", "routed_proof"])
    if (row["id"] == "CDC-15" and row["severity"] == "Warning" and
            row["source"] == row["destination"] == "<hidden>" and
            row["source_clock"] == "mmcm_clkout0" and row["destination_clock"] == "clk_out1_clk_wiz_ddr" and
            row["exception"] == "False Path" and row["clock_relationship"] == "Safely Timed"):
        return ("vendor_encrypted_boundary",
                "Only this exact hidden MIG vendor clock boundary retains its existing False Path. "
                "Reliance on encrypted vendor IP is explicit; this is not independent verification "
                "of vendor logic or permission to waive visible native endpoints.", ["cdc_facts", "routed_proof"])
    category, unused_reason, unused_refs = classify(row, facts)
    reasons = {
        "reset_async_assert_sync_release": "Current netlist has a direct three-stage ASYNC_REG reset-release chain with common asynchronous assertion and timed release sinks. Common cold reset is required; unilateral endpoint reset is unsupported.",
        "persistent_level_two_sync": "Current netlist has separate direct two-stage synchronizers for the registered quiesce fanout. The source must remain a persistent level through drain/stop; that protocol assumption is not a new independent runtime proof.",
        "held_payload_mailbox": "Current mailbox captures have bounded routed payload timing and bus skew. The txConfig folded bit also has the current exhaustive 32-state actual-netlist check. Stable payload until synchronized ACK remains an ownership assumption.",
        "held_payload_register_bridge": "Current register-bridge fields are statically checked for atomic held/capture qualifiers and bounded routed payload timing/skew. One-outstanding stable ownership until synchronized response is required; full metadata asynchronous behavior is not dynamically certified.",
        "async_fifo_gray": "Every current Gray pointer bit has a direct two-stage ASYNC_REG crossing with no intermediate functional fanout and passing routed delay/skew. One-bit Gray evolution and common-reset ownership remain source protocol assumptions.",
        "async_fifo_payload": "All 38 current FIFO RAM payload capture bits are covered by routed timing. Ownership must be transferred by synchronized Gray pointers and retained until synchronous capture; this structural review is not a new independent FIFO runtime test.",
        "vendor_debug_fifo": "Only the exact vendor Debug Hub FIFO endpoint and clock pair are trusted under its existing exception. No independent vendor RTL verification or qualification of any other native endpoint is claimed.",
    }
    refs = ["cdc_facts", "routed_proof"]
    if category == "held_payload_register_bridge":
        refs.append("register_bridge_static")
    if category == "held_payload_mailbox":
        refs.append("mailbox_truth")
    return category, reasons[category], refs


def build_review(report, facts, truth, dcp):
    findings = []
    for row in cdc_inventory(report):
        if row["severity"] == "Info":
            continue
        category, reason, refs = current_classification(row, facts, truth)
        findings.append(dict(fingerprint=fingerprint(row), classification=category, reason=reason,
                             evidence=refs, actual_finding=row))
    return dict(status="PASS_CURRENT_ROUTED_NATIVE_CDC_REVIEW_WITH_DOCUMENTED_FINDINGS_NOT_BOARD_RUNTIME",
                scope="CURRENT_STATIC_CANDIDATE_REVIEW_NOT_FULL_CDC_PROTOCOL_SIGNOFF",
                dcp_sha256=sha(dcp), timing_exceptions_added=False, unreviewed_findings=[], findings=findings,
                class_counts=dict(collections.Counter(row["classification"] for row in findings)),
                independent_protocol_runtime_verified=False, board_verified=False, limitations=LIMITS)


def validate_facts(facts, truth, dcp):
    for text, markers in ((facts, ("PART=xczu15eg-ffvb1156-2-i", "QUARTER_TX_COMMON_WORD_RESET_EPOCH_PASS",
                                  "READ_ONLY_STRUCTURAL_FACTS_COMPLETE_NOT_CDC_SIGNOFF",
                                  "FIFO_PAYLOAD_PATHS txFifo COUNT=38", "FIFO_PAYLOAD_PATHS rxFifo COUNT=38",
                                  "MIG_VENDOR_TARGET RIU_ADDR EXACT=84 EXPANDED=84",
                                  "MIG_VENDOR_TARGET RIU_WR_DATA EXACT=224 EXPANDED=224")),
                          (truth, ("PASS_TXCONFIG_BIT3_ACTUAL_NEXT_STATE_32_CASES_RESET_INACTIVE",))):
        bindings = re.findall(r"^CHECKPOINT=(.+)$", text, re.M)
        require(len(bindings) == 1 and Path(bindings[0]).resolve() == Path(dcp).resolve() and
                all(marker in text for marker in markers), "Incomplete or foreign current netlist facts")
    for name in ("COMMON_RELEASE_MODULES", "LEVEL_MODULES"):
        value = re.findall(r"^" + name + r"=(\d+)$", facts, re.M)
        require(len(value) == 1 and int(value[0]) >= 20, "Incomplete synchronizer inventory: " + name)


def validate(contract_path, dcp, cdc_report=None):
    contract, dcp = load(contract_path), Path(dcp).resolve()
    require(contract["status"] == STATUS and contract["limits"] == LIMITS, "Wrong candidate qualification scope")
    require(contract["board_verified"] is False and contract["independent_protocol_runtime_verified"] is False,
            "Static candidate must not claim runtime qualification")
    root, repo = Path(contract["candidate"]), Path(contract["repo"])
    require(dcp == (root / "implementation/routed.dcp").resolve(), "Wrong candidate's own routed checkpoint")
    require(sha(dcp) == contract["dcp_sha256"] and sha(root / "inputs.json") == contract["inputs_sha256"],
            "DCP/input identity drift")
    inputs = load_release_inputs(root, repo)
    require(inputs["status"] == FRESH_STATUS and inputs["variant"] == "integrated-off" and
            inputs["cpu_precheck"] is False, "Only requested current integrated-off candidate is supported")
    require(contract["hardware_source_commit"] == inputs["hardware_source_commit"], "Wrong hardware source commit")
    require(contract["qualification_tools_sha256"] == tools_map(), "Qualification tool drift")
    evidence = contract["evidence"]
    require(set(evidence) == {"routed_proof", "cdc_facts", "mailbox_truth", "register_bridge_static", "cdc_review"},
            "Incomplete current candidate evidence")
    texts = {}
    for role, item in evidence.items():
        require(sha(item["path"]) == item["sha256"], "Evidence identity drift: " + role)
        texts[role] = Path(item["path"]).read_text(encoding="utf-8-sig")
    proof = json.loads(texts["routed_proof"])
    require(proof["status"] == "RV64GC100_ROUTED_TIMING_MET_CDC_BOARD_REVIEW_PENDING" and
            proof["dcp_sha256"] == sha(dcp) and proof["hardware_source_commit"] == inputs["hardware_source_commit"] and
            proof["candidate_manifest_sha256"] == contract["inputs_sha256"] and
            proof["source_integrated"] is True and proof["bit_requested"] is True and
            proof["routed_timing_met"] is True and proof["ddr_bytes"] == 0x80000000, "Current route is not qualified")
    for key in ("candidate_input_drift", "current_source_drift", "runtime_errors",
                "runtime_critical_warnings", "drc_errors_or_critical"):
        require(not proof[key], "Unreviewed route issue: " + key)
    require(REQUIRED_REPORTS <= set(proof["artifact_sha256"]), "Incomplete current route report inventory")
    for name, digest in proof["artifact_sha256"].items():
        path = dcp.parent / name
        require(sha(path if path.is_file() else root / name) == digest, "Current route report drift: " + name)
    timing = (dcp.parent / "timing_summary.rpt").read_text()
    require(routed_state(timing) and summary(timing) == proof["board"], "Not current routed STA")
    require(all(proof["board"][key] >= 0 for key in ("setup_ns", "hold_ns", "pulse_ns")) and
            all(proof["board"][key] == 0 for key in ("setup_failures", "hold_failures", "pulse_failures")), "STA failed")
    require(proof["routing"]["all_routed"] and set(proof["clock_coverage"]) == COVERAGE and
            all(proof["clock_coverage"].values()) and proof["bus_skew"]["checks"] >= 27 and
            proof["bus_skew"]["failures"] == 0 and proof["bus_skew"]["minimum_slack_ns"] >= 0,
            "Route/clock coverage/bus-skew failed")
    for group in (proof["io"]["tx"], proof["io"]["rx"], proof["divider_release"]):
        require(set(group) == {"setup_ns", "hold_ns"} and min(group.values()) >= 0, "IO/reset release timing failed")
    validate_facts(texts["cdc_facts"], texts["mailbox_truth"], dcp)
    require(json.loads(texts["register_bridge_static"]) == json.loads(json.dumps(bridge_fields(root, repo))),
            "Current bridge field proof drift")
    report = (Path(cdc_report) if cdc_report else dcp.parent / "cdc.rpt").read_text()
    review = json.loads(texts["cdc_review"])
    require(review == build_review(report, texts["cdc_facts"], texts["mailbox_truth"], dcp),
            "CDC review differs from current exact findings and structural evidence")
    count = validate_cdc_review(report, review, sha(dcp), set(evidence))
    return dict(status="PASS_CURRENT_RV64GC100_STATIC_CANDIDATE_BIT_CONTRACT_NOT_RUNTIME",
                dcp_sha256=sha(dcp), reviewed_cdc_findings=count, board_verified=False,
                independent_protocol_runtime_verified=False, bit_generated=False, limits=LIMITS)


def prepare(args):
    root, repo, output = args.candidate.resolve(), args.repo.resolve(), args.out.resolve()
    require(not output.exists(), "Preserve previous candidate contract")
    inputs = load_release_inputs(root, repo)
    require(inputs["status"] == FRESH_STATUS, "Expected fresh current candidate manifest")
    dcp = root / "implementation/routed.dcp"
    facts, truth = args.cdc_facts.read_text(), args.mailbox_truth.read_text()
    validate_facts(facts, truth, dcp)
    review = build_review((dcp.parent / "cdc.rpt").read_text(), facts, truth, dcp)
    bridge = bridge_fields(root, repo)
    roles = dict(routed_proof=args.routed_proof.resolve(), cdc_facts=args.cdc_facts.resolve(),
                 mailbox_truth=args.mailbox_truth.resolve())
    output.mkdir(parents=True)
    for role, value in (("cdc_review", review), ("register_bridge_static", bridge)):
        path = output / (role + ".json")
        path.write_text(json.dumps(value, indent=2) + "\n")
        roles[role] = path
    contract = dict(status=STATUS, candidate=str(root), repo=str(repo), dcp_sha256=sha(dcp),
                    inputs_sha256=sha(root / "inputs.json"), hardware_source_commit=inputs["hardware_source_commit"],
                    qualification_tools_sha256=tools_map(),
                    evidence={role: dict(path=str(path), sha256=sha(path)) for role, path in roles.items()},
                    board_verified=False, independent_protocol_runtime_verified=False, limits=LIMITS)
    path = output / "qualified-contract.json"
    # A failed validation must not leave a ready-looking contract behind.
    pending = output / "pending-contract.json"
    pending.write_text(json.dumps(contract, indent=2) + "\n")
    result = validate(pending, dcp)
    pending.rename(path)
    (output / "verification.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(dict(result, contract=str(path)), sort_keys=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("contract", "dcp", "cdc-report", "candidate", "repo", "out", "routed-proof", "cdc-facts", "mailbox-truth"):
        parser.add_argument("--" + name, type=Path)
    args = parser.parse_args()
    if args.contract:
        require(args.dcp is not None, "--dcp required")
        print(json.dumps(validate(args.contract, args.dcp, args.cdc_report), sort_keys=True))
    else:
        require(all((args.candidate, args.repo, args.out, args.routed_proof, args.cdc_facts, args.mailbox_truth)),
                "Missing explicit current candidate evidence arguments")
        prepare(args)


if __name__ == "__main__":
    main()
