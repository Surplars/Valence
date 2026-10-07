#!/usr/bin/env python3
"""Stage the RX admission-stop integration for fresh full-board synthesis.

Only unchanged clock/AXI/MIG IP and placement hints are reused; ROM and SoC
are rebuilt. Preserve all existing evidence and do not generate a bitstream.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def check_sources(repo, mapping):
    for name, expected in mapping.items():
        require(sha(repo / name.replace("\\", "/")) == expected, "Source drift: " + name)


def check_delivery_sources(repo, mapping):
    """Documentation may evolve after integration; executable proof may not."""
    documents = {"fpga/firmware/NETBOOT-BOARD-TEST.txt", "fpga/firmware/README.md",
                 "fpga/zu15eg/bootrom-update-plan.md"}
    drift = {}
    for name, expected in mapping.items():
        normalized = name.replace("\\", "/")
        actual = sha(repo / normalized)
        if actual != expected:
            require(normalized.startswith("docs/") or normalized in documents,
                    "Operational delivery source drift: " + name)
            drift[name] = dict(delivery_sha256=expected, current_sha256=actual)
    return drift


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--integration", type=Path, required=True)
    parser.add_argument("--cloud", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--finalize-rom", action="store_true")
    args = parser.parse_args()
    repo, integration, cloud, old, out = (args.repo.resolve(), args.integration.resolve(),
                                        args.cloud.resolve(), args.baseline.resolve(), args.output.resolve())
    evidence = {
        "mac_dma": repo / "build/gsim/gmac-shutdown-integrated-20261007-r1/receipt.json",
        "default_boundaries": repo / "build/gsim/gmac-stop-boundaries-integrated-20261007-r1/receipt.json",
        "firmware": integration / "firmware/receipt.json",
        "independent_cdc": out / "verification/cdc-xsim/receipt.json",
    }
    statuses = {
        "mac_dma": "PASS_GMAC_SHUTDOWN_SINGLE_CLOCK",
        "default_boundaries": "PASS_GMAC_STOP_DEFAULT_BOUNDARIES",
        "firmware": "passed",
        "independent_cdc": "PASS_RX_ADMISSION_STOP_CDC_SHORT",
    }
    proofs = {}
    for role, path in evidence.items():
        proof = proofs[role] = load(path)
        require(proof["status"] == statuses[role], "Unpassed proof: " + role)
        check_sources(repo, proof.get("source_sha256", {}))
    require(proofs["independent_cdc"]["independent_clock_runtime_verified"], "CDC not executed")
    require(set(proofs["independent_cdc"]["negative_checks"]) == {"payload", "drain"}, "Missing CDC negatives")
    for name, digest in proofs["independent_cdc"]["output_sha256"].items():
        require(sha(evidence["independent_cdc"].parent / name) == digest, "CDC output drift")
    firmware_proof = proofs["firmware"]
    require((firmware_proof["cpu_hz"], firmware_proof["uart_baud"], firmware_proof["ddr_bytes"],
             firmware_proof["netboot_rx_stop_abi"]) == (100000000, 460800, 0x80000000, 2), "Wrong firmware profile")
    require(sha(integration / "firmware/netboot/bootrom.bin") == firmware_proof["netboot_rom_sha256"],
            "Firmware binary drift")
    delivery = load(cloud / "source-manifest.json")
    document_drift = check_delivery_sources(repo, delivery["files"])
    protected = load(cloud / "build/gsim/gmac-stop-20261007-r1/aggregate-receipt.json")["protected_cpu_dma_sha256"]
    check_sources(repo, protected)
    old_inputs = load(old / "inputs.json")
    # The signed r6 was produced before the explicitly requested legacy cleanup.
    # Its retired source/tests are not reused as current correctness evidence.
    missing_old_paths = [name for name in old_inputs["checked_source_sha256"] if not (repo / name).is_file()]
    require(all(not name.startswith(("src/main/scala/core/ooo/", "src/main/scala/ip/"))
                for name in missing_old_paths), "Current production source missing")
    drift = [name for name, digest in old_inputs["checked_source_sha256"].items()
             if (repo / name).is_file() and sha(repo / name) != digest]
    require(set(drift) <= set(delivery["files"]) | {"build.mill"},
            "Unexpected change outside delivery/legacy build isolation: " + repr(drift))
    donor = old / "implementation/routed.dcp"
    require(sha(donor) == "0039bc823e3defd999061c385871dc288dc00664a5b5059611d4cb0df4f7953c",
            "Latest signed r6 routed reference identity changed")
    staged = out / "inputs-staged.json"
    if args.finalize_rom:
        require(staged.is_file() and not (out / "inputs.json").exists(), "Preserve frozen inputs")
        manifest = load(staged)
        for name, digest in manifest["staged_sha256"].items():
            require(sha(out / name) == digest, "Staged input drift: " + name)
        sys.path.insert(0, str(repo / "fpga/firmware"))
        from audit_bootrom import audit
        rom = out / "ip-build/board_ip.gen/sources_1/ip/blk_mem_gen_0"
        manifest["rom_word_audit"] = audit(out / "firmware/bootrom.bin", rom / "blk_mem_gen_0.mif",
                                          rom / "blk_mem_gen_0.dcp")
        for tree in ("board_ip.srcs", "board_ip.gen"):
            for name in ("clk_wiz_ddr", "axi_clock_converter_ddr"):
                relative = Path("ip-build") / tree / "sources_1/ip" / name
                require(not (out / relative).exists(), "Do not overwrite reused IP: " + str(relative))
                for source in (old / relative).rglob("*"):
                    if source.is_file():
                        key = source.relative_to(old).as_posix()
                        require(key in old_inputs["candidate_sha256"] and
                                sha(source) == old_inputs["candidate_sha256"][key], "Frozen IP drift: " + key)
                shutil.copytree(old / relative, out / relative)
        manifest["candidate_sha256"] = {p.relative_to(out).as_posix(): sha(p)
            for folder in ("rtl", "board", "scripts", "firmware", "mig", "ip-build/board_ip.srcs", "ip-build/board_ip.gen")
            for p in sorted((out / folder).rglob("*")) if p.is_file()}
        manifest.update(status="STAGED_DDR2G_RV64GC_CHECKED_EXPORT_NOT_ROUTED",
                        checked_source_sha256=manifest["source_sha256"],
                        ram_base="0x80200000", end_exclusive="0x100200000",
                        monitor_reserved=["0xffff8000", "0xffffc000"],
                        tx_clock_architecture="common_clk250_dedicated_oddr",
                        functional_scope="Fresh GMAC/DMA-drain, firmware and CDC short checks; CPU/FPU/DDR RTL unchanged")
        (out / "inputs.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print("PASS_NETBOOT_DRAIN_INPUTS_FROZEN", "ROM_WORDS=32768", "sources=" + str(len(manifest["source_sha256"])))
        return
    require(not staged.exists(), "Preserve staged inputs")
    require(not any((out / name).exists() for name in ("rtl", "board", "scripts", "firmware", "mig", "ip-build", "implementation")),
            "Only an existing verification directory is permitted")
    fresh_rtl = integration / "export/rtl"
    require(len(list(fresh_rtl.glob("*.sv"))) >= 230, "Incomplete full-board RTL")
    require("FloatingPointSystem floatingPoint" in (fresh_rtl / "MachineSystemUnit.sv").read_text(), "FPU absent")
    require("EthernetRxAdmissionStop rxStop" in (fresh_rtl / "ManagedGmac.sv").read_text(), "New stop hardware absent")
    shutil.copytree(fresh_rtl, out / "rtl")
    shutil.copytree(integration / "firmware/netboot", out / "firmware")
    board = repo / "fpga/zu15eg"
    (out / "board").mkdir()
    for name in ("soc_top_gmac_ddr.sv", "native_rgmii.sv", "native_gmac_clocks.sv", "native_gmac_divided_clock.sv",
                 "native_gmac_pll_pair.sv", "native_tx_common_delay.sv", "native_tx_reset_boundary.sv",
                 "native_tx_word_reset_boundary.sv", "native_phy_board_control.sv", "native_phy_tx_init.sv",
                 "board_ddr.xdc", "pl_ddr4_pins.xdc", "native_gmac_pins.xdc"):
        shutil.copy2(board / name, out / "board" / name)
    (out / "scripts").mkdir()
    for name in ("build_native_board.tcl", "build_netboot_rom.tcl", "native_board_constraints.tcl",
                 "native-gmac-cdc-constraints.tcl", "cdc_constraints.tcl", "native_divided_clock_constraints.tcl",
                 "native_quarter_clock_constraints.tcl", "review_native_cdc_facts.tcl", "review_native_mailbox_control.tcl"):
        shutil.copy2(board / name, out / "scripts" / name)
    shutil.copytree(old / "mig", out / "mig")
    for source in (old / "mig").rglob("*"):
        if source.is_file():
            key = source.relative_to(old).as_posix()
            require(sha(source) == old_inputs["candidate_sha256"][key], "Frozen MIG drift: " + key)
    verification = out / "verification/short"
    verification.mkdir()
    for role, path in evidence.items():
        shutil.copy2(path, verification / (role + "-receipt.json"))
    for source in integration.glob("*.log"):
        shutil.copy2(source, verification / source.name)
    previous = {p.name: sha(p) for p in (old / "rtl").glob("*.sv")}
    current = {p.name: sha(p) for p in (out / "rtl").glob("*.sv")}
    changed = sorted(name for name in current if previous.get(name) != current[name])
    expected_modified = {"GmiiFrameRx.sv", "ManagedGmac.sv", "TileLinkGmacControl.sv"}
    expected_added = {"CdcMailbox_4.sv", "EthernetRxAdmissionStop.sv"}
    require(set(current) - set(previous) == expected_added and not (set(previous) - set(current)),
            "Unexpected module additions/removals")
    require(set(changed) == expected_modified | expected_added,
            "Unexpected RTL modification outside GMAC stop: " + repr(changed))
    source_paths = list((repo / "src/main/scala").rglob("*.scala")) + [repo / "build.mill"]
    source_paths += list((repo / "fpga/zu15eg").glob("*.sv")) + list((repo / "fpga/zu15eg").glob("*.xdc"))
    manifest = dict(status="STAGED_FRESH_RV64GC100_NETBOOT_DRAIN_ROM_IP_PENDING", vendor="OpenIon", soc="VL100",
                    cpu="Orbital-A1", isa="rv64gc", issue_width=2, f_d_enabled=True, cpu_hz=100000000,
                    aon_uart_hz=50000000, uart_baud=460800, ddr_bytes=0x80000000, netboot_enabled=True,
                    netboot_rx_stop_abi=2, base_commit=delivery["base_commit"], cpu_checkpoint_reused=False,
                    incremental_routed_reference=str(donor), incremental_routed_reference_sha256=sha(donor),
                    baseline_manifest_sha256=sha(old / "inputs.json"), changed_rtl=changed,
                    unchanged_rtl_files=len(current)-len(changed),
                    pre_cleanup_paths_not_reused_as_proof=missing_old_paths,
                    added_rtl=sorted(set(current)-set(previous)), removed_rtl=sorted(set(previous)-set(current)),
                    protected_cpu_dma_sha256=protected,
                    delivery_document_drift=document_drift,
                    source_sha256={p.relative_to(repo).as_posix(): sha(p) for p in source_paths},
                    evidence={role: dict(path=str(path), sha256=sha(path)) for role, path in evidence.items()},
                    staged_sha256={p.relative_to(out).as_posix(): sha(p)
                                   for folder in ("rtl", "board", "scripts", "firmware", "mig")
                                   for p in sorted((out / folder).rglob("*")) if p.is_file()},
                    bit_generated=False, routed_timing_verified=False, board_verified=False,
                    limits=["CPU/DMA sources unchanged; focused affected checks only.",
                            "Fresh synthesis of current complete RTL and ROM; old route is placement/routing hints only.",
                            "CDC short test uses surrogate ownership, not whole-board gate/PHY verification.",
                            "No physical boot, throughput or Linux large-packet liveness claim."])
    staged.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print("PASS_NETBOOT_DRAIN_STAGED", "RTL=" + str(len(current)), "changed=" + repr(changed))


if __name__ == "__main__":
    main()
