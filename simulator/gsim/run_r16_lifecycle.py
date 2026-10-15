#!/usr/bin/env python3
"""R16 lifecycle extension: reuse the published isolated compiler and GSIM builder."""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import zipfile

HERE = Path(__file__).resolve().parent

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

gate = load("r16_lifecycle_gate", HERE / "run_r16_shared_address.py")
BASE_CATALOG = gate.CATALOG
gate.SUPPORT = HERE / "r16_shared_address/lifecycle"
gate.CATALOG = gate.SUPPORT / "qualified_inputs.json"
gate.TOP = "R16SharedAddressLifecycle"
gate.FIXTURE = "src/test/scala/core/ooo/R16SharedAddressLifecycle.scala"
compiler = load("r16_lifecycle_compiler", HERE / "compile_r16_shared_address.py")
compiler.gate = gate
gate.fresh_compiler = lambda: compiler

def catalog(negative=False):
    extension = gate.read(gate.CATALOG)
    gate.need(extension.get("schema") == "r16-lifecycle-extension-v1", "unsupported lifecycle catalog")
    gate.need(gate.sha(BASE_CATALOG) == extension["baseCatalogSha256"], "base R16 catalog changed")
    data = gate.read(BASE_CATALOG)
    data["publicInputs"].update(extension["publicInputs"])
    data.update({key: extension[key] for key in ("actualCore", "scalarAbi")})
    data["emitter"] = "soc.core.ooo.R16SharedAddressLifecycleMain"
    data["publicTestInputs"] = [gate.NATIVE, gate.FIXTURE,
        "src/test/scala/core/ooo/R16SharedAddressLifecycleBare.scala"]
    if negative:
        mutation = extension["mutation"]
        gate.need(data["sources"][mutation["source"]] == mutation["originalSha256"], "mutation baseline changed")
        data["sources"][mutation["source"]] = mutation["mutantSha256"]
    return data, extension

def check_trace(path, case):
    lines = path.read_text().splitlines()
    cycles = case["counts"]["cycles"]
    gate.need(len(lines) == 3 * cycles, "truncated lifecycle trace")
    for i in range(cycles):
        gate.need(lines[3*i].split()[0] == str(i), "nonconsecutive cycle")
        gate.need(len(lines[3*i+1].split()) == 276, "public snapshot width changed")
        gate.need(len(lines[3*i+2].split()) == 145, "lifecycle snapshot width changed")
    gate.need(gate.sha(path) == case["trace_sha256"], "trace differs from qualified lifecycle case")

def check_negative(code, text, trace, extension):
    gate.need(not any(marker in text for marker in gate.BAD_RUNTIME), "infrastructure failure cannot qualify negative")
    failures = [s for s in text.splitlines() if s.startswith("FAIL ")]
    gate.need(code == 1 and failures == ["FAIL independent row payload mismatch"] and "RESULT " not in text,
              "negative did not reach independent payload oracle")
    gate.need(gate.sha(trace) == extension["negativeTraceSha256"], "negative failure point changed")

def run(args, data, extension):
    gate.validate_build(args, data)
    gate.need(args.out is not None and not args.out.exists(), "run requires fresh --out")
    args.out.mkdir(parents=True)
    receipt = {"schema": "r16-lifecycle-run-v1", "status": "FAIL", "fullCpu": False,
        "physicalRun": False, "productionRecompiled": True, "sourceNegative": args.negative,
        "catalogSha256": gate.sha(gate.CATALOG), "runnerSha256": gate.sha(Path(__file__)),
        "buildReceiptSha256": gate.sha(args.build_dir / "build.json"), "commands": []}
    try:
        cases = extension["historicalCases"][:1] if args.negative else extension["historicalCases"]
        for case in cases:
            scenario = case["case"]
            for side in (["on"] if args.negative else ["off", "on"]):
                binary = args.build_dir / side / "run"
                trace = args.out / f"{side}-case{scenario}.trace"
                log = args.out / f"{side}-case{scenario}.log"
                code, text, row = gate.launch([binary, str(scenario), trace], args.out, log, args.timeout)
                row.update(side=side, scenario=scenario, binarySha256=gate.sha(binary))
                receipt["commands"].append(row)
                if args.negative:
                    check_negative(code, text, trace, extension)
                else:
                    row["counts"] = gate.check_runtime(code, text, case["counts"])
                    check_trace(trace, case)
                row["traceSha256"] = gate.sha(trace)
            if not args.negative:
                for suffix in ("trace", "log"):
                    gate.need((args.out / f"off-case{scenario}.{suffix}").read_bytes() ==
                              (args.out / f"on-case{scenario}.{suffix}").read_bytes(), "OFF/ON mismatch")
        gate.validate_build(args, data)
        receipt["status"] = "PASS_FRESH_SOURCE_NEGATIVE_REJECTED" if args.negative else "PASS_FRESH_LIFECYCLE_PAIR"
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        receipt["error"] = str(error)
        raise
    finally:
        gate.write(args.out / "receipt.json", receipt)
    return {"status": receipt["status"], "receiptSha256": gate.sha(args.out / "receipt.json")}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("verify-source", "bind-deps", "compile", "verify", "build", "run", "prepare-negative"))
    parser.add_argument("--repo-root", type=Path, required=True, help="exact historical source checkout, separate from public recipe")
    parser.add_argument("--negative", action="store_true", help="exact mutated separate source checkout; never a production edit")
    for name in ("mill-metadata-root", "deps-dir", "classes-dir", "build-dir", "out", "gsim-setup-receipt"):
        parser.add_argument("--" + name, type=Path)
    for name in ("java", "gsim", "cxx"):
        parser.add_argument("--" + name, type=Path)
        parser.add_argument("--" + name + "-sha256")
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()
    for key, value in vars(args).items():
        if isinstance(value, Path):
            setattr(args, key, value.resolve())
    args.frozen_root = None
    try:
        gate.need(args.timeout > 0, "positive timeout required")
        data, extension = catalog(args.negative)
        if args.stage == "prepare-negative":
            gate.need(not args.negative, "prepare from original source, without --negative")
            compiler.source_closure(args.repo_root, data)
            gate.need(args.out is not None and not args.out.exists(), "mutation requires a fresh --out file")
            mutation = extension["mutation"]
            content = gate.local(args.repo_root, mutation["source"]).read_text()
            gate.need(content.count(mutation["before"]) == 1, "mutation site is not unique")
            candidate = content.replace(mutation["before"], mutation["after"])
            import hashlib
            gate.need(hashlib.sha256(candidate.encode()).hexdigest() == mutation["mutantSha256"], "mutant source hash changed")
            args.out.write_text(candidate)
            result = {"status": "EXACT_MUTANT_SOURCE_WRITTEN_NOT_COMPILED", "sha256": gate.sha(args.out)}
        elif args.stage == "verify-source":
            closure = compiler.source_closure(args.repo_root, data)
            result = {"status": "EXACT_SOURCE_CLOSURE_VERIFIED_NOT_COMPILED", "sourceCount": len(closure)}
        elif args.stage == "bind-deps":
            result = compiler.bind_deps(args, data)
        elif args.stage == "compile":
            result = compiler.compile_sources(args, data)
        elif args.stage == "verify":
            gate.need(args.classes_dir is not None, "--classes-dir required")
            compiler.verify(args.classes_dir, args.repo_root, data)
            result = {"status": "FRESH_CLASSES_VERIFIED_NOT_RUN"}
        elif args.stage == "build":
            gate.need(args.classes_dir is not None, "fresh --classes-dir required; no cloud-private fallback")
            result = gate.build(args, data)
        else:
            gate.need(args.classes_dir is not None, "fresh --classes-dir required")
            result = run(args, data, extension)
        print(json.dumps(result, sort_keys=True))
    except (OSError, ValueError, KeyError, StopIteration, zipfile.BadZipFile, subprocess.SubprocessError) as error:
        parser.exit(2, "R16 lifecycle rejected: " + str(error) + "\n")

if __name__ == "__main__":
    main()
