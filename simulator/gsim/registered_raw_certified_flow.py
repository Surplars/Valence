#!/usr/bin/env python3
"""Fresh actual-DTA A/B proof for registered raw results and certified-only flow.

No tool installation, broad regression, CPU, timing or board qualification. Every
model uses the real generated-header syntax gate before model compilation. The
caller owns the one frozen-batch Scala compile; run this only after that gate.
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
import registered_raw_certified_cones as cones

HERE = Path(__file__).resolve().parent
TOP = "RegisteredRawCertifiedFlowGsim"
MAIN = "ooo.RegisteredRawCertifiedFlowGsimMain"
HOST = HERE / "harness/registered_raw_certified_flow.cpp"
PREFIX = "REGISTERED_RAW_CERTIFIED_FLOW"
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


def histograms(log):
    result = {}
    for line in log.splitlines():
        if line.startswith(PREFIX + "_HIST "):
            fields = dict(word.split("=", 1) for word in line.split()[1:])
            histogram = result.setdefault(fields["scenario"], {}).setdefault(fields["kind"], {})
            latency = fields["latency"]
            assert latency not in histogram, line
            histogram[latency] = int(fields["count"])
    assert result, "missing measured latency histograms"
    return result


def poison(binary, target, flag, marker, diagnostics, hardware=False):
    result = subprocess.run([str(binary), flag], capture_output=True, text=True, timeout=90, env=ENV)
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


def compare(a, b):
    assert a["cases"].keys() == b["cases"].keys()
    for name in a["cases"]:
        for key in ("accepted", "returned", "physical", "certificates", "faults", "trace"):
            assert a["cases"][name][key] == b["cases"][name][key], (name, key)
    assert a["metrics"].keys() == b["metrics"].keys()
    for label, model in (("control", a), ("registered", b)):
        registered = label == "registered"
        metrics = model["metrics"]
        for name in ("raw_load_single", "raw_store_single"):
            assert metrics[name]["first_physical_latency"] == (3 if registered else 2), (label, name)
        assert metrics["prechecked_single"]["first_physical_latency"] == 2
        for name in ("raw_load_stream", "raw_store_stream", "prechecked_stream", "alternating_raw_first"):
            row = metrics[name]
            assert row["acceptance_span"] == row["physical_span"] == row["count"] == 128, (label, name)
        # A certified owner can leave one cycle before the following raw owner
        # reaches its new register. Record this real startup gap, not a speedup.
        row = metrics["alternating_certified_first"]
        assert row["acceptance_span"] == row["count"] == 128
        assert row["physical_span"] == 128 + int(registered)
        for name in ("congested_raw", "congested_alternating"):
            assert metrics[name]["full_release_events"] > 0
            assert metrics[name]["first_release_resume_gap"] == 1
        for name, kinds in model["physicalLatencyHistograms"].items():
            assert sum(sum(hist.values()) for hist in kinds.values()) == metrics[name]["count"], (label, name)
        assert model["cases"]["certified_shape"]["faults"] == 2
        assert model["cases"]["cold_walk_access_fault"]["faults"] == 1
        assert model["cases"]["certified_checked_full_spill"]["prechecked_spills"] > 0
        assert model["cases"]["identity_and_bare"]["identity_pass"] == 4
        assert model["cases"]["identity_shape_and_spill"]["identity_pass"] >= 30
        assert model["cases"]["identity_shape_and_spill"]["certificates"] == 0
        hints = model["cases"]["identity_bare_next_line_permission"]
        assert hints["identity_hint_allowed"] == hints["bare_hint_allowed"] == 1
        assert hints["identity_hint_denied"] == hints["bare_hint_denied"] == 2
        if registered:
            assert all(case["hit_pass"] == 0 for case in model["cases"].values())
            assert model["physicalLatencyHistograms"]["prechecked_stream"] == {"prechecked": {"2": 128}}
            assert model["physicalLatencyHistograms"]["alternating_raw_first"]["prechecked"] == {"3": 64}
    return {name: {key: b["metrics"][name][key] - a["metrics"][name][key]
                   for key in ("cycles", "acceptance_span", "physical_span", "first_physical_latency",
                               "first_return_latency", "translated_push", "prechecked_pass", "hit_pass")}
            for name in a["metrics"]}


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
    compiler_path = Path(shutil.which(str(cxx)) or str(cxx)).resolve()
    sources = sorted((common.ROOT / "src/main/scala").rglob("*.scala")) + sorted(
        (common.ROOT / "src/test/scala").rglob("*.scala")) + [
        HOST, HERE / "harness/virtual_load_test_memory.h", HERE / "m2_data_translation/oracle.h",
        Path(__file__), HERE / "registered_raw_certified_cones.py",
        HERE / "test_registered_raw_certified_cones.py", HERE / "run.py", HERE / "config/toolchain.json",
    ]
    frozen = {str(p.relative_to(common.ROOT)): sha(p) for p in sources}
    for source in sources:
        copied = out / "inputs" / source.relative_to(common.ROOT)
        copied.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, copied)
        assert sha(copied) == frozen[str(source.relative_to(common.ROOT))]
    state = {"status": "RUNNING", "sourceSha256": frozen, "compiler": compiler,
             "compilerPath": str(compiler_path), "compilerSha256": sha(compiler_path),
             "gsimSha256": sha(gsim), "models": {}, "negativeControls": [],
             "scope": "fresh actual A1-shaped DTA/16-entry DTLB control and candidate; no CPU, PPA or board qualification",
             "profiles": {"control": "full-r1-m3-checked-flow-store-row-elastic-proof",
                          "registered": "full-r1-m3-checked-flow-store-row-elastic-proof-registered-raw"},
             "delta": {"registeredRawCertifiedFlow": [False, True], "registeredDataTranslation": [False, True],
                       "translationHitFlow": [True, False], "combinedCheckedDataFlow": [True, False]},
             "preserved": {"precheckedDataRequestFlow": True, "identityDataRequestFlow": True, "translatedEntries": 8, "checkedEntries": 2,
                           "orderedResponseOwners": 8, "extraOwnersOrCredits": 0,
                           "preparedHeadStoreOperands": True, "elasticLoadProofSupply": True},
             "policy": "Both profiles enforce complete certified shape/epoch/range/PMP checks. No speedup is required."}

    def save():
        (out / "receipt.json").write_text(json.dumps(state, indent=2) + "\n")

    save()
    try:
        for label, enabled in (("control", 0), ("registered", 1)):
            target = out / label
            target.mkdir()
            result = {"status": "RUNNING", "enabled": enabled}
            state["models"][label] = result
            flags = ["-std=c++20", "-O1", "-g", "-fsanitize=address,undefined",
                     "-fno-sanitize-recover=all", "-I" + str(target),
                     "-DREGISTERED_RAW_CERTIFIED_FLOW=" + str(enabled)]
            result["compileFlags"] = flags
            save()
            common.run(["mill", "-i", "IonSoC.test.runMain", MAIN, target, label], log=target / "elaborate.log")
            fir = target / (TOP + ".fir")
            result["firSha256"] = sha(fir); save()
            # Fail closed on the actual emitted hierarchy before GSIM generation.
            # This graph check cannot be replaced by source grep or toy-fixture results.
            structural = cones.check(fir, candidate=bool(enabled))
            structural_path = target / "structural-cone.json"
            structural_path.write_text(json.dumps(structural, indent=2) + "\n")
            result["structuralCone"] = structural
            result["structuralConeSha256"] = sha(structural_path); save()
            common.run([gsim, "--threads=1", f"--dir={target}", target / (TOP + ".fir")], log=target / "generate.log")
            result["headerSha256"] = sha(target / (TOP + ".h")); save()
            # Never compile a model against a fabricated or stale header API.
            common.run([cxx, *flags, "-fsyntax-only", HOST], log=target / "header-syntax.log")
            result["actualHeaderSyntax"] = "PASS"; save()
            objects = []
            generated = sorted(target.glob(TOP + "[0-9]*.cpp"))
            assert generated
            for source in [*generated, HOST]:
                obj = target / (source.stem + ".o")
                common.run([cxx, *flags, "-c", source, "-o", obj], log=target / (source.stem + "-compile.log"))
                objects.append(obj)
            common.run([cxx, *flags, *objects, "-ldl", "-o", target / "run"], log=target / "link.log")
            result["generatedSha256"] = {p.name: sha(p) for p in generated}
            result["objectSha256"] = {p.name: sha(p) for p in objects}
            result["binarySha256"] = sha(target / "run"); save()
            common.run([target / "run"], env=ENV, timeout=90, log=target / "test.log")
            log = (target / "test.log").read_text()
            assert log.count(f"{PREFIX}_PASS enabled={enabled}") == 1, log
            result.update(status="PASS", logSha256=sha(target / "test.log"),
                          metrics=rows(log, PREFIX + "_METRIC", "scenario"),
                          cases=rows(log, PREFIX + "_CASE", "name"),
                          physicalLatencyHistograms=histograms(log))
            save()
            for flag, marker, diagnostic in (
                ("--inject-pa", "physical PA", "independent physical PA/order mismatch"),
                ("--inject-data", "response data", "independent ordered response data mismatch"),
                ("--inject-fault", "response fault", "independent ordered fault classification mismatch"),
                ("--inject-canonical", "canonical attribution", "independent canonical certificate attribution mismatch"),
            ):
                state["negativeControls"].append({"model": label, **poison(target / "run", target, flag,
                    "INJECT " + PREFIX + " " + marker, [diagnostic])})
                save()
            state["negativeControls"].append({"model": label, **poison(target / "run", target,
                "--force-undrained-flush", "INJECT " + PREFIX + " undrained flush", [
                    "VM/PMP/SFENCE context changes must drain accepted prechecked loads before changing authorization",
                    "VM/PMP/SFENCE changes must drain accepted canonical stores and overlapping adapter work"], hardware=True)})
            save()
        a, b = (state["models"][label] for label in ("control", "registered"))
        state["measuredMetricDelta"] = compare(a, b)
        assert frozen == {str(p.relative_to(common.ROOT)): sha(p) for p in sources}, "source drift"
        assert sha(gsim) == state["gsimSha256"] and sha(compiler_path) == state["compilerSha256"], "tool drift"
        state["status"] = "PASS_REGISTERED_RAW_CERTIFIED_FLOW_COMPONENTS"
        state["limits"] = ["No CPU throughput claim; actual tile comparison is separate",
                           "No arbitrary in-flight authorization mutation",
                           "No timing, area, 300MHz or DDR-bandwidth claim",
                           "Sampled negative controls mutate observations, not RTL"]
        save()
        print(state["status"])
    except Exception as error:
        state["status"] = "FAIL"
        state["error"] = str(error)
        save()
        raise


if __name__ == "__main__":
    main()
