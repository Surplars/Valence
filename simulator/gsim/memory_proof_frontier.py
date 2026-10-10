#!/usr/bin/env python3
"""Focused real-DUT qualification; invoke only with a coordinator heavy slot.

Bank/service/PMP, held frozen transport, and controlled backend/cache/TL are
separate boundaries. This runner never launches the original CPU/home/AXI case.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import run as common


MODELS = {
    "bank": ("MemoryProofFrontierBankGsim", "bank", (1,), "MEMORY_PROOF_FRONTIER_BANK_PASS",
             "--inject-token", "frontier full tuple differs"),
    "transport": ("MemoryProofFrontierTransportGsim", "transport", (0, 1), "MEMORY_PROOF_FRONTIER_TRANSPORT_PASS",
                  "--inject-token", "independent full-token origin pairing mismatch"),
    "backend": ("MemoryProofFrontierBackendGsim", "backend", (0, 1), "MEMORY_PROOF_FRONTIER_BACKEND_PASS",
                "--inject-data", "actual loaded data differs from independent golden bytes"),
}


def hashes(models):
    files = list((common.ROOT / "src").rglob("*.scala"))
    files += [Path(__file__), common.HERE / "harness/memory_proof_frontier_reference.h"]
    files += [common.HERE / f"harness/memory_proof_frontier_{MODELS[m][1]}.cpp" for m in models]
    return {str(f.relative_to(common.ROOT)): hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(set(files))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--models", default="bank")
    parser.add_argument("--gsim", type=Path, help="Existing pinned GSIM binary; avoids rebuilding its already-verified toolchain")
    parser.add_argument("--flags", choices=("0", "1", "both"), default="both")
    parser.add_argument("--reuse", type=Path, help="Prior runner output; reuse model only after exact all-Scala identity check")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.tag):
        parser.error("tag must be a simple unique output label")
    models = args.models.split(",")
    if not models or any(m not in MODELS for m in models):
        parser.error("models must be bank,transport,backend")
    output = common.BUILD / ("memory-proof-frontier-" + args.tag)
    output.mkdir(parents=True, exist_ok=False)
    pinned = hashes(models)
    receipt = {"status": "RUNNING", "source_sha256": pinned, "models": {},
               "scope": "focused actual RTL; backend boundary is real cache plus external TileLink manager; CPU/home/AXI NOT RUN"}
    (output / "freeze.json").write_text(json.dumps(receipt, indent=2) + "\n")
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}
    try:
        if args.gsim:
            gsim = args.gsim.resolve(strict=True)
            cxx, _ = common.compiler()
            receipt["gsim_binary_sha256"] = hashlib.sha256(gsim.read_bytes()).hexdigest()
        else:
            gsim, cxx = common.setup(False)
        for model in models:
            top, stem, default_flags, anchor, mutation, reason = MODELS[model]
            flags = default_flags if args.flags == "both" else tuple(f for f in default_flags if str(f) == args.flags)
            if not flags:
                raise ValueError(f"unsupported {model} flag {args.flags}")
            for flag in flags:
                target = output / f"{model}-{flag}"
                target.mkdir()
                parameters = [] if model == "bank" else [str(flag)]
                reused = None
                if args.reuse:
                    prior = json.loads((args.reuse / "receipt.json").read_text())
                    scala = lambda record: {k: v for k, v in record.items() if k.startswith("src/")}
                    old = args.reuse / f"{model}-{flag}"
                    key = f"{model}-{flag}"
                    if prior.get("status") != "PASS" or prior.get("models", {}).get(key, {}).get("status") != "PASS":
                        raise AssertionError("reuse requires a previously passing exact model boundary")
                    if prior.get("gsim_binary_sha256") != receipt.get("gsim_binary_sha256"):
                        raise AssertionError("reuse requires the same recorded GSIM binary")
                    if scala(prior["source_sha256"]) != scala(pinned):
                        raise AssertionError("reuse requires exact complete Scala identity")
                    if not (old / (top + ".h")).is_file():
                        raise AssertionError("requested reusable model header is absent")
                    if hashlib.sha256((old / (top + ".fir")).read_bytes()).hexdigest() != prior["models"][key]["fir_sha256"]:
                        raise AssertionError("reused model FIR differs from its passing receipt")
                    for artifact in old.iterdir():
                        if artifact.suffix in (".h", ".cpp", ".fir", ".o"):
                            shutil.copy2(artifact, target / artifact.name)
                    reused = str(old.resolve())
                else:
                    common.run(["mill", "-i", "IonSoC.test.runMain", "ooo." + top + "Main", target, *parameters],
                               log=target / "elaborate.log", timeout=600)
                    common.run([gsim, "--threads=1", f"--dir={target}", target / (top + ".fir")],
                               log=target / "generate.log", timeout=600)
                cflags = ["-std=c++20", "-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all", f"-I{target}"]
                objects = []
                for source in sorted(target.glob(top + "[0-9]*.cpp")):
                    obj = source.with_suffix(".o")
                    if not obj.exists():
                        common.run([cxx, *cflags, "-c", source, "-o", obj], log=obj.with_suffix(".compile.log"), timeout=600)
                    objects.append(obj)
                common.run([cxx, *cflags, f"-DMEMORY_PROOF_ENABLED={flag}",
                            common.HERE / f"harness/memory_proof_frontier_{stem}.cpp", *objects,
                            "-ldl", "-o", target / "run"], log=target / "driver-compile.log")
                common.run([target / "run"], log=target / "positive.log", timeout=120, env=env)
                positive = (target / "positive.log").read_text()
                if anchor not in positive:
                    raise AssertionError("positive boundary PASS anchor missing")
                negative = subprocess.run([target / "run", mutation], capture_output=True, text=True, timeout=120, env=env)
                (target / "negative.log").write_text(negative.stdout + negative.stderr)
                if negative.returncode == 0 or reason not in negative.stdout + negative.stderr:
                    raise AssertionError("independent mutation was not rejected for its intended reason")
                controls = {mutation: {"returncode": negative.returncode, "reason": reason}}
                if model == "bank":
                    asserted = subprocess.run([target / "run", "--assert-bound-epoch"], capture_output=True, text=True, timeout=120, env=env)
                    (target / "assert-bound-epoch.log").write_text(asserted.stdout + asserted.stderr)
                    if asserted.returncode == 0 or "context epoch must not discard" not in asserted.stdout + asserted.stderr:
                        raise AssertionError("production surviving-bound epoch assertion not exercised")
                    controls["--assert-bound-epoch"] = {"returncode": asserted.returncode, "assertion": "context epoch must not discard"}
                if model == "transport" and flag:
                    asserted = subprocess.run([target / "run", "--assert-mask"], capture_output=True, text=True, timeout=120, env=env)
                    (target / "assert-mask.log").write_text(asserted.stdout + asserted.stderr)
                    if asserted.returncode == 0 or "frozen store proof requires" not in asserted.stdout + asserted.stderr:
                        raise AssertionError("production malformed-frozen assertion not exercised")
                    controls["--assert-mask"] = {"returncode": asserted.returncode, "assertion": "frozen store proof requires"}
                if model == "backend" and flag:
                    common.run([target / "run", "--late-store-fault"], log=target / "late-store-fault.log", timeout=120, env=env)
                    late = (target / "late-store-fault.log").read_text()
                    if anchor not in late or "traps=1" not in late:
                        raise AssertionError("real late store fault did not satisfy exact architectural recovery oracle")
                    controls["--late-store-fault"] = {"status": "PASS", "log": late}
                receipt["models"][f"{model}-{flag}"] = {"status": "PASS", "controls": controls,
                    "fir_sha256": hashlib.sha256((target / (top + ".fir")).read_bytes()).hexdigest(), "positive_log": positive,
                    "reused_model": reused, "model_objects_sha256": {obj.name: hashlib.sha256(obj.read_bytes()).hexdigest() for obj in objects}}
                (output / "progress.json").write_text(json.dumps(receipt, indent=2) + "\n")
        if hashes(models) != pinned:
            raise AssertionError("source changed during focused qualification")
        receipt["status"] = "PASS"
    except BaseException as error:
        receipt["status"] = "FAIL"
        receipt["error"] = str(error)
        raise
    finally:
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    main()
