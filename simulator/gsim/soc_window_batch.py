#!/usr/bin/env python3
"""One affected batch: registered fetch window, FP cuts, store preparation, line writer."""
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
    ap.add_argument("--resume-units", type=Path,
                    help="Only resume the known bare-fixture configuration rejection; re-elaborate/compare unit FIR.")
    a = ap.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", a.tag):
        ap.error("Unsafe tag")
    out = common.BUILD / ("soc-window-batch-" + a.tag)
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
                   limits=["Affected bounded checks only; not full GSIM/Linux/ISA certification.",
                           "No physical CDC/SDF/FPGA timing or bit release proof."])
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}
    try:
        reusable = None
        if a.resume_units:
            reusable = a.resume_units.resolve()
            if not reusable.is_relative_to(common.BUILD.resolve()):
                raise RuntimeError("Reuse must stay inside GSIM evidence directory")
            old = json.loads((reusable / "receipt.json").read_text())
            if old["status"] != "FAILED" or old.get("failure") != (
                    "command failed (1); full log: " + str(reusable / "integer-core/elaborate.log")):
                raise RuntimeError("Only the known fixture elaboration failure permits unit reuse")
            if "registered cache window requires compressed packets and the fetch reservoir" not in (
                    reusable / "integer-core/elaborate.log").read_text():
                raise RuntimeError("Unexpected old failure; no reuse")
            changes = {name for name in set(before) | set(old["source_sha256"])
                       if before.get(name) != old["source_sha256"].get(name)}
            fixture = "src/test/scala/ooo/ThroughputPerfGsim.scala"
            if changes - {fixture, str(Path(__file__).relative_to(common.ROOT))}:
                raise RuntimeError("Hardware, oracle or other fixture changed; no isolated reuse")
            restored = (common.ROOT / fixture).read_bytes().replace(
                b"capturedFetchPermission = false, registeredFetchWindow = false)",
                b"capturedFetchPermission = false)")
            if hashlib.sha256(restored).hexdigest() != old["source_sha256"][fixture]:
                raise RuntimeError("Fixture change must be exactly the unused window-option removal")
            receipt["reuse"] = dict(origin=str(reusable), changes=sorted(changes),
                                   original_receipt_sha256=sha(reusable / "receipt.json"),
                                   contract="Unchanged isolated sources + exact fresh FIR + rerun independent oracles")
        common.run(["mill", "-i", "IonSoC.test.compile"], log=out / "compile.log", timeout=300)
        gsim, cxx = common.setup(False)

        def unit(name, emitter, top, harness, negative_message, parameters=(), runtime=(), defines=None):
            logs = out / name
            if reusable:
                if name not in old["checks"]:
                    raise RuntimeError("Old isolated model never passed: " + name)
                model = reusable / name
                common.run(["mill", "-i", "IonSoC.test.runMain", emitter, logs, *parameters],
                           log=out / (name + "-elaborate-recheck.log"), timeout=120)
                if sha(logs / (top + ".fir")) != sha(model / (top + ".fir")):
                    raise RuntimeError("Current isolated FIR differs; cannot reuse: " + name)
                common.run([model / "run", *runtime], env=env, log=logs / "test.log", timeout=180)
            else:
                model = common.test(gsim, cxx, out.name + "/" + name, emitter, top, harness,
                                    parameters=parameters, runtime_args=runtime, defines=defines or {}, timeout=180)
            artifacts = {str(p): sha(p) for p in model.iterdir()
                         if p.is_file() and (p.name == "run" or p.suffix in (".fir", ".cpp", ".h"))}
            receipt.setdefault("model_sha256", {})[name] = artifacts
            receipt["checks"][name] = (logs / "test.log").read_text().strip()
            if negative_message:
                negative = subprocess.run([str(model / "run"), *map(str, runtime), "--inject-mismatch"],
                                          env=env, capture_output=True, text=True, timeout=180)
                (logs / "negative.log").write_text(negative.stdout + negative.stderr)
                if negative.returncode != 1 or negative_message not in negative.stdout + negative.stderr:
                    raise RuntimeError("Independent negative control not rejected: " + name)
                receipt["checks"][name + "-negative"] = negative_message
            if artifacts != {str(p): sha(p) for p in model.iterdir()
                             if p.is_file() and (p.name == "run" or p.suffix in (".fir", ".cpp", ".h"))}:
                raise RuntimeError("Reused/generated model changed while running: " + name)
            (out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
            return model

        for capacity in (3, 5):
            unit(f"fetch-window-{capacity}", "ooo.RegisteredFetchWindowGsimMain", "RegisteredFetchWindowGsim",
                 "registered_fetch_window.cpp", "fetch window independent oracle mismatch",
                 parameters=(str(capacity),), defines={"WINDOW_CAPACITY": capacity})
        unit("fp-state", "ooo.FloatingPointStateGsimMain", "FloatingPointStateGsim", "floating_point_state.cpp",
             "FP oracle mismatch")
        vector_dir = common.BUILD / "floating-point-full-20261004-nan-cut-r1"
        vector_receipt = json.loads((vector_dir / "receipt.json").read_text())
        vectors = vector_dir / "vectors.txt"
        if vector_receipt["status"] != "PASS_FUNCTIONAL_CANDIDATE" or sha(vectors) != vector_receipt["vector_sha256"]:
            raise RuntimeError("Independent SoftFloat evidence mismatch")
        receipt["softfloat_vector_sha256"] = sha(vectors)
        for profile in ("fd", "f", "small"):
            unit("fp-numerical-" + profile, "ooo.FloatingPointFullGsimMain", "FloatingPointFullGsim",
                 "floating_point_full.cpp", "FP full mismatch", parameters=(profile,), runtime=(vectors, profile))
        unit("line-writer", "ooo.TileLinkLineWriteGsimMain", "TileLinkLineWriteGsim", "line_write.cpp",
             "line write oracle mismatch")
        # Read/write fabric integration keeps its independent memory contents oracle.
        unit("line-read-write", "ooo.TileLinkLineReadWriteRamGsimMain", "TileLinkLineReadWriteRamGsim",
             "line_read_write_ram.cpp", None)
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
        if json.loads(native.read_text())["status"] != "PASS_RV64GC_NATIVE_AFFECTED_SHORT":
            raise RuntimeError("Real RV64GC CPU/current board proof failed")
        receipt["native_receipt"] = str(native)
        receipt["native_receipt_sha256"] = sha(native)
        if before != {str(p.relative_to(common.ROOT)): sha(p) for p in sources}:
            raise RuntimeError("Source/oracle changed during affected batch")
        receipt["status"] = "PASS_SOC_WINDOW_BATCH_AFFECTED_SHORT"
    except Exception as error:
        receipt["status"] = "FAILED"
        receipt["failure"] = str(error)
        raise
    finally:
        (out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(receipt["status"], json.dumps(receipt["checks"], ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
