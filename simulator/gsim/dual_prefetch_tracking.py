#!/usr/bin/env python3
"""Serial, source-bound real cache/home gate for separate resident PF tokens."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
TOP = "CoherentCacheHomeGsim"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inputs():
    names = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    return {name: sha(ROOT / name) for name in names if name and (ROOT / name).is_file()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-grant", action="store_true", help="caller holds the authorized serial build slot")
    parser.add_argument("--modes", choices=("both", "off", "on"), default="both")
    parser.add_argument("--store-lru", type=int, choices=(0, 1), default=0)
    parser.add_argument("--lifetime", type=int, choices=(1, 16), default=1)
    parser.add_argument("--ways", type=int, choices=(1, 2), default=2)
    parser.add_argument("--skip-config", action="store_true", help="reuse separately recorded unchanged config gate")
    args = parser.parse_args()
    if not args.run_grant:
        parser.error("an explicit serial build/run grant is required")
    assert not subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT), "freeze and commit source first"
    output = args.output.resolve()
    assert not output.exists(), "fresh output directory required"
    tools = Path(os.environ["VALENCE_CLOUD_ENV"])
    gsim = tools / "gsim-src/build/gsim/gsim"
    cxx = tools / "sysroot/usr/bin/clang++-19"
    mill = Path(shutil.which("mill"))
    assert all(p.is_file() for p in (gsim, cxx, mill)), "activate the installed pinned tools"
    output.mkdir(parents=True)
    receipt = {
        "schema": "dual-prefetch-tracking-component-gate-v1", "status": "RUNNING",
        "source_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "inputs": inputs(), "tools": {str(p): sha(p) for p in (gsim, cxx.resolve(), mill)},
        "modes": args.modes, "store_lru": args.store_lru, "lifetime": args.lifetime, "ways": args.ways,
        "gsim_cpp_max_size_KB": 1024, "compiler_jobs": 1, "commands": [], "models": {},
        "independent_demand_admission": True, "executing_cpu": False, "physical_qualification": False,
        "component_transport": "existing Mixed home/AXI; full CPU line-read transport is a separate gate",
    }

    def save():
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")

    def step(name, command, expected=0, anchor=None, timeout=600):
        assert inputs() == receipt["inputs"], "frozen source drift"
        assert all(sha(path) == digest for path, digest in receipt["tools"].items()), "tool drift"
        log = output / (name + ".log")
        command = list(map(str, command))
        print("+ " + " ".join(command), flush=True)
        start = time.monotonic()
        with log.open("x") as stream:
            result = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                                    timeout=timeout, env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0",
                                                          "PYTHONDONTWRITEBYTECODE": "1"})
        text = log.read_text()
        receipt["commands"].append({"name": name, "argv": command, "exit": result.returncode,
                                    "expected_exit": expected, "seconds": time.monotonic() - start,
                                    "log_sha256": sha(log)})
        save()
        assert result.returncode == expected, f"{name} failed: {text[-3000:]}"
        assert not re.search(r"ERROR: AddressSanitizer|UndefinedBehaviorSanitizer|runtime error:|LeakSanitizer", text), name
        if anchor:
            assert anchor in text, f"{name} lacks {anchor}"
        return text

    try:
        save()
        if not args.skip_config:
            step("configuration", [mill, "-i", "-j", "1", "IonSoC.test.testOnly",
                                   "ooo.SplitPrefetchTrackingConfigSpec"], anchor="All tests passed")
        for enabled in ((0, 1) if args.modes == "both" else (int(args.modes == "on"),)):
            label = "on" if enabled else "off"
            model = output / label
            model.mkdir()
            step(label + "-emit", [mill, "-i", "-j", "1", "IonSoC.test.runMain",
                                  "ooo.DualPrefetchTrackingGsimMain", model, enabled,
                                  args.store_lru, args.lifetime, args.ways])
            actual = json.loads((model / "actual-parameters.json").read_text())
            cache = actual["cacheConcurrency"]
            assert cache["splitPrefetchTracking"] == bool(enabled) and cache["independentDemandAdmission"]
            assert cache["prefetchCandidateCycles"] == args.lifetime and cache["storePrefetchLruVictim"] == bool(args.store_lru)
            assert actual["cacheMshrs"] == actual["cacheResponses"] == actual["cacheWritebacks"] == 2
            assert actual["cacheWays"] == args.ways and actual["cacheLines"] == 512
            step(label + "-generate", [gsim, "--threads=1", "--cpp-max-size-KB=1024",
                                      "--dir=" + str(model), model / (TOP + ".fir")])
            units = sorted(model.glob(TOP + "[0-9]*.cpp"))
            assert units, "official GSIM generated no translation units"
            flags = ["-std=c++20", "-O1", "-g", "-gz=zlib", "-fsanitize=address,undefined",
                     "-fno-sanitize-recover=all", "-I" + str(model),
                     "-I" + str(ROOT / "simulator/gsim/harness"),
                     "-DSPLIT_PREFETCH_TRACKING=" + str(enabled), "-DSTORE_PF_LRU_ON=" + str(args.store_lru),
                     "-DPF_CANDIDATE_CYCLES=" + str(args.lifetime), "-DCACHE_WAYS=" + str(args.ways),
                     "-DREAD_MSHRS=2", "-DCACHE_LINES=512", "-DRESPONSE_ENTRIES=2", "-DAXI_SLOTS=4"]
            objects = []
            for i, unit in enumerate(units):
                obj = unit.with_suffix(".o")
                step(label + "-compile-" + str(i), [cxx, *flags, "-c", unit, "-o", obj])
                objects.append(obj)
            binary = model / "run"
            step(label + "-link", [cxx, *flags, ROOT / "simulator/gsim/harness/dual_prefetch_tracking.cpp",
                                  *objects, "-ldl", "-o", binary])
            runtime = ["--one-way"] if args.ways == 1 else []
            step(label + "-positive", [binary, *runtime, "--images=" + str(model / "images")],
                 anchor="DUAL_PREFETCH_TRACKING_PASS", timeout=180)
            negatives = [("mismatch", "CPU independent byte oracle mismatch"),
                         ("token-address", "resident token full PA/index differs"),
                         ("token-origin", "useful event changed immutable refill origin")]
            if args.ways == 1:
                negatives = negatives[:2]
            elif enabled:
                negatives.append(("victim", "candidate selected protected or wrong full-PA victim"))
            for mutation, message in negatives:
                text = step(label + "-negative-" + mutation, [binary, *runtime, "--inject-" + mutation],
                            expected=1, anchor=message, timeout=180)
                if mutation != "mismatch":
                    assert "DUAL_PREFETCH_TRACKING_MUTATION_TRIGGER " + mutation in text
            receipt["models"][label] = {"actual_parameters": actual, "split_units": len(units),
                "artifacts": {str(p.relative_to(model)): sha(p) for p in model.rglob("*") if p.is_file()}}
            save()
        assert inputs() == receipt["inputs"], "final frozen source drift"
        receipt["status"] = "PASS_COMPONENT_ONLY"
    except BaseException as error:
        receipt["status"] = "FAIL"
        receipt["error"] = str(error)
        raise
    finally:
        save()
    print(receipt["status"], output / "receipt.json", flush=True)


if __name__ == "__main__":
    main()
