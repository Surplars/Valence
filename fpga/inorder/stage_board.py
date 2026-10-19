#!/usr/bin/env python3
"""Stage an isolated REAL I1 board, preserving incomplete short-test scope."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rtl-package", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--ddr-pins", required=True, type=Path)
    args = ap.parse_args()
    source, out = args.rtl_package.resolve(), args.output.resolve()
    if out.parent != Path("/mnt/e/VM/Share/Valence-rtl") or not out.name.startswith("orbital-i1-board-zu15eg-"):
        ap.error("explicit isolated board output required")
    if (out / "board-manifest.json").exists() or any((out / n).exists() for n in ("rtl", "board", "scripts")):
        ap.error("preserve previous staged board inputs")
    if not (out / "project/i1_board.xpr").is_file():
        ap.error("actual isolated board IP project must exist")
    manifest = json.loads((source / "manifest.json").read_text())
    if manifest["status"] != "DIAGNOSTIC_USER_STOPPED_TARGET_CPU_RTL_EXPORT_NOT_FULL_QUALIFICATION":
        ap.error("this board candidate retains the explicit user-stopped diagnostic scope")
    if manifest["target_hz"] != 300000000 or manifest["icache_bytes"] != 32768 or manifest["dcache_bytes"] != 32768:
        ap.error("do not silently change CPU/cache target")
    for name, digest in manifest["source_sha256"].items():
        if sha(ROOT / name) != digest:
            ap.error("hardware/oracle drift: " + name)
    for name, digest in manifest["files_sha256"].items():
        if sha(source / name) != digest:
            ap.error("exported candidate drift: " + name)
    for name in ("rtl", "board", "scripts"):
        (out / name).mkdir()
    for path in sorted(source.glob("*.sv")) + [source / "bootrom.hex"]:
        shutil.copy2(path, out / "rtl" / path.name)
    mappings = {
        HERE / "soc_top_i1_network_ddr.sv": "board/soc_top_i1_network_ddr.sv",
        ROOT / "fpga/zu15eg/native_rgmii_trispeed_quarter.sv": "board/native_rgmii_trispeed_quarter.sv",
        ROOT / "fpga/zu15eg/native_tx_word_reset_boundary.sv": "board/native_tx_word_reset_boundary.sv",
        ROOT / "fpga/zu15eg/board_ddr.xdc": "board/board_ddr.xdc",
        args.ddr_pins.resolve(): "board/pl_ddr4_pins.xdc",
        HERE / "build_board.tcl": "scripts/build_board.tcl",
        HERE / "board_constraints.tcl": "scripts/board_constraints.tcl",
        HERE / "prepare_board_mem.tcl": "scripts/prepare_board_mem.tcl",
        HERE / "network_cdc.tcl": "scripts/network_cdc.tcl",
        HERE / "resume_board.tcl": "scripts/resume_board.tcl",
        HERE / "report_board.tcl": "scripts/report_board.tcl",
        HERE / "inspect_board.tcl": "scripts/inspect_board.tcl",
        HERE / "check_board_rates.tcl": "scripts/check_board_rates.tcl",
        HERE / "bscan_timing_i1.tcl": "scripts/bscan_timing_i1.tcl",
        ROOT / "fpga/next/check_jtag_chain.tcl": "scripts/check_jtag_chain.tcl",
    }
    for name in ("trispeed_board_constraints.tcl", "trispeed_quarter_constraints.tcl",
                 "native_quarter_clock_constraints.tcl", "native-gmac-cdc-constraints.tcl",
                 "cdc_constraints.tcl"):
        mappings[ROOT / "fpga/zu15eg" / name] = "scripts/" + name
    inputs = {}
    for path, target in mappings.items():
        shutil.copy2(path, out / target)
        inputs[str(path)] = sha(path)
    pins = ROOT / "fpga/zu15eg/native_gmac_pins.xdc"
    text = pins.read_text()
    marker = "create_clock -name phy_rx"
    if text.count(marker) != 2 and text.count(marker) != 1:
        raise RuntimeError("physical Ethernet pin/timing split changed")
    # Keep the verified package pins, electrical standards and calibration pad
    # acknowledgement. Real per-rate clocks are applied AFTER actual IP linking.
    (out / "board/rgmii_pins.xdc").write_text(text.split(marker, 1)[0])
    inputs[str(pins)] = sha(pins)
    report = {
        "status": "REAL_BOARD_STAGED_NOT_IMPLEMENTED_NOT_QUALIFIED",
        "top": "soc_top_i1_network_ddr", "part": manifest["part"],
        "cpu_hz": 300000000, "uart_hz": 50000000, "uart_baud": 460800,
        "mac_word_hz": 125000000, "mac_pad_hz": 250000000, "idelay_ref_hz": 500000000,
        "ddr_bytes": 2147483648, "mig_ui_hz": 250000000, "mig_axi_data_bits": 64,
        "axi_cdc": "actual axi_clock_converter_i1; CPU300 to MIG_UI250",
        "boot": "actual BRAM-inferred I1 BootROM hex; USER2 JTAG DDR download",
        "rtl_package": str(source), "rtl_manifest_sha256": sha(source / "manifest.json"),
        "short_receipt": manifest["receipt"], "short_receipt_sha256": manifest["receipt_sha256"],
        "full_short_qualified": False, "deferred_short_checks": 36,
        "original_gui_project_modified": False, "ooo_core_modified": False,
        "source_sha256": inputs,
        "staged_sha256": {str(p.relative_to(out)): sha(p) for name in ("rtl", "board", "scripts")
                          for p in (out / name).rglob("*") if p.is_file()},
        "physical_qualified": False, "board_qualified": False, "bit_generated": False}
    (out / "board-manifest.json").write_text(json.dumps(report, indent=2) + "\n")
    print("I1_REAL_BOARD_STAGED CPU300 DDR2GiB MIG AXI_CDC CLK_WIZ RGMII PHY MDIO UART USER2")


if __name__ == "__main__":
    main()
