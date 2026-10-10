#!/usr/bin/env python3
"""Run the preserved same-edge host-ledger controls without a DUT or model build.

Use an existing C++20 compiler via --cxx or GSIM_CXX. Output must be fresh;
failures and their logs are preserved. No tools are downloaded or installed.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / "simulator/gsim/harness"
SNAPSHOT = HARNESS / "translated_response_flow_ledger"
ANCHOR = ("PASS_RETURN_FLOW_LEDGER_CONTROLS positive=44 negative=19 "
          "error_tuples=4 direct_load_store=1 local_faults=2 "
          "held_capture_then_pop=4 old_pop_new_push=1 full_pop=1 posted_ack=1")
SANITIZER = re.compile(r"AddressSanitizer|UndefinedBehaviorSanitizer|LeakSanitizer|runtime error:")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="fresh directory for executable, logs and receipt")
    parser.add_argument("--cxx", default=os.environ.get("GSIM_CXX", "clang++"), help="existing C++20 compiler executable")
    args = parser.parse_args()
    compiler = shutil.which(args.cxx)
    if compiler is None:
        parser.error("compiler unavailable; select an installed compiler with --cxx or GSIM_CXX")
    # Preserve argv[0]: resolving clang++ to clang changes its linker mode.
    compiler = os.path.abspath(compiler)
    output = args.output.resolve()
    if output.exists():
        parser.error("output exists; preserve it and choose a fresh directory")
    provenance = json.loads((SNAPSHOT / "provenance.json").read_text())
    for name, expected in provenance["preserved_files"].items():
        if sha(SNAPSHOT / name) != expected["sha256"]:
            parser.error("preserved observer source drift: " + name)
    inputs = [Path(__file__).resolve(), SNAPSHOT / "provenance.json",
              SNAPSHOT / "cpu_flow_bandwidth.h", SNAPSHOT / "test_return_ledger.cpp",
              HARNESS / "data_path_sample.h", HARNESS / "backend_ownership_ledger.h"]
    frozen = {str(p.relative_to(ROOT)): sha(p) for p in inputs}
    output.mkdir(parents=True)
    binary = output / "test_return_ledger"
    command = [compiler, "-std=c++20", "-O1", "-g", "-fsanitize=address,undefined",
               "-fno-sanitize-recover=all", "-DBACKEND_OWNER_COUNT=4",
               "-DSTORE_PREFETCH_PROFILE=1", "-DPHYSICAL_INGRESS_FLOW=1",
               "-I" + str(SNAPSHOT), "-I" + str(HARNESS),
               str(SNAPSHOT / "test_return_ledger.cpp"), "-o", str(binary)]
    state = {"schema": "valence-return-flow-ledger-host-controls-v1", "status": "RUNNING",
             "started_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
             "scope": "host ledger validate/advance controls only; no DUT execution or new CPU qualification",
             "source_files": frozen, "compiler": {"path": compiler, "sha256": sha(compiler)},
             "steps": [], "expected_anchor": ANCHOR}

    def save():
        (output / "receipt.json").write_text(json.dumps(state, indent=2) + "\n")

    def guard():
        if any(sha(ROOT / name) != digest for name, digest in frozen.items()):
            raise RuntimeError("host source changed during controls")
        if sha(compiler) != state["compiler"]["sha256"]:
            raise RuntimeError("compiler changed during controls")

    def step(name, argv):
        guard()
        record = {"name": name, "argv": argv, "status": "RUNNING", "timeout_seconds": 60}
        state["steps"].append(record)
        save()
        log = output / (name + ".log")
        with log.open("x") as stream:
            result = subprocess.run(argv, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                                    timeout=60, env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
        text = log.read_text()
        record.update(exit_code=result.returncode, log_sha256=sha(log), status="FAIL")
        save()
        if result.returncode or SANITIZER.search(text):
            raise RuntimeError(name + " failed; see " + str(log))
        record["status"] = "PASS"
        save()
        return text

    save()
    try:
        step("compile", command)
        state["executable_sha256"] = sha(binary)
        text = step("controls", [str(binary)])
        if text.splitlines().count(ANCHOR) != 1:
            raise RuntimeError("missing exact coverage anchor")
        guard()
        state.update(status="PASS_HOST_CONTROLS_ONLY", positive_validations=44, negative_controls=19)
    except BaseException as error:
        state.update(status="FAIL_PRESERVED", error=str(error))
        raise
    finally:
        state["finished_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        save()
    print(json.dumps({"status": state["status"], "positive_validations": 44, "negative_controls": 19,
                      "receipt": str(output / "receipt.json"), "receipt_sha256": sha(output / "receipt.json")}))


if __name__ == "__main__":
    main()
