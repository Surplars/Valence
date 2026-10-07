#!/usr/bin/env python3
"""Bind the actual r3 routed findings to reviewed facts and independent proofs.

No waiver/constraint change, implementation, board access or bit generation.
Unknown endpoints fail closed. Vendor Debug Hub trust is explicitly scoped.
"""
import argparse
import collections
import json
from pathlib import Path
import re
import sys

from verify_native_release_contract import (
    cdc_inventory, fingerprint, require, sha, validate_cdc_review,
    vendor_debug_fifo, verify_contract,
)


def write_new(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")


def bridge_fields(candidate, repo):
    path = candidate / "rtl/RegisterClockDomainBridge.sv"
    text = path.read_text(encoding="utf-8")
    requests = ("address", "write", "size", "data", "byteEnable")
    blocks = {
        "_GEN": [("requestHeld_" + f, "source_request_bits_" + f) for f in requests],
        "_GEN_0": [("reply_" + f, "responseHeld_" + f) for f in ("data", "error")],
        "_GEN_1": [("request_" + f, "requestHeld_" + f) for f in requests],
        "_GEN_2": [("responseHeld_" + f, "destination_response_bits_" + f) for f in ("data", "error")],
    }
    for control, fields in blocks.items():
        match = re.search(r"if \(" + control + r"\) begin\s*(.*?)\s*end", text, re.S)
        require(match is not None, "missing full bridge capture block " + control)
        actual = re.findall(r"(\w+)\s*<=\s*(\w+);", match[1])
        require(actual == fields, "non-atomic bridge capture fields " + control)
        for lhs, _ in fields:
            require(len(re.findall(r"\b" + lhs + r"\s*<=", text)) == 1,
                    "another field update can break held data: " + lhs)
    for equation in (
        "wire        _GEN = source_request_ready_0 & source_request_valid;",
        "wire        _GEN_0 = _responseSync_levelOut != seen & busy & ~valid;",
        "wire        _GEN_1 = _requestSync_levelOut != seen_1 & ~valid_1 & ~waiting;",
        "wire        _GEN_2 = destination_response_ready_0 & destination_response_valid;",
    ):
        require(equation in text, "bridge ownership/capture qualifier changed")
    return dict(status="PASS_CURRENT_REGISTER_BRIDGE_ATOMIC_FIELD_STATIC_REVIEW_NOT_FULL_METADATA_ASYNC_TEST",
                rtl=str(path), rtl_sha256=sha(path), field_groups=blocks,
                source_sha256=sha(repo / "src/main/scala/ip/bus/ClockDomainCrossing.scala"),
                limits=["Old independent CDC simulation prunes unused address/size/mask/error ports.",
                        "Those full fields are reviewed here for identical held/capture qualifiers, not claimed dynamically tested.",
                        "The actual full-board payload timing and bus-skew constraints are checked separately."])


def classify(row, facts):
    src, dst, kind = row["source"], row["destination"], row["id"]
    exception = row["exception"]
    if kind in {"CDC-10", "CDC-11"} and dst.endswith("[0]/PRE"):
        prefix = dst[:-len("[0]/PRE")]
        require(exception == "False Path" and
                f"CHAIN_DIRECT_PASS prefix={prefix} stages=3 async_assert=1" in facts,
                "reset release chain not structurally verified: " + dst)
        return ("reset_async_assert_sync_release",
                "Async assertion enters the common PRE of a verified three-stage ASYNC_REG chain. "
                "Only assertion is excepted; release-stage functional sinks remain timed. "
                "Coordinated cold reset is required; unilateral endpoint reset is unsupported.",
                ["cdc_facts", "clock_gate_cdc", "gmac_cdc", "managed_cdc", "quarter_tx", "quarter_rx"])
    quiesce = "u_soc/nativeBank/cmu/cmu/policy_2/io_quiesce_REG_reg/C"
    targets = {"u_soc/nativeBank/gmac/agent_1/request/stages_reg[0]/D",
               "u_soc/nativeBank/gmac/ingress/q_sync/stages_reg[0]/D"}
    if kind == "CDC-11" and src == quiesce and dst in targets:
        prefix = dst[:-len("[0]/D")]
        require(exception == "Max Delay Datapath Only" and src in facts and
                f"CHAIN_DIRECT_PASS prefix={prefix} stages=2 async_assert=0" in facts,
                "quiesce fanout not independently synchronized")
        return ("persistent_level_two_sync",
                "Registered CMU quiesce is a persistent level held through drain/stop, not a pulse. "
                "Both fanout destinations have independent verified two-stage synchronizers with no intermediate "
                "functional fanout. ACK requires local engines, FIFO storage and CPU-side work to drain.",
                ["cdc_facts", "gmac_cdc", "clock_gate_cdc", "managed_cdc"])
    mailbox = re.fullmatch(r"u_soc/nativeBank/gmac/(txConfig|rxConfig|txStats|rxStats)/mailbox/held_reg(\[\d+\])/C", src)
    if mailbox and kind in {"CDC-1", "CDC-15"}:
        name, bit = mailbox.groups()
        expected = f"u_soc/nativeBank/gmac/{name}/mailbox/captured_reg{bit}/D"
        require(dst == expected and exception == "Max Delay Datapath Only" and dst in facts,
                "unreviewed native held payload")
        if kind == "CDC-1":
            require(name == "txConfig" and bit == "[3]", "unknown folded mailbox bit")
        return ("held_payload_mailbox",
                "Held payload cannot change before the destination consumes it and returns synchronized ACK. "
                "Capture follows the synchronized request toggle; routed payload max-delay and bus-skew pass. "
                "For txConfig bit3, the folded self-hold LUT is additionally exhaustively checked for 32 actual "
                "netlist next states; it is not an unqualified direct asynchronous sample.",
                ["cdc_facts", "mailbox_truth", "gmac_cdc", "routed_proof"])
    gray = re.fullmatch(r"u_soc/nativeBank/gmac/(txFifo|rxFifo)/fifo/(read|write)Gray_reg\[(\d+):0\]/C", src)
    if kind == "CDC-6" and gray:
        fifo, direction, high = gray.groups()
        prefix = f"u_soc/nativeBank/gmac/{fifo}/fifo/{direction}GraySync_stage0_reg"
        require(dst == prefix + f"[{high}:0]/D" and exception == "Max Delay Datapath Only",
                "unexpected Gray destination")
        for bit in range(int(high) + 1):
            require(f"GRAY_STAGE {prefix}[{bit}] " in facts, "missing actual two-stage Gray bit")
        return ("async_fifo_gray",
                "Registered Gray pointer changes at most one bit per local transfer and crosses two direct "
                "ASYNC_REG stages. Scoped max-delay/bus-skew bounds pass; wraparound, backpressure and independently "
                "paused clocks were checked by the unchanged native FIFO short test. Common cold reset only.",
                ["cdc_facts", "gmac_cdc", "routed_proof"])
    fifo = re.fullmatch(r"u_soc/nativeBank/gmac/(txFifo|rxFifo)/fifo/storage_ext/.+/(CLK|WCLK)", src)
    if kind == "CDC-15" and fifo:
        name = fifo[1]
        require(re.fullmatch(fr"u_soc/nativeBank/gmac/{name}/fifo/output_0_reg\[\d+\]/D", dst) and
                exception == "Max Delay Datapath Only" and f"FIFO_PAYLOAD_PATHS {name} COUNT=38" in facts,
                "unknown FIFO payload path")
        return ("async_fifo_payload",
                "Dual-clock RAM ownership is transferred by synchronized Gray pointers. Read credit returns "
                "only after synchronous RAM output is captured, preventing producer overwrite before capture. "
                "All 38 physical capture bits are timed; the registered output remains stable under stall.",
                ["cdc_facts", "gmac_cdc", "routed_proof"])
    bridge = re.fullmatch(r"(u_soc/nativeBank/(?:cmu|uart)/bridge)/(requestHeld|responseHeld)_(address|write|size|data|byteEnable|error)_reg(\[\d+\])?/C", src)
    if kind == "CDC-15" and bridge:
        prefix, held, field, bit = bridge.groups()
        output = "request" if held == "requestHeld" else "reply"
        require(dst == f"{prefix}/{output}_{field}_reg{bit or ''}/D" and
                exception == "Max Delay Datapath Only", "unknown register bridge payload")
        return ("held_payload_register_bridge",
                "One-outstanding request/response bridge retains the full bundled payload until synchronized "
                "toggle ownership permits atomic capture. Original asynchronous data/control/gate tests remain "
                "hash-identical. The previously pruned metadata/error fields are statically checked for the same "
                "capture qualifiers, not claimed independently dynamically tested; full-board max-delay/skew pass.",
                ["managed_cdc", "register_bridge_static", "cdc_facts", "routed_proof", "native_short"])
    if vendor_debug_fifo(row):
        return ("vendor_debug_fifo",
                "This exact endpoint is inside the installed Vivado Debug Hub's vendor FIFO Generator, "
                "between its 62.5MHz debug clock and JTAG TCK. Existing vendor exceptions are retained. "
                "Reliance on the vendor implementation is explicit; no independent proof of Debug Hub RTL "
                "or arbitrary native Critical path is claimed.", ["routed_proof", "cdc_facts"])
    raise ValueError("Unreviewed routed CDC finding: " + json.dumps(row, sort_keys=True))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("candidate", type=Path)
    ap.add_argument("--repo", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    candidate, repo, output = args.candidate.resolve(), args.repo.resolve(), args.out.resolve()
    require(not output.exists(), "Preserve prior release contract")
    stage = repo / "build/fpga/soc-return-control-20261006-r3"
    dcp = candidate / "implementation-report-recovery-r1/routed.dcp"
    roles = {
        "routed_proof": stage / "routed-r3/completion.json",
        "cdc_facts": candidate / "cdc-facts-r3-r2/structural_facts.txt",
        "mailbox_truth": candidate / "mailbox-facts-r3-r4/mailbox_next_state.txt",
        "path_facts": candidate / "path-review-r3/release_input_facts.txt",
        "linux_image": stage / "linux-input-audit.json",
        "linux_rootfs": stage / "kernel-rootfs-input-audit.json",
        "gmac_cdc": repo / "build/fpga/soc-window-20261006-r2/cdc-short/gmac/receipt.json",
        "clock_gate_cdc": repo / "build/fpga/soc-window-20261006-r2/cdc-short/clock/receipt.json",
        "managed_cdc": repo / "build/fpga/managed-peripherals-20261004-r1/native-results/functional-r5/receipt.json",
        "quarter_tx": stage / "tx-quarter-board/short-r3/receipt.json",
        "quarter_rx": stage / "tx-quarter-board/rx-short-r1/receipt.json",
        "native_short": repo / "build/gsim/rv64gc-native-soc-return-control-20261006-r3-resume/receipt.json",
    }
    facts = roles["cdc_facts"].read_text(encoding="utf-8")
    require("READ_ONLY_STRUCTURAL_FACTS_COMPLETE_NOT_CDC_SIGNOFF" in facts and
            "PASS_TXCONFIG_BIT3_ACTUAL_NEXT_STATE_32_CASES_RESET_INACTIVE" in
            roles["mailbox_truth"].read_text(encoding="utf-8"), "actual netlist checks incomplete")
    for leaf, count in (("RIU_ADDR", 84), ("RIU_WR_DATA", 224)):
        require(f"MIG_VENDOR_TARGET {leaf} EXACT={count} EXPANDED={count}" in facts,
                "MIG vendor endpoint coverage changed")
    rows = cdc_inventory((dcp.parent / "cdc.rpt").read_text(encoding="utf-8"))
    findings = []
    for row in rows:
        if row["severity"] == "Info":
            continue
        classification, reason, evidence = classify(row, facts)
        findings.append(dict(fingerprint=fingerprint(row), classification=classification,
                             reason=reason, evidence=evidence, actual_finding=row))
    review = dict(status="PASS_CURRENT_ROUTED_NATIVE_CDC_REVIEW_WITH_DOCUMENTED_FINDINGS_NOT_BOARD_RUNTIME",
                  dcp_sha256=sha(dcp), timing_exceptions_added=False, unreviewed_findings=[], findings=findings,
                  class_counts=dict(collections.Counter(f["classification"] for f in findings)),
                  severity_counts=dict(collections.Counter(r["severity"] for r in rows)),
                  independent_vendor_debug_verification=False, physical_gmac_verified=False)
    static_bridge = bridge_fields(candidate, repo)
    sys.path.insert(0, str(repo / "fpga/firmware"))
    from audit_bootrom import audit
    rom = audit(candidate / "firmware/bootrom.bin",
                candidate / "ip-build/board_ip.gen/sources_1/ip/blk_mem_gen_0/blk_mem_gen_0.mif",
                candidate / "ip-build/board_ip.gen/sources_1/ip/blk_mem_gen_0/blk_mem_gen_0.dcp")
    output.mkdir(parents=True)
    for role, name, content in (("cdc_review", "cdc-review.json", review),
                                ("register_bridge_static", "register-bridge-static.json", static_bridge),
                                ("rom_words", "rom-words.json", rom)):
        roles[role] = output / name
        write_new(roles[role], content)
    contract = dict(status="READY_RV64GC100_NATIVE_BOARD_BIT_GENERATION_STATIC_REVIEW_NOT_BOARD_RUNTIME",
                    isa="rv64gc", f_d_enabled=True, issue_width=2, cpu_hz=100000000, uart_baud=460800,
                    physical_board_programmed=False, candidate=str(candidate), repo=str(repo),
                    candidate_manifest_sha256=sha(candidate / "inputs.json"), dcp=str(dcp), dcp_sha256=sha(dcp),
                    evidence={role: dict(path=str(path), sha256=sha(path)) for role, path in roles.items()},
                    phy_tx_delay_enabled=False, phy_rx_delay_enabled=True, phy_initialization_owner="software",
                    original_wrapper_failure="Original route passed, but redirect report command aborted before DCP save.",
                    route_recovery="Same own placed DCP, same route commands/constraints; no synthesis or source edits.",
                    limitations=["Not physical UART/DDR/GMAC proof or independent whole-netlist equivalence.",
                                 "Linux FPU context scheduling and native MAC driver remain board/software work.",
                                 "FPU is single-outstanding at ROB head, not dual-issue floating-point OoO."])
    path = output / "qualified-contract.json"
    write_new(path, contract)
    result = verify_contract(path, dcp)
    write_new(output / "verification.json", result)
    print(json.dumps(dict(result, cdc_class_counts=review["class_counts"], contract=str(path)), sort_keys=True))


if __name__ == "__main__":
    main()
