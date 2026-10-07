#!/usr/bin/env python3
"""Native short xsim: new CDC/retention policy only, no CPU/MAC/PHY simulation."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("rtl", type=Path)
    p.add_argument("output", type=Path)
    p.add_argument("--vivado-bin", type=Path, default=Path(r"E:\Xilinx\2025.1\Vivado\bin"))
    a = p.parse_args()
    if a.output.exists(): p.error("use a fresh output directory")
    here = Path(__file__).resolve().parent
    root = here.parent.parent
    sources = [root / name for name in (
        "src/main/scala/ip/bus/CdcDataChannels.scala", "src/main/scala/ip/bus/ClockDomainCrossing.scala",
        "src/main/scala/ip/bus/PeripheralClockControl.scala", "src/main/scala/ip/ethernet/EthernetClockCrossing.scala",
        "src/main/scala/ip/ethernet/EthernetPort.scala", "src/test/scala/ip/SelfGmacCdc.scala",
        "src/test/scala/ip/SelfGmacCdcSpec.scala", "build.mill")]
    inputs = [*sorted(a.rtl.glob("*.sv")), here / "self_gmac_cdc_tb.sv", here / "cdc_run.tcl", Path(__file__)]
    if len(list(a.rtl.glob("*.sv"))) < 4: p.error("missing complete exported CDC RTL")
    before = {str(f): digest(f) for f in sources + inputs}
    protected = {str(f): digest(f) for f in sorted((root / "src/main/scala/core").rglob("*.scala"))}
    protected[str(root / "src/main/scala/ip/dma/EthernetPacketDma.scala")] = digest(root / "src/main/scala/ip/dma/EthernetPacketDma.scala")
    a.output.mkdir(parents=True)
    for f in inputs:
        if f.suffix != ".py": shutil.copy2(f, a.output / f.name)
    report = {"status": "RUNNING", "scope": "CDC channels and retention-clock policy only",
              "input_sha256": before, "protected_cpu_dma_sha256": protected,
              "rgmii_verified": False, "soc_runtime_clock_control_connected": False,
              "physical_gate_verified": False, "physical_cdc_constraints_verified": False,
              "board_verified": False, "bit_generated": False}
    def run(tool, args, log):
        result = subprocess.run([str(a.vivado_bin / (tool + ".bat")), *args], cwd=a.output,
                                capture_output=True, text=True, timeout=90)
        output = result.stdout + result.stderr
        (a.output / log).write_text(output)
        return result.returncode, output
    failed = False
    try:
        for tool, args, log in (
            ("xvlog", ["--sv", *[f.name for f in inputs if f.suffix == ".sv"]], "compile.log"),
            ("xelab", ["self_gmac_cdc_tb", "--snapshot", "native_gmac_cdc", "--debug", "typical",
                       "--timescale", "1ns/1ps"], "elaborate.log")):
            code, output = run(tool, args, log)
            if code: raise RuntimeError(log + ": " + output[-1800:])
        code, output = run("xsim", ["native_gmac_cdc", "-tclbatch", "cdc_run.tcl"], "positive.log")
        if code or "SELF_GMAC_CDC_PASS clock_cases=4" not in output:
            raise RuntimeError("positive failed: " + output[-2500:])
        report["positive_summary"] = [line for line in output.splitlines() if "CDC_CASE_PASS" in line or "SELF_GMAC_CDC_PASS" in line]
        report["negative_checks"] = {}
        for injection, marker in (
            ("frame", "native TX CDC independent scoreboard mismatch"),
            ("config", "atomic config independent scoreboard mismatch"),
            ("event", "event accumulation independent scoreboard mismatch"),
            ("clock", "clock stop independent scoreboard mismatch")):
            code, negative = run("xsim", ["native_gmac_cdc", "-tclbatch", "cdc_run.tcl",
                                          "-testplusarg", "inject_" + injection], "negative-" + injection + ".log")
            if marker not in negative or "SELF_GMAC_CDC_PASS" in negative:
                raise RuntimeError("negative did not reject: " + injection)
            report["negative_checks"][injection] = "passed"
        report.update(status="PASS_NATIVE_GMAC_CDC_CLOCK_POLICY_SHORT", independent_clocks_verified=True,
                      coordinated_reset_only=True, clock_pause_model_only=True)
    except BaseException as error:
        failed = True
        report.update(status="FAIL_NATIVE_GMAC_CDC_CLOCK_POLICY_SHORT", failure=str(error))
    finally:
        if before != {str(f): digest(f) for f in sources + inputs} or protected != {name: digest(Path(name)) for name in protected}:
            failed = True
            report.update(status="FAIL_INPUT_DRIFT", failure="RTL/source/protected CPU/DMA drift")
        report["output_sha256"] = {f.name: digest(f) for f in a.output.glob("*.log")}
        (a.output / "receipt.json").write_text(json.dumps(report, indent=2) + "\n")
    print(report["status"])
    if failed: raise SystemExit(report.get("failure", "failed"))


if __name__ == "__main__": main()
