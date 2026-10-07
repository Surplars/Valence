#!/usr/bin/env python3
"""Fail-closed RX-stop bit qualification. Never edits DCP/constraints or programs a board.

Affected MAC/DMA and independent-clock checks supplement the hash-identical r6
CPU/FPU/DDR/interface baseline; they are not whole-SoC dynamic equivalence.
Linux image delivery is separate, because the bit cannot establish Linux runtime.
"""
import argparse
import collections
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_native_release_contract import cdc_inventory, fingerprint, require, sha, validate_cdc_review
from prepare_native_release_contract import bridge_fields, classify
from audit_native_rv64gc import checked_source_map, routed_state, summary


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def check_map(repo, mapping):
    for name, digest in mapping.items():
        require(sha(repo / name.replace("\\", "/")) == digest, "Source drift: " + name)


def rx_stop_finding(row, facts, truth):
    prefix = "u_soc/nativeBank/gmac/rxStop/command/"
    require(row["id"] == "CDC-1" and row["severity"] == "Critical" and
            row["source"] == prefix + "held_reg/C" and
            row["destination"] == prefix + "captured_reg/D" and
            row["exception"] == "Max Delay Datapath Only" and row["depth"] == "0" and
            row["source_clock"] == "clk_out1_clk_wiz_ddr" and
            row["destination_clock"] == "centered_rx_clock.rx_source", "Unknown RX-stop CDC finding")
    require(prefix + "captured_reg/D" in facts and
            "PASS_RXSTOP_ACTUAL_NEXT_STATE_32_CASES_RESET_INACTIVE" in truth,
            "Missing actual RX-stop capture proof")
    return ("held_payload_mailbox", "The scalar held command is sampled only after a two-stage synchronized "
            "request and while the destination is not holding a previous command. The actual routed LUT/D/CE "
            "next-state recurrence passed all 32 combinations; ACK protects ownership. Scoped routed payload "
            "delay/skew and independent-clock stop/drain/release tests pass. Common cold reset only.")


def validate(contract_path, dcp, cdc_report=None):
    contract = load(contract_path)
    require(contract["status"] == "READY_NETBOOT_RX_STOP_RV64GC100_STATIC_BIT_RELEASE", "Unqualified contract")
    root, repo = Path(contract["candidate"]), Path(contract["repo"])
    require(Path(dcp).resolve() == (root / "implementation-resume-opt-r1/routed.dcp").resolve(), "Wrong own route")
    require(sha(dcp) == contract["dcp_sha256"] and sha(root / "inputs.json") == contract["inputs_sha256"],
            "DCP/input identity drift")
    inputs = load(root / "inputs.json")
    require((inputs["isa"], inputs["f_d_enabled"], inputs["issue_width"], inputs["cpu_hz"],
             inputs["uart_baud"], inputs["ddr_bytes"], inputs["netboot_rx_stop_abi"]) ==
            ("rv64gc", True, 2, 100000000, 460800, 0x80000000, 2), "Wrong hardware profile")
    require(inputs["ram_base"] == "0x80200000" and inputs["end_exclusive"] == "0x100200000" and
            inputs["monitor_reserved"] == ["0xffff8000", "0xffffc000"], "Wrong DDR/monitor map")
    for name, digest in inputs["candidate_sha256"].items():
        require(sha(root / name) == digest, "Frozen candidate drift: " + name)
    check_map(repo, checked_source_map(inputs))
    for path, digest in contract["tools_sha256"].items():
        require(sha(path) == digest, "Qualification tool drift: " + path)
    evidence = contract["evidence"]
    texts = {}
    for role, item in evidence.items():
        require(sha(item["path"]) == item["sha256"], "Evidence drift: " + role)
        texts[role] = Path(item["path"]).read_text(encoding="utf-8-sig")
    proof = json.loads(texts["routed_proof"])
    require(proof["status"] == "RV64GC100_ROUTED_TIMING_MET_CDC_BOARD_REVIEW_PENDING" and
            proof["dcp_sha256"] == sha(dcp) and proof["source_integrated"] and proof["bit_requested"] and
            proof["routed_timing_met"] and proof["ddr_bytes"] == 0x80000000, "Route not qualified")
    for key in ("candidate_input_drift", "current_source_drift", "runtime_errors",
                "runtime_critical_warnings", "drc_errors_or_critical"):
        require(not proof[key], "Unreviewed route issue: " + key)
    run = Path(dcp).parent
    for name, digest in proof["artifact_sha256"].items():
        path = run / name
        require(sha(path if path.is_file() else root / name) == digest, "Route report drift: " + name)
    timing = (run / "timing_summary.rpt").read_text()
    require(routed_state(timing) and summary(timing) == proof["board"], "Not current routed STA")
    require(all(proof["board"][k] >= 0 for k in ("setup_ns", "hold_ns", "pulse_ns")) and
            all(proof["board"][k] == 0 for k in ("setup_failures", "hold_failures", "pulse_failures")), "STA failed")
    require(proof["routing"]["all_routed"] and all(proof["clock_coverage"].values()) and
            proof["bus_skew"]["checks"] >= 27 and proof["bus_skew"]["failures"] == 0 and
            proof["bus_skew"]["minimum_slack_ns"] >= 0, "Route/coverage/skew failed")
    for group in (proof["io"]["tx"], proof["io"]["rx"], proof["divider_release"]):
        require(group and min(group.values()) >= 0, "IO/reset release timing failed")
    for role, markers in {
        "cdc_facts": ["READ_ONLY_STRUCTURAL_FACTS_COMPLETE_NOT_CDC_SIGNOFF", "QUARTER_TX_COMMON_WORD_RESET_EPOCH_PASS"],
        "mailbox_truth": ["PASS_TXCONFIG_BIT3_ACTUAL_NEXT_STATE_32_CASES_RESET_INACTIVE", "PASS_RXSTOP_ACTUAL_NEXT_STATE_32_CASES_RESET_INACTIVE"],
    }.items():
        binding = re.search(r"^CHECKPOINT=(.+)$", texts[role], re.M)
        require(binding and Path(binding[1]).resolve() == Path(dcp).resolve() and
                all(marker in texts[role] for marker in markers), "Wrong actual netlist facts: " + role)
    for role, status in {
        "mac_dma": "PASS_GMAC_SHUTDOWN_SINGLE_CLOCK",
        "default_boundaries": "PASS_GMAC_STOP_DEFAULT_BOUNDARIES",
        "firmware": "passed", "rx_stop_cdc": "PASS_RX_ADMISSION_STOP_CDC_SHORT",
        "linux_handoff": "PASS_LINUX_GMAC_RX_STOP_HANDOFF_SCRIPTED_MMIO",
    }.items():
        receipt = json.loads(texts[role])
        require(receipt["status"] == status, "Failed affected check: " + role)
        check_map(repo, receipt.get("source_sha256", {}))
    cdc = json.loads(texts["rx_stop_cdc"])
    require(cdc["independent_clock_runtime_verified"] and set(cdc["negative_checks"]) == {"payload", "drain"},
            "Incomplete independent-clock proof")
    check_map(repo, cdc["protected_cpu_dma_sha256"])
    for name, digest in cdc["output_sha256"].items():
        require(sha(Path(evidence["rx_stop_cdc"]["path"]).parent / name) == digest, "CDC output drift")
    firmware = json.loads(texts["firmware"])
    require(firmware["netboot_rx_stop_abi"] == 2 and firmware["netboot_rom_sha256"] == sha(root / "firmware/bootrom.bin") and
            firmware["compiled_uart_contract_verified"], "Wrong compiled ROM")
    require(json.loads(texts["linux_handoff"])["driver_sha256"] == sha(repo / "fpga/firmware/linux_net/valence_gmac.c"),
            "Linux handoff driver changed")
    baseline = Path(contract["baseline"])
    require(sha(baseline / "inputs.json") == inputs["baseline_manifest_sha256"], "Baseline identity drift")
    unchanged = [p.name for p in (root / "rtl").glob("*.sv") if (baseline / "rtl" / p.name).is_file()
                 and sha(p) == sha(baseline / "rtl" / p.name)]
    require(len(unchanged) == inputs["unchanged_rtl_files"] == 234, "Unchanged baseline RTL identity mismatch")
    require(sha(baseline / "implementation/routed.dcp") == inputs["incremental_routed_reference_sha256"], "Baseline DCP changed")
    sys.path.insert(0, str(repo / "fpga/firmware"))
    from audit_bootrom import audit
    ip = root / "ip-build/board_ip.gen/sources_1/ip/blk_mem_gen_0"
    rom = audit(root / "firmware/bootrom.bin", ip / "blk_mem_gen_0.mif", ip / "blk_mem_gen_0.dcp")
    require(rom["mifWordsMatched"] == 32768 and rom["binarySha256"] == firmware["netboot_rom_sha256"], "ROM words differ")
    count = validate_cdc_review((Path(cdc_report) if cdc_report else run / "cdc.rpt").read_text(),
                               json.loads(texts["cdc_review"]), sha(dcp), set(evidence))
    return dict(status="PASS_NETBOOT_RX_STOP_RV64GC100_STATIC_BIT_RELEASE", dcp_sha256=sha(dcp),
                reviewed_cdc_findings=count, engineering_margin_met=False, board_verified=False)


def prepare(args):
    root, repo = args.candidate.resolve(), args.repo.resolve()
    require(not args.out.exists(), "Preserve previous contract")
    stage = repo / "build/integration/netboot-drain-20261007-r1"
    dcp = root / "implementation-resume-opt-r1/routed.dcp"
    roles = dict(routed_proof=args.routed_proof,
        cdc_facts=root / "verification/routed-cdc-facts/structural_facts.txt",
        mailbox_truth=root / "verification/routed-mailbox-facts-r2/mailbox_next_state.txt",
        mac_dma=repo / "build/gsim/gmac-shutdown-integrated-20261007-r1/receipt.json",
        default_boundaries=repo / "build/gsim/gmac-stop-boundaries-integrated-20261007-r1/receipt.json",
        firmware=stage / "firmware/receipt.json", rx_stop_cdc=root / "verification/cdc-xsim/receipt.json",
        linux_handoff=stage / "linux-rx-stop-handoff/receipt.json", baseline_binding=args.baseline_release)
    facts, truth = roles["cdc_facts"].read_text(), roles["mailbox_truth"].read_text()
    findings = []
    for row in cdc_inventory((dcp.parent / "cdc.rpt").read_text()):
        if row["severity"] == "Info":
            continue
        if "/rxStop/command/held_reg/" in row["source"]:
            category, reason = rx_stop_finding(row, facts, truth)
            refs = ["cdc_facts", "mailbox_truth", "rx_stop_cdc", "mac_dma", "routed_proof"]
        else:
            category, reason, unused = classify(row, facts)
            reason += " This batch reuses the byte-identical baseline interface RTL; it does not replay its full historical suite."
            refs = ["cdc_facts", "baseline_binding", "routed_proof"]
            if category == "held_payload_mailbox": refs += ["mailbox_truth", "rx_stop_cdc"]
            if category.startswith("async_fifo_"): refs += ["rx_stop_cdc", "mac_dma"]
            if category == "held_payload_register_bridge": refs += ["register_bridge_static"]
        findings.append(dict(fingerprint=fingerprint(row), classification=category, reason=reason,
                             evidence=refs, actual_finding=row))
    review = dict(status="PASS_CURRENT_ROUTED_NATIVE_CDC_REVIEW_WITH_DOCUMENTED_FINDINGS_NOT_BOARD_RUNTIME",
                  dcp_sha256=sha(dcp), timing_exceptions_added=False, unreviewed_findings=[], findings=findings,
                  class_counts=dict(collections.Counter(f["classification"] for f in findings)))
    args.out.mkdir(parents=True)
    for role, value in (("cdc_review", review), ("register_bridge_static", bridge_fields(root, repo))):
        path = args.out / (role + ".json")
        path.write_text(json.dumps(value, indent=2) + "\n")
        roles[role] = path
    tools = [Path(__file__), Path(__file__).with_name("release_netboot_rv64gc.tcl"),
             Path(__file__).with_name("review_netboot_mailbox_control.tcl")]
    contract = dict(status="READY_NETBOOT_RX_STOP_RV64GC100_STATIC_BIT_RELEASE",
        candidate=str(root), repo=str(repo), baseline=str(args.baseline),
        dcp_sha256=sha(dcp), inputs_sha256=sha(root / "inputs.json"),
        tools_sha256={str(p): sha(p) for p in tools},
        evidence={role: dict(path=str(p), sha256=sha(p)) for role, p in roles.items()},
        bit_requested=True, physical_board_programmed=False, engineering_margin_met=False,
        limits=["Affected short checks, not a repeated full GSIM/CDC or whole-SoC dynamic equivalence test.",
                "1 ps nominal setup margin requires board stability tests; no throughput recovery claimed.",
                "A matching Linux RX_STOP-aware module/image is required for Ethernet after ROM handoff."])
    path = args.out / "qualified-contract.json"
    path.write_text(json.dumps(contract, indent=2) + "\n")
    print(json.dumps(validate(path, dcp), sort_keys=True))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--contract", type=Path)
    ap.add_argument("--dcp", type=Path)
    ap.add_argument("--cdc-report", type=Path)
    ap.add_argument("--candidate", type=Path)
    ap.add_argument("--repo", type=Path)
    ap.add_argument("--baseline", type=Path)
    ap.add_argument("--baseline-release", type=Path)
    ap.add_argument("--routed-proof", type=Path)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    if args.contract:
        print(json.dumps(validate(args.contract, args.dcp, args.cdc_report), sort_keys=True))
    else:
        require(all((args.candidate, args.repo, args.baseline, args.baseline_release, args.routed_proof, args.out)), "Missing prepare arguments")
        prepare(args)
