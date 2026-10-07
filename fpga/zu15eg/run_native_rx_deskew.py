"""Short boundary-only RX MMCM candidate, existing independent byte oracle."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("output", type=Path)
    ap.add_argument("--delay-ps", type=int, default=200)
    ap.add_argument("--rx-phase", type=float, default=0.0,
                    help="RX MMCM phase in degrees; 5.625deg steps at DIV8")
    ap.add_argument("--isolate-tx", action="store_true",
                    help="separate phase-aligned TX pad BUFG, unchanged PHY contract")
    ap.add_argument("--board-rx", action="store_true",
                    help="simulate the exact current board RX module, not a phase-edited experimental replica")
    ap.add_argument("--vivado-bin", type=Path, default=Path(r"E:\Xilinx\2025.1\Vivado\bin"))
    a = ap.parse_args()
    if a.output.exists(): ap.error("use a fresh output directory")
    if not 0 <= a.delay_ps <= 1100: ap.error("illegal calibrated delay")
    if not 0 <= a.rx_phase <= 45 or abs(a.rx_phase / 5.625 - round(a.rx_phase / 5.625)) > 1e-9:
        ap.error("use a legal MMCM phase step in the scoped 0..45deg eye range")
    here = Path(__file__).resolve().parent
    inputs = [here / n for n in ("native_rx_clock.sv", "native_rgmii.sv", "native_rgmii_tb.sv")]
    inputs += [Path(__file__), a.vivado_bin.parent / "data/verilog/src/glbl.v"]
    if a.board_rx:
        inputs.append(here / "native_gmac_clocks.sv")
    before = {str(f): sha(f) for f in inputs}
    a.output.mkdir(parents=True)
    for f in inputs:
        if f.suffix in (".sv", ".v"): shutil.copy2(f, a.output / f.name)
    clock_data = inputs[0].read_text()
    if a.board_rx:
        board = (here / "native_gmac_clocks.sv").read_text()
        module = re.search(r"module native_gmac_rx_clock\b.*?endmodule", board, re.S)
        assert module, "Missing actual board RX module"
        phases = re.findall(r"\.CLKOUT0_PHASE\(([^)]+)\)", module.group())
        assert len(phases) == 1 and float(phases[0]) == a.rx_phase, "Board/proof phase mismatch"
        # Use the board's original module/ports/parameters verbatim. The
        # independent ETH frequency proxy is not a proof of board TX phase.
        clock_data, count = re.subn(r"module native_rx_clock\b.*?endmodule", "", clock_data, count=1, flags=re.S)
        assert count == 1
        (a.output / "tested_board_rx.sv").write_text("`timescale 1ns/1ps\n" + module.group() + "\n")
        (a.output / "native_gmac_clocks.sv").unlink()
    else:
        assert clock_data.count(".CLKOUT0_PHASE(0.0)") == 1
        clock_data = clock_data.replace(".CLKOUT0_PHASE(0.0)", f".CLKOUT0_PHASE({a.rx_phase})")
    (a.output / "native_rx_clock.sv").write_text(clock_data)
    data = inputs[1].read_text()
    assert data.count("parameter RX_DATA_DELAY_PS = 1100") == 1
    (a.output / "native_rgmii.sv").write_text(data.replace("parameter RX_DATA_DELAY_PS = 1100", f"parameter RX_DATA_DELAY_PS = {a.delay_ps}"))
    tb = inputs[2].read_text().replace("rx_reset", "rx_cold_reset")
    tb = tb.replace("rx_clock=0, ", "rx_pad_clock=0, ", 1)
    tb = tb.replace("reg tx_clock=0, rx_pad_clock=0, tx_reset=1, rx_cold_reset=1;",
                    "reg tx_reset=1;", 1)
    tb = tb.replace("reg delay_clock=0, delay_reset=1;", "reg delay_reset=1;", 1)
    tb = tb.replace("always #4 tx_clock=~tx_clock;", "", 1)
    tb = tb.replace("always #1 delay_clock=~delay_clock;", "", 1)
    tb = tb.replace("forever #4 rx_clock=~rx_clock", "forever #4 rx_pad_clock=~rx_pad_clock", 1)
    tb = tb.replace(".rx_cold_reset(rx_cold_reset)", ".rx_reset(rx_reset)", 1)
    tb = tb.replace("module native_rgmii_tb;", """module native_rgmii_tb;
    wire tx_clock, delay_clock;
    reg ui_clock=0, eth_cold_reset=1;
    always #2 ui_clock=~ui_clock;
    initial begin #121; eth_cold_reset=0; end
    wire tx_source, delay_source, eth_locked;
    native_eth_clock eth_clock_dut(.ui_clock(ui_clock), .cold_reset(eth_cold_reset),
        .tx_source(tx_source), .delay_source(delay_source), .locked(eth_locked));
    BUFG tx_buffer(.I(tx_source), .O(tx_clock));
    BUFG ref_buffer(.I(delay_source), .O(delay_clock));
    real last_tx=0, last_ref=0, rx_shift=2.0;
    integer tx_edges=0, ref_edges=0;
    initial begin
        if($test$plusargs("eye_early") && $test$plusargs("eye_late")) $fatal(1,"Ambiguous PHY eye stimulus");
        if($test$plusargs("eye_early")) rx_shift=0.95;
        if($test$plusargs("eye_late")) rx_shift=3.05;
    end
    always @(posedge tx_clock) if(eth_locked) begin
        if(last_tx!=0 && ($realtime-last_tx<7.999 || $realtime-last_tx>8.001))
            $fatal(1,"TX 125MHz independent period oracle");
        last_tx=$realtime; tx_edges=tx_edges+1;
    end else last_tx=0;
    always @(posedge delay_clock) if(eth_locked) begin
        if(last_ref!=0 && ($realtime-last_ref<1.999 || $realtime-last_ref>2.001))
            $fatal(1,"IDELAY 500MHz independent period oracle");
        last_ref=$realtime; ref_edges=ref_edges+1;
    end else last_ref=0;
    reg rx_pad_clock=0, rx_cold_reset=1;
    wire rx_clock, rx_source, rx_locked;
    native_rx_clock clock_dut(.pad_clock(rx_pad_clock), .cold_reset(rx_cold_reset),
        .clock_source(rx_source), .locked(rx_locked));
    BUFG raw_buffer(.I(rx_source), .O(rx_clock));
    (* ASYNC_REG=\"TRUE\" *) reg [2:0] rx_reset_pipe=3'b111;
    wire rx_request=rx_cold_reset | ($test$plusargs(\"bypass_lock\") ? 1'b0 : ~rx_locked);
    always @(posedge rx_clock or posedge rx_request)
        if(rx_request) rx_reset_pipe<=3'b111;
        else rx_reset_pipe<={rx_reset_pipe[1:0],1'b0};
    wire rx_reset=rx_reset_pipe[2];
    always @(negedge rx_pad_clock) if($realtime>150 && !rx_cold_reset && !rx_locked && !rx_request)
        $fatal(1,\"RX lock reset independent oracle\");
""", 1)
    tb = tb.replace("@(negedge rx_clock); rx_cold_reset=0;",
                    "@(negedge rx_pad_clock); rx_cold_reset=0; wait(rx_locked); wait(!rx_reset);", 1)
    tb = tb.replace("#139; //", "#139; wait(eth_locked); //", 1)
    if a.isolate_tx:
        tb = tb.replace("BUFG tx_buffer(.I(tx_source), .O(tx_clock));",
                        "BUFG tx_buffer(.I(tx_source), .O(tx_clock));\n"
                        "    wire tx_pad_clock;\n"
                        "    BUFG tx_pad_buffer(.I(tx_source), .O(tx_pad_clock));", 1)
        tb = tb.replace("native_rgmii dut", "native_rgmii #(.ISOLATE_TX_PAD_CLOCK(1)) dut", 1)
        tb = tb.replace(".tx_pad_clock(tx_clock)", ".tx_pad_clock(tx_pad_clock)", 1)
    tb = tb.replace("if (tx_seen!=16 || rx_seen!=16)",
                    "if (tx_seen!=16 || rx_seen!=16 || tx_edges<20 || ref_edges<80)", 1)
    if a.board_rx:
        assert tb.count("native_rx_clock clock_dut") == 1
        tb = tb.replace("native_rx_clock clock_dut", "native_gmac_rx_clock clock_dut", 1)
    # Observe the actual UNISIM output against the external pad clock. Do
    # not move the PHY stimulus together with the DUT's sampling phase.
    phase_check = f"""
    real last_rx_pad=0, last_rx_edge=0, rx_phase_ns;
    integer rx_locked_edges=0;
    always @(posedge rx_pad_clock) last_rx_pad=$realtime;
    always @(posedge rx_clock) if(rx_locked && !rx_reset) begin
        rx_locked_edges=rx_locked_edges+1;
        if(rx_locked_edges>8) begin
            rx_phase_ns=$realtime-last_rx_pad;
            if(rx_phase_ns<{a.rx_phase * 8.0 / 360.0 - .002:.9f} ||
               rx_phase_ns>{a.rx_phase * 8.0 / 360.0 + .002:.9f})
                $fatal(1,"RX physical phase independent oracle");
            if($realtime-last_rx_edge<7.999 || $realtime-last_rx_edge>8.001)
                $fatal(1,"RX 125MHz independent period oracle");
        end
        last_rx_edge=$realtime;
    end else begin rx_locked_edges=0; last_rx_edge=0; end
"""
    phase_anchor = "wire rx_reset=rx_reset_pipe[2];"
    assert tb.count(phase_anchor) == 1
    tb = tb.replace(phase_anchor, phase_anchor + "\n" + phase_check, 1)
    # External PHY stimulus follows the input pad, NOT the DUT sampling clock.
    start, end = tb.index("    task automatic rx_byte"), tb.index("    endtask")
    task = tb[start:end].replace("rx_clock", "rx_pad_clock").replace("#2; rxd", "#rx_shift; rxd")
    tb = tb[:start] + task + tb[end:]
    (a.output / "native_rgmii_tb.sv").write_text(tb)
    (a.output / "run.tcl").write_text("run all\nquit\n")
    report = {"status": "RUNNING", "input_sha256": before, "delay_ps": a.delay_ps,
              "rx_phase_degrees": a.rx_phase, "rx_vco_hz": 1000000000,
              "actual_board_rx": a.board_rx,
              "isolated_tx_pad_clock": a.isolate_tx,
              "rx_primitive": "MMCME4_ADV", "eth_primitive": "PLLE4_ADV",
              "eye_transition_ns": [0.95, 2.0, 3.05],
              "scope": f"RX MMCM feedback / ETH PLL frequency synthesis, {a.delay_ps}ps DDR and PHY eye endpoints; no CPU",
              "bit_generated": False, "negative_checks": {}}
    def run(tool, args, log):
        p = subprocess.run([str(a.vivado_bin / (tool + ".bat")), *args], cwd=a.output,
                           capture_output=True, text=True, timeout=90)
        output = p.stdout + p.stderr
        (a.output / log).write_text(output)
        return p.returncode, output
    failed = False
    try:
        for tool, args, log in (
            ("xvlog", ["--sv", *[f.name for f in a.output.glob("*.sv")], "glbl.v"], "compile.log"),
            ("xelab", ["native_rgmii_tb", "glbl", "-L", "unisims_ver", "--snapshot", "rx_deskew",
                       "--timescale", "1ns/1ps"], "elaborate.log")):
            code, output = run(tool, args, log)
            if code: raise RuntimeError(log + ": " + output[-1800:])
        for case in ("positive", "eye_early", "eye_late", "corrupt_rx", "corrupt_tx", "bypass_lock"):
            args = ["rx_deskew", "-tclbatch", "run.tcl"]
            if case != "positive": args += ["-testplusarg", case]
            code, output = run("xsim", args, case + ".log")
            if case in ("positive", "eye_early", "eye_late"):
                if code or "PASS_RGMII_DDR_BOUNDARY" not in output or "Fatal:" in output:
                    raise RuntimeError("Positive: " + output[-2400:])
            elif "Fatal:" not in output or "PASS_RGMII" in output:
                raise RuntimeError("Independent oracle did not reject " + case)
            else: report["negative_checks"][case] = "PASS"
        report["status"] = "PASS_NATIVE_RX_DESKEW_SHORT"
    except BaseException as error:
        failed = True
        report.update(status="FAIL_NATIVE_RX_DESKEW_SHORT", failure=str(error))
    finally:
        if before != {str(f): sha(f) for f in inputs}:
            failed = True
            report.update(status="FAIL_INPUT_DRIFT", failure="RX proof input drift")
        report["output_sha256"] = {f.name: sha(f) for f in a.output.iterdir()
                                  if f.is_file() and f.suffix in (".log", ".sv", ".v", ".tcl")}
        (a.output / "receipt.json").write_text(json.dumps(report, indent=2) + "\n")
    print(report["status"])
    if failed: raise SystemExit(report.get("failure", "failed"))


if __name__ == "__main__": main()
