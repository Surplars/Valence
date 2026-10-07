#!/usr/bin/env python3
"""Record one source-integrated RV64GC whole-board route, without releasing bit.

Finite STA is necessary, not sufficient for a board release: CDC and external
PHY readback still require their own review. Preserve failures and all reports.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil

from audit_native_io_qualification import io_slack


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def routed_state(text):
    # phys_opt_design preserves completed routing but labels its report
    # "Physopt postRoute". Route-status coverage is checked separately below.
    return bool(re.search(r"^\| Design State\s*:\s*(?:Routed|Physopt postRoute)\s*$", text, re.M))


def checked_source_map(inputs):
    # The Chisel receipt alone cannot detect a later edit to the physical
    # clock/top/XDC/Tcl sources. Compare them with the frozen staged bytes too.
    result = dict(inputs["checked_source_sha256"])
    for name, digest in inputs["candidate_sha256"].items():
        parts = name.replace("\\", "/").split("/")
        if len(parts) == 2 and parts[0] in ("board", "scripts"):
            key = "fpga/zu15eg/" + parts[1]
            assert key not in result or result[key] == digest, "Conflicting source provenance"
            result[key] = digest
    return result


def summary(text):
    section = text[text.index("| Design Timing Summary"):]
    row = re.search(r"^\s+([-\d.]+)\s+([-\d.]+)\s+(\d+)\s+(\d+)\s+([-\d.]+)\s+([-\d.]+)\s+(\d+)\s+(\d+)\s+([-\d.]+)\s+([-\d.]+)\s+(\d+)\s+(\d+)\s*$", section, re.M)
    assert row, "Missing timing summary row"
    v = row.groups()
    return dict(setup_ns=float(v[0]), setup_failures=int(v[2]), hold_ns=float(v[4]),
                hold_failures=int(v[6]), pulse_ns=float(v[8]), pulse_failures=int(v[10]))


def resources(text):
    keys = ("luts", "logic_luts", "lutram", "srl", "ffs", "ramb36", "ramb18", "uram", "dsps")
    result = {}
    for line in text.splitlines():
        columns = [c.strip() for c in line.split("|")[1:-1]]
        if len(columns) != 11 or not all(c.isdigit() for c in columns[2:]):
            continue
        if columns[0].startswith("("):
            # Vivado repeats a module's own (non-descendant) usage in a
            # parenthesized row. It is not a second instance or total.
            continue
        if columns[0] == "soc_top_gmac_ddr":
            result["board"] = dict(zip(keys, map(int, columns[2:])))
        elif columns[1] in ("FloatingPointSystem", "FloatingPointExecute", "IntegerCore"):
            assert columns[1] not in result, "Duplicate module resource totals"
            result[columns[1]] = dict(zip(keys, map(int, columns[2:])))
    assert "board" in result and "FloatingPointSystem" in result, "FPU absent from routed utilization"
    return result


def review_runtime_critical(log, board, sta_met):
    """Retain all warnings; resolve only an earlier router STA warning.

    A successfully completed post-route optimization and matching final STA
    must supersede it. No other critical warning or failing final check is
    waived. The raw log and explicit resolution remain release evidence.
    """
    pending, resolved = [], []
    final = re.search(r"^NATIVE_BOARD_RESULT ISA=rv64gc WNS=([-\d.]+) WHS=([-\d.]+) CPU100 UART460800 GMAC125$", log, re.M)
    command = log.rfind("Command: phys_opt_design -directive Explore")
    complete = log.rfind("phys_opt_design completed successfully")
    route_complete = log.rfind("route_design completed successfully")
    final_matches = (final is not None and sta_met and
                     abs(float(final[1]) - board['setup_ns']) < 0.0005 and
                     abs(float(final[2]) - board['hold_ns']) < 0.0005)
    expected = 'The design did not meet timing requirements. Please run report_timing_summary for detailed reports.'
    for warning in re.finditer(r"^CRITICAL WARNING: \[([^\]]+)\] (.+)$", log, re.M):
        item = (warning[1], warning[2])
        if (final_matches and item == ('Route 35-39', expected) and
                warning.start() < route_complete < command < complete < final.start()):
            resolved.append(dict(id=item[0], message=item[1],
                                 resolution='Superseded by successful post-route phys_opt and matching fully passing final STA; no constraint changes'))
        else:
            pending.append(item)
    return pending, resolved


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("candidate", type=Path)
    ap.add_argument("--repo", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--inputs", default="inputs.json")
    ap.add_argument("--implementation", default="implementation")
    ap.add_argument("--log", default="build.log")
    ap.add_argument("--bit-requested", action="store_true",
                    help="record current bit-generation request; still requires separate CDC/release signoff")
    a = ap.parse_args()
    assert not (a.out / "completion.json").exists(), "Preserve existing result"
    assert not (a.out / "windows-run").exists(), "Preserve existing report archive"
    inputs = json.loads((a.candidate / a.inputs).read_text())
    assert inputs["status"] in {"STAGED_RV64GC_SOURCE_NOT_TIMING_QUALIFIED",
                                "STAGED_DDR2G_RV64GC_CHECKED_EXPORT_NOT_ROUTED"}
    assert inputs["isa"] == "rv64gc" and inputs["f_d_enabled"]
    drift = {name: sha(a.candidate / name) if (a.candidate / name).exists() else "MISSING" for name, expected in inputs["candidate_sha256"].items()
             if not (a.candidate / name).exists() or sha(a.candidate / name) != expected}
    source_drift = [name for name, expected in checked_source_map(inputs).items()
                    if not (a.repo / name).exists() or sha(a.repo / name) != expected]
    run = a.candidate / a.implementation
    timing = (run / "timing_summary.rpt").read_text()
    assert routed_state(timing), "Not routed STA"
    board = summary(timing)
    cpu = re.search(r"^\s+clk_out1_clk_wiz_ddr\s+([\d.-]+)\s+([\d.-]+)\s+(\d+)\s+(\d+)\s+([\d.-]+)\s+([\d.-]+)\s+(\d+)\s+(\d+)\s+([\d.-]+)", timing, re.M)
    assert cpu, "Actual CPU100 clock group missing"
    cpu_result = dict(setup_ns=float(cpu[1]), setup_failures=int(cpu[3]),
                      hold_ns=float(cpu[5]), hold_failures=int(cpu[7]), pulse_ns=float(cpu[9]))
    ports = lambda d: {"eth_" + d + "_ctl", *(f"eth_{d}d[{n}]" for n in range(4))}
    tx_text = (run / "tx_io.rpt").read_text()
    tx = io_slack(tx_text, ports("tx"), "Destination")
    rx = io_slack((run / "rx_io.rpt").read_text(), ports("rx"), "Source")
    assert set(re.findall(r"Output Delay:\s+([-\d.]+)ns", tx_text)) == {"1.250", "-1.250"}, "TX budget changed"
    quarter = inputs.get("tx_clock_architecture") == "common_clk250_dedicated_oddr"
    if quarter:
        assert set(re.findall(r"Requirement:\s+([-\d.]+)ns", tx_text)) == {"2.000", "-2.000"}, "Unproved TX edge relationship"
        identity = (run / "quarter_tx_identity.txt").read_text()
        assert ("PASS_NATIVE_QUARTER_TX_TOPOLOGY SIX_COMMON_CLK250_RESET FIVE_EXACT_D0_D4_PAIRS PHASE_FEEDBACK" in identity or
                "PASS_NATIVE_QUARTER_TX_TOPOLOGY ACTUAL_VALIDATED_DATA_PADS=" in identity)
    clear_names = ("raw_div", "quarter_div") if quarter else ("raw_div", "pad_div", "forward_div")
    clear_ports = {f"centered_tx_clock.clock_dut/{name}/CLR" for name in clear_names}
    clear = io_slack((run / "divider_clear.rpt").read_text(), clear_ports, "Destination")
    coverage_text = (run / "check_timing.rpt").read_text()
    coverage_names = ("no_clock", "unconstrained_internal_endpoints", "generated_clocks", "loops", "multiple_clock", "latch_loops")
    coverage = {name: bool(re.search(rf"checking {name} \(0\)", coverage_text)) for name in coverage_names}
    skew_text = (run / "bus_skew.rpt").read_text()
    skews = list(map(float, re.findall(r"Slack \((?:MET|VIOLATED)\)\s*:\s*([-+\d.]+)ns", skew_text)))
    skew_failures = len(re.findall(r"Slack \(VIOLATED\)", skew_text))
    assert len(skews) >= 27, "Lost original bus-skew checks"
    route = (run / "route_status.rpt").read_text()
    net_count = lambda name: int(re.search(r"# of " + name + r"\.*\s*:\s*(\d+)", route)[1])
    routing = dict(routable_nets=net_count("routable nets"), fully_routed_nets=net_count("fully routed nets"), errors=net_count("nets with routing errors"))
    routing["all_routed"] = routing["errors"] == 0 and routing["routable_nets"] == routing["fully_routed_nets"]
    drc = re.findall(r"^\|\s*(\S+)\s*\|\s*(Error|Critical Warning)\s*\|", (run / "drc.rpt").read_text(), re.M)
    log = (a.candidate / a.log).read_text()
    errors = re.findall(r"^ERROR:.*$", log, re.M)
    sta_met = all(board[name] >= 0 for name in ("setup_ns", "hold_ns", "pulse_ns"))
    sta_met = sta_met and all(board[name] == 0 for name in ("setup_failures", "hold_failures", "pulse_failures"))
    sta_met = sta_met and min(skews) >= 0 and skew_failures == 0 and all(coverage.values())
    sta_met = sta_met and min(*tx.values(), *rx.values(), *clear.values()) >= 0
    critical, resolved_critical = review_runtime_critical(log, board, sta_met)
    data_valid = not drift and not source_drift and routing["all_routed"] and not drc and not errors
    status = "RV64GC100_ROUTED_TIMING_MET_CDC_BOARD_REVIEW_PENDING" if sta_met and data_valid and not critical else (
        "RV64GC100_ROUTED_TIMING_MET_INPUT_OR_CONSTRAINT_REVIEW_PENDING" if sta_met else "RV64GC100_ROUTED_TIMING_NOT_MET")
    a.out.mkdir(parents=True, exist_ok=True)
    archive = a.out / "windows-run"
    archive.mkdir()
    artifacts = {}
    for path in sorted(run.iterdir()):
        if path.is_file() and path.suffix in (".rpt", ".xdc", ".txt"):
            shutil.copy2(path, archive / path.name)
            artifacts[path.name] = sha(path)
    for name in {"inputs.json", "build.log", a.inputs, a.log}:
        shutil.copy2(a.candidate / name, archive / name)
        artifacts[name] = sha(a.candidate / name)
    result = dict(status=status, isa="rv64gc", f_d_enabled=True, issue_width=2,
                  cpu_hz=100000000, uart_baud=460800, integer_cpu_checkpoint_reused=False,
                  candidate_post_synth_checkpoint_reused=inputs.get("candidate_post_synth_checkpoint_reused", False),
                  board=board, cpu=cpu_result, io=dict(tx=tx, rx=rx), divider_release=clear,
                  resources=resources((run / "utilization.rpt").read_text()),
                  clock_coverage=coverage, bus_skew=dict(checks=len(skews), failures=skew_failures, minimum_slack_ns=min(skews)),
                  routing=routing, drc_errors_or_critical=drc, runtime_critical_warnings=critical,
                  runtime_resolved_critical_warnings=resolved_critical,
                  runtime_errors=errors, candidate_input_drift=drift, current_source_drift=source_drift,
                  source_integrated=not drift and not source_drift, routed_timing_met=sta_met,
                  dcp=str(run / "routed.dcp"), dcp_sha256=sha(run / "routed.dcp"), artifact_sha256=artifacts,
                  bit_generated=False, bit_requested=a.bit_requested,
                  bit_deferred_by_user=not a.bit_requested, phy_initialization_owner="software",
                  tx_clock_architecture=inputs.get("tx_clock_architecture", "common_ref500_div4_phases"),
                  phy_tx_delay_enabled=False, phy_rx_delay_enabled=True,
                  limits=["Source-integrated full-board route, not independent netlist equivalence certification.",
                          "FPU executes single-outstanding at ROB head; not dual-issue FP OoO.",
                          "Affected short GSIM plus separately rehashed peripheral proofs; not full GSIM or Linux FP scheduling.",
                          "CDC structural report and physical PHY/software delay readback still need review.",
                          "No new IPC/benchmark improvement claim and no bitstream release."])
    if inputs.get("ddr_bytes") == 0x80000000:
        result.update(ddr_bytes=0x80000000, ram_base=inputs["ram_base"],
                      end_exclusive=inputs["end_exclusive"],
                      functional_scope="Affected DDR2G bridge/window/DMA and network-pressure checks, not complete CPU/Linux runtime")
    (a.out / "completion.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(status, "CPU", cpu_result, "BOARD", board, "IO", result["io"])


if __name__ == "__main__":
    main()
