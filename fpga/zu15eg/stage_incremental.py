#!/usr/bin/env python3
"""Stage the selected dot handoff after live short tests, never reuse old CPU RTL.

Run --finalize-rom only after the private build_netboot_rom.tcl completed.
The copied fixed clock/AXI/MIG IP must match the signed deployed input manifest.
No GUI project, git branch, old delivery or bitstream is changed.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
BOARD_FILES = ("soc_top_gmac_ddr.sv", "native_rgmii.sv", "native_gmac_clocks.sv",
    "native_gmac_divided_clock.sv", "native_gmac_pll_pair.sv", "native_tx_common_delay.sv",
    "native_tx_reset_boundary.sv", "native_tx_word_reset_boundary.sv", "native_phy_board_control.sv",
    "native_phy_tx_init.sv", "board_ddr.xdc", "pl_ddr4_pins.xdc", "native_gmac_pins.xdc")
SCRIPTS = ("build_native_board.tcl", "build_netboot_rom.tcl", "native_board_constraints.tcl",
    "native-gmac-cdc-constraints.tcl", "cdc_constraints.tcl", "native_divided_clock_constraints.tcl",
    "native_quarter_clock_constraints.tcl", "review_native_cdc_facts.tcl", "review_native_mailbox_control.tcl")


def sha(p):
    with Path(p).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def check(value, message):
    if not value:
        raise RuntimeError(message)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--proof", type=Path, required=True)
    ap.add_argument("--network-proof", type=Path, required=True)
    ap.add_argument("--baseline", type=Path, required=True)
    ap.add_argument("--rtl", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--finalize-rom", action="store_true")
    a = ap.parse_args()
    proof, net, old, rtl, out = (p.resolve() for p in
        (a.proof, a.network_proof, a.baseline, a.rtl, a.output))
    cpu = json.loads(proof.read_text())
    check(cpu["status"] == "PASS_SELECTED_BOARD_FUNCTIONAL", "Selected CPU proof has not passed")
    for path, digest in cpu["inputs"].items():
        check(sha(path) == digest, "CPU frozen source drift: " + path)
    for path, digest in cpu["artifacts"].items():
        check(sha(path) == digest, "CPU proof artifact drift: " + path)
    network = json.loads(net.read_text())
    check(network["status"] == "passed", "Posted network proof has not passed")
    for path, digest in network["source_sha256"].items():
        check(sha(ROOT / path) == digest, "Network frozen source drift: " + path)
    old_inputs = json.loads((old / "inputs.json").read_text())
    previous = old_inputs["candidate_sha256"]
    manifest = out / "inputs-staged.json"
    if a.finalize_rom:
        state = json.loads(manifest.read_text())
        check(state["proof_sha256"] == sha(proof) and state["network_proof_sha256"] == sha(net),
              "Proof changed after staging")
        for name, digest in state["staged_sha256"].items():
            check(sha(out / name) == digest, "Staged input drift: " + name)
        sys.path.insert(0, str(ROOT / "fpga/firmware"))
        from audit_bootrom import audit
        rom = out / "ip-build/board_ip.gen/sources_1/ip/blk_mem_gen_0"
        state["rom_word_audit"] = audit(out / "firmware/bootrom.bin", rom / "blk_mem_gen_0.mif",
                                        rom / "blk_mem_gen_0.dcp", profile="menu")
        for tree in ("board_ip.srcs", "board_ip.gen"):
            for name in ("clk_wiz_ddr", "axi_clock_converter_ddr"):
                relative = Path("ip-build") / tree / "sources_1/ip" / name
                check(not (out / relative).exists(), "Refusing to overwrite IP")
                for p in (old / relative).rglob("*"):
                    if p.is_file():
                        rel = p.relative_to(old).as_posix()
                        check(previous.get(rel) == sha(p), "Fixed IP drift: " + rel)
                shutil.copytree(old / relative, out / relative)
        state["candidate_sha256"] = {p.relative_to(out).as_posix(): sha(p)
            for folder in ("rtl", "board", "scripts", "firmware", "mig", "ip-build/board_ip.srcs", "ip-build/board_ip.gen")
            for p in sorted((out / folder).rglob("*")) if p.is_file()}
        state["status"] = "STAGED_SELECTED_DDR2G_RV64GC100_NOT_ROUTED"
        (out / "inputs.json").write_text(json.dumps(state, indent=2) + "\n")
        print(state["status"], flush=True)
        return
    check(not out.exists(), "Preserve existing candidate output; select a fresh root")
    sv = list(rtl.glob("*.sv"))
    check(len(sv) > 200, "Incomplete managed RTL")
    for name in ("OwnerBankedPhysicalRegisterFile.sv", "BankedRobPayload.sv", "NonBlockingCoherentLineCache.sv",
                 "MixedCoherentLineHome.sv", "EthernetTxDescriptorQueue.sv", "FloatingPointSystem.sv"):
        check((rtl / name).is_file(), "Missing selected hardware: " + name)
    check("[3:0]" in (rtl / "BoardSocTop.sv").read_text(), "DDR ID contract absent")
    out.mkdir(parents=True)
    shutil.copytree(rtl, out / "rtl")
    # Select ROM by its exact input proof, not by a different dated build.
    roms = [Path(p) for p in cpu["inputs"] if p.endswith("/firmware/bootrom.bin")]
    check(len(roms) == 1, "Expected one CPU-tested ROM")
    shutil.copytree(roms[0].parent, out / "firmware")
    check(sha(out / "firmware/bootrom.bin") == sha(roms[0]), "ROM not the CPU-tested image")
    for folder, names in (("board", BOARD_FILES), ("scripts", SCRIPTS)):
        (out / folder).mkdir()
        for name in names:
            shutil.copy2(ROOT / "fpga/zu15eg" / name, out / folder / name)
    for p in (old / "mig").rglob("*"):
        if p.is_file():
            rel = p.relative_to(old).as_posix()
            check(previous.get(rel) == sha(p), "MIG drift: " + rel)
    shutil.copytree(old / "mig", out / "mig")
    check((old / "implementation/routed.dcp").is_file(), "Missing optional placement/routing reference")
    state = {"status": "STAGED_SELECTED_ROM_IP_PENDING", "cpu_hz": 100000000,
        "uart_baud": 460800, "isa": "rv64gc", "issue_width": 2, "ddr_bytes": 2147483648,
        "instruction_cache_bytes": 32768, "data_cache_bytes": 32768, "network_tx_slots": 4,
        "board_gsim_args": cpu["parameters"], "source_sha256": cpu["inputs"],
        "proof": str(proof), "proof_sha256": sha(proof), "network_proof_sha256": sha(net),
        "baseline_manifest_sha256": sha(old / "inputs.json"),
        "incremental_routed_reference": str(old / "implementation/routed.dcp"),
        "incremental_routed_reference_sha256": sha(old / "implementation/routed.dcp"),
        "cpu_checkpoint_reused": False, "bit_generated": False, "board_verified": False,
        "routed_timing_verified": False,
        "limitations": ["Short functional proof is not timing signoff", "Old route is a hint only",
                        "Native GMAC/CDC physical signoff still required", "Linux modules/throughput not yet verified"],
        "staged_sha256": {p.relative_to(out).as_posix(): sha(p)
            for folder in ("rtl", "board", "scripts", "firmware", "mig")
            for p in sorted((out / folder).rglob("*")) if p.is_file()}}
    manifest.write_text(json.dumps(state, indent=2) + "\n")
    print(state["status"], flush=True)


if __name__ == "__main__":
    main()
