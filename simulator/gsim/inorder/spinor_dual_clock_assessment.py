#!/usr/bin/env python3
"""Elaborate native dual-clock CPU/Spinor RTL and observe GSIM clock/reset capability.

An unsupported clock probe is a recorded simulator limitation, never CDC acceptance.
No alternate simulator, physical implementation or synthetic clock gating is used.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "simulator/gsim"))
import run as common


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rtl-output", type=Path, required=True)
    args = parser.parse_args()
    output, rtl = args.output.resolve(), args.rtl_output.resolve()
    if output.exists() or not output.is_relative_to(ROOT / "build"):
        parser.error("fresh output within clone build/ required")
    if rtl.exists() or not rtl.is_relative_to(Path("/mnt/e/VM/Share/Valence-rtl/Valence-InOrder")):
        parser.error("fresh RTL output within designated Windows root required")
    values = json.loads((ROOT / "out/SpinorHost/test/runClasspath.json").read_text())["value"]
    runtime = os.pathsep.join(str(p) for v in values if (p := Path(v.split(":", 3)[3])).exists())
    gsim, cxx = common.setup(False)
    source = ROOT / json.loads((ROOT / "simulator/gsim/config/spinor-integration.json").read_text())["source_root"]
    subprocess.run([sys.executable, ROOT / "scripts/fetch_spinor.py", "--verify-only"], check=True)
    inputs = [ROOT / "build.mill", Path(__file__).resolve(),
              ROOT / "src/main/scala/ip/bus/CdcDataChannels.scala",
              ROOT / "src/main/scala/ip/bus/ClockDomainCrossing.scala",
              ROOT / "src/test/scala/ooo/IndependentClockProbeGsim.scala",
              ROOT / "simulator/gsim/harness/independent_clock_probe.cpp",
              ROOT / "simulator/gsim/config/spinor-integration.json"]
    for directory in [source / "src/main/scala", ROOT / "src/main/scala/core/inorder",
                      ROOT / "integration/spinor", ROOT / "third_party/berkeley-hardfloat/src/main/scala"]:
        inputs += sorted(directory.rglob("*.scala"))
    frozen = {str(p.relative_to(ROOT)): sha(p) for p in inputs}
    output.mkdir(parents=True)
    for p in inputs:
        target = output / "source-at-model" / p.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, target)
    receipt = {"status": "RUNNING", "scope": __doc__, "source_sha256": frozen,
               "gsim_sha256": sha(gsim), "commands": [], "rtl_output": str(rtl),
               "independent_clock_function_qualified": False, "cdc_physical_qualified": False,
               "soc_interconnect_present": False, "cmu_present": False, "vpu_target_hz": 300000000}

    def run(argv, log, expected_exit=0):
        argv = list(map(str, argv)); receipt["commands"].append({"argv": argv, "log": log})
        with (output / log).open("w") as f:
            result = subprocess.run(argv, cwd=ROOT, stdout=f, stderr=subprocess.STDOUT,
                                    env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
        text = (output / log).read_text()
        if result.returncode != expected_exit:
            raise RuntimeError("command exit mismatch: " + log)
        return text

    try:
        run(["java", "-cp", runtime, "spinor_integration.I1SpinorDualClockMain", output], "elaborate.log")
        run(["java", "-cp", runtime, "spinor_integration.I1SpinorDualClockMain", rtl, "--sv"], "export-sv.log")
        top = (rtl / "I1SpinorDualClockCore.sv").read_text()
        if "cpuClock" not in top or "vpuClock" not in top or "I1SpinorClockBoundary" not in top:
            raise RuntimeError("independent clock top boundary missing")
        receipt["rtl_sha256"] = {str(p.relative_to(rtl)): sha(p) for p in sorted(rtl.rglob("*.sv"))}
        receipt["rtl_elaboration"] = "PASS_FIR_AND_SV_WITH_FIRTOOL_CIRCUIT_CHECKS"
        probe = output / "clock-probe"; probe.mkdir()
        run(["java", "-cp", runtime, "ooo.IndependentClockProbeGsimMain", probe], "probe-elaborate.log")
        run([gsim, "--threads=1", "--dir=" + str(probe), probe / "IndependentClockProbeGsim.fir"],
            "probe-generate.log")
        run([cxx, "-std=c++20", "-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
             "-I" + str(probe), *sorted(probe.glob("IndependentClockProbeGsim[0-9]*.cpp")),
             ROOT / "simulator/gsim/harness/independent_clock_probe.cpp", "-o", probe / "run"],
            "probe-compile.log")
        observation = json.loads(run([probe / "run", "--observe"], "probe-observation.log"))
        receipt["clock_probe"] = observation
        supported = observation["independent_edges_verified"] and observation["async_reset"]["verified"]
        text = run([probe / "run"], "probe-required-contract.log", 0 if supported else 1)
        if not supported and "independent clock edge/reset contract mismatch" not in text:
            raise RuntimeError("unrelated probe failure")
        receipt["status"] = ("ELABORATED_DUAL_CLOCK_RTL_GSIM_CLOCK_CAPABILITY_PASS_BRIDGE_TEST_PENDING" if supported
                             else "ELABORATED_DUAL_CLOCK_RTL_GSIM_INDEPENDENT_CLOCK_RESET_UNSUPPORTED")
        for name, digest in frozen.items():
            if sha(ROOT / name) != digest:
                raise RuntimeError("source drift: " + name)
    except BaseException as error:
        receipt.update(status="FAIL", error=repr(error)); raise
    finally:
        receipt["artifact_sha256"] = {str(p.relative_to(output)): sha(p) for p in output.rglob("*")
                                      if p.is_file() and not p.is_relative_to(output / "source-at-model")
                                      and p != output / "receipt.json"}
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(receipt["status"], flush=True)
    print(json.dumps(receipt.get("clock_probe", {})), flush=True)


if __name__ == "__main__":
    main()
