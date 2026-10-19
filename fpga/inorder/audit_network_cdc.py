#!/usr/bin/env python3
"""Inventory every detailed CDC Critical row; classification NEVER waives STA/CDC."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(text):
    expected = {rule: int(count) for rule, count in re.findall(
        r"(?m)^ *(CDC-\d+) +Critical +(\d+) +", text)}
    rows = []
    source_clock = destination_clock = None
    for line in text.splitlines():
        if line.startswith("Source Clock:"):
            source_clock = line.split(":", 1)[1].strip()
        if line.startswith("Destination Clock:"):
            destination_clock = line.split(":", 1)[1].strip()
        tokens = line.split()
        if len(tokens) < 8 or not tokens[0].isdigit() or tokens[2] != "Critical":
            continue
        rule, source, destination = tokens[1], tokens[-2], tokens[-1]
        category = "UNKNOWN_CRITICAL_REQUIRES_REVIEW"
        # Exact held/captured pairing and max-delay are necessary, NOT sufficient
        # for a bundled-data proof. Keep the CDC rule and unresolved status.
        if rule == "CDC-1" and "Max Delay Datapath Only" in line:
            match = re.fullmatch(r"(bank/gmac/(?:rxStop/command|txConfig/mailbox)/)held_reg(\[\d+\])?/C", source)
            if match and destination == match[1] + "captured_reg" + (match[2] or "") + "/D":
                category = "HELD_MAILBOX_REQUIRES_INSTANCE_HANDSHAKE_REVIEW"
        elif rule in ("CDC-10", "CDC-11") and source == "io_resetN" and re.search(
                r"/release_0_reg\[0\]/PRE$", destination):
            category = ("COMMON_RESET_WITH_COMBINATIONAL_WARM_RESET_REQUIRES_REVIEW"
                        if rule == "CDC-10" else "COMMON_RESET_FANOUT_REQUIRES_RECOVERY_REMOVAL")
        elif rule == "CDC-10" and source == "bank/gmac/media/ingressResetSource_reg/C" and re.fullmatch(
                r"bank/gmac/physicalIngress/(?:crossing/fifo/)?(?:source|destination)Release/release_0_reg\[0\]/PRE",
                destination):
            category = "REGISTERED_WARM_RESET_OR_TREE_REQUIRES_INSTANCE_RESET_REVIEW"
        elif rule == "CDC-10" and source == "release_0/release_0_reg[2]/C" and re.fullmatch(
                r"transport/enabled.transport/(?:raw|source|update)_release_reg\[0\]/CLR", destination):
            category = "BSCAN_RESET_OR_TREE_REQUIRES_INSTANCE_RESET_REVIEW"
        elif rule == "CDC-10" and source == "u_soc/release_0/release_0_reg[2]/C" and re.fullmatch(
                r"u_soc/transport/enabled.transport/(?:raw|source|update)_release_reg\[0\]/CLR", destination):
            category = "BSCAN_RESET_OR_TREE_REQUIRES_INSTANCE_RESET_REVIEW"
        elif rule == "CDC-11" and source == "reset_pipe_reg[2]/C" and destination in {
                "u_soc/bank/cmu/bridge/destinationResetSync/release_0_reg[0]/PRE",
                "u_soc/bank/uart/agent/release_0/release_0_reg[0]/PRE",
                "u_soc/bank/uart/bridge/destinationResetSync/release_0_reg[0]/PRE",
                "u_soc/bank/uart/gatedClock_gate/release_0/release_0_reg[0]/PRE",
                "u_soc/bank/uart/ingress/release_0/release_0_reg[0]/PRE",
                "u_soc/bank/uart/rawRelease/release_0_reg[0]/PRE"}:
            category = "CPU_RELEASE_TO_AON_RESET_FANOUT_REQUIRES_RECOVERY_REMOVAL_REVIEW"
        elif rule == "CDC-11" and re.fullmatch(
                r"bank/cmu/cmu/policy(?:_2)?/io_quiesce_REG_reg/C", source) and re.fullmatch(
                r"bank/(?:gmac|uart)/(?:agent(?:_1)?/request|ingress/q_sync)/stages_reg\[0\]/D", destination):
            category = "DUPLICATED_QUIESCE_SYNCHRONIZERS_REQUIRE_RECONVERGENCE_REVIEW"
        elif rule == "CDC-11" and source == "bank/gmac/mediaOpen_reg/C" and re.fullmatch(
                r"bank/gmac/(?:rx|tx)Link_sync/stages_reg\[0\]/D", destination):
            category = "DUPLICATED_MEDIA_LEVEL_REQUIRES_RECONVERGENCE_REVIEW"
        rows.append({"rule": rule, "source_clock": source_clock, "destination_clock": destination_clock,
                     "source": source, "destination": destination, "category": category,
                     "waived": False, "original_row": line.strip()})
    actual = dict(Counter(row["rule"] for row in rows))
    if actual != expected:
        raise ValueError(f"CDC detailed/header inventory mismatch: {actual} != {expected}")
    unknown = [row for row in rows if row["category"].startswith("UNKNOWN")]
    return {"status": "UNKNOWN_CRITICAL_REQUIRES_REVIEW" if unknown else
                     ("KNOWN_CRITICAL_REVIEW_REQUIRED" if rows else "NO_CRITICAL_ROWS_NOT_SIGNOFF"),
            "critical_counts": actual, "categories": dict(Counter(row["category"] for row in rows)),
            "unknown_critical_count": len(unknown), "critical_rows": rows,
            "cdc_signed_off": False, "physical_qualified": False,
            "note": "No exceptions/waivers applied. Short BUFG/mailbox proof does not qualify all MAC/reset instances."}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report", required=True, type=Path)
    ap.add_argument("--clock-receipt", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()
    if args.output.exists():
        ap.error("preserve previous audit evidence")
    proof = json.loads(args.clock_receipt.read_text())
    if proof["status"] != "PASS_I1_BALANCED_CLOCK_CDC_SHORT":
        ap.error("balanced clock short proof is required, not physical signoff")
    result = audit(args.report.read_text())
    result.update({"report_sha256": sha(args.report), "clock_short_receipt_sha256": sha(args.clock_receipt),
                   "auditor_sha256": sha(Path(__file__))})
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "critical_rows"}))
    if result["unknown_critical_count"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
