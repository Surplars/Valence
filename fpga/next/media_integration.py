"""Freeze the opt-in native tri-speed boundary; never run FPGA tools.

This is deliberately separate from the default board assembly. The shipping
native_gmac_pins.xdc contains a fixed-1G clock and cannot be copied wholesale
into a 10/100 scenario. Its package/electrical assignments are retained exactly.
"""
import hashlib
import json
from pathlib import Path
import re
import shutil

NATIVE_SOURCES = (
    "native_gmac_divided_clock.sv",
    "native_tx_word_reset_boundary.sv",
    "native_rgmii_trispeed_quarter.sv",
)
NATIVE_CONSTRAINTS = (
    "cdc_constraints.tcl",
    "native-gmac-cdc-constraints.tcl",
    "native_quarter_clock_constraints.tcl",
    "trispeed_quarter_constraints.tcl",
    "trispeed_board_constraints.tcl",
)
PIN_SOURCE = "native_gmac_pins.xdc"
INPUTS = tuple("fpga/zu15eg/" + name for name in (*NATIVE_SOURCES, *NATIVE_CONSTRAINTS, PIN_SOURCE))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_hashes(root):
    return {name: sha(root / name) for name in INPUTS}


def pin_only_constraints(text):
    marker = "create_clock -name phy_rx -period 8.000 -waveform {0 4} [get_ports eth_rxc]"
    boundary = re.search(r"^" + re.escape(marker) + r"\r?$", text, re.M)
    if text.count(marker) != 1 or boundary is None:
        raise RuntimeError("native pin/timing boundary changed; re-review required")
    pins = text[:boundary.start()]
    expected = {"eth_mdc": "Y1", "eth_mdio": "Y12", "eth_reset_gate": "Y2", "eth_rxc": "AA7",
        "eth_rx_ctl": "AB9", "eth_rxd[0]": "AC4", "eth_rxd[1]": "AB4", "eth_rxd[2]": "AB10",
        "eth_rxd[3]": "AB11", "eth_txc": "AC8", "eth_tx_ctl": "AB8", "eth_txd[0]": "AC11",
        "eth_txd[1]": "AC12", "eth_txd[2]": "AA6", "eth_txd[3]": "AA12"}
    expected_pins = {f"set_property PACKAGE_PIN {pin} [get_ports {{{port}}}]" for port, pin in expected.items()}
    expected_commands = expected_pins | {
        "set_property IOSTANDARD LVCMOS18 [get_ports {eth_mdc eth_mdio eth_reset_gate eth_rxc eth_rx_ctl eth_rxd[*] eth_txc eth_tx_ctl eth_txd[*]}]",
        "set_property DRIVE 8 [get_ports {eth_txc eth_tx_ctl eth_txd[*] eth_mdc eth_reset_gate}]",
        "set_property SLEW FAST [get_ports {eth_txc eth_tx_ctl eth_txd[*]}]",
        "set_property UNAVAILABLE_DURING_CALIBRATION TRUE [get_ports {eth_txd[1]}]",
    }
    # This is an allowlist for reviewed complete statements, not a Tcl parser.
    # Even a comment's backslash-newline could hide the next accepted command.
    commands = []
    for raw_line in pins.split("\n"):
        line = raw_line.removesuffix("\r").strip(" \t")
        if any(char in line for char in "\r\v\f") or line.endswith("\\"):
            raise RuntimeError("unexpected timing or continued statement in package-only constraints")
        if line and not line.startswith("#"):
            commands.append(line)
    assignments = [line for line in commands if line.startswith("set_property PACKAGE_PIN ")]
    if len(assignments) != len(expected_pins) or set(assignments) != expected_pins:
        raise RuntimeError("tri-speed package pin map differs from the verified carrier")
    if len(commands) != len(expected_commands) or set(commands) != expected_commands:
        raise RuntimeError("unexpected timing or property statement in package-only constraints; re-review required")
    return pins + "# Timing belongs to trispeed_board_constraints.tcl, one explicit rate per design.\n"


def stage(root, output):
    """Stage immutable media dependencies after the matched wrapper is written.

    The returned recipe is an integration candidate, never a timing or CDC pass.
    It intentionally contains no IP generation, synthesis, route or bit command.
    """
    before = source_hashes(root)
    board = output / "board"
    wrapper = board / "soc_top_fpga_next_ddr.sv"
    if not wrapper.is_file():
        raise RuntimeError("stage the matched tri-speed wrapper first")
    for name in (*NATIVE_SOURCES, *NATIVE_CONSTRAINTS):
        shutil.copy2(root / "fpga/zu15eg" / name, board / name)
    (board / "trispeed_pins_only.xdc").write_text(pin_only_constraints((root / "fpga/zu15eg" / PIN_SOURCE).read_text()))
    sources = ["board/soc_top_fpga_next_ddr.sv", *("board/" + n for n in NATIVE_SOURCES)]
    (output / "board-synthesis-files.f").write_text("".join(name + "\n" for name in sources))
    (board / "require_trispeed.tcl").write_text(
        "# Run on a fresh matched synthesized board, after package-only XDC.\n"
        "# This scoped gate is not complete board/CDC/RDC/routed signoff.\n"
        "if {![info exists VALENCE_TRISPEED_MBPS]} {error {Set VALENCE_TRISPEED_MBPS to 10, 100 or 1000}}\n"
        "source [file join [file dirname [info script]] trispeed_board_constraints.tcl]\n"
        "valence_trispeed_board_constraints $VALENCE_TRISPEED_MBPS\n")
    artifacts = {p.relative_to(output).as_posix(): sha(p) for p in sorted(board.iterdir()) if p.is_file()}
    artifacts["board-synthesis-files.f"] = sha(output / "board-synthesis-files.f")
    manifest = {
        "schema": "valence-trispeed-native-integration-v1", "status": "PREPARED_NOT_PHYSICALLY_QUALIFIED",
        "top": "soc_top_fpga_next_ddr", "source_sha256": before, "artifacts_sha256": artifacts,
        "native_sources": sources, "package_constraints": "board/trispeed_pins_only.xdc",
        "post_synthesis_gate": "board/require_trispeed.tcl", "rates_mbps": [10, 100, 1000],
        "clock_contract": {"cpu_hz": 100000000, "aon_hz": 50000000, "tx_raw_hz": 125000000,
            "rx_frame_hz": 125000000, "pad_hz": 250000000, "delay_hz": 500000000,
            "rx_recovered_hz": [2500000, 25000000, 125000000], "rx_clock_can_stop": True},
        "external_ip_required": ["ddr4_0", "clk_wiz_ddr", "axi_clock_converter_ddr", "blk_mem_gen_0"],
        "do_not_import": ["native_gmac_pins.xdc fixed-1G clocks", "native_board_constraints.tcl legacy RX MMCM",
            "native_phy_board_control or any second MDIO writer", "native_rgmii_trispeed.sv delay-cascade experiment"],
        "retained_owner_reset": "cold reset only; epoch reset is restricted to physical ingress",
        "required_remaining_gates": ["source-matched combined RTL export and short behavioral tests",
            "independent-clock reset/epoch/stop-restart and vendor pad simulation",
            "all actual board, management, JTAG and reset endpoints constrained and reviewed",
            "complete-netlist CDC/RDC review, no unconstrained or globally cut data paths",
            "separate 10/100/1000 both-edge routed setup/hold and bus-skew reports",
            "partner-controlled negotiated rates, cable loss, PHY restart and DMA credit recovery on board"],
        "synthesis_run": False, "route_run": False, "bit_generated": False, "on_board_verified": False,
    }
    if before != source_hashes(root):
        raise RuntimeError("native media sources changed while staging")
    path = board / "trispeed-integration.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    return {"manifest": path.relative_to(output).as_posix(), "sha256": sha(path),
        "source_sha256": before, "status": manifest["status"], "physical_qualification": False}
