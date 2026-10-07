#!/usr/bin/env python3
"""Prove only the exact parent-RTL constants/aliases pruned by full-board opt."""
import argparse
import json
from pathlib import Path
import re
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_native_release_contract import sha, require


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("candidate", type=Path)
    a = p.parse_args()
    root, rtl = a.candidate, a.candidate / "rtl"
    names = ("CoherentLineHome.sv", "CoherentLineCache.sv", "TileLinkLineProbeEngine.sv",
             "TileLinkLineAcquireEngine.sv", "ParallelRegisterRouter_1.sv",
             "EthernetDmaFrameAdapter.sv", "MachinePlatform.sv", "BoardSocTop.sv",
             "ManagedPeripheralBank.sv", "ManagedGmac.sv")
    text = {name: re.sub(r"\s+", "", (rtl / name).read_text()) for name in names}
    checks = {
        "CoherentLineHome.sv": (
            "assignio_clients_0_d_bits_opcode=_io_clients_0_d_bits_source_T?3'h6:3'h5;",
            "assignio_clients_0_d_bits_denied=_io_clients_0_d_bits_corrupt_T&lineError;",
            "assignio_clients_0_d_bits_corrupt=_io_clients_0_d_bits_corrupt_T&lineError;",
            "releaseSource<=io_clients_0_c_bits_source;", "acquireSource<=io_clients_0_a_bits_source;",
            "probeAddress<=io_clients_0_a_bits_address;",
            "probeAddress<={io_upstream_request_bits_address[63:6],6'h0};"),
        "CoherentLineCache.sv": (
            ".io_request_bits_address({pending_address[63:6],6'h0})",
            "probeSource<=io_tl_b_bits_source;",
            "assignio_tl_c_bits_source=_io_tl_c_bits_data_T?3'h0:probeSource;"),
        "TileLinkLineProbeEngine.sv": (
            "assignio_probe_bits_source={1'h0,sendSlot};",
            "assignio_probe_bits_address=_GEN[sendSlot];",
            *("address_" + str(n) + "<=io_request_bits_address;" for n in range(4))),
        "TileLinkLineAcquireEngine.sv": (
            "assignio_a_bits_source={1'h0,sendSlot};",
            "assignio_a_bits_address=_GEN[sendSlot];"),
        "ParallelRegisterRouter_1.sv": (
            "io_registers_5_request_bits_size_0={1'h0,io_upstream_request_bits_size};",
            "assignio_registers_4_request_bits_size=io_registers_5_request_bits_size_0;"),
        "EthernetDmaFrameAdapter.sv": (
            "assignio_rxStatus_bits_data=io_rxStatus_bits_last_0?{16'h0,resultLength}:"
            "statusIndex==3'h3?{24'h0,resultBad?8'h80:8'h40}:"
            "statusIndex==3'h0?32'h50000000:32'h0;",),
    }
    for name, snippets in checks.items():
        for snippet in snippets:
            require(snippet in text[name], "Parent RTL expression changed: " + name + " " + snippet)
    # Exhaustively check every possible 16-bit length plus other status forms.
    values = list(range(65536)) + [0x80, 0x40, 0x50000000, 0]
    zero_status = list(range(16, 28)) + [29, 31]
    require(all(not (value >> bit & 1) for value in values for bit in zero_status), "Status constants invalid")
    require(all((value >> 30 & 1) == (value >> 28 & 1) for value in values), "Status alias invalid")
    cache = {f"io_tl_b_bits_address[{n}]": ("CONST", "0") for n in range(6)}
    cache.update({"io_tl_b_bits_source[2]": ("CONST", "0"),
                  "io_tl_d_bits_source[2]": ("CONST", "0"),
                  "io_tl_d_bits_opcode[2]": ("CONST", "1"),
                  "io_tl_d_bits_corrupt": ("ALIAS", "io_tl_d_bits_denied")})
    dma = {f"io_rxStatus_bits_data[{n}]": ("CONST", "0") for n in zero_status}
    dma.update({"io_control_request_bits_size[2]": ("CONST", "0"),
                "io_rxStatus_bits_data[30]": ("ALIAS", "io_rxStatus_bits_data[28]")})
    rules = {"CoherentLineCache": cache, "EthernetPacketDma": dma}
    out = root / "context-proof"
    require(not out.exists(), "Preserve prior proof")
    out.mkdir()
    for top, mapping in rules.items():
        # Pure Tcl list/dict data; consumed using dict, never eval/source.
        (out / (top + ".tcldict")).write_text(" ".join(
            "{" + name + "} {" + mode + " {" + value + "}}" for name, (mode, value) in mapping.items()) + "\n")
    (out / "receipt.json").write_text(json.dumps(dict(
        status="PASS_EXACT_PARENT_RTL_CONTEXT_CONSTANT_ALIAS_REVIEW_VALID_TRANSACTIONS_ONLY",
        source_sha256={name: sha(rtl / name) for name in names}, rules=rules,
        exhaustive_rx_status_values=len(values),
        limits=["Line address/source invariants hold for accepted transactions, not uninitialized invalid fields.",
                "Explicit context specialization, not arbitrary grounding or general netlist equivalence."]),
        indent=2) + "\n")
    print("PASS_PARENT_RTL_CONTEXT", {top: len(mapping) for top, mapping in rules.items()})


if __name__ == "__main__":
    main()
