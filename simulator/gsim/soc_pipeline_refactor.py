#!/usr/bin/env python3
"""Affected acceptance for the SoC pipeline refactor; no full GSIM/Linux/CAD."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import run as common
from control_stage import core_payloads, reference
import throughput_perf as perf


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tag", required=True)
    a = ap.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", a.tag):
        ap.error("Unsafe tag")
    out = common.BUILD / ("soc-pipeline-refactor-" + a.tag)
    out.mkdir(parents=True, exist_ok=False)
    sources = [p for base in ("src/main/scala", "src/test/scala", "third_party/berkeley-hardfloat/src/main/scala")
               for p in sorted((common.ROOT / base).rglob("*.scala"))]
    sources += [p for p in sorted((common.HERE / "harness").iterdir()) if p.is_file()]
    sources += [common.ROOT / "build.mill", Path(__file__), common.HERE / "run.py",
                common.HERE / "control_stage.py", common.HERE / "throughput_perf.py",
                common.HERE / "rv64gc_native_short.py", common.HERE / "rv64gc_board.py"]
    before = {str(p.relative_to(common.ROOT)): sha(p) for p in sources}
    receipt = dict(status="RUNNING", source_sha256=before, checks={}, issue_width=2,
                   isa="rv64gc", cpu_hz=100000000, uart_baud=460800,
                   limits=["Affected bounded checks, not full GSIM/Linux/ISA certification.",
                           "No physical multi-clock/CDC/SDF/FPGA timing or bit release proof."])
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}
    try:
        gsim, cxx = common.setup(False)
        def unit(name, main, top, harness, message, parameters=(), defines=None):
            model = common.test(gsim, cxx, out.name + "/" + name, main, top, harness,
                                parameters=parameters, defines=defines or {}, timeout=180)
            receipt["checks"][name] = (model / "test.log").read_text().strip()
            negative = subprocess.run([str(model / "run"), "--inject-mismatch"], env=env,
                                      capture_output=True, text=True, timeout=120)
            (model / "negative.log").write_text(negative.stdout + negative.stderr)
            if negative.returncode != 1 or message not in negative.stdout + negative.stderr:
                raise RuntimeError("Independent negative control not rejected: " + name)
            receipt["checks"][name + "-negative"] = message
            (out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
            return model
        unit("cursor-neighbor", "ooo.CursorNeighborGsimMain", "CursorNeighborGsim", "cursor_neighbor.cpp",
             "cursor neighbor independent oracle mismatch")
        unit("natural-pmp", "ooo.PmpCheckerGsimMain", "PmpCheckerGsim", "pmp_checker.cpp",
             "PMP oracle mismatch", parameters=("natural-aligned",), defines={"ALIGNED_WORD_PMP": 1})
        unit("fp-memory", "ooo.FpMemoryPipelineGsimMain", "FpMemoryPipelineGsim", "fp_memory_pipeline.cpp",
             "FP memory boundary oracle mismatch")
        unit("translation-context", "ooo.TranslationContextGsimMain", "TranslationContextGsim",
             "translation_context.cpp", "VM context independent oracle mismatch")
        for width, hints in ((2, 32), (4, 8)):
            unit(f"fetch-{width}-{hints}", "ooo.RegisteredFetchPacketGsimMain", "RegisteredFetchPacketGsim",
                 "registered_fetch_packet.cpp", "fetch packet oracle mismatch",
                 parameters=(str(width), "parallel-validation", f"hints{hints}", "split-cursor", "mixed"),
                 defines={"FETCH_WIDTH": width, "COMPRESSED": 1, "HINT_ENTRIES": hints})
        ref = reference()
        payloads = core_payloads(out)
        model = common.test(gsim, cxx, out.name + "/integer-core", "ooo.ThroughputPerfGsimMain",
                            "IntegerCoreGsim", "core.cpp", parameters=("staged-fetch-feedback",),
                            defines={**perf.DEFINES, "REGISTERED_FETCH_PACKET": 1, "FETCH_HINT_ALIAS_BENCH": 1},
                            runtime_args=(ref, *payloads, "--throughput-short"), timeout=180)
        receipt["checks"]["integer-core"] = (model / "test.log").read_text().strip()
        receipt["integer_measurements"] = perf.parse_measurements((model / "test.log").read_text(), 13,
            perf.EXPECTED_KEYS | {("throughput_hint_alias_loop", 1)})
        for mode in ("--timing-smoke", "--pipeline-recovery"):
            common.run([model / "run", ref, *payloads, mode], env=env, log=model / (mode[2:] + ".log"), timeout=180)
            receipt["checks"][mode[2:]] = (model / (mode[2:] + ".log")).read_text().strip()
        negative = subprocess.run([str(model / "run"), str(ref), *map(str, payloads), "--inject-mismatch"],
                                  env=env, capture_output=True, text=True, timeout=180)
        (model / "negative.log").write_text(negative.stdout + negative.stderr)
        if negative.returncode != 1 or "NEMU register mismatch" not in negative.stdout + negative.stderr:
            raise RuntimeError("Independent CPU negative control not rejected")
        common.run(["python3", common.HERE / "rv64gc_native_short.py", "--tag", a.tag],
                   log=out / "native.log", timeout=1800)
        native = common.BUILD / ("rv64gc-native-" + a.tag) / "receipt.json"
        proof = json.loads(native.read_text())
        if proof["status"] != "PASS_RV64GC_NATIVE_AFFECTED_SHORT":
            raise RuntimeError("Real RV64GC CPU/current board proof failed")
        receipt["native_receipt"] = str(native)
        receipt["native_receipt_sha256"] = sha(native)
        if before != {str(p.relative_to(common.ROOT)): sha(p) for p in sources}:
            raise RuntimeError("Source/oracle changed during affected batch")
        receipt["status"] = "PASS_SOC_PIPELINE_REFACTOR_AFFECTED_SHORT"
    except Exception as error:
        receipt["status"] = "FAILED"
        receipt["failure"] = str(error)
        raise
    finally:
        (out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(receipt["status"], json.dumps(receipt["checks"], ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
