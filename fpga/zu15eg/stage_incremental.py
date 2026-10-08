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
STAGED_FOLDERS = ("rtl", "board", "scripts", "firmware", "mig")
# This is the selected candidate contract, not the elaborator's defaults.
CPU_PARAMETERS = ("ddr", "100000000", "staged-fetch-turnover", "460800", "2", "2",
    "1", "rv64gc", "2147483648", "0", "512", "0", "512", "4", "16", "2", "2", "1",
    "--compact-tags", "--identity-data-flow", "--banked-rob", "--shared-store-reads",
    "--ddr-write-slots=2", "--cache-writebacks=2", "--overlap-writeback-refill",
    "--unordered-ddr-responses", "--lvt-prf", "--data-next-line-prefetch")


def sha(p):
    with Path(p).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def check(value, message):
    if not value:
        raise RuntimeError(message)


def check_hashes(root, mapping, label):
    """Do not accept empty receipts or proof inputs from another checkout."""
    check(isinstance(mapping, dict) and mapping, label + ": empty hash manifest")
    root = root.resolve()
    for name, digest in mapping.items():
        path = (root / name).resolve()
        check(path.is_relative_to(root), label + ": input outside current root: " + name)
        check(path.is_file() and sha(path) == digest, label + ": " + name)


def validate_cpu_proof(cpu, root):
    check(cpu.get("status") == "PASS_SELECTED_BOARD_FUNCTIONAL", "Selected CPU proof has not passed")
    check(tuple(cpu.get("parameters", ())) == CPU_PARAMETERS, "Wrong selected CPU parameters")
    check_hashes(root, cpu.get("inputs"), "CPU frozen source drift")
    check_hashes(root, cpu.get("artifacts"), "CPU proof artifact drift")
    # A new source can affect elaboration even when every old hash still matches.
    required = list((root / "src").rglob("*.scala"))
    required += list((root / "third_party/berkeley-hardfloat/src/main/scala").rglob("*.scala"))
    required += [root / "build.mill", root / ".mill-version"]
    frozen = {(root / name).resolve() for name in cpu["inputs"]}
    for path in required:
        check(path.resolve() in frozen, "CPU proof missing current source: " + str(path))


def snapshot(root, folders):
    result = {}
    for folder in folders:
        directory = root / folder
        check(directory.is_dir() and not directory.is_symlink(), "Missing/linked input directory: " + str(directory))
        for path in sorted(directory.rglob("*")):
            check(not path.is_symlink(), "Linked input is not frozen: " + str(path))
            if path.is_file():
                result[path.relative_to(root).as_posix()] = sha(path)
    return result


def check_tree(root, mapping, folders, label):
    expected = {name: digest for name, digest in mapping.items()
                if any(name.startswith(folder + "/") for folder in folders)}
    check(expected and snapshot(root, folders) == expected, label)


def validate_staged(state, out, old, proof, net):
    """Validate everything before auditing ROM or copying any fixed IP."""
    check(state.get("status") == "STAGED_SELECTED_ROM_IP_PENDING", "Unexpected staged status")
    check(not (out / "inputs.json").exists(), "Preserve finalized inputs")
    check(state["proof_sha256"] == sha(proof) and state["network_proof_sha256"] == sha(net),
          "Proof changed after staging")
    check(state["baseline_manifest_sha256"] == sha(old / "inputs.json"),
          "Baseline manifest changed after staging")
    reference = old / "implementation/routed.dcp"
    check(Path(state["incremental_routed_reference"]).resolve() == reference.resolve()
          and reference.is_file() and state["incremental_routed_reference_sha256"] == sha(reference),
          "Routed reference changed after staging")
    check_tree(out, state["staged_sha256"], STAGED_FOLDERS, "Staged input inventory/content drift")


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
    validate_cpu_proof(cpu, ROOT)
    network = json.loads(net.read_text())
    check(network["status"] == "passed", "Posted network proof has not passed")
    check_hashes(ROOT, network.get("source_sha256"), "Network frozen source drift")
    old_inputs = json.loads((old / "inputs.json").read_text())
    previous = old_inputs["candidate_sha256"]
    manifest = out / "inputs-staged.json"
    if a.finalize_rom:
        state = json.loads(manifest.read_text())
        validate_staged(state, out, old, proof, net)
        sys.path.insert(0, str(ROOT / "fpga/firmware"))
        from audit_bootrom import audit
        rom = out / "ip-build/board_ip.gen/sources_1/ip/blk_mem_gen_0"
        state["rom_word_audit"] = audit(out / "firmware/bootrom.bin", rom / "blk_mem_gen_0.mif",
                                        rom / "blk_mem_gen_0.dcp", profile="menu")
        fixed_ip = []
        for tree in ("board_ip.srcs", "board_ip.gen"):
            for name in ("clk_wiz_ddr", "axi_clock_converter_ddr"):
                relative = Path("ip-build") / tree / "sources_1/ip" / name
                check(not (out / relative).exists(), "Refusing to overwrite IP")
                check_tree(old, previous, (relative.as_posix(),), "Fixed IP inventory/content drift: " + str(relative))
                fixed_ip.append(relative)
        for relative in fixed_ip:
            shutil.copytree(old / relative, out / relative)
        state["candidate_sha256"] = snapshot(out, (*STAGED_FOLDERS, "ip-build/board_ip.srcs", "ip-build/board_ip.gen"))
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
    # Select ROM by its exact input proof, not by a different dated build.
    roms = [Path(p) for p in cpu["inputs"] if p.endswith("/firmware/bootrom.bin")]
    check(len(roms) == 1, "Expected one CPU-tested ROM")
    check_tree(old, previous, ("mig",), "MIG inventory/content drift")
    check((old / "implementation/routed.dcp").is_file(), "Missing optional placement/routing reference")
    out.mkdir(parents=True)
    shutil.copytree(rtl, out / "rtl")
    shutil.copytree(roms[0].parent, out / "firmware")
    check(sha(out / "firmware/bootrom.bin") == sha(roms[0]), "ROM not the CPU-tested image")
    for folder, names in (("board", BOARD_FILES), ("scripts", SCRIPTS)):
        (out / folder).mkdir()
        for name in names:
            shutil.copy2(ROOT / "fpga/zu15eg" / name, out / folder / name)
    shutil.copytree(old / "mig", out / "mig")
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
        "staged_sha256": snapshot(out, STAGED_FOLDERS)}
    manifest.write_text(json.dumps(state, indent=2) + "\n")
    print(state["status"], flush=True)


if __name__ == "__main__":
    main()
