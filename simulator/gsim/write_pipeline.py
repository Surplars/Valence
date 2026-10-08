#!/usr/bin/env python3
"""Independent fixed-capacity AW/W overlap, ownership, and sustained GSIM proof.
No broad regression, hardware access, synthesis, or tool downloads.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import run as common

TOP = "TileLinkAxi4Bridge"
HARNESSES = ["tilelink_axi4_write_pipeline.cpp", "tilelink_axi4_mixed.cpp", "tilelink_axi4_mixed_channels.cpp", "tilelink_axi4_unordered.cpp"]

def hashes():
    paths = sorted((common.ROOT / "src/main/scala").rglob("*.scala")) + [common.ROOT / "src/test/scala/ooo/TileLinkAxi4OutstandingGsimMain.scala"] + [common.HERE / "harness" / n for n in HARNESSES] + [Path(__file__)]
    return {str(p.relative_to(common.ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}

def run_result(exe, args, log, expected=None):
    r = subprocess.run([str(exe), *args], capture_output=True, text=True, timeout=180,
                       env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
    output = r.stdout + r.stderr
    log.write_text(output)
    if expected:
        assert r.returncode != 0 and expected in output, (log, r.returncode, output[-2500:])
    else:
        assert r.returncode == 0, (log, r.returncode, output[-4000:])
    return {"returncode": r.returncode, "log": str(log), "output": output}

def parse_metrics(text):
    return [dict(re.findall(r"([a-z_]+)=([0-9.]+)", line)) for line in text.splitlines() if line.startswith("WRITE_PIPELINE_PASS")]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--baseline-control", action="store_true")
    ap.add_argument("--selected-only", action="store_true")
    ap.add_argument("--baseline", type=Path)
    args = ap.parse_args()
    out = common.BUILD / ("write-pipeline-" + args.tag)
    out.mkdir(parents=True, exist_ok=False)
    report = {"status": "RUNNING", "source_sha256": hashes(), "cases": {},
              "scope": "bounded GSIM synthetic bus traffic, unchanged transaction capacity; no FPGA timing/resource or CPU IPC claim"}
    try:
        cxx, version = common.compiler()
        gsim = common.SOURCE / "build/gsim/gsim"
        assert gsim.is_file(), "pinned installed GSIM binary missing"
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=common.SOURCE, text=True).strip()
        assert revision == common.LOCK["revision"]
        report["toolchain"] = {"gsim_revision": revision, "cxx": version}
        matrix = [(4, 2, 1)] if args.selected_only else [(4, 2, 1), (4, 2, 0), (4, 1, 1), (8, 4, 1)]
        for slots, writes, unordered in matrix:
            name = f"s{slots}-w{writes}-u{unordered}"
            d = out / name; d.mkdir()
            params = [slots, 16, 3, writes, unordered, 5]
            common.run(["mill", "-i", "IonSoC.test.runMain", "ooo.TileLinkAxi4OutstandingGsimMain", d, *params], log=d / "elaborate.log")
            common.run([gsim, "--threads=1", f"--dir={d}", d / (TOP + ".fir")], log=d / "generate.log")
            objects = []
            flags = ["-std=c++20", "-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-I" + str(d)]
            for cpp in sorted(d.glob(TOP + "[0-9]*.cpp")):
                obj = cpp.with_suffix(".o"); objects.append(obj)
                common.run([cxx, *flags, "-c", cpp, "-o", obj], log=cpp.with_suffix(".compile.log"))
            def compile_driver(harness, defines=None):
                exe = d / harness.removesuffix(".cpp")
                common.run([cxx, *flags, *[f"-D{k}={v}" for k,v in (defines or {}).items()],
                    common.HERE / "harness" / harness, *objects, "-ldl", "-o", exe], log=exe.with_suffix(".compile.log"))
                return exe
            defs = {"AXI_SLOTS": slots, "WRITE_CREDITS": writes}
            if unordered: defs["UNORDERED_TL"] = 1
            channels = compile_driver("tilelink_axi4_mixed_channels.cpp", defs)
            entry = {"parameters": params, "channels": run_result(channels, [], d / "channels.log"), "negative": {}}
            entry["negative"]["write-data"] = run_result(channels, ["--inject-data"], d / "negative-write.log", "W independent payload/strobe/last mismatch")
            if writes >= 2:
                mixedDefs = {"REQUIRE_MIXED": 1}
                if unordered: mixedDefs["UNORDERED_TL"] = 1
                mixed = compile_driver("tilelink_axi4_unordered.cpp" if unordered else "tilelink_axi4_mixed.cpp", mixedDefs)
                entry["mixed"] = run_result(mixed, [], d / "mixed.log")
                for flag, anchor in [("--inject-data", "independent TL data oracle mismatch"), ("--bad-id", "AXI R response has no live read owner"),
                    ("--bad-bid", "AXI B response has no live write owner"), ("--bad-last", "AXI read ID or RLAST mismatch")]:
                    entry["negative"][flag] = run_result(mixed, [flag], d / (flag[2:] + ".log"), anchor)
            if (slots, writes, unordered) == (4, 2, 1):
                pipeline = compile_driver("tilelink_axi4_write_pipeline.cpp", defs)
                entry["pipeline"] = run_result(pipeline, [], d / "pipeline.log")
                entry["metrics"] = parse_metrics(entry["pipeline"]["output"])
                entry["negative"]["pairing-data"] = run_result(pipeline, ["--inject-w"], d / "negative-pairing.log", "pipeline independent W pairing/data mismatch")
                entry["aw-lead"] = run_result(pipeline, ["--require-aw-lead"], d / "aw-lead.log",
                    "independent AW pipeline did not advance ahead of W" if args.baseline_control else None)
                entry["denied-tail"] = run_result(pipeline, ["--denied-tail"], d / "denied-tail.log",
                    "write FIFO lost its live owner" if args.baseline_control else None)
                if not args.baseline_control: entry["reset-skew"] = run_result(pipeline, ["--reset-skew"], d / "reset-skew.log")
            entry["status"] = "PASS"; report["cases"][name] = entry
            assert hashes() == report["source_sha256"], "source drift during test"
            (out / "progress.json").write_text(json.dumps(report, indent=2) + "\n")
            print("CASE_PASS", name, flush=True)
        report["status"] = "PASS"
        if args.baseline:
            old = json.loads((args.baseline / "receipt.json").read_text())
            assert old["status"] == "PASS"
            differences = sorted(k for k in old["source_sha256"].keys() | report["source_sha256"].keys()
                                 if old["source_sha256"].get(k) != report["source_sha256"].get(k))
            assert differences == ["src/main/scala/core/ooo/TileLinkAxi4OutstandingBridge.scala"], differences
            prior = old["cases"]["s4-w2-u1"]["metrics"]
            after = report["cases"]["s4-w2-u1"]["metrics"]
            assert len(prior) == len(after)
            comparisons = []
            for a,b in zip(prior, after):
                assert all(a[k] == b[k] for k in ("beats", "prepare", "stress", "mixed", "transactions", "wbeats", "rbeats"))
                comparisons.append({"workload": {k:b[k] for k in ("beats", "prepare", "stress", "mixed")},
                    "baseline": a, "candidate": b, "cycle_reduction_pct": 100 * (1 - int(b["cycles"]) / int(a["cycles"]))})
            report["comparison"] = {"changed_sources": differences, "metrics": comparisons}
            (out / "comparison.json").write_text(json.dumps(report["comparison"], indent=2) + "\n")
    except BaseException as e:
        report["status"] = "FAIL"; report["error"] = str(e); raise
    finally:
        (out / "receipt.json").write_text(json.dumps(report, indent=2) + "\n")

if __name__ == "__main__": main()
