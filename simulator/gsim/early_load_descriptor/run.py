#!/usr/bin/env python3
"""Fresh, serial, explicit-path GSIM checks for the default-off early-load experiment."""
import argparse
import hashlib
import os
from pathlib import Path
import shlex
import signal
import subprocess

HERE = Path(__file__).resolve().parent
HELPERS = {
    "selector": ("EarlyLoadDescriptorGsim", "ooo.EarlyLoadDescriptorGsimMain", HERE / "early_load_descriptor.cpp"),
    "lifetime": ("EarlyLoadSourceLifetimeGsim", "ooo.EarlyLoadSourceLifetimeGsimMain", HERE / "early_load_lifetime.cpp"),
    "legacy-selector": ("PreparationDescriptorGsim", "ooo.PreparationDescriptorGsimMain", None),
}
NEW_CASES = ["early_waiting_load", "early_waiting_priority", "early_waiting_reuse",
             "early_waiting_cancel", "early_waiting_epoch"]
RETAINED_CASES = ["owner_reuse", "ready_all_phase", "normal_fault_overlap", "full_kill",
                  "recovery_phase_positive", "recovery_cancel_negative", "reset_clocked",
                  "qlive_cancel", "proof_control_scenarios", "proof_control_block_new",
                  "pool_bare_preparation"]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("repo", "mill", "gsim", "cxx", "models", "out"):
        p.add_argument("--" + name, type=Path, required=True,
                       help="explicit path" + ("; must not exist" if name in ("models", "out") else ""))
    p.add_argument("--suite", choices=("helpers", "backend", "all"), default="all")
    p.add_argument("--timeout", type=int, default=600, help="seconds per external command (default: 600)")
    a = p.parse_args()
    for name in ("repo", "mill", "gsim", "cxx", "models", "out"):
        setattr(a, name, getattr(a, name).expanduser().resolve())
    if a.timeout <= 0 or not a.repo.is_dir():
        p.error("positive timeout and an existing repository are required")
    for name in ("mill", "gsim", "cxx"):
        tool = getattr(a, name)
        if not tool.is_file() or not os.access(tool, os.X_OK):
            p.error(f"--{name} must name an existing executable")
    if (a.models.exists() or a.out.exists() or a.models == a.out or
            a.models in a.out.parents or a.out in a.models.parents):
        p.error("--models and --out must be disjoint, fresh paths; existing artifacts are never overwritten")
    retained = a.repo / "simulator/gsim/preparation_descriptor"
    oracle = a.repo / "simulator/gsim/ready_store_query77"
    legacy = a.repo / "simulator/gsim/harness/preparation_descriptor.cpp"
    required = [retained / "observed_backend.cpp", oracle / "ready_store_query77_reference.h", legacy]
    required += [HERE / (n + ".cpp") for n in NEW_CASES]
    required += [retained / (n + ".cpp") for n in RETAINED_CASES]
    required += [HERE / "early_load_descriptor.cpp", HERE / "early_load_lifetime.cpp", Path(__file__)]
    for path in required:
        if not path.is_file():
            p.error(f"missing fixture dependency: {path}")
    # Bind source/tool inputs across this run; fresh directories forbid stale-header object reuse.
    inputs = set(required) | set((a.repo / "src").rglob("*.scala"))
    inputs |= {f for f in (a.repo / "build.sc", a.repo / ".mill-version") if f.is_file()}
    inputs |= {a.mill, a.gsim, a.cxx}
    digest = lambda f: hashlib.sha256(f.read_bytes()).hexdigest()
    hashes = {f: digest(f) for f in sorted(inputs)}
    a.models.mkdir(parents=True)
    a.out.mkdir(parents=True)
    (a.out / "inputs.sha256").write_text("".join(f"{h}  {f}\n" for f, h in hashes.items()))

    def verify():
        if any(digest(f) != h for f, h in hashes.items()):
            raise RuntimeError("source/tool inputs changed during this run")

    def run(label, command, negative=None):
        verify()
        argv = [str(x) for x in command]
        log = a.out / (label + ".log")
        print(shlex.join(argv), flush=True)
        env = dict(os.environ, ASAN_OPTIONS="detect_leaks=0", UBSAN_OPTIONS="halt_on_error=1")
        with log.open("x") as stream:
            proc = subprocess.Popen(argv, cwd=a.repo, stdout=stream, stderr=subprocess.STDOUT,
                                    env=env, start_new_session=True)
            try:
                code = proc.wait(timeout=a.timeout)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
                raise RuntimeError(f"timeout: {label}; see {log}") from None
        text = log.read_text(errors="replace")
        if (negative is None and code != 0) or (negative is not None and (code == 0 or negative not in text)):
            raise RuntimeError(f"unexpected result: {label}, exit={code}; see {log}")
        verify()
        print(label + " PASS", flush=True)

    def build(name, top, emitter):
        model = a.models / name
        run("emit-" + name, [a.mill, "-i", "IonSoC.test.runMain", emitter, model])
        run("generate-" + name, [a.gsim, "--threads=1", "--cpp-max-size-KB=1024",
                                "--dir=" + str(model), model / (top + ".fir")])
        flags = ["-std=c++20", "-O1", "-g0", "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                 "-I" + str(model), "-I" + str(HERE), "-I" + str(retained), "-I" + str(oracle)]
        sources = sorted(model.glob(top + "[0-9]*.cpp"))
        if not sources:
            raise RuntimeError("no generated C++ translation units: " + str(model))
        objects = []
        for source in sources:  # Deliberately serial; no cross-model object reuse.
            obj = a.out / (source.stem + ".o")
            run("compile-" + source.stem, [a.cxx, *flags, "-c", source, "-o", obj])
            objects.append(obj)
        return flags, objects

    def link(name, source, flags, objects):
        binary = a.out / name
        run("link-" + name, [a.cxx, *flags, source, *objects, "-ldl", "-o", binary])
        return binary

    if a.suite in ("helpers", "all"):
        for name, (top, emitter, source) in HELPERS.items():
            flags, objects = build(name, top, emitter)
            binary = link(name, source or legacy, flags, objects)
            run(name, [binary])
            if name == "selector":
                negatives = [(x, "independent early-load descriptor mismatch") for x in
                             ("omit-q-reservation", "unready-transfer", "waiting-over-ready")]
            elif name == "lifetime":
                negatives = [("mapping", "preparation source mapping changed"),
                             ("range", "preparation source outside physical capacity"),
                             ("reserve", "preparation source illegally reserved again"),
                             ("bad-producer", "waiting preparation source write must be its accepted producer wake"),
                             ("ready-rewrite", "preparation source illegally written again")]
            else:
                negatives = [(x, "independent descriptor reservation mismatch") for x in
                             ("mutate-control", "omit-q-reservation")]
            for flag, expected in negatives:
                run(name + "-negative-" + flag, [binary, "--" + flag], expected)
    if a.suite in ("backend", "all"):
        flags, objects = build("backend", "ReadyStoreQuery77BackendGsim", "ooo.EarlyLoadPreparationBackendMain")
        binaries = {}
        for name in NEW_CASES + RETAINED_CASES:
            source = (HERE if name in NEW_CASES else retained) / (name + ".cpp")
            binary = link(name, source, flags, objects)
            binaries[name] = binary
            run(name, [binary, *(["on"] if name == "ready_all_phase" else [])])
        run("negative-data", [binaries["ready_all_phase"], "on", "--mutate-data"],
            "independent execution data mismatch")
        run("negative-retirement", [binaries["full_kill"], "--mutate-retirement"],
            "fault/killed/duplicate retirement")
        run("negative-bare", [binaries["pool_bare_preparation"], "--mutate-bare-address"],
            "independent bare resident address mismatch")
    verify()
    print("EARLY_LOAD_FOCUSED_PASS suite=" + a.suite)


if __name__ == "__main__":
    main()
