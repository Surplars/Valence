#!/usr/bin/env python3
"""Read-only, fail-closed current RV64GC/native board release contract check.

A documented CDC review is required; this does not waive findings, change
constraints, certify encrypted vendor RTL, or claim physical board operation.
"""
import argparse
import collections
import hashlib
import json
from pathlib import Path
import re
import sys


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def cdc_inventory(text):
    """Parse every detailed row and check it against the declared ID totals."""
    declared = {}
    rows = []
    clocks = {}
    for line in text.splitlines():
        summary = re.fullmatch(r"(CDC-\d+)\s+(Critical|Warning|Info)\s+(\d+)\s+.*", line.strip())
        if summary:
            require(summary[1] not in declared, "duplicate CDC summary")
            declared[summary[1]] = int(summary[3])
        for label, key in (("Source Clock: ", "source_clock"), ("Destination Clock: ", "destination_clock"),
                           ("CDC Type: ", "clock_relationship")):
            if line.startswith(label):
                clocks[key] = line[len(label):].strip()
        if re.match(r"^\s*\d+\s+CDC-\d+\s+(Critical|Warning|Info)\b", line):
            columns = re.split(r"\s{2,}", line.strip())
            require(len(columns) == 8, "unparsed CDC detail row")
            require(set(clocks) == {"source_clock", "destination_clock", "clock_relationship"},
                    "CDC detail has no complete clock-pair identity")
            row = dict(zip(("row", "id", "severity", "description", "depth", "exception", "source", "destination"),
                           columns))
            row.pop("row")
            rows.append(dict(row, **clocks))
    actual = dict(collections.Counter(row["id"] for row in rows))
    require(declared and actual == declared, "CDC summary/detail counts disagree")
    return rows


def fingerprint(row):
    return hashlib.sha256(json.dumps(row, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def vendor_debug_fifo(row):
    """Only four observed vendor Debug Hub data captures, never native paths."""
    tck = "dbg_hub/inst/BSCANID.u_xsdbm_id/SWITCH_N_EXT_BSCAN.bscan_inst/SERIES7_BSCAN.bscan_inst/INTERNAL_TCK"
    base = "dbg_hub/inst/BSCANID.u_xsdbm_id/CORE_XSDB.UUT_MASTER/U_ICON_INTERFACE/"
    for direction in ("RD", "WR"):
        leaf = direction.lower()
        prefix = (base + f"U_CMD6_{direction}/U_{direction}_FIFO/SUBCORE_FIFO.xsdbm_v3_0_4_{leaf}fifo_inst/"
                  "inst_fifo_gen/gconvfifo.rf/grf.rf/gntv_or_sync_fifo.mem/gdm.dm_gen.dm/")
        clocks = ("mmcm_clkout5", tck) if direction == "RD" else (tck, "mmcm_clkout5")
        for bit, suffix in ((14, ""), (15, "__0")):
            if (row["source"] == prefix + "RAM_reg_0_15_14_15" + suffix + "/DP/CLK" and
                    row["destination"] == prefix + f"gpr1.dout_i_reg[{bit}]/D" and
                    (row["source_clock"], row["destination_clock"]) == clocks and
                    row["id"] == "CDC-15" and row["severity"] == "Warning" and
                    row["exception"] == "False Path" and row["depth"] == "0"):
                return True
    return False


def validate_cdc_review(text, review, dcp_sha256, evidence_roles):
    require(review["status"] == "PASS_CURRENT_ROUTED_NATIVE_CDC_REVIEW_WITH_DOCUMENTED_FINDINGS_NOT_BOARD_RUNTIME",
            "CDC review is incomplete")
    require(review["dcp_sha256"] == dcp_sha256, "CDC review belongs to another DCP")
    require(review["timing_exceptions_added"] is False and not review["unreviewed_findings"],
            "CDC review must not hide an unreviewed finding")
    rows = [row for row in cdc_inventory(text) if row["severity"] != "Info"]
    expected = {fingerprint(row): row for row in rows}
    require(len(expected) == len(rows), "duplicate CDC finding identities")
    checked = {}
    classes = {
        "reset_async_assert_sync_release", "persistent_level_two_sync",
        "held_payload_mailbox", "held_payload_register_bridge", "async_fifo_gray", "async_fifo_payload",
        "vendor_encrypted_boundary", "vendor_debug_fifo",
    }
    for finding in review["findings"]:
        key = finding["fingerprint"]
        require(key not in checked and key in expected, "CDC review has duplicate/foreign finding")
        require(finding["classification"] in classes and len(finding["reason"]) >= 30,
                "CDC finding lacks a concrete classification/reason")
        require(finding["evidence"] and set(finding["evidence"]) <= evidence_roles,
                "CDC finding lacks bound evidence")
        row = expected[key]
        if finding["classification"] == "vendor_encrypted_boundary":
            require(row["severity"] == "Warning" and row["id"] == "CDC-15" and
                    row["source"] == row["destination"] == "<hidden>",
                    "vendor trust must not cover a visible/critical native path")
            require(row["source_clock"] == "mmcm_clkout0" and
                    row["destination_clock"] == "clk_out1_clk_wiz_ddr" and
                    row["exception"] == "False Path", "unknown encrypted vendor clock boundary")
        if finding["classification"] == "vendor_debug_fifo":
            require(vendor_debug_fifo(row), "vendor debug trust must not cover another path")
        checked[key] = finding
    require(set(checked) == set(expected), "not every Critical/Warning CDC finding was reviewed")
    return len(checked)


def verify_contract(contract_path, dcp, cdc_report=None):
    contract_path, dcp = Path(contract_path), Path(dcp)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    require(contract["status"] == "READY_RV64GC100_NATIVE_BOARD_BIT_GENERATION_STATIC_REVIEW_NOT_BOARD_RUNTIME",
            "contract is not ready for bit generation")
    require(contract["isa"] == "rv64gc" and contract["f_d_enabled"] is True and
            contract["issue_width"] == 2 and contract["cpu_hz"] == 100000000 and
            contract["uart_baud"] == 460800, "wrong release profile")
    require(dcp.resolve() == Path(contract["dcp"]).resolve(), "unexpected routed checkpoint")
    digest = sha(dcp)
    require(digest == contract["dcp_sha256"], "routed checkpoint identity changed")
    require(contract["physical_board_programmed"] is False, "static contract must not claim board operation")
    candidate, repo = Path(contract["candidate"]), Path(contract["repo"])
    require(dcp.resolve() == (candidate / "implementation-report-recovery-r1/routed.dcp").resolve(),
            "release only this source candidate's own recovered route")
    manifest = candidate / "inputs.json"
    require(sha(manifest) == contract["candidate_manifest_sha256"], "frozen manifest changed")
    inputs = json.loads(manifest.read_text(encoding="utf-8"))
    require(inputs["isa"] == "rv64gc" and inputs["f_d_enabled"] is True and
            inputs["issue_width"] == 2 and inputs["cpu_hz"] == 100000000 and
            inputs["uart_baud"] == 460800 and
            inputs["tx_clock_architecture"] == "common_clk250_dedicated_oddr",
            "frozen source candidate has wrong hardware profile")
    sys.path.insert(0, str(repo / "fpga/zu15eg"))
    from audit_native_rv64gc import checked_source_map, summary, routed_state
    for name, expected in inputs["candidate_sha256"].items():
        require(sha(candidate / name) == expected, "frozen input drift: " + name)
    for name, expected in checked_source_map(inputs).items():
        require(sha(repo / name) == expected, "current source drift: " + name)

    evidence = contract["evidence"]
    required = {
        "routed_proof", "cdc_review", "cdc_facts", "mailbox_truth", "path_facts",
        "rom_words", "linux_image", "linux_rootfs", "gmac_cdc", "clock_gate_cdc",
        "quarter_tx", "quarter_rx", "native_short", "managed_cdc",
    }
    require(required <= set(evidence), "missing required release evidence")
    texts = {}
    for role, item in evidence.items():
        require(sha(item["path"]) == item["sha256"], "evidence identity changed: " + role)
        texts[role] = Path(item["path"]).read_text(encoding="utf-8")
    proof = json.loads(texts["routed_proof"])
    require(proof["status"] == "RV64GC100_ROUTED_TIMING_MET_CDC_BOARD_REVIEW_PENDING" and
            proof["dcp_sha256"] == digest and proof["routed_timing_met"] is True and
            proof["source_integrated"] is True and proof["bit_requested"] is True,
            "route is not fully timing qualified for this DCP")
    require(not any(proof[key] for key in (
        "candidate_input_drift", "current_source_drift", "runtime_errors",
        "runtime_critical_warnings", "drc_errors_or_critical")), "route has unreviewed errors/drift")
    run = dcp.parent
    for name, expected in proof["artifact_sha256"].items():
        local = run / name
        if not local.is_file():
            local = candidate / name
        require(sha(local) == expected, "routed evidence changed: " + name)
    timing = (run / "timing_summary.rpt").read_text(encoding="utf-8")
    require(routed_state(timing), "STA is not routed")
    actual = summary(timing)
    require(actual == proof["board"], "STA result disagrees with archived proof")
    require(all(actual[name] >= 0 for name in ("setup_ns", "hold_ns", "pulse_ns")) and
            all(actual[name] == 0 for name in ("setup_failures", "hold_failures", "pulse_failures")),
            "setup/hold/pulse failure")
    require(proof["routing"]["all_routed"] and all(proof["clock_coverage"].values()) and
            proof["bus_skew"]["checks"] >= 27 and proof["bus_skew"]["failures"] == 0 and
            proof["bus_skew"]["minimum_slack_ns"] >= 0, "routing/coverage/skew failure")
    for group in (proof["io"]["tx"], proof["io"]["rx"], proof["divider_release"]):
        require(group and min(group.values()) >= 0, "external IO/divider reset failure")

    marker_checks = {
        "cdc_facts": ("READ_ONLY_STRUCTURAL_FACTS_COMPLETE_NOT_CDC_SIGNOFF", "QUARTER_TX_COMMON_WORD_RESET_EPOCH_PASS"),
        "mailbox_truth": ("PASS_TXCONFIG_BIT3_ACTUAL_NEXT_STATE_32_CASES_RESET_INACTIVE",),
        "path_facts": ("BOOTROM_INIT_MATCH=4176", "LEGACY_ETH_CLOCK_IP_CELLS=0"),
    }
    for role, markers in marker_checks.items():
        require(all(marker in texts[role] for marker in markers), "missing actual-netlist fact: " + role)
        binding = re.search(r"^CHECKPOINT=(.+)$", texts[role], re.M)
        require(binding and Path(binding[1]).resolve() == dcp.resolve(), "fact belongs to another DCP: " + role)
    reviewed = validate_cdc_review((Path(cdc_report) if cdc_report else run / "cdc.rpt").read_text(encoding="utf-8"),
                                  json.loads(texts["cdc_review"]), digest, set(evidence))

    # Replay all MIF words, padding and selected ROM IP provenance now.
    sys.path.insert(0, str(repo / "fpga/firmware"))
    from audit_bootrom import audit
    rom = audit(candidate / "firmware/bootrom.bin",
                candidate / "ip-build/board_ip.gen/sources_1/ip/blk_mem_gen_0/blk_mem_gen_0.mif",
                candidate / "ip-build/board_ip.gen/sources_1/ip/blk_mem_gen_0/blk_mem_gen_0.dcp")
    declared_rom = json.loads(texts["rom_words"])
    require(rom["binarySha256"] == declared_rom["binarySha256"] and
            rom["romDcpSha256"] == declared_rom["romDcpSha256"] and
            declared_rom["mifWordsMatched"] == 32768, "selected ROM word proof changed")
    for role, status in (
        ("linux_image", "PASS_NATIVE_LINUX_PAYLOAD_IDENTITY_NOT_RUNTIME"),
        ("linux_rootfs", "PASS_ACTUAL_KERNEL_INITRAMFS_CONTENTS_NOT_RUNTIME"),
        ("native_short", "PASS_RV64GC_NATIVE_AFFECTED_SHORT"),
    ):
        require(json.loads(texts[role])["status"] == status, "wrong functional/firmware proof: " + role)
    linux, rootfs = json.loads(texts["linux_image"]), json.loads(texts["linux_rootfs"])
    require(linux["candidate_inputs_sha256"] == contract["candidate_manifest_sha256"] and
            linux["isa"] == "rv64gc" and linux["issue_width"] == 2 and
            linux["cpu_hz"] == 100000000 and linux["uart_baud"] == 460800,
            "Linux payload belongs to another board profile")
    linux_dir = repo / linux["source_directory"]
    require(sha(linux_dir / "manifest.json") == linux["manifest_sha256"] == rootfs["manifest_sha256"],
            "Linux manifest changed")
    linux_manifest = json.loads((linux_dir / "manifest.json").read_text(encoding="utf-8"))
    for name, item in linux_manifest["files"].items():
        require(sha(linux_dir / name) == item["sha256"] and
                (linux_dir / name).stat().st_size == item["bytes"], "Linux file changed: " + name)
    require(rootfs["kernel_image_sha256"] == sha(linux_dir / "Image") and
            any(item["sha256"] == linux["payload_sha256"] and item["bytes"] == linux["payload_bytes"]
                for item in linux_manifest["files"].values()), "actual rootfs/payload identity changed")
    statuses = {
        "gmac_cdc": "PASS_NATIVE_GMAC_CDC_CLOCK_POLICY_SHORT",
        "clock_gate_cdc": "PASS_MANAGED_CLOCK_GATE_CDC_SHORT",
        "managed_cdc": "PASS_MANAGED_PERIPHERAL_CDC_SHORT",
        "quarter_tx": "PASS_NATIVE_TX_QUARTER_BOARD_SHORT",
        "quarter_rx": "PASS_NATIVE_RX_DESKEW_SHORT",
    }
    for role, status in statuses.items():
        item = json.loads(texts[role])
        require(item["status"] == status and item["input_sha256"], "missing independent interface proof")
        for name, expected in item["input_sha256"].items():
            require(sha(name) == expected, "independent interface input drift: " + name)
    tx, rx = json.loads(texts["quarter_tx"]), json.loads(texts["quarter_rx"])
    require(tx["actual_board_tx"] and tx["clock_architecture"] == "common_clk250_dedicated_oddr" and
            tx["physical_tx_phase_ns"] == 2.0 and tx["phy_tx_delay_enabled"] is False and
            tx["phy_rx_delay_enabled"] is True and tx["hardware_phy_init_enabled"] is False and
            len(tx["negative_checks"]) == 6, "wrong production TX short proof")
    require(rx["actual_board_rx"] and rx["isolated_tx_pad_clock"] and rx["delay_ps"] == 0 and
            rx["rx_phase_degrees"] == 33.75 and len(rx["negative_checks"]) == 3,
            "wrong production RX short proof")
    require(json.loads(texts["native_short"]) and
            evidence["native_short"]["sha256"] == inputs["short_receipt_sha256"], "wrong native short receipt")
    return dict(status="PASS_RV64GC100_NATIVE_RELEASE_CONTRACT_NOT_BOARD_RUNTIME",
                dcp_sha256=digest, reviewed_cdc_findings=reviewed, bit_generated=False)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--contract", type=Path, required=True)
    ap.add_argument("--dcp", type=Path, required=True)
    ap.add_argument("--cdc-report", type=Path, help="recheck a current reopened-DCP inventory")
    args = ap.parse_args()
    print(json.dumps(verify_contract(args.contract, args.dcp, args.cdc_report), sort_keys=True))


if __name__ == "__main__":
    main()
