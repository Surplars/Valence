#!/usr/bin/env python3
"""Real I1 private-cache owner drain observations; no full-system gating claim."""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import run as common


def verify_read_first(gsim, cxx, output):
    witness = output / "read-first-witness"
    witness.mkdir()
    raw = (common.HERE / "fixtures/i1_read_first_witness.fir.in").read_text()
    adapted = raw.replace("[2], old", "[2] old")
    (witness / "original.fir").write_text(raw)
    fir = witness / "I1ReadFirstWitness.fir"
    fir.write_text(adapted)
    common.run([gsim, "--threads=1", f"--dir={witness}", fir], log=witness / "generate.log")
    common.run([cxx, "-std=c++20", "-O1", "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
        f"-I{witness}", *witness.glob("I1ReadFirstWitness[0-9]*.cpp"),
        common.HERE / "harness/i1_read_first_witness.cpp", "-ldl", "-o", witness / "run"],
        log=witness / "compile.log")
    common.run([witness / "run"], log=witness / "test.log",
        env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
    result = subprocess.run([witness / "run", "--wrong-read-first"], capture_output=True, text=True,
        env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}, timeout=30)
    (witness / "negative.log").write_text(result.stdout + result.stderr)
    if result.returncode == 0 or "independent same-address ReadFirst oracle" not in result.stderr:
        raise RuntimeError("ReadFirst mutation was not rejected")
    return {"status": "PASS", "collisions": 32, "negative": "REJECTED",
        "original_sha256": hashlib.sha256(raw.encode()).hexdigest(),
        "adapted_sha256": hashlib.sha256(adapted.encode()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default="focused")
    parser.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()
    if not args.tag.replace("-", "").replace("_", "").isalnum():
        parser.error("tag must contain only letters, digits, hyphens, or underscores")
    name = "i1-cache-quiescence-" + args.tag
    mode_args = ("--cache-bytes=256", "--miss-turnover")
    if args.dry_run:
        print(json.dumps({"name": name, "top": "I1CacheQuiescenceFixture", "clock": "single",
                          "scope": "real private coherent cache owner drain",
                          "negative": "--wrong-probe"}))
        return
    output = common.BUILD / name
    if output.exists() and any(output.iterdir()):
        parser.error("choose a fresh tag; existing evidence is never overwritten")
    output.mkdir(parents=True, exist_ok=True)
    paths = [common.ROOT / path for path in (
        "src/main/scala/core/inorder/I1CoherentInterfaces.scala",
        "src/main/scala/core/inorder/I1CoherentLineCache.scala",
        "src/main/scala/core/inorder/FiveStageWordCache.scala",
        "src/main/scala/core/inorder/I1FlowResponseQueue.scala",
        "src/main/scala/core/inorder/I1TimingMath.scala",
        "src/main/scala/core/inorder/I1ExecuteDatapath.scala",
        "src/main/scala/ip/tilelink/TileLinkLineAcquireEngine.scala",
        "src/test/scala/inorder/I1CacheQuiescenceMain.scala")]
    paths += [common.HERE / "harness/i1_cache_quiescence.cpp", common.HERE / "run.py",
              common.HERE / "config/toolchain.json", Path(__file__).resolve(),
              common.HERE / "fixtures/i1_read_first_witness.fir.in",
              common.HERE / "harness/i1_read_first_witness.cpp"]
    def hashes():
        return {str(path.relative_to(common.ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in paths}
    report = {"status": "RUNNING", "source_sha256": hashes(),
              "scope": "Private cache only; no system drain, CDC, PLL or physical timing claim"}
    try:
        gsim, cxx = common.setup(False)
        report["ruw_source_evidence"] = {
            "parser/syntax.y:220": "SMem datatype Ruw keeps the explicit token; old spelling has no comma",
            "src/AST2Graph.cpp:787-808": "memory extraInfo retains Ruw policy",
            "src/AST2Graph.cpp:1608-1621": "new schedules the read after writes; old schedules it before writes",
            "src/Node.cpp:234": "non-new readwriter activates its next-cycle evaluation",
            "source_sha256": {path: hashlib.sha256((common.SOURCE / path).read_bytes()).hexdigest()
                for path in ("parser/syntax.y", "src/AST2Graph.cpp", "src/Node.cpp")}}
        report["read_first_semantics"] = verify_read_first(gsim, cxx, output)
        original_run = common.run
        def compatible_run(command, **kwargs):
            if str(command[0]) == str(gsim):
                fir = output / "I1CacheQuiescenceFixture.fir"
                raw = fir.read_text()
                # Installed GSIM accepts the old/new RUW token but its grammar
                # predates the comma separator. Preserve the actual OLD policy.
                adapted, count = re.subn(r"(smem [^\n]+), (old|new)(?= @|\n)", r"\1 \2", raw)
                (output / "I1CacheQuiescenceFixture.original.fir").write_text(raw)
                fir.write_text(adapted)
                report["ruw_comma_compatibility"] = {"count": count, "policy": "old preserved",
                    "original_sha256": hashlib.sha256(raw.encode()).hexdigest(),
                    "adapted_sha256": hashlib.sha256(adapted.encode()).hexdigest()}
            return original_run(command, **kwargs)
        common.run = compatible_run
        common.test(gsim, cxx, name, "inorder.I1CacheQuiescenceMain", "I1CacheQuiescenceFixture",
                    "i1_cache_quiescence.cpp", parameters=mode_args, runtime_args=(), defines={}, timeout=180)
        log = (output / "test.log").read_text()
        marker = "I1_CACHE_QUIESCENCE_PASS"
        if marker not in log:
            raise RuntimeError("positive test omitted completion marker")
        for owner in ("partial", "e", "reply", "release", "probe", "native"):
            result = subprocess.run([output / "run", "--wrong-" + owner], capture_output=True, text=True,
                                    timeout=30, env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
            negative = result.stdout + result.stderr
            (output / ("wrong-" + owner + ".log")).write_text(negative)
            if result.returncode == 0 or "independent live-owner quiescence oracle" not in negative:
                raise RuntimeError("wrong quiescence oracle was not rejected: " + owner)
        if hashes() != report["source_sha256"]:
            raise RuntimeError("test sources changed during run")
        report.update(status="PASS", positive_log=log, wrong_owner_oracles="REJECTED")
    except BaseException as error:
        report.update(status="FAIL", error=str(error))
        raise
    finally:
        (output / "receipt.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
