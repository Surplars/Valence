#!/usr/bin/env python3
"""M2 result/permission boundary: independent module contracts and matched real-DTLB A/B supply."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

import run as common

HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def negative(executable, output, flag, diagnostic, marker, hardware=False):
    result = subprocess.run([str(executable), flag], capture_output=True, text=True, timeout=60,
                            env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
    log = result.stdout + result.stderr
    (output / (flag[2:] + ".log")).write_text(log)
    assert (result.returncode != 0 if hardware else result.returncode == 1), (flag, result.returncode, log)
    assert marker in log and diagnostic in log, (flag, result.returncode, log)
    assert "ERROR: AddressSanitizer" not in log and "runtime error:" not in log, log
    # A deliberate contract violation counts only if the exact hardware assertion
    # fired, not when a host timeout or its 'assertion did not fire' fallback exits.
    if hardware:
        assert "undrained context-change assertion did not fire" not in log, log
    return {"flag": flag, "exit": result.returncode, "diagnostic": diagnostic, "marker": marker,
            "hardwareAssertion": hardware, "logSha256": sha(output / (flag[2:] + ".log"))}


def parse_metrics(log):
    rows = {}
    for line in log.splitlines():
        if line.startswith("M2_TRANSLATION_METRIC "):
            row = dict(word.split("=", 1) for word in line.split()[1:])
            name = row.pop("scenario")
            assert name not in rows
            rows[name] = {key: int(value) for key, value in row.items()}
    assert set(rows) == {"warm_single", "warm_stream", "congested_stream"}, rows
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gsim", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    args = parser.parse_args()
    assert re.fullmatch(r"[A-Za-z0-9_-]+", args.tag)
    output = common.BUILD / args.tag
    assert not output.exists(), "fresh evidence directory required"
    gsim = args.gsim.resolve(strict=True)
    cxx, compiler = common.compiler()
    sources = sorted((common.ROOT / "src/main/scala").rglob("*.scala")) + [
        common.ROOT / "src/test/scala/ooo/M2TranslationBufferGsim.scala",
        common.ROOT / "src/test/scala/ooo/M2DataPermissionGsim.scala",
        common.ROOT / "src/test/scala/ooo/M2DataTranslationGsim.scala",
        common.ROOT / "src/test/scala/platform/M2R1ProfileSpec.scala",
        HERE / "m2_data_translation.py", HERE / "run.py", HERE / "harness/virtual_load_test_memory.h",
        *sorted((HERE / "m2_data_translation").glob("*.*")),
    ]
    inputs = {str(path.relative_to(common.ROOT)): sha(path) for path in sources}
    tool_hash = sha(gsim)
    units, negatives, models = {}, [], {}
    for label, main, top, driver, marker in (
        ("buffer", "ooo.M2TranslationBufferGsimMain", "M2TranslationBufferGsim", "buffer.cpp", "M2_TRANSLATION_BUFFER_PASS "),
        ("permission", "ooo.M2DataPermissionGsimMain", "M2DataPermissionGsim", "permission.cpp", "M2_PERMISSION_PASS "),
    ):
        model = common.test(gsim, cxx, f"{args.tag}/{label}", main, top,
                            "../m2_data_translation/" + driver, defines={}, timeout=60)
        log = (model / "test.log").read_text()
        assert log.count(marker) == 1, log
        units[label] = {"log": log.strip(), "firSha256": sha(model / (top + ".fir")),
                        "executableSha256": sha(model / "run")}
        controls = [("--inject-payload", "descriptor mismatch field=request.data",
                     "INJECT M2_TRANSLATION_BUFFER field=request.data bit=37")] if label == "buffer" else [
            ("--inject-permission", "permission fault/PMP/access differs from independent byte oracle", "INJECT M2_PERMISSION fault observation"),
            ("--inject-certificate", "canonical descriptor owner/token/epoch/payload mismatch", "INJECT M2_PERMISSION certificate PA observation"),
        ]
        for flag, diagnostic, witness in controls:
            negatives.append({"model": label, **negative(model / "run", model, flag, diagnostic, witness)})
    for label in ("baseline", "registered"):
        model = common.test(gsim, cxx, f"{args.tag}/{label}", "ooo.M2DataTranslationGsimMain",
                            "M2DataTranslationGsim", "../m2_data_translation/adapter.cpp",
                            parameters=(label,), defines={}, timeout=60)
        log = (model / "test.log").read_text()
        assert log.count("M2_TRANSLATION_ADAPTER_PASS ") == 1, log
        fir = (model / "M2DataTranslationGsim.fir").read_text()
        assert ("module DataTranslationResultBuffer" in fir) == (label == "registered")
        assert ("module DataPhysicalPermissionEvaluator" in fir) == (label == "registered")
        models[label] = {"metrics": parse_metrics(log), "log": log.strip(),
                         "firSha256": sha(model / "M2DataTranslationGsim.fir"),
                         "executableSha256": sha(model / "run")}
        # Same independent oracle sensitivity in A/B. Illegal undrained flush is
        # negative coverage, not a claim of support for arbitrary in-flight CSR changes.
        for flag, diagnostic, witness in (
            ("--inject-pa", "independent PTE/write-PMP/byte-range certificate mismatch", "INJECT M2_ADAPTER certificate observation"),
            ("--inject-permission", "ordered real response lost page/access/late physical error", "INJECT M2_ADAPTER permission observation"),
            ("--force-undrained-flush", "VM/PMP/SFENCE changes must drain accepted canonical stores and overlapping adapter work", "INJECT M2_ADAPTER undrained flush"),
        ):
            negatives.append({"model": label, **negative(model / "run", model, flag, diagnostic, witness,
                                                         hardware=flag == "--force-undrained-flush")})
    a, b = models["baseline"]["metrics"], models["registered"]["metrics"]
    comparison = {}
    for name in ("warm_single", "warm_stream", "congested_stream"):
        control, candidate = a[name], b[name]
        assert control["count"] == candidate["count"] == control["demand_hits"] == candidate["demand_hits"]
        if name != "congested_stream":
            for row in (control, candidate):
                assert row["acceptance_span"] == row["physical_span"] == row["count"]
            assert candidate["first_physical_latency"] == control["first_physical_latency"] + 1
            assert candidate["first_return_latency"] == control["first_return_latency"] + 1
            assert candidate["cycles"] == control["cycles"] + 1
            assert control["hit_pass"] == control["count"] and control["translated_push"] == 0
        else:
            assert control["full_release_events"] > 0 and candidate["full_release_events"] > 0
            assert control["first_release_resume_gap"] == candidate["first_release_resume_gap"] == 1
        assert candidate["hit_pass"] == 0 and candidate["translated_push"] == candidate["count"]
        assert candidate["translated_pop"] == candidate["count"]
        comparison[name] = {key: candidate[key] - control[key] for key in control}
    assert inputs == {str(path.relative_to(common.ROOT)): sha(path) for path in sources}, "source drift"
    assert tool_hash == sha(gsim), "tool drift"
    receipt = {
        "status": "PASS_M2_REGISTERED_TRANSLATION_CONTRACT_AND_MATCHED_DTLB_SUPPLY",
        "sourceSha256": inputs, "gsimSha256": tool_hash, "compiler": compiler,
        "units": units, "models": models, "candidateMinusControl": comparison, "negativeControls": negatives,
        "serviceLaw": {"idealPhysicalReady": True, "idealResponseReady": True, "physicalResponseLatency": 1,
                       "streamRequests": 256, "congestedPhysicalBlockCycles": 64, "congestedResponseBlockCycles": 96,
                       "mixedPhysicalReady": "cycle modulo 7 != 5", "mixedResponseLatency": 9,
                       "pageTableLatency": 2, "pageTableReady": "ideal or cycle modulo 5 != 3"},
        "contract": {"virtualIngressEntries": 2, "translationResults": 8, "checkedRequests": 2,
                     "orderedResponseOwners": 8, "dtlbEntries": 16, "warmDemandHitExtraLatency": 1,
                     "sustainedII": 1, "fullRelease": "one no-borrow edge, next-cycle admission",
                     "flush": "accepted owners drain before VM/PMP/SFENCE changes; never erase descriptors"},
        "limits": ["No extra cache MSHR, TileLink source, DDR credit, or external outstanding claim",
                   "Only formerly bypassable demand hits pay the extra result edge; prechecked loads do not measure it",
                   "Actual CPU four-control VM/retirement comparison is separate, not implied by module II=1",
                   "No new timing, Fmax, area, STA, 300MHz, board, or DDR bandwidth qualification"],
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print("PASS M2 registered translation contracts and matched real-DTLB supply")


if __name__ == "__main__":
    main()
