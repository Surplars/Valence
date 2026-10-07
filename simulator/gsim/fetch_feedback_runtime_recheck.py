#!/usr/bin/env python3
"""Recheck a firmware-only fix with the exact unchanged short-batch hardware models."""
import argparse
import json
import os
from pathlib import Path
import re
from run import BUILD, ROOT, run
from control_stage import negative, reference, core_payloads
from fetch_feedback import firmware
import throughput_perf as perf


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("previous", type=Path)
    parser.add_argument("--tag", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.tag):
        parser.error("unsafe tag")
    previous = json.loads(args.previous.read_text())
    if (previous["status"] != "failed" or previous["profile"] != "staged-fetch-feedback" or
            "board/permission.log" not in previous.get("failure", "")):
        raise RuntimeError("only a completed short batch with a firmware-smoke failure is reusable")
    allowed = "fpga/firmware/fetch_permission_smoke.S"
    before = {name:perf.sha256(ROOT / name) for name in previous["source_sha256"]}
    changed = [name for name, sha in previous["source_sha256"].items() if before[name] != sha]
    if changed != [allowed]:
        raise RuntimeError("not a firmware-only change: " + repr(changed))
    old = args.previous.resolve().parent
    output = BUILD / ("fetch-feedback-" + args.tag)
    output.mkdir(parents=True, exist_ok=False)
    before[str(Path(__file__).resolve().relative_to(ROOT))] = perf.sha256(Path(__file__))
    report = {**previous, "status":"running", "failure":None, "source_sha256":before,
              "runtime_recheck":{"previous_receipt":str(args.previous.resolve()),
                  "previous_receipt_sha256":perf.sha256(args.previous), "allowed_changed_inputs":changed,
                  "no_hardware_or_harness_changes":True}, "reused_models_sha256":{}}
    env = {**os.environ, "ASAN_OPTIONS":"detect_leaks=0"}
    artifacts = []
    try:
        for stem, anchor in (("reservoir2-mixed", "fetch packet oracle mismatch"),
                             ("reservoir2-plain", "fetch packet oracle mismatch"),
                             ("reservoir4-mixed", "fetch packet oracle mismatch"),
                             ("permission", "PMP oracle mismatch")):
            model = old / stem
            artifacts += [model / "run", *model.glob("*.fir"), *model.glob("*.cpp"), *model.glob("*.h")]
            run([model / "run"], env=env, log=output / (stem + ".log"), timeout=120)
            negative(model / "run", (), anchor, output / (stem + "-negative.log"))
            report["checks"][stem] = (output / (stem + ".log")).read_text()
        ref = reference()
        payloads = core_payloads(output)
        keys = perf.EXPECTED_KEYS | {("throughput_hint_alias_loop", 1)}
        baseline_receipt = json.loads((BUILD / "ethernet-stage-20261004-r2/receipt.json").read_text())
        models = {"staged-ethernet":Path(baseline_receipt["profiles"]["staged-ethernet"]["model_directory"]),
                  "staged-fetch-feedback":old / "core"}
        for profile, model in models.items():
            row = previous["profiles"][profile]
            if perf.sha256(model / "run") != row["executable_sha256"]:
                raise RuntimeError("frozen executable changed: " + profile)
            if profile == "staged-fetch-feedback" and perf.sha256(model / "IntegerCoreGsim.fir") != row["model_fir_sha256"]:
                raise RuntimeError("candidate model changed")
            run([model / "run", ref, *payloads, "--throughput-short"], env=env,
                log=output / (profile + ".log"), timeout=180)
            measured = perf.parse_measurements((output / (profile + ".log")).read_text(), 13, keys)
            if measured != row["measurements"]:
                raise RuntimeError("frozen throughput replay changed")
            artifacts += [model / "run", model / "IntegerCoreGsim.fir"]
        core = models["staged-fetch-feedback"]
        for mode in ("--timing-smoke", "--pipeline-recovery"):
            run([core / "run", ref, *payloads, mode], env=env,
                log=output / (mode[2:] + ".log"), timeout=180)
        negative(core / "run", (ref, *payloads), "NEMU register mismatch", output / "negative-core.log")
        board = old / "board"
        artifacts += [board / "run", *board.glob("*.fir"), *board.glob("*.cpp"), *board.glob("*.h")]
        model_hashes = {str(p.relative_to(ROOT)):perf.sha256(p) for p in artifacts}
        for stem, mode, key in (("rv64gc_smoke", (), "rv64gc"),
                                ("fetch_permission_smoke", ("--fetch-permission",), "permission_revoke_restore")):
            image = firmware(output, stem)
            run([board / "run", image, *mode], env=env, log=output / (stem + ".log"), timeout=120)
            negative(board / "run", (image, *mode), "firmware independent anchor/context failure",
                     output / (stem + "-negative.log"))
            report["checks"][key] = (output / (stem + ".log")).read_text()
        if model_hashes != {name:perf.sha256(ROOT / name) for name in model_hashes}:
            raise RuntimeError("reused model changed during execution")
        report["reused_models_sha256"] = model_hashes
        report["board_model"] = {"model_fir_sha256":perf.sha256(board / "BoardSocGsim.fir"),
                                 "executable_sha256":perf.sha256(board / "run")}
        report["status"] = "passed"
    except BaseException as error:
        report["status"] = "failed"
        report["failure"] = str(error)
        raise
    finally:
        if before != {name:perf.sha256(ROOT / name) for name in before}:
            report["status"] = "failed"
            report["failure"] = "source drift during firmware-only recheck"
        (output / "receipt.json").write_text(json.dumps(report, indent=2)+"\n")
    if report["status"] != "passed":
        raise RuntimeError(report["failure"])
    print(report["checks"]["permission_revoke_restore"], end="")
    print(f"FETCH_FEEDBACK_RUNTIME_RECHECK_PASS receipt={output / 'receipt.json'}")


if __name__ == "__main__":
    main()
