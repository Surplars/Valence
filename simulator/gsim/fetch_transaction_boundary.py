#!/usr/bin/env python3
"""S1 integrated transaction boundary; bounded owners and unchanged permission oracle."""
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


def negative(output, flag, marker, reason):
    result = subprocess.run([str(output / "run"), flag], text=True, capture_output=True,
                            timeout=30, env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
    log = result.stdout + result.stderr
    (output / (flag[2:] + ".log")).write_text(log)
    assert result.returncode != 0 and marker in log and reason in log, (flag, result.returncode, log)
    assert "ERROR: AddressSanitizer" not in log and "runtime error:" not in log, log
    return {"flag": flag, "exit": result.returncode, "witness": marker, "reason": reason}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gsim", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    args = parser.parse_args()
    assert re.fullmatch(r"[A-Za-z0-9_-]+", args.tag), "unsafe tag"
    output = common.BUILD / args.tag
    assert not output.exists(), "fresh output directory required"
    gsim = args.gsim.resolve(strict=True)
    cxx, compiler = common.compiler()
    sources = sorted((common.ROOT / "src/main/scala").rglob("*.scala")) + [
        common.ROOT / "src/test/scala/ooo/FetchTransactionBoundaryGsim.scala",
        common.ROOT / "src/test/scala/ooo/InstructionTranslationTransactionGsim.scala",
        common.ROOT / "src/test/scala/ooo/FrozenInstructionTranslationAdapterBeforeTransactionBoundary.scala",
        common.ROOT / "src/test/scala/ooo/InstructionPermissionGsim.scala",
        HERE / "fetch_transaction_boundary.py", HERE / "fetch_transaction_boundary/boundary.cpp",
        HERE / "harness/instruction_permission.cpp", HERE / "harness/instruction_permission_stream.cpp",
        HERE / "run.py",
    ]
    inputs = {str(path.relative_to(common.ROOT)): sha(path) for path in sources}
    gsim_sha = sha(gsim)
    controls, checks = [], []
    for bits in (64, 2):
        name = f"{args.tag}/boundary-{bits}"
        model = common.test(gsim, cxx, name, "ooo.FetchTransactionBoundaryGsimMain",
                            "FetchTransactionBoundaryGsim", "../fetch_transaction_boundary/boundary.cpp",
                            parameters=(str(bits),), defines={"BOUNDARY_TOKEN_BITS": bits}, timeout=30)
        log = (model / "test.log").read_text()
        assert "PASS FETCH_TRANSACTION_BOUNDARY" in log
        checks.append({"name": name, "log": log.strip(), "logSha256": sha(model / "test.log")})
        if bits == 64:
            for flag, marker, reason in (
                ("--wrong-generation", "INJECT wrong-generation", "fetch transaction result generation mismatch"),
                ("--duplicate-result", "INJECT duplicate-result", "fetch transaction result has no owner"),
                ("--inject-held-data", "INJECT held-data", "FETCH_BOUNDARY_ORACLE held/returned payload or fault metadata changed"),
                ("--inject-turnover-context", "INJECT turnover-context", "FETCH_BOUNDARY_ORACLE accepted/offered token or atomic context mismatch"),
            ):
                controls.append(negative(model, flag, marker, reason))
    for label, words, aligned, stream, turnover in (
        ("selected-stream", 2, True, True, True),
        ("generic-cross-page-stream", 2, False, True, False),
        ("wide-isolated", 4, True, False, False),
    ):
        name = f"{args.tag}/{label}"
        params = ((str(words),) + (("aligned",) if aligned else ()) +
                  (("stream",) if stream else ()) + (() if turnover else ("no-turnover",)))
        harness = "instruction_permission_stream.cpp" if stream else "instruction_permission.cpp"
        model = common.test(gsim, cxx, name, "ooo.InstructionTranslationTransactionGsimMain",
                            "InstructionPermissionGsim", harness, parameters=params,
                            defines={"PACKET_WORDS": words, "RETIMED_PERMISSIONS": 1,
                                     "ALIGNED_PACKET": int(aligned), "FETCH_REPLY_TURNOVER": int(turnover),
                                     "FETCH_IDENTITY_TRANSLATION": int(stream)}, timeout=30)
        log = (model / "test.log").read_text()
        assert ": PASS " in log
        checks.append({"name": name, "log": log.strip(), "logSha256": sha(model / "test.log")})
        reason = "independent multi-owner response oracle mismatch" if stream else "independent I-fetch permission oracle mismatch"
        controls.append(negative(model, "--inject-mismatch", reason, reason))
    assert inputs == {str(path.relative_to(common.ROOT)): sha(path) for path in sources}, "source changed during run"
    assert gsim_sha == sha(gsim), "GSIM executable changed during run"
    receipt = {
        "status": "PASS_S1_TRANSACTION_BOUNDARY_AND_PAIRED_ADAPTER_ONLY",
        "checks": checks, "negativeControls": controls, "sourceSha256": inputs,
        "gsimSha256": gsim_sha, "compiler": compiler,
        "scope": {
            "production": "InstructionTranslationAdapter registered-heads path uses the real boundary and engine",
            "latency": "zero new register edges; existing single owner retained",
            "token": "64-bit modulo generation; two-bit unit configuration exercises 64 legal drained wraps",
            "serviceLaw": "boundary response latencies 1,2,7,17; deterministic independent ready periods",
            "pairedOracle": "frozen aaa2af4 adapter gives cycle comparison only; unchanged byte-range PMP and owner ledger are independent",
            "negativeControls": "bad generation and duplicate are actual input faults with mandatory hardware diagnostics; payload/context are observation or host mutations",
            "configuration": "selected-stream uses exact FpgaNext.Selected coreParams; generic two-word disables turnover for held-offer window; four-word uses isolated requests; both use existing reduced InstructionPermission parameters",
        },
        "limits": [
            "Not proof of two in-flight requests, II=1, 8B/cycle, core IPC, PPA or 300 MHz",
            "Zero extra cycles does not prove zero timing or area cost: token compare gates response/credit and token registers/counter are added",
            "Two-bit legal wrap assumes exactly one terminal result and complete drain before reuse; arbitrary late duplicates after tag reuse are outside this contract",
            "End-to-end nine-scenario exact comparison is a separate mandatory A1FetchSupply check",
        ],
    }
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print("PASS S1 transaction boundary and frozen-peer comparison; end-to-end supply gate remains separate")


if __name__ == "__main__":
    main()
