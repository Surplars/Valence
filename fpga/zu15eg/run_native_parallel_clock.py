"""Short actual-BUFGCE input rewiring validation; no CPU or whole-board sim."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("rtl", type=Path)
    ap.add_argument("output", type=Path)
    ap.add_argument("--vivado-bin", type=Path, default=Path(r"E:\Xilinx\2025.1\Vivado\bin"))
    a = ap.parse_args()
    if a.output.exists(): ap.error("use a fresh output directory")
    here = Path(__file__).resolve().parent
    inputs = [a.rtl / name for name in ("ManagedClockBuffer.sv", "CdcResetRelease.sv", "CdcLevel.sv")]
    inputs += [here / "native_parallel_clock_tb.sv", here / "native_parallel_clocks.tcl", Path(__file__),
               a.vivado_bin.parent / "data/verilog/src/glbl.v"]
    before = {str(f): sha(f) for f in inputs}
    original = inputs[0].read_text()
    assert original.count("module ManagedClockBuffer(") == 1
    assert original.count("input  rawClock,") == 1 and original.count(".I  (rawClock),") == 1
    lowered = original.replace("module ManagedClockBuffer(", "module ParallelManagedClockBuffer(")
    lowered = lowered.replace("input  rawClock,", "input  rawClock,\n         bufferSource,", 1)
    lowered = lowered.replace(".I  (rawClock),", ".I  (bufferSource),", 1)
    a.output.mkdir(parents=True)
    for f in inputs:
        if f.suffix in (".sv", ".v", ".tcl"): shutil.copy2(f, a.output / f.name)
    (a.output / "ParallelManagedClockBuffer.sv").write_text(lowered)
    (a.output / "run.tcl").write_text("run all\nquit\n")
    result = {"status": "RUNNING", "input_sha256": before, "bit_generated": False,
              "scope": "Same actual raw reset/CE synchronizers, only BUFGCE I source changed; UNISIM simulation"}
    def run(tool, args, log):
        process = subprocess.run([str(a.vivado_bin / (tool + ".bat")), *args], cwd=a.output,
                                 capture_output=True, text=True, timeout=90)
        output = process.stdout + process.stderr
        (a.output / log).write_text(output)
        return process.returncode, output
    failed = False
    try:
        for tool, args, log in (
            ("xvlog", ["--sv", *[f.name for f in a.output.glob("*.sv")], "glbl.v"], "compile.log"),
            ("xelab", ["native_parallel_clock_tb", "glbl", "-L", "unisims_ver",
                       "--snapshot", "native_parallel_clock", "--timescale", "1ns/1ps"], "elaborate.log")):
            code, output = run(tool, args, log)
            if code: raise RuntimeError(log + ": " + output[-1800:])
        code, output = run("xsim", ["native_parallel_clock", "-tclbatch", "run.tcl"], "positive.log")
        if code or "PASS_NATIVE_PARALLEL_CLOCK" not in output or "Fatal:" in output:
            raise RuntimeError("Positive: " + output[-2400:])
        code, output = run("xsim", ["native_parallel_clock", "-tclbatch", "run.tcl",
                                    "-testplusarg", "invert_source"], "negative-source.log")
        if "Fatal:" not in output or "oracle" not in output or "PASS_NATIVE" in output:
            raise RuntimeError("Negative source oracle did not reject")
        result.update(status="PASS_NATIVE_PARALLEL_CLOCK_SHORT", independent_negative="PASS")
    except BaseException as error:
        failed = True
        result.update(status="FAIL_NATIVE_PARALLEL_CLOCK_SHORT", failure=str(error))
    finally:
        if before != {str(f): sha(f) for f in inputs}:
            failed = True
            result.update(status="FAIL_INPUT_DRIFT", failure="Clock proof input drift")
        result["output_sha256"] = {f.name: sha(f) for f in a.output.glob("*.log")}
        (a.output / "receipt.json").write_text(json.dumps(result, indent=2) + "\n")
    print(result["status"])
    if failed: raise SystemExit(result.get("failure", "failed"))


if __name__ == "__main__": main()
