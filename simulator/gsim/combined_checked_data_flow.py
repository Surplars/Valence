#!/usr/bin/env python3
"""Bounded actual-DTA A/B proof for explicitly combined demand-hit/certified-PA flow.

No tool installation, broad tests or CPU performance claim. The separate actual
CPU runner owns its strict baseline reuse gate and matched two-guest comparison.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import run as common

HERE = Path(__file__).resolve().parent
TOP = "CombinedCheckedDataFlowGsim"
MAIN = "ooo.CombinedCheckedDataFlowGsimMain"
HOST = HERE / "harness/combined_checked_data_flow.cpp"
ENV = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rows(log, prefix, key):
    result = {}
    for line in log.splitlines():
        if line.startswith(prefix + " "):
            fields = dict(word.split("=", 1) for word in line.split()[1:])
            name = fields.pop(key)
            assert name not in result, (prefix, name)
            result[name] = {k: int(v) for k, v in fields.items()}
    assert result, prefix
    return result


def poison(binary, target, flag, marker, diagnostics, hardware=False):
    result = subprocess.run([str(binary), flag], capture_output=True, text=True, timeout=60, env=ENV)
    log = result.stdout + result.stderr
    path = target / (flag[2:] + ".log")
    path.write_text(log)
    assert (result.returncode != 0 if hardware else result.returncode == 1), (flag, result.returncode, log)
    assert marker in log and any(text in log for text in diagnostics), (flag, log)
    assert "assertion did not fire" not in log, (flag, log)
    assert "ERROR: AddressSanitizer" not in log and "runtime error:" not in log, log
    return {"flag": flag, "exit": result.returncode, "marker": marker,
            "matchedDiagnostics": [text for text in diagnostics if text in log],
            "hardwareAssertion": hardware, "logSha256": sha(path)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gsim", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    args = parser.parse_args()
    assert re.fullmatch(r"[A-Za-z0-9_-]+", args.tag)
    out = common.BUILD / args.tag
    out.mkdir(parents=True, exist_ok=False)
    gsim = args.gsim.resolve(strict=True)
    cxx, compiler = common.compiler()
    sources = sorted((common.ROOT / "src/main/scala").rglob("*.scala")) + [
        common.ROOT / "src/test/scala/ooo/CombinedCheckedDataFlowGsim.scala",
        common.ROOT / "src/test/scala/platform/CombinedCheckedDataFlowSpec.scala",
        HOST, HERE / "harness/virtual_load_test_memory.h", HERE / "m2_data_translation/oracle.h",
        Path(__file__), HERE / "run.py", HERE / "config/toolchain.json",
    ]
    frozen = {str(p.relative_to(common.ROOT)): sha(p) for p in sources}
    for source in sources:
        copied = out / "inputs" / source.relative_to(common.ROOT)
        copied.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, copied)
        assert sha(copied) == frozen[str(source.relative_to(common.ROOT))]
    state = {"status": "RUNNING", "sourceSha256": frozen, "compiler": compiler,
             "compilerPath": str(Path(shutil.which(str(cxx)) or str(cxx)).resolve()),
             "compilerSha256": sha(Path(shutil.which(str(cxx)) or str(cxx)).resolve()),
             "gsimSha256": sha(gsim), "models": {}, "negativeControls": [],
             "scope": "actual A1-shaped DTA/16-entry DTLB A/B; no CPU, PPA or board qualification",
             "delta": {"precheckedDataRequestFlow": [False, True], "combinedCheckedDataFlow": [False, True]},
             "preserved": {"translationHitFlow": True, "translatedEntries": 8, "checkedEntries": 2,
                           "orderedResponseOwners": 8, "extraOwnersOrCredits": 0},
             "policy": "Malformed certified alignment/mask hardening is enabled only in candidate, as in the old separate flow."}

    def save():
        (out / "receipt.json").write_text(json.dumps(state, indent=2) + "\n")

    save()
    try:
        for label, enabled in (("baseline", 0), ("combined", 1)):
            target = out / label
            target.mkdir()
            result = {"status": "RUNNING", "enabled": enabled}
            state["models"][label] = result
            flags = ["-std=c++20", "-O1", "-g", "-fsanitize=address,undefined",
                     "-fno-sanitize-recover=all", "-I" + str(target),
                     "-DCOMBINED_CHECKED_FLOW=" + str(enabled)]
            result["compileFlags"] = flags
            save()
            common.run(["mill", "-i", "IonSoC.test.runMain", MAIN, target, label], log=target / "elaborate.log")
            result["firSha256"] = sha(target / (TOP + ".fir")); save()
            common.run([gsim, "--threads=1", f"--dir={target}", target / (TOP + ".fir")], log=target / "generate.log")
            result["headerSha256"] = sha(target / (TOP + ".h")); save()
            # Validate against the actual generated API before expensive model compilation.
            common.run([cxx, *flags, "-fsyntax-only", HOST], log=target / "header-syntax.log")
            objects = []
            generated = sorted(target.glob(TOP + "[0-9]*.cpp"))
            assert generated
            for source in [*generated, HOST]:
                obj = target / (source.stem + ".o")
                common.run([cxx, *flags, "-c", source, "-o", obj],
                           log=target / (source.stem + "-compile.log"))
                objects.append(obj)
            common.run([cxx, *flags, *objects, "-ldl", "-o", target / "run"], log=target / "link.log")
            result["generatedSha256"] = {p.name: sha(p) for p in generated}
            result["objectSha256"] = {p.name: sha(p) for p in objects}
            result["binarySha256"] = sha(target / "run"); save()
            common.run([target / "run"], env=ENV, timeout=60, log=target / "test.log")
            log = (target / "test.log").read_text()
            assert log.count(f"COMBINED_CHECKED_FLOW_PASS enabled={enabled}") == 1, log
            result.update(status="PASS", logSha256=sha(target / "test.log"),
                          metrics=rows(log, "COMBINED_CHECKED_FLOW_METRIC", "scenario"),
                          cases=rows(log, "COMBINED_CHECKED_FLOW_CASE", "name"))
            save()
            for flag, marker, diagnostic in (
                ("--inject-pa", "INJECT COMBINED_CHECKED_FLOW physical PA", "independent physical PA/order mismatch"),
                ("--inject-data", "INJECT COMBINED_CHECKED_FLOW response data", "independent ordered response data mismatch"),
                ("--inject-fault", "INJECT COMBINED_CHECKED_FLOW response fault", "independent ordered fault classification mismatch"),
                ("--inject-canonical", "INJECT COMBINED_CHECKED_FLOW canonical attribution", "independent canonical certificate attribution mismatch"),
            ):
                state["negativeControls"].append({"model": label, **poison(target / "run", target, flag, marker, [diagnostic])})
                save()
            if enabled:
                state["negativeControls"].append({"model": label, **poison(target / "run", target,
                    "--force-undrained-flush", "INJECT COMBINED_CHECKED_FLOW undrained flush", [
                        "VM/PMP/SFENCE context changes must drain accepted prechecked loads before changing authorization",
                        "VM/PMP/SFENCE changes must drain accepted canonical stores and overlapping adapter work"], hardware=True)})
                save()
        a, b = (state["models"][label] for label in ("baseline", "combined"))
        assert a["cases"].keys() == b["cases"].keys()
        for name in a["cases"]:
            if name == "shape_hardening":
                assert a["cases"][name]["faults"] == 0 and b["cases"][name]["faults"] == 2
                assert a["cases"][name]["accepted"] == b["cases"][name]["accepted"]
                assert a["cases"][name]["returned"] == b["cases"][name]["returned"]
            else:
                for key in ("accepted", "returned", "physical", "certificates", "faults", "trace"):
                    assert a["cases"][name][key] == b["cases"][name][key], (name, key)
        assert a["metrics"].keys() == b["metrics"].keys()
        for label, model in (("baseline", a), ("combined", b)):
            metrics = model["metrics"]
            assert metrics["raw_single"]["first_physical_latency"] == 2
            assert metrics["prechecked_single"]["first_physical_latency"] == (3 if label == "baseline" else 2)
            for name in ("raw_stream", "prechecked_stream", "alternating_stream"):
                row = metrics[name]
                assert row["acceptance_span"] == row["physical_span"] == row["count"] == 128
            for name in ("congested_raw", "congested_alternating"):
                assert metrics[name]["full_release_events"] > 0 and metrics[name]["first_release_resume_gap"] == 1
        assert frozen == {str(p.relative_to(common.ROOT)): sha(p) for p in sources}, "source drift"
        assert sha(gsim) == state["gsimSha256"], "GSIM drift"
        state["status"] = "PASS_COMBINED_CHECKED_DATA_FLOW_COMPONENTS"
        state["limits"] = ["CPU results belong to the separate actual-tile comparison",
                           "No arbitrary in-flight authorization mutation",
                           "No timing, area, 300MHz or DDR-bandwidth claim"]
        save()
        print(state["status"])
    except Exception as error:
        state["status"] = "FAIL"
        state["error"] = str(error)
        save()
        raise


if __name__ == "__main__":
    main()
