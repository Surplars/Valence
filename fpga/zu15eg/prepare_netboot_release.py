#!/usr/bin/env python3
"""Build a fresh r4 release contract with actual netlist facts, not old STA."""
import argparse
import collections
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from prepare_native_release_contract import bridge_fields, classify, write_new
from verify_native_release_contract import cdc_inventory, fingerprint, require, sha, verify_contract


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("candidate", type=Path)
    p.add_argument("--repo", type=Path, required=True)
    p.add_argument("--stage", type=Path, required=True)
    p.add_argument("--old-contract", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    root, stage, output = a.candidate.resolve(), a.stage.resolve(), a.out.resolve()
    require(not output.exists(), "Preserve prior release evidence")
    old = json.loads(a.old_contract.read_text(encoding="utf-8"))
    unchanged = ("gmac_cdc", "clock_gate_cdc", "managed_cdc", "quarter_tx", "quarter_rx")
    roles = {role: Path(old["evidence"][role]["path"]) for role in unchanged}
    for role in unchanged:
        require(sha(roles[role]) == old["evidence"][role]["sha256"], "Independent proof identity drift")
    roles.update(
        routed_proof=stage / "routed-r4/completion.json",
        cdc_facts=root / "cdc-facts-r4/structural_facts.txt",
        mailbox_truth=root / "mailbox-facts-r4/mailbox_next_state.txt",
        path_facts=root / "path-review-r4/release_input_facts.txt",
        linux_image=stage / "linux-audit-r4/linux-input-audit.json",
        linux_rootfs=stage / "linux-audit-r4/kernel-rootfs-input-audit.json",
        native_short=a.repo / "build/gsim/rv64gc-native-netboot-20261006-r4/receipt.json")
    dcp = root / "implementation-report-recovery-r1/routed.dcp"
    facts = roles["cdc_facts"].read_text(encoding="utf-8")
    require("READ_ONLY_STRUCTURAL_FACTS_COMPLETE_NOT_CDC_SIGNOFF" in facts and
            "PASS_TXCONFIG_BIT3_ACTUAL_NEXT_STATE_32_CASES_RESET_INACTIVE" in
            roles["mailbox_truth"].read_text(encoding="utf-8"), "Actual netlist facts incomplete")
    findings = []
    rows = cdc_inventory((dcp.parent / "cdc.rpt").read_text(encoding="utf-8"))
    for row in rows:
        if row["severity"] == "Info":
            continue
        kind, reason, evidence = classify(row, facts)
        findings.append(dict(fingerprint=fingerprint(row), classification=kind,
                             reason=reason, evidence=evidence, actual_finding=row))
    review = dict(status="PASS_CURRENT_ROUTED_NATIVE_CDC_REVIEW_WITH_DOCUMENTED_FINDINGS_NOT_BOARD_RUNTIME",
                  dcp_sha256=sha(dcp), timing_exceptions_added=False,
                  unreviewed_findings=[], findings=findings,
                  class_counts=dict(collections.Counter(f["classification"] for f in findings)),
                  severity_counts=dict(collections.Counter(r["severity"] for r in rows)),
                  physical_gmac_verified=False)
    import sys
    sys.path.insert(0, str(a.repo / "fpga/firmware"))
    from audit_bootrom import audit
    rom = audit(root / "firmware/bootrom.bin",
                root / "ip-build/board_ip.gen/sources_1/ip/blk_mem_gen_0/blk_mem_gen_0.mif",
                root / "ip-build/board_ip.gen/sources_1/ip/blk_mem_gen_0/blk_mem_gen_0.dcp")
    output.mkdir(parents=True)
    for role, name, value in (
        ("cdc_review", "cdc-review.json", review),
        ("register_bridge_static", "register-bridge-static.json", bridge_fields(root, a.repo)),
        ("rom_words", "rom-words.json", rom)):
        roles[role] = output / name
        write_new(roles[role], value)
    manifest = json.loads((root / "inputs.json").read_text())
    for role, item in manifest["new_evidence"].items():
        roles["netboot_" + role] = Path(item["path"])
        require(sha(roles["netboot_" + role]) == item["sha256"], "Changed-boundary proof drift")
    contract = dict(
        status="READY_RV64GC100_NATIVE_BOARD_BIT_GENERATION_STATIC_REVIEW_NOT_BOARD_RUNTIME",
        isa="rv64gc", f_d_enabled=True, issue_width=2, cpu_hz=100000000, uart_baud=460800,
        physical_board_programmed=False, candidate=str(root), repo=str(a.repo.resolve()),
        candidate_manifest_sha256=sha(root / "inputs.json"), dcp=str(dcp), dcp_sha256=sha(dcp),
        evidence={role: dict(path=str(path), sha256=sha(path)) for role, path in roles.items()},
        phy_tx_delay_enabled=False, phy_rx_delay_enabled=True, phy_initialization_owner="software",
        incremental_route=True, donor_checkpoint_sha256=manifest["donor_checkpoint_sha256"],
        limits=["Two leaf partitions replaced; unaffected placement preserved; existing routing reused but blocking routes may be rerouted.",
                "Actual netlist CDC, ROM and full-board STA reviewed; not independent whole-netlist equivalence.",
                "TCP liveness fix and network BootROM still require physical board testing."])
    path = output / "qualified-contract.json"
    write_new(path, contract)
    result = verify_contract(path, dcp)
    write_new(output / "verification.json", result)
    print(json.dumps(dict(result, contract=str(path), cdc_class_counts=review["class_counts"])))


if __name__ == "__main__":
    main()
