"""Explicit batch37 receipt schema; no failed/stopped or physical signoff override."""
import hashlib
import json
from pathlib import Path

BANDWIDTH37 = "PASS_I1_BANDWIDTH37_AFFECTED_SHORT_ONLY"
REQUIRED_FLAGS = {
    "--coherent-line-grants", "--coherent-miss-turnover", "--coherent-writeback-overlap",
    "--coherent-read-overlap", "--data-reply-handoff", "--coherent-ways=2",
    "--icache=32768", "--dcache=32768", "--soc-clock-hz=300000000",
    "--cache-fetch-predecode", "--indexed-data-proofs", "--overlap-data-retirement",
    "--direct-fast-data-issue",
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def bandwidth37_flags(receipt):
    if receipt.get("status") != BANDWIDTH37:
        raise ValueError("exact complete batch37 short PASS required")
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
    if set(checks) != expected or len(gates) != 13 or any(v is not True for v in gates.values()):
        raise ValueError("exact affected29 / performance13 proof required")
    if any(not isinstance(v, str) or "PASS" not in v for v in checks.values()):
        raise ValueError("every affected check must explicitly pass")
    return list(flags)


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
    return flags, {"audit": str(audit_path), "audit_sha256": sha(audit_path),
                   "jtag_scan_bits": 65, "jtag_transport_proofs": proof,
                   "whole_cpu_rtl_identity_claimed": False}
