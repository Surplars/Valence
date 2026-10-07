#!/usr/bin/env python3
"""One affected timing batch: independent unit oracles + bounded real CPUs.

No full GSIM regression, long Linux, whole-board multi-clock simulation or CAD.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import run as common
from control_stage import core_payloads, negative, reference
import throughput_perf as perf


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--resume-units", type=Path,
                    help="failed runner receipt; only unchanged isolated units may be replayed")
    a = ap.parse_args()
    if a.resume_units:
        a.resume_units = a.resume_units.resolve()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", a.tag):
        ap.error("Unsafe tag")
    out = common.BUILD / ("rv64gc-path-batch-" + a.tag)
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
                   limits=["Affected bounded models, not full GSIM/Linux/ISA certification.",
                           "No managed peripheral multi-clock/SDF/FPGA timing proof."])
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}
    try:
        prior = None
        if a.resume_units:
            prior = json.loads(a.resume_units.read_text())
            changed = {name for name, value in prior["source_sha256"].items() if before.get(name) != value}
            allowed = {str(Path(__file__).relative_to(common.ROOT)), "src/main/scala/core/ooo/RegisteredFetchPacket.scala"}
            if (prior["status"] != "FAILED" or set(before) != set(prior["source_sha256"]) or
                    not changed <= allowed or prior.get("failure") != "independent oracle failed to reject injected corruption"):
                raise RuntimeError("Not a runner/fetch-only repair; isolated model reuse refused")
            receipt["reused_units_receipt_sha256"] = sha(a.resume_units)
            receipt["reused_units_changed_files"] = sorted(changed)
            receipt["reused_models"] = {}
        gsim, cxx = common.setup(False)
        def reject(binary, arguments, message, unused_log):
            log = out / (binary.parent.name + "-negative.log")
            result = subprocess.run([str(binary), *map(str, arguments), "--inject-mismatch"], env=env,
                                    capture_output=True, text=True, timeout=120)
            log.write_text(result.stdout + result.stderr)
            # Some independent C++ TL drivers deliberately throw without a
            # main-level catch (SIGABRT), others catch and exit(1). Demand the
            # exact intended diagnostic, not merely any nonzero exit.
            if result.returncode == 0 or message not in result.stdout + result.stderr:
                raise RuntimeError("Independent negative control did not reject the intended mismatch")
            print("Negative oracle: PASS", message, "exit=" + str(result.returncode), flush=True)
        def unit(name, main, top, harness, parameters=(), defines=None, runtime=()):
            # These isolated tops do not instantiate RegisteredFetchPacket.
            # Do not reuse a fetch/core/board top across the extra cursor edit.
            if prior and name in ("interval", "fp-state", "fp-producers", "crossbar-legacy") and name in prior["checks"]:
                model = a.resume_units.parent / name
                if (model / "test.log").read_text().strip() != prior["checks"][name]:
                    raise RuntimeError("Previous unit log changed: " + name)
                replay = out / (name + "-replay.log")
                common.run([model / "run", *runtime], env=env, log=replay, timeout=180)
                if replay.read_text().strip() != prior["checks"][name]:
                    raise RuntimeError("Unchanged isolated unit replay differs: " + name)
                receipt["checks"][name] = replay.read_text().strip()
                receipt["reused_models"][name] = {str(p.relative_to(common.ROOT)): sha(p) for p in model.iterdir()
                                                if p.is_file() and (p.name == "run" or p.suffix in (".fir", ".cpp", ".h"))}
                return model
            model = common.test(gsim, cxx, out.name + "/" + name, main, top, harness,
                                parameters=parameters, defines={} if defines is None else defines,
                                runtime_args=runtime, timeout=180)
            receipt["checks"][name] = (model / "test.log").read_text().strip()
            return model
        model = unit("interval", "ooo.AlignedMemoryDisjointGsimMain", "AlignedMemoryDisjointGsim",
                     "aligned_memory_disjoint.cpp")
        negative(model / "run", (), "independent memory interval mismatch", out / "interval-negative.log")
        model = unit("fp-state", "ooo.FloatingPointStateGsimMain", "FloatingPointStateGsim", "floating_point_state.cpp")
        negative(model / "run", (), "FP oracle mismatch", out / "fp-state-negative.log")
        reference_dir = common.BUILD / "floating-point-full-20261004-nan-cut-r1"
        vectors = reference_dir / "vectors.txt"
        old_fp = json.loads((reference_dir / "receipt.json").read_text())
        if old_fp["status"] != "PASS_FUNCTIONAL_CANDIDATE" or sha(vectors) != old_fp["vector_sha256"]:
            raise RuntimeError("Independent SoftFloat vector evidence mismatch")
        model = unit("fp-producers", "ooo.FloatingPointFullGsimMain", "FloatingPointFullGsim",
                     "floating_point_full.cpp", parameters=("fd",), runtime=(vectors, "fd"))
        negative(model / "run", (vectors, "fd"), "FP full mismatch", out / "fp-producers-negative.log")
        for width, hints in ((2, 32), (4, 8)):
            model = unit(f"fetch-{width}-{hints}", "ooo.RegisteredFetchPacketGsimMain", "RegisteredFetchPacketGsim",
                         "registered_fetch_packet.cpp",
                         parameters=(str(width), "parallel-validation", f"hints{hints}", "split-cursor", "mixed"),
                         defines={"FETCH_WIDTH": width, "COMPRESSED": 1, "HINT_ENTRIES": hints})
            negative(model / "run", (), "fetch packet oracle mismatch", model / "negative.log")
        for raw in (False, True):
            parameters = ("prefix-decode", "raw-replies", "raw-requests") if raw else ()
            model = unit("crossbar-raw" if raw else "crossbar-legacy", "ip.TileLinkCrossbarGsimMain",
                         "TileLinkCrossbarGsim", "tilelink_crossbar.cpp", parameters=parameters)
            reject(model / "run", (), "TileLink crossbar D source, data or owner mismatch", model / "negative.log")
            # Same generated model, second independent driver. Do not emit or
            # generate the crossbar again just to exercise multibeat traffic.
            binary = out / (model.name + "-run-burst")
            common.run([cxx, "-std=c++20", "-O1", "-g", "-fsanitize=address,undefined",
                        "-fno-sanitize-recover=all", "-I" + str(model),
                        *sorted(model.glob("TileLinkCrossbarGsim[0-9]*.cpp")),
                        common.HERE / "harness/tilelink_burst.cpp", "-ldl", "-o", binary],
                       log=out / (model.name + "-burst-compile.log"))
            burst_log = out / (model.name + "-burst.log")
            common.run([binary], env=env, log=burst_log, timeout=120)
            receipt["checks"][model.name + "-burst"] = burst_log.read_text().strip()
        model = unit("router-errors", "ip.TileLinkRouterGsimMain", "TileLinkRouterGsim", "tilelink_router.cpp",
                     parameters=("prefix-decode", "raw-replies"))
        reject(model / "run", (), "TileLink router response data, source or route mismatch", model / "negative.log")
        wrong = subprocess.run([str(model / "run"), "--inject-wrong-owner"], env=env,
                               capture_output=True, text=True, timeout=120)
        (model / "wrong-owner.log").write_text(wrong.stdout + wrong.stderr)
        if wrong.returncode == 0 or "TileLink bank response has no matching source" not in wrong.stdout + wrong.stderr:
            raise RuntimeError("Wrong-bank response was not rejected")
        ref = reference()
        payloads = core_payloads(out)
        model = unit("integer-core", "ooo.ThroughputPerfGsimMain", "IntegerCoreGsim", "core.cpp",
                     parameters=("staged-fetch-feedback",),
                     defines={**perf.DEFINES, "REGISTERED_FETCH_PACKET": 1, "FETCH_HINT_ALIAS_BENCH": 1},
                     runtime=(ref, *payloads, "--throughput-short"))
        receipt["integer_measurements"] = perf.parse_measurements((model / "test.log").read_text(), 13,
            perf.EXPECTED_KEYS | {("throughput_hint_alias_loop", 1)})
        for mode in ("--timing-smoke", "--pipeline-recovery"):
            common.run([model / "run", ref, *payloads, mode], env=env, log=model / (mode[2:] + ".log"), timeout=180)
            receipt["checks"][mode[2:]] = (model / (mode[2:] + ".log")).read_text().strip()
        negative(model / "run", (ref, *payloads), "NEMU register mismatch", model / "negative.log")
        common.run(["python3", common.HERE / "rv64gc_native_short.py", "--tag", a.tag],
                   log=out / "rv64gc-native.log", timeout=1800)
        native = common.BUILD / ("rv64gc-native-" + a.tag) / "receipt.json"
        checked = json.loads(native.read_text())
        if checked["status"] != "PASS_RV64GC_NATIVE_AFFECTED_SHORT":
            raise RuntimeError("RV64GC real CPU/board smoke did not pass")
        receipt.update(status="PASS_RV64GC_PATH_BATCH_AFFECTED_SHORT", native_receipt=str(native),
                       native_receipt_sha256=sha(native), vector_sha256=sha(vectors), reference_sha256=sha(ref))
    except BaseException as error:
        receipt.update(status="FAILED", failure=str(error))
        raise
    finally:
        if before != {str(p.relative_to(common.ROOT)): sha(p) for p in sources}:
            receipt.update(status="FAILED", failure="Source/oracle changed during verification")
        (out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    if receipt["status"] != "PASS_RV64GC_PATH_BATCH_AFFECTED_SHORT":
        raise RuntimeError(receipt["failure"])
    print(receipt["status"], "checks=" + str(len(receipt["checks"])), flush=True)


if __name__ == "__main__":
    main()
