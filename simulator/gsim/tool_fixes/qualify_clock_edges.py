#!/usr/bin/env python3
"""Qualify the opt-in explicit-edge GSIM profile on independent clocks, resets, RAM and mailbox."""
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


def source_files(root):
    return {str(p.relative_to(root)): p for p in root.rglob("*")
            if p.is_file() and not p.is_relative_to(root / "build")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tool", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--array-receipt", type=Path)
    args = parser.parse_args()
    output, tool = args.output.resolve(), args.tool.resolve()
    if output.exists() or not output.is_relative_to(ROOT / "build") or not tool.is_relative_to(ROOT / "build"):
        parser.error("fresh qualification output and isolated tool within clone build/ required")
    baseline, cxx = common.setup(False)
    output.mkdir(parents=True)
    expected = output / "expected-source"
    shutil.copytree(baseline.parents[2], expected, ignore=shutil.ignore_patterns("build"))
    patch = ROOT / "simulator/gsim/tool_fixes/explicit-clock-edges.patch"
    subprocess.run(["git", "apply", "--check", patch], cwd=expected, check=True)
    subprocess.run(["git", "apply", patch], cwd=expected, check=True)
    array_patch = None
    if args.array_receipt is not None:
        array_receipt = args.array_receipt.resolve()
        array_proof = json.loads(array_receipt.read_text())
        if (not array_receipt.is_relative_to(ROOT / "build") or
                array_proof["status"] != "PASS_EXPLICIT_EDGE_SYNC_ASYNC_ONE_TWO_DIMENSIONAL_RESET_ARRAYS" or
                array_proof["tool_sha256"] != sha(tool)):
            raise RuntimeError("reset-array proof must qualify this exact isolated tool")
        array_patch = ROOT / "simulator/gsim/tool_fixes/explicit-clock-reset-arrays.patch"
        subprocess.run(["git", "apply", "--check", array_patch], cwd=expected, check=True)
        subprocess.run(["git", "apply", array_patch], cwd=expected, check=True)
    wanted, actual = source_files(expected), source_files(tool.parents[2])
    if wanted.keys() != actual.keys() or any(sha(p) != sha(actual[n]) for n, p in wanted.items()):
        raise RuntimeError("candidate source differs from verified initialization epoch plus the exact patch")
    cp_values = json.loads((ROOT / "out/SpinorHost/test/runClasspath.json").read_text())["value"]
    cp = os.pathsep.join(str(p) for v in cp_values if (p := Path(v.split(":", 3)[3])).exists())
    receipt = {"status": "RUNNING", "mode": "GSIM_CLOCK_EDGES=1", "gsim": str(tool),
               "gsim_sha256": sha(tool), "source_root": str(tool.parents[2]),
               "source_sha256": {n: sha(p) for n, p in actual.items()}, "patch_sha256": sha(patch),
               "baseline_gsim_sha256": sha(baseline), "compiler": cxx, "commands": [],
               "scope": "top-level clock aliases; sequential sampling; scalar/flattened resets; defined RAM accesses; 80-bit mailbox",
               "physical_cdc_qualified": False, "default_tool_changed": False}
    frozen = {p: sha(p) for p in [patch, Path(__file__).resolve(),
              ROOT / "integration/spinor/src/test/scala/GsimClockContract.scala",
              ROOT / "src/test/scala/ooo/IndependentClockProbeGsim.scala",
              ROOT / "src/main/scala/ip/bus/CdcDataChannels.scala",
              ROOT / "src/main/scala/ip/bus/ClockDomainCrossing.scala",
              ROOT / "simulator/gsim/harness/gsim_clock_contract.cpp",
              ROOT / "simulator/gsim/harness/independent_clock_probe.cpp"]}
    if array_patch is not None:
        frozen[array_patch] = sha(array_patch)
        frozen[array_receipt] = sha(array_receipt)
        receipt["array_reset_qualification"] = {"receipt": str(array_receipt), "sha256": sha(array_receipt)}
        receipt["scope"] += "; independently qualified one/two-dimensional reset arrays"
    for p in frozen:
        target = output / "test-source" / p.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(p, target)
    receipt["test_source_sha256"] = {str(p.relative_to(ROOT)): digest for p, digest in frozen.items()}

    def run(argv, log, expected_exit=0, edge=True):
        argv = list(map(str, argv)); receipt["commands"].append({"argv": argv, "log": log})
        env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}
        if edge: env["GSIM_CLOCK_EDGES"] = "1"
        else: env.pop("GSIM_CLOCK_EDGES", None)
        with (output / log).open("w") as f:
            result = subprocess.run(argv, cwd=ROOT, env=env, stdout=f, stderr=subprocess.STDOUT)
        if result.returncode != expected_exit:
            raise RuntimeError("qualification command failed: " + log)
        return (output / log).read_text()

    def model(name, main_class, driver, executable):
        folder = output / name; folder.mkdir()
        run(["java", "-cp", cp, main_class, folder], name + "-elaborate.log")
        top = "IndependentClockProbeGsim" if name != "contract" else "GsimClockContract"
        run([executable, "--threads=1", "--dir=" + str(folder), folder / (top + ".fir")], name + "-generate.log")
        run([cxx, "-std=c++20", "-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
             "-I" + str(folder), *sorted(folder.glob(top + "[0-9]*.cpp")),
             ROOT / "simulator/gsim/harness" / driver, "-o", folder / "run"], name + "-compile.log")
        return folder / "run"

    try:
        probe = model("probe", "ooo.IndependentClockProbeGsimMain", "independent_clock_probe.cpp", tool)
        receipt["probe"] = json.loads(run([probe], "probe-positive.log"))
        contract = model("contract", "spinor_integration.GsimClockContractMain", "gsim_clock_contract.cpp", tool)
        receipt["contract"] = run([contract], "contract-positive.log").strip()
        text = run([contract, "--wrong-token"], "contract-negative.log", 1)
        if "independent mailbox 80-bit order oracle" not in text:
            raise RuntimeError("unrelated negative failure")
        bad = model("baseline", "ooo.IndependentClockProbeGsimMain", "independent_clock_probe.cpp", baseline)
        receipt["baseline_observation"] = json.loads(run([bad, "--observe"], "baseline-observation.log"))
        if "independent clock edge/reset contract mismatch" not in run([bad], "baseline-required.log", 1):
            raise RuntimeError("baseline failed for unrelated reason")
        if not receipt["probe"]["independent_edges_verified"] or not receipt["probe"]["async_reset"]["verified"]:
            raise RuntimeError("clock/reset probe not qualified")
        if any(sha(p) != digest for p, digest in frozen.items()) or sha(tool) != receipt["gsim_sha256"]:
            raise RuntimeError("qualification input drift")
        receipt["status"] = "PASS_SCOPED_EXPLICIT_CLOCK_EDGE_RESET_RAM_MAILBOX_GSIM_TOOL"
    except BaseException as error:
        receipt.update(status="FAIL", error=repr(error)); raise
    finally:
        receipt["artifact_sha256"] = {str(p.relative_to(output)): sha(p) for p in output.rglob("*")
            if p.is_file() and p != output / "receipt.json" and not p.is_relative_to(expected)}
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(receipt["status"], receipt["contract"], flush=True)


if __name__ == "__main__":
    main()
