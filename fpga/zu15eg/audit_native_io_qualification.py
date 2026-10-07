"""Archive truthful peripheral-only candidate results; no stale CPU proof reuse."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def io_slack(text, expected_ports, field):
    values = {"setup_ns": [], "hold_ns": []}
    endpoints = {name: set() for name in values}
    for block in re.split(r"(?=Slack \((?:MET|VIOLATED)\))", text):
        match = re.match(r"Slack \((?:MET|VIOLATED)\)\s*:\s*([-+\d.]+)ns", block)
        if match:
            kind = "hold_ns" if re.search(r"Path Type:.*(?:Hold|Min at)", block) else "setup_ns"
            values[kind].append(float(match[1]))
            endpoint = re.search(rf"^\s+{field}:\s+(\S+)", block, re.M)
            if endpoint: endpoints[kind].add(endpoint[1])
    if not all(values.values()): raise ValueError("Missing finite setup/hold I/O paths")
    for kind in values:
        assert expected_ports <= endpoints[kind], f"Missing {kind} I/O endpoints: {expected_ports - endpoints[kind]}"
    return {name: min(numbers) for name, numbers in values.items()}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("candidate", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--rx-proof", type=Path)
    ap.add_argument("--parallel-proof", type=Path)
    ap.add_argument("--tx-proof", type=Path)
    ap.add_argument("--clock-ooc", type=Path, action="append", default=[])
    ap.add_argument("--diagnostics", type=Path, action="append", default=[])
    ap.add_argument("--software-phy", action="store_true", help="physical FPGA TX90, default software-owned PHY")
    ap.add_argument("--divider-clock", action="store_true", help="common physical REF500 / raw, pad and forwarded DIV4s")
    a = ap.parse_args()
    if a.divider_clock and not a.software_phy: ap.error("divider clock requires software PHY contract")
    if a.out.exists(): ap.error("preserve existing evidence")
    root = Path(__file__).resolve().parents[2]
    short_path = root / "build/gsim/native-timing-20261004-r3/receipt.json"
    short = json.loads(short_path.read_text())
    assert short["status"] == "PASS_NATIVE_TIMING_SHORT"
    for name, expected in short["source_sha256"].items():
        assert sha(root / name) == expected, "Unverified CPU input drift: " + name
    timing = (a.candidate / "timing_summary.rpt").read_text()
    table = timing[timing.index("| Design Timing Summary"):]
    row = re.search(r"^\s+([-\d.]+)\s+([-\d.]+)\s+(\d+)\s+(\d+)\s+([-\d.]+)\s+([-\d.]+)\s+(\d+)\s+(\d+)\s+([-\d.]+)\s+([-\d.]+)\s+(\d+)\s+(\d+)\s*$", table, re.M)
    assert row, "Unparseable board timing summary"
    v = row.groups()
    cpu = re.search(r"^\s+clk_out1_clk_wiz_ddr\s+([\d.-]+)\s+([\d.-]+)\s+(\d+)\s+(\d+)\s+([\d.-]+)\s+([\d.-]+)\s+(\d+)\s+(\d+)\s+([\d.-]+)", timing, re.M)
    assert cpu, "CPU100 group missing"
    check = (a.candidate / "check_timing.rpt").read_text()
    coverage = all(f"checking {name} (0)" in check for name in
                   ("no_clock", "unconstrained_internal_endpoints", "generated_clocks", "loops"))
    tx_text = (a.candidate / "tx_io.rpt").read_text()
    rx_text = (a.candidate / "rx_io.rpt").read_text()
    tx = io_slack(tx_text, {"eth_tx_ctl", *(f"eth_txd[{i}]" for i in range(4))}, "Destination")
    rx = io_slack(rx_text, {"eth_rx_ctl", *(f"eth_rxd[{i}]" for i in range(4))}, "Source")
    assert "Slack:                    inf" not in tx_text, "TX excluded by invalid generated clock"
    if a.software_phy:
        assert a.tx_proof is not None, "Current TX/reset proof required"
        tx_proof = json.loads((a.tx_proof / "receipt.json").read_text())
        assert tx_proof["status"] == "PASS_NATIVE_TX90_SHORT" and not tx_proof["hardware_phy_init_enabled"]
        assert tx_proof["negative_checks"] == {"corrupt_data": "PASS", "corrupt_control": "PASS", "bad_phase": "PASS"}
        if a.divider_clock:
            assert tx_proof["clock_architecture"] == "common_ref500_div4_phases"
            assert "native_tx_ref_pll/CLKOUT0" in tx_text
            assert tx_proof["pad_clock_isolated"] and "native_tx_pad_divider" in tx_text
            assert "native_tx90_forward_buffer" in tx_text
            assert "cold_reset=1; last_raw=0; last_forward=0; last_ref=0;" in (a.tx_proof / "native_tx90_tb.sv").read_text()
        else:
            assert "native_eth_mmcm/CLKOUT0" in tx_text and "native_eth_mmcm/CLKOUT1" in tx_text
        assert set(re.findall(r"Output Delay:\s+([-\d.]+)ns", tx_text)) == {"1.250", "-1.250"}
        top_source = (root / "fpga/zu15eg/soc_top_gmac_ddr.sv").read_text()
        assert "parameter HARDWARE_PHY_INIT = 0" in top_source
    skew_text = (a.candidate / "bus_skew.rpt").read_text()
    skews = [float(n) for n in re.findall(r"Slack \((?:MET|VIOLATED)\)\s*:\s*([-+\d.]+)ns", skew_text)]
    assert skews, "Bus-skew report missing"
    route_text = (a.candidate / "route_status.rpt").read_text()
    route_errors = re.search(r"# of nets with routing errors\.*\s*:\s*(\d+)", route_text)
    fully_routed = re.search(r"# of fully routed nets\.*\s*:\s*(\d+)", route_text)
    routable = re.search(r"# of routable nets\.*\s*:\s*(\d+)", route_text)
    assert route_errors and fully_routed and routable, "Route status incomplete"
    route_met = int(route_errors[1]) == 0 and fully_routed[1] == routable[1]
    drc_text = (a.candidate / "drc.rpt").read_text()
    drc_errors = re.findall(r"^\|\s*(\S+)\s*\|\s*(Error|Critical Warning)\s*\|", drc_text, re.M)
    runtime_log = a.candidate.with_suffix(".log")
    runtime_critical = (re.findall(r"^CRITICAL WARNING: \[([^\]]+)\] (.+)$",
                                  runtime_log.read_text(), re.M) if runtime_log.exists() else [])
    timing_met = coverage and all(float(v[i]) >= 0 for i in (0, 4, 8)) and min(skews) >= 0
    a.out.mkdir(parents=True)
    copied = {}
    sources = [("routed", a.candidate), ("rx-short", a.rx_proof),
               ("parallel-short", a.parallel_proof), ("tx-short", a.tx_proof)]
    sources += [(f"clock-ooc-{i}", source) for i, source in enumerate(a.clock_ooc)]
    sources += [(f"diagnostics-{i}", source) for i, source in enumerate(a.diagnostics)]
    for label, source in sources:
        if source is None: continue
        target = a.out / label
        target.mkdir()
        for f in source.iterdir():
            if f.is_file() and f.suffix in (".rpt", ".log", ".json", ".sv", ".v", ".tcl"):
                shutil.copy2(f, target / f.name)
                copied[f"{label}/{f.name}"] = sha(f)
        external_log = source.with_suffix(".log")
        if external_log.exists():
            shutil.copy2(external_log, target / "vivado.log")
            copied[f"{label}/vivado.log"] = sha(external_log)
        if label.endswith("short"):
            proof = json.loads((source / "receipt.json").read_text())
            assert proof["status"].startswith("PASS_"), "Short candidate proof failed"
            for name, expected in proof["input_sha256"].items():
                assert sha(Path(name)) == expected, "Short proof source drift: " + name
            for name, expected in proof.get("output_sha256", {}).items():
                assert sha(source / name) == expected, "Short proof artifact drift: " + name
    src = a.out / "inputs"
    src.mkdir()
    for name in ("native_rx_clock.sv", "run_native_rx_deskew.py", "repair_native_rx_deskew.tcl",
                 "repair_native_feedback_clocks.tcl", "resume_native_rx_deskew.tcl",
                 "repair_native_mmcm_pll.tcl",
                 "repair_native_mmcm_trim.tcl", "review_native_tx_forwarded_model.tcl",
                 "review_native_tx_clock_ancestry.tcl", "repair_native_tx_isolation.tcl",
                 "native_tx_logic_tb.sv", "run_native_tx_logic.py",
                 "native_tx_isolation_probe.sv", "synth_native_tx_isolation.tcl",
                 "review_native_rx_compensation.tcl", "review_native_rx_eye.tcl", "synth_native_rx_clock.tcl",
                 "repair_native_clock_model.tcl", "repair_native_parallel_clocks.tcl",
                 "native_parallel_clocks.tcl", "review_native_io_options.tcl",
                 "native_gmac_clocks.sv", "native_tx_reset_boundary.sv", "native_tx90_tb.sv", "run_native_tx90.py",
                 "native_phy_board_control.sv", "native_phy_tx_init.sv", "native_phy_tx_init_tb.sv",
                 "repair_native_tx90.tcl", "synth_native_tx90_batch.tcl", "build_native_board.tcl", "reassemble_native_board.tcl",
                 "qualify_native_tx90_model.tcl", "synth_native_board_boundary.tcl", "check_native_tx90_source_constraints.tcl",
                 "native_gmac_pll_pair.sv", "synth_native_pll_pair.tcl", "repair_native_pll_pair.tcl",
                 "native_tx_common_delay.sv", "native_tx_calibrated_tb.sv", "synth_native_common_delay.tcl",
                 "native_gmac_divided_clock.sv", "native_divided_clock_constraints.tcl", "synth_native_divided_clock.tcl", "repair_native_divided_clock.tcl",
                 "resume_native_divided_clock.tcl",
                 "report_native_divided_clock.tcl",
                 "finish_native_divided_clock.tcl", "review_native_divided_model.tcl",
                 "native_rgmii.sv", "native_rgmii_tb.sv", "soc_top_gmac_ddr.sv",
                 "native_gmac_pins.xdc", "native_board_constraints.tcl", Path(__file__).name):
        f = root / "fpga/zu15eg" / name
        shutil.copy2(f, src / name)
        copied[f"inputs/{name}"] = sha(f)
    log = a.candidate.with_suffix(".log")
    if log.exists():
        shutil.copy2(log, a.out / "vivado.log")
        copied["vivado.log"] = sha(log)
    cpu_met = min(float(cpu[i]) for i in (1, 5, 9)) >= 0
    status = "ROUTED_STA_MET_OTHER_SIGNOFF_PENDING" if timing_met else (
        "CPU100_MET_IO_CANDIDATE_NOT_QUALIFIED" if cpu_met else "CPU100_REGRESSION_IO_NOT_QUALIFIED")
    if timing_met and (not route_met or drc_errors): status = "ROUTED_STA_MET_DRC_OR_ROUTE_NOT_MET"
    elif timing_met and runtime_critical: status = "ROUTED_STA_MET_RUNTIME_CONSTRAINT_REVIEW_PENDING"
    result = {"status": status,
        "date": "2026-10-05", "issue_width": 2, "cpu_hz": 100000000,
        "aon_uart_hz": 50000000, "uart_baud": 460800, "f_d_enabled": False,
        "bit_generated": False, "bit_deferred_by_user": True,
        "cpu_proof": {"sha256": sha(short_path), "unchanged_inputs": len(short["source_sha256"])},
        "cpu": {"setup_ns": float(cpu[1]), "hold_ns": float(cpu[5]), "pulse_ns": float(cpu[9])},
        "board": {"setup_ns": float(v[0]), "setup_failures": int(v[2]), "hold_ns": float(v[4]),
                  "hold_failures": int(v[6]), "pulse_ns": float(v[8])},
        "io": {"rx": rx, "tx": tx}, "clock_coverage_complete": coverage,
        "routing": {"all_routed": route_met, "routable_nets": int(routable[1]), "errors": int(route_errors[1])},
        "drc_errors_or_critical": drc_errors,
        "runtime_critical_warnings": runtime_critical,
        "bus_skew": {"minimum_slack_ns": min(skews), "checks": len(skews), "all_met": min(skews) >= 0},
        "dcp": str(a.candidate / "routed.dcp"), "dcp_sha256": sha(a.candidate / "routed.dcp"),
        "source_integrated": False, "artifact_sha256": copied,
        "limitations": ["Experimental physical clock changes are not current board RTL integration.",
                        "No full CPU/GSIM rerun: all 471 prior CPU proof inputs rehashed unchanged.",
                        "CPU100 is not whole-board/FPU qualification; board tests and CDC protocol review remain.",
                        "Unused CLKDIV model was rejected; TX must retain finite actual-CLK setup and hold."]}
    if a.software_phy:
        result.update(candidate_board_source_updated=True, hardware_phy_init_enabled=False,
                      physical_tx_phase_ns=2.0, phy_mode="rgmii-rxid",
                      phy_register_initialization_owner="software", phy_tx_delay_enabled=False,
                      phy_rx_delay_enabled=True, tx_phy_setup_hold_ns=1.0, pcb_skew_budget_ns=0.25)
        result["limitations"] = [
            "Physical ECO and board RTL candidate updated; full assembled-source equivalence/signoff pending.",
            "PHY mode is a required software contract, NOT real-board register readback evidence.",
            "Native Linux MAC driver is not implemented; use MDIO software before enabling TX/RX.",
            "All prior CPU proof inputs rehashed unchanged; no full CPU/GSIM/Linux rerun.",
            "No board/FPU100 qualification or bit generation."]
    if a.divider_clock:
        clear = io_slack((a.candidate / "divider_clear.rpt").read_text(),
                         {"u_eth_clk_wiz/inst/clkout1_buf/CLR", "native_tx_pad_divider/CLR", "native_tx90_forward_buffer/CLR"}, "Destination")
        result.update(clock_architecture="common_ref500_div4_phases",
                      phase_established_by="own-REF500 registered rising-edge CLR release; forward one source cycle later",
                      pad_clock_isolated=True, divider_release=clear,
                      phy_setup_hold_and_pcb_budget_unchanged=True,
                      io_delay_cascade_enabled=False, negative_source_latency_used=False)
    (a.out / "completion.json").write_text(json.dumps(result, indent=2) + "\n")
    print(result["status"], "CPU", result["cpu"], "IO", result["io"])


if __name__ == "__main__": main()
