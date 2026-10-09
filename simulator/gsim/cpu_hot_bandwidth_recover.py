#!/usr/bin/env python3
"""Recover an interrupted frozen-model hot replay without writing prior evidence.

Only the original runner's observer/guest builds may run. Existing successful
cases are revalidated and reused; an interrupted case with successful build
commands reuses its executable. A fresh directory is required for every attempt.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import subprocess
import time

import cpu_hot_bandwidth as hot

CASES = [f"{op}-{size}" for size in (4096, 8192) for op in ("read", "write", "copy")]


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def stable(path, expected, description):
    require(path.is_file(), f"missing {description}: {path}")
    require(hot.sha(path) == expected, f"hash mismatch for {description}: {path}")


def tree_hashes(directory):
    require(not any(p.is_symlink() for p in directory.rglob("*")), "prior evidence contains symlink")
    return {str(p.relative_to(directory)): hot.sha(p)
            for p in sorted(directory.rglob("*")) if p.is_file()}


def validate_prior(prior):
    receipt_path = prior / "receipt.json"
    state = json.loads(receipt_path.read_text())
    require(state["schema"] == "valence-cpu-hot-bandwidth-reuse-v1", "not an original hot replay receipt")
    require(state["reuse_qualified"] and not state["current_source_model_qualified"], "invalid model qualification")
    require(state["generated_models"] == state["model_objects_compiled"] == 0, "prior compiled hardware model")
    require(state["geometry"] == {"store_buffer_entries": 2, "lsu_slots": 2}, "unexpected geometry")
    for name, expected in state["inputs"].items():
        stable(hot.ROOT / name, expected, "frozen observer/guest source")
    checkpoint = Path(state["selected_model"]["path"])
    stable(checkpoint / "receipt.json", state["selected_model"]["receipt_sha256"], "selected model receipt")
    model_receipt = json.loads((checkpoint / "receipt.json").read_text())
    for name, expected in state["model_artifacts"].items():
        require(model_receipt["artifacts"][name] == expected, "model artifact not anchored in model receipt")
        stable(checkpoint / name, expected, "frozen generated artifact")
    board_source = hot.git("show", state["selected_model"]["git_head"] + ":src/main/scala/core/ooo/BoardSocTop.scala")
    require(hot.hashlib.sha256(board_source).hexdigest() == model_receipt["inputs"]["src/main/scala/core/ooo/BoardSocTop.scala"],
            "StoreBuffer geometry source not bound to selected model")
    require(hot.re.findall(r"storeBufferEntries\s*=\s*(\d+)", board_source.decode()) == ["2"], "StoreBuffer geometry changed")
    logs = {}
    for command in state["commands"]:
        require(command["log"] not in logs, "duplicate prior command log")
        logs[command["log"]] = command
        stable(prior / command["log"], command["log_sha256"], "prior command log")
    for case, result in state["cases"].items():
        require(case in CASES, "unexpected prior case")
        require(result["result"]["reps"] == 4, "recovery requires four timed repetitions")
        run = logs.get(case + "-run.log")
        require(run is not None and run["exit"] == 0, "case lacks successful historical run command")
        for name, expected in result["artifacts"].items():
            stable(prior / case / name, expected, "prior case artifact")
        parsed = hot.parse((prior / run["log"]).read_text())
        require(parsed == {k: v for k, v in result.items() if k not in ("symbols", "artifacts")},
                "prior parsed case does not match preserved log")
    return state, logs


def prepared_case(prior, case, logs):
    """Conservatively accept only this runner's exact successful build recipe."""
    op, size = case.split("-")
    mode = ("read", "write", "copy").index(op)
    directory = prior / case
    stages = [case + "-" + stage + ".log" for stage in ("guest", "binary", "observer")]
    present = [name in logs for name in stages]
    if not any(present):
        require(not directory.exists(), "unrecorded partially built case requires manual inspection")
        return False
    require(all(present), "partially compiled case requires manual inspection")
    commands = [logs[name] for name in stages]
    require(all(c["exit"] == 0 for c in commands), "existing case build failed")
    for command in (commands[0]["command"], commands[2]["command"]):
        for define in ("-DHOT_SB_ENTRIES=2", f"-DHOT_OP={mode}", f"-DHOT_BYTES={size}", "-DHOT_REPS=4"):
            require(command.count(define) == 1, "prior build flags differ from recovery plan")
    require(commands[0]["command"][-2:] == ["-o", str(directory / "guest.elf")], "unexpected guest output")
    require(commands[1]["command"][1:] == ["-O", "binary", str(directory / "guest.elf"), str(directory / "guest.bin")],
            "unexpected binary extraction command")
    require(commands[2]["command"][-2:] == ["-o", str(directory / "run")], "unexpected observer output")
    for name in ("guest.elf", "guest.bin", "cpu_hot_bandwidth_symbols.h", "run"):
        require((directory / name).is_file() and (directory / name).stat().st_size > 0, "missing prebuilt artifact: " + name)
    require(os.access(directory / "run", os.X_OK), "prebuilt observer is not executable")
    # These artifacts were not hashed by the old runner until a completed run.
    # Record that limitation, rather than pretend there is a historical digest.
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--prior", type=Path, required=True)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--verify-only", action="store_true")
    args = ap.parse_args()
    prior = args.prior.resolve()
    old, logs = validate_prior(prior)
    missing = [case for case in CASES if case not in old["cases"]]
    prepared = [case for case in missing if prepared_case(prior, case, logs)]
    if args.verify_only:
        print(json.dumps({"status": "PASS_PRIOR_QUALIFICATION", "receipt_sha256": hot.sha(prior / "receipt.json"),
                          "passed_cases": list(old["cases"]), "prepared_cases": prepared,
                          "unbuilt_cases": [case for case in missing if case not in prepared]}, indent=2))
        return
    require(args.out is not None, "--out is required except with --verify-only")
    out = args.out.resolve()
    require(not out.exists(), "choose a fresh output directory; recovery never overwrites earlier evidence")
    require(prior != out and prior not in out.parents, "recovery output cannot be inside prior evidence")
    prior_snapshot = tree_hashes(prior)
    out.mkdir(parents=True)
    state = copy.deepcopy(old)
    state.update({"schema": "valence-cpu-hot-bandwidth-recovery-v1", "status": "RUNNING",
                  "prior_receipt": {"path": str(prior / "receipt.json"), "sha256": prior_snapshot["receipt.json"],
                                    "status": old["status"]},
                  "prior_evidence_files": prior_snapshot,
                  "recovery_runner": {"path": str(Path(__file__).resolve()), "sha256": hot.sha(__file__)},
                  "commands": [], "prior_commands": old["commands"], "prepared_artifacts": {},
                  "case_provenance": {case: {"kind": "prior_pass", "directory": str(prior / case),
                                             "run_log": str(prior / (case + "-run.log")),
                                             "run_log_sha256": prior_snapshot[case + "-run.log"]}
                                      for case in old["cases"]},
                  "recovery_working_tree_status": hot.git("status", "--short").decode()})
    if prepared:
        state["limitations"].append("Interrupted prebuilt case artifacts were first hashed at recovery, not in the original receipt. "
            "Successful historical build commands and unchanged sources survive, but no pre-interruption binary digest exists; "
            "new replay, independent oracles, symbols, guest bytes, and before/after artifact hashes qualify their recovery use.")

    def save():
        temporary = out / "receipt.json.tmp"
        temporary.write_text(json.dumps(state, indent=2) + "\n")
        temporary.replace(out / "receipt.json")

    def command(name, cmd, timeout=180):
        log = out / (name + ".log")
        start = time.monotonic()
        print("+", " ".join(map(str, cmd)), flush=True)
        with log.open("x") as stream:
            run = subprocess.run(list(map(str, cmd)), cwd=hot.ROOT, stdout=stream, stderr=subprocess.STDOUT,
                                 timeout=timeout, env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
        state["commands"].append({"command": list(map(str, cmd)), "exit": run.returncode,
                                  "seconds": time.monotonic()-start, "log": log.name, "log_sha256": hot.sha(log)})
        save()
        require(run.returncode == 0, log.read_text()[-6000:])
        return log.read_text()

    save()
    try:
        for case in prepared:
            directory = prior / case
            before = {p.name: hot.sha(p) for p in directory.iterdir() if p.is_file()}
            state["prepared_artifacts"][case] = {"first_hash_at_recovery": True, "artifacts": before,
                                                "historical_compile_log": str(prior / (case + "-observer.log")),
                                                "historical_compile_command": logs[case + "-observer.log"]["command"]}
            save()
            cc = Path(logs[case + "-guest.log"]["command"][0])
            nm = cc.with_name("riscv64-unknown-elf-nm")
            symbols = {}
            for line in command(case + "-verify-symbols", [nm, "-n", directory / "guest.elf"]).splitlines():
                fields = line.split()
                if len(fields) == 3 and fields[2].startswith("hot_"):
                    symbols[fields[2]] = int(fields[0], 16)
            expected_header = "\n".join(f"#define {name.upper()} {value}ULL" for name, value in symbols.items()) + "\n"
            require((directory / "cpu_hot_bandwidth_symbols.h").read_text() == expected_header,
                    "prebuilt observer symbol header differs from guest ELF")
            objcopy = logs[case + "-binary.log"]["command"][0]
            extracted = out / (case + "-verified-guest.bin")
            command(case + "-verify-binary", [objcopy, "-O", "binary", directory / "guest.elf", extracted])
            require(hot.sha(extracted) == before["guest.bin"], "prebuilt guest binary differs from ELF")
            parsed = hot.parse(command(case + "-run", [directory / "run", directory / "guest.bin"]))
            require(parsed["result"]["op"] + "-" + str(parsed["result"]["buffer_bytes"]) == case,
                    "prebuilt observer reports wrong case")
            require(parsed["result"]["reps"] == 4, "prebuilt observer reports wrong repetitions")
            require(before == {p.name: hot.sha(p) for p in directory.iterdir() if p.is_file()}, "prebuilt artifact changed")
            parsed.update({"symbols": symbols, "artifacts": before})
            state["cases"][case] = parsed
            state["case_provenance"][case] = {"kind": "recovered_prebuilt", "directory": str(directory),
                                             "run_log": str(out / (case + "-run.log")),
                                             "run_log_sha256": hot.sha(out / (case + "-run.log"))}
            save()
            print("PASS", case, json.dumps(parsed["result"]), flush=True)
        unbuilt = [case for case in missing if case not in prepared]
        if unbuilt:
            child_out = out / "new-cases"
            command("new-cases", ["python3", hot.HERE / "cpu_hot_bandwidth.py", "--model-root",
                    Path(old["selected_model"]["path"]).parent, "--baseline", old["baseline_commit"],
                    "--repetitions", "4", "--cases", *unbuilt, "--out", child_out], timeout=600)
            child, _ = validate_prior(child_out)
            require(child["status"] == "PASS_CPU_HOT_BANDWIDTH_REUSE", "new case runner did not finish")
            for field in ("inputs", "model_artifacts", "selected_model", "geometry", "baseline_commit"):
                require(child[field] == old[field], "new case qualification differs: " + field)
            require(sorted(child["cases"]) == sorted(unbuilt), "new case set differs")
            state["new_cases_receipt"] = {"path": str(child_out / "receipt.json"), "sha256": hot.sha(child_out / "receipt.json")}
            for case, parsed in child["cases"].items():
                state["cases"][case] = parsed
                state["case_provenance"][case] = {"kind": "new_lightweight_build", "directory": str(child_out / case),
                                                 "run_log": str(child_out / (case + "-run.log")),
                                                 "run_log_sha256": hot.sha(child_out / (case + "-run.log"))}
        validate_prior(prior)
        require(tree_hashes(prior) == prior_snapshot, "prior evidence changed during recovery")
        require(hot.sha(__file__) == state["recovery_runner"]["sha256"], "recovery runner changed during replay")
        require(sorted(state["cases"]) == sorted(CASES), "incomplete recovered case set")
        state["prior_evidence_unchanged"] = True
        state["status"] = "PASS_CPU_HOT_BANDWIDTH_RECOVERY"
        state["recovery_summary"] = {"historical_passes_reused": len(old["cases"]), "prebuilt_observers_reused": len(prepared),
                                     "new_guest_and_observer_builds": len(unbuilt), "generated_models": 0, "model_objects_compiled": 0}
    except Exception as error:
        state["status"] = "FAIL"
        state["error"] = str(error)
        save()
        raise
    save()
    print("PASS receipt=" + str(out / "receipt.json"))


if __name__ == "__main__":
    main()
