#!/usr/bin/env python3
"""Serial, source-bound real cache/home gate for fresh read retries and protected dirty victims."""
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
    parser.add_argument("--skip-config", action="store_true", help="reuse separately recorded unchanged config gate")
    parser.add_argument("--reuse-off-model", type=Path,
                        help="reuse verified frozen OFF generated sources/objects after a harness-only correction")
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
        "schema": "read-prefetch-dirty-retry-component-gate-v1", "status": "RUNNING",
        "source_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "inputs": inputs(), "tools": {str(p): sha(p) for p in (gsim, cxx.resolve(), mill)},
        "modes": args.modes, "split_tracking": True, "store_lru": 0, "lifetime": 16, "ways": 2,
        "gsim_cpp_max_size_KB": 1024, "compiler_jobs": 1, "commands": [], "models": {},
        "independent_demand_admission": True, "executing_cpu": False, "physical_qualification": False,
        "component_transport": "existing Mixed home/AXI; full CPU line-read transport is a separate gate",
    }

    reuse_off = args.reuse_off_model.resolve() if args.reuse_off_model else None
    if reuse_off:
        previous_receipt = reuse_off.parent / "receipt.json"
        previous = json.loads(previous_receipt.read_text())
        current = inputs()
        allowed_changes = {"simulator/gsim/harness/read_prefetch_dirty_retry.cpp",
                           "simulator/gsim/read_prefetch_dirty_retry.py"}
        assert set(previous["inputs"]) == set(current), "OFF reuse changed tracked file inventory"
        changed = {name for name in current if current[name] != previous["inputs"][name]}
        assert changed <= allowed_changes, "OFF reuse crossed a hardware/config change: " + str(changed)
        assert previous["tools"] == receipt["tools"], "OFF reuse tool identity differs"
        assert all(any(c["name"] == name and c["exit"] == 0 for c in previous["commands"])
                   for name in ("configuration", "off-emit", "off-generate", "off-compile-0", "off-compile-1"))
        receipt["reused_off_model"] = {"path": str(reuse_off), "source_head": previous["source_head"],
            "receipt_path": str(previous_receipt), "receipt_sha256": sha(previous_receipt),
            "changed_host_only_inputs": sorted(changed)}

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
                                   "ooo.ReadPrefetchDirtyRetryConfigSpec"], anchor="All tests passed")
        for enabled in ((0, 1) if args.modes == "both" else (int(args.modes == "on"),)):
            label = "on" if enabled else "off"
            model = output / label
            model.mkdir()
            reused = not enabled and reuse_off is not None
            if reused:
                names = ["actual-parameters.json", TOP + ".fir", TOP + ".h"]
                names += [p.name for p in sorted(reuse_off.glob(TOP + "[0-9]*.cpp"))]
                names += [p.name for p in sorted(reuse_off.glob(TOP + "[0-9]*.o"))]
                assert len(list(reuse_off.glob(TOP + "[0-9]*.cpp"))) == 2
                assert len(list(reuse_off.glob(TOP + "[0-9]*.o"))) == 2
                receipt["reused_off_model"]["artifacts"] = {name: sha(reuse_off / name) for name in names}
                for name in names:
                    (model / name).symlink_to(reuse_off / name)
                save()
            else:
                step(label + "-emit", [mill, "-i", "-j", "1", "IonSoC.test.runMain",
                                      "ooo.ReadPrefetchDirtyRetryGsimMain", model, enabled])
            actual = json.loads((model / "actual-parameters.json").read_text())
            cache = actual["cacheConcurrency"]
            assert cache["splitPrefetchTracking"] and cache["independentDemandAdmission"]
            assert cache["readPrefetchDirtyRetry"] == bool(enabled)
            assert cache["prefetchCandidateCycles"] == 16 and not cache["storePrefetchLruVictim"]
            assert not cache["distinctWayRelease"] and not cache["postedPrefetchCoexistence"]
            assert actual["cacheMshrs"] == actual["cacheResponses"] == actual["cacheWritebacks"] == 2
            assert actual["cacheWays"] == 2 and actual["cacheLines"] == 512
            assert actual["additionalSequentialHistoryBitsSpecified"] == enabled
            assert actual["additionalOwnerOrTokenBitsSpecified"] == 0
            if not reused:
                step(label + "-generate", [gsim, "--threads=1", "--cpp-max-size-KB=1024",
                                          "--dir=" + str(model), model / (TOP + ".fir")])
            units = sorted(model.glob(TOP + "[0-9]*.cpp"))
            assert units, "official GSIM generated no translation units"
            flags = ["-std=c++20", "-O1", "-g", "-gz=zlib", "-fsanitize=address,undefined",
                     "-fno-sanitize-recover=all", "-I" + str(model),
                     "-I" + str(ROOT / "simulator/gsim/harness"),
                     "-DSPLIT_PREFETCH_TRACKING=1", "-DSTORE_PF_LRU_ON=0",
                     "-DPF_CANDIDATE_CYCLES=16", "-DCACHE_WAYS=2",
                     "-DREAD_PF_DIRTY_RETRY=" + str(enabled),
                     "-DREAD_MSHRS=2", "-DCACHE_LINES=512", "-DRESPONSE_ENTRIES=2", "-DAXI_SLOTS=4"]
            objects = []
            for i, unit in enumerate(units):
                obj = unit.with_suffix(".o")
                if not reused:
                    step(label + "-compile-" + str(i), [cxx, *flags, "-c", unit, "-o", obj])
                objects.append(obj)
            binary = model / "run"
            step(label + "-link", [cxx, *flags, ROOT / "simulator/gsim/harness/read_prefetch_dirty_retry.cpp",
                                  *objects, "-ldl", "-o", binary])
            positive = step(label + "-positive", [binary, "--images=" + str(model / "images")],
                            anchor="READ_PREFETCH_DIRTY_RETRY_PASS", timeout=180)
            assert len(re.findall(r"^DUAL_PREFETCH_TRACKING_CASE ", positive, re.M)) == 14
            assert len(re.findall(r"^READ_PREFETCH_DIRTY_RETRY_RESULT ", positive, re.M)) == 2
            negatives = [("cpu-byte", "CPU independent byte oracle mismatch"),
                         ("dirty-data", "dirty retry C disagrees with independent byte image"),
                         ("early-expectation", "OFF/ON early dirty-writeback expectation differs")]
            if enabled:
                negatives += [("history", "candidate lacks independent accepted sequential-entry history"),
                              ("lineage", "dirty retry changed read origin or ordinary-demand victim identity"),
                              ("release-owner", "ReleaseAck inherited reused MSHR demand origin")]
            for mutation, message in negatives:
                text = step(label + "-negative-" + mutation, [binary, "--inject-" + mutation],
                            expected=1, anchor=message, timeout=180)
                assert "READ_PREFETCH_DIRTY_RETRY_MUTATION_TRIGGER " + mutation in text
            images = sorted((model / "images").glob("*-expected.bin"))
            assert len(images) == 14
            for expected in images:
                actual_image = expected.with_name(expected.name.replace("-expected.bin", "-actual.bin"))
                assert expected.stat().st_size == 128 * 1024 and sha(expected) == sha(actual_image)
            receipt["models"][label] = {"actual_parameters": actual, "split_units": len(units),
                "artifacts": {str(p.relative_to(model)): sha(p) for p in model.rglob("*") if p.is_file()}}
            save()
        if args.modes == "both":
            off = receipt["models"]["off"]["actual_parameters"]
            on = receipt["models"]["on"]["actual_parameters"]
            off_cache = dict(off["cacheConcurrency"]); on_cache = dict(on["cacheConcurrency"])
            assert off_cache.pop("readPrefetchDirtyRetry") is False
            assert on_cache.pop("readPrefetchDirtyRetry") is True
            assert off_cache == on_cache, "OFF/ON changed another policy/resource field"
            for key in ("cacheGeometry", "homeGeometry", "cacheLines", "cacheWays", "cacheMshrs",
                        "cacheResponses", "cacheWritebacks", "homeTrackedLines", "homeTrackedWays",
                        "homeAcquireEntries", "homeWritebackEntries", "axiSlots"):
                assert off[key] == on[key], "OFF/ON resource mismatch: " + key
            for expected in sorted((output / "off/images").glob("*-expected.bin")):
                assert sha(expected) == sha(output / "on/images" / expected.name), "authored OFF/ON images differ"
            receipt["off_on_authored_images_equal"] = True
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
