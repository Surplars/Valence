#!/usr/bin/env python3
"""Explicit, hash-bound ROB/fetch component stages. No stage runs another stage implicitly."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import zipfile

from make_rob_fetch_source_mutant import CASES, create, verify

HERE = Path(__file__).resolve().parent
MODES = ("rob", "keys", "native", "unstaged", "no-window")
SCHEMA = "rob-fetch-component-model-v1"
BAD_RUNTIME = ("ERROR: AddressSanitizer", "AddressSanitizer:DEADLYSIGNAL", "runtime error:",
               "UndefinedBehaviorSanitizer", "ERROR: LeakSanitizer")


def need(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    with path.open("rb") as stream:
        value = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def read(path):
    return json.loads(path.read_text())


def write(path, data):
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def local(root, name):
    path = Path(name)
    need(not path.is_absolute() and path.parts and ".." not in path.parts,
         "manifest paths must be relative and contained: " + name)
    result = (root / path).resolve()
    need(result.is_relative_to(root.resolve()), "manifest path escapes its root: " + name)
    return result


def check_hashes(root, hashes, label):
    need(isinstance(hashes, dict) and hashes, label + " hash inventory is empty")
    for name, digest in hashes.items():
        need(isinstance(digest, str) and re.fullmatch("[0-9a-f]{64}", digest), label + " invalid digest")
        path = local(root, name)
        need(path.is_file() and sha(path) == digest, label + " hash mismatch: " + name)


def files(root):
    return {str(p.relative_to(root)): sha(p) for p in sorted(root.rglob("*")) if p.is_file()}


def public_inputs(root, mode):
    manifest = read(HERE / "rob_fetch_public_inputs.json")
    need(manifest["schema"] == "rob-fetch-public-leaves-v1", "unsupported public-input schema")
    leaves = manifest["groups"]["rob" if mode == "rob" else "fetch"]
    check_hashes(root, leaves, "public test/host")
    return leaves


def validate_case(mode, kind, sets):
    need(mode in MODES, "invalid component mode")
    need(isinstance(sets, int) and 4 <= sets <= 256 and not sets & (sets - 1), "sets must be a power of two in [4, 256]")
    if kind != "positive":
        need(kind in CASES and CASES[kind]["mode"] == mode, "mutation is not valid for this component mode")
    if mode == "rob":
        need(sets == 16, "ROB geometry is fixed; --sets must remain 16")


def top_for(mode):
    return "RobCompletionPayloadGsim" if mode == "rob" else (
        "CompactFetchCacheKeysGsim" if mode == "keys" else "CompactFetchFrontendGsim")


def host_for(mode):
    if mode == "rob":
        return "simulator/gsim/rob_completion_payload/rob_completion_payload.cpp"
    return "simulator/gsim/compact_fetch_keys/" + (
        "compact_fetch_cache_keys.cpp" if mode == "keys" else "compact_fetch_frontend.cpp")


def macros_for(mode, sets):
    return {} if mode == "rob" else {"CACHE_SETS": sets, "FETCH_WINDOW": int(mode != "no-window"),
                                    "FETCH_STAGED": int(mode == "native")}


def validate_sources(root, source_hashes, mode):
    check_hashes(root, source_hashes, "source")
    production = {str(p.relative_to(root)) for p in (root / "src/main/scala").rglob("*.scala")}
    declared = {p for p in source_hashes if p.startswith("src/main/scala/") and p.endswith(".scala")}
    need(production and production == declared, "production Scala source closure is incomplete or changed")
    leaves = public_inputs(root, mode)
    need(all(source_hashes.get(p) == h for p, h in leaves.items()), "public tests/host not bound in source closure")


def mutation_for(args, mode, kind):
    if kind == "positive":
        need(args.mutation_dir is None, "positive case may not use a source mutation")
        return None
    need(args.mutation_dir is not None, "negative case requires a freshly generated --mutation-dir")
    need(CASES[kind]["mode"] == mode, "wrong negative-control mode")
    return verify(args.repo_root, kind, args.mutation_dir)


def tool(args, name):
    path, digest = getattr(args, name), getattr(args, name + "_sha256")
    need(path is not None and digest is not None, "explicit --" + name + " and --" + name + "-sha256 are required")
    path = path.resolve()
    need(path.is_file() and os.access(path, os.X_OK) and sha(path) == digest, name + " tool hash mismatch")
    return path


def launch(command, cwd, log, timeout, extra_env=None):
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0", "UBSAN_OPTIONS": "halt_on_error=1"}
    if extra_env:
        env.update(extra_env)
    start = time.monotonic()
    with log.open("x") as stream:
        result = subprocess.run([str(x) for x in command], cwd=cwd, env=env,
                                stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)
    text = log.read_text(errors="replace")
    need(not any(marker in text for marker in BAD_RUNTIME), "sanitizer/runtime failure is not an oracle result")
    return result.returncode, text, {"exit": result.returncode, "seconds": round(time.monotonic() - start, 4),
                                   "log": log.name, "logSha256": sha(log)}


def class_entries(path):
    if path.is_dir():
        return {str(p.relative_to(path)) for p in path.rglob("*.class")}
    need(zipfile.is_zipfile(path), "classpath file is not a JAR")
    with zipfile.ZipFile(path) as archive:
        return {n for n in archive.namelist() if n.endswith(".class")}


def validate_classpath(args, mode, mutation):
    need(args.classpath and args.classpath_manifest, "emit requires explicit --classpath and --classpath-manifest")
    manifest = read(args.classpath_manifest)
    need(manifest.get("schema") == "rob-fetch-classpath-v1" and
         manifest.get("status") == "PASS_ISOLATED_COMPONENT_CLASSES" and
         manifest.get("oldApplicationClasspath") is False, "unqualified application classpath")
    sources = manifest["sources"]
    validate_sources(args.repo_root, sources, mode)
    need(manifest.get("mutation") == mutation, "compiled source mutation does not match actual source overlay")
    entries = [Path(p).resolve() for p in args.classpath.split(os.pathsep)]
    need(len(entries) == len(manifest["entries"]) and len(set(entries)) == len(entries), "classpath declaration mismatch")
    classes, role_counts = set(), {"main": 0, "test": 0}
    for path, declaration in zip(entries, manifest["entries"]):
        role = declaration["role"]
        need(role in ("main", "test", "dependency", "resource"), "unknown classpath role")
        if path.is_dir():
            if declaration["files"]:
                check_hashes(path, declaration["files"], "classpath")
            need(files(path) == declaration["files"], "classpath directory inventory changed")
        else:
            need(sha(path) == declaration["sha256"], "classpath JAR hash mismatch")
        found = class_entries(path) if role != "resource" else set()
        if role == "resource":
            need(not any(path.rglob("*.class")), "resource entry contains application classes")
        if role in role_counts:
            need(path.is_dir(), "application classpath must be isolated classes directories")
            role_counts[role] += 1
        else:
            need(not any(n.startswith(("soc/", "ooo/")) for n in found),
                 "dependency classpath contains old same-name application classes")
        application = {n for n in found if n.startswith(("soc/", "ooo/"))}
        need(not application & classes, "duplicate application class fallback is forbidden")
        classes |= application
    need(role_counts == {"main": 1, "test": 1}, "require exactly one isolated main and test classes entry")
    need("ooo/" + top_for(mode) + "Main.class" in classes, "emitter main is absent")
    return entries, sources


def inventory(model_dir):
    return {p: h for p, h in files(model_dir).items() if p != "model.json"}


def validate_model(args):
    need(args.model_dir is not None, "--model-dir is required")
    if args.qualified_model:
        need(args.model_manifest is None, "choose --qualified-model or --model-manifest")
        declaration = HERE / "rob_fetch_qualified_models.json"
        catalog = read(declaration)
        need(catalog["schema"] == "rob-fetch-qualified-model-catalog-v1", "unsupported qualified catalog")
        need(args.qualified_model in catalog["models"], "unknown qualified component model")
        manifest = dict(catalog["models"][args.qualified_model])
        manifest["sources"] = catalog["sourceClosures"][manifest.pop("sourceClosureId")]
    else:
        declaration = args.model_manifest or args.model_dir / "model.json"
        manifest = read(declaration)
        need(manifest.get("state") != "QUALIFIED_REUSE", "reuse must select an immutable --qualified-model catalog entry")
    need(manifest.get("schema") == SCHEMA and manifest.get("scope") == "COMPONENT_ONLY", "unsupported model declaration")
    need(manifest.get("fullCpu") is False and manifest.get("nativeBoard") is False,
         "component runner cannot establish CPU/board qualification")
    validate_case(manifest["mode"], manifest["kind"], manifest["sets"])
    need(manifest["top"] == top_for(manifest["mode"]), "wrong model top")
    need(manifest["hostMacros"] == macros_for(manifest["mode"], manifest["sets"]), "host geometry/control mismatch")
    validate_sources(args.repo_root, manifest["sources"], manifest["mode"])
    need(manifest.get("mutation") == mutation_for(args, manifest["mode"], manifest["kind"]), "source mutation/model binding mismatch")
    check_hashes(args.model_dir, manifest["artifacts"], "model input")
    # Inventory the executable model closure, not only the entries a caller remembered to list.
    relevant = {str(p.relative_to(args.model_dir)) for p in args.model_dir.rglob("*") if p.is_file() and
                (p.suffix in (".fir", ".cpp", ".h", ".hpp", ".o", ".a", ".so") or p.name == "run")}
    need(relevant <= set(manifest["artifacts"]), "model has undeclared generated/binary input files")
    need(manifest["top"] + ".fir" in manifest["artifacts"], "model FIRRTL is unbound")
    if manifest["mode"] == "rob":
        for side in ("candidate", "reference"):
            name = "actual-core-" + side + ".json"
            need(name in manifest["artifacts"], "ROB actual profile is unbound")
        need(read(args.model_dir / "actual-core-candidate.json") == read(args.model_dir / "actual-core-reference.json"),
             "ROB reference/candidate OooParams differ")
    return declaration, manifest



def bind_classpath(args):
    """Normalize a successful compiler receipt; do not compile or invent its success."""
    need(args.compile_receipt and args.classpath, "bind-classpath requires --compile-receipt and --classpath")
    raw = read(args.compile_receipt)
    need(raw.get("status") == "PASS_ISOLATED_COMPONENT_CLASSES" and
         raw.get("old_application_classpath", raw.get("oldApplicationClasspath")) is False,
         "compiler receipt must certify an isolated successful compile")
    validate_case(args.mode, args.kind, args.sets)
    mutation = mutation_for(args, args.mode, args.kind)
    entries = [Path(p).resolve() for p in args.classpath.split(os.pathsep)]
    recorded = [Path(p).resolve() for p in raw["classpath"] if Path(p).exists()]
    need(entries == recorded, "explicit classpath must match the compiler receipt (omit nonexistent resource entries)")
    need(len(entries) >= 2 and entries[0].is_dir() and entries[1].is_dir(), "expected isolated test/main directories first")
    sources = {}
    leaves = public_inputs(args.repo_root, args.mode)
    for name, digest in raw["sources"].items():
        source = Path(name).resolve()
        need(source.is_file() and sha(source) == digest, "compiler source hash mismatch")
        if source.is_relative_to(args.repo_root):
            relative = str(source.relative_to(args.repo_root))
        elif "/src/" in source.as_posix():
            relative = "src/" + source.as_posix().split("/src/", 1)[1]
        else:
            matches = [p for p, h in leaves.items() if Path(p).name == source.name and h == digest]
            need(len(matches) == 1, "cannot map compiler source to a unique public test leaf")
            relative = matches[0]
        expected_hash = digest
        if mutation and relative == mutation["sourceRelativePath"]:
            need(digest == mutation["mutantSourceSha256"], "compiler receipt did not compile the actual source mutation")
            expected_hash = mutation["candidateSourceSha256"]
        need(relative not in sources and sha(local(args.repo_root, relative)) == expected_hash,
             "compiler source differs from current repository or is duplicated: " + relative)
        sources[relative] = expected_hash
    sources.update(leaves)
    declarations = []
    for index, path in enumerate(entries):
        if index < 2:
            role = "test" if index == 0 else "main"
            prefix = "classes-" + role + "/"
            expected_classes = {p[len(prefix):]: h for p, h in raw["classes"].items() if p.startswith(prefix)}
            actual_classes = {str(p.relative_to(path)): sha(p) for p in path.rglob("*.class")}
            need(expected_classes and actual_classes == expected_classes, "compiled application class inventory mismatch")
        else:
            role = "dependency" if path.is_file() or list(path.rglob("*.class")) else "resource"
        declarations.append({"role": role, **({"files": files(path)} if path.is_dir() else {"sha256": sha(path)})})
    output = {"schema": "rob-fetch-classpath-v1", "status": "PASS_ISOLATED_COMPONENT_CLASSES",
              "oldApplicationClasspath": False, "compilerReceiptSha256": sha(args.compile_receipt),
              "sources": sources, "entries": declarations, "mutation": mutation}
    args.out.mkdir(parents=True, exist_ok=False)
    destination = args.out / "classpath.json"
    write(destination, output)
    args.classpath_manifest = destination
    validate_classpath(args, args.mode, mutation)
    return {"status": "CLASSPATH_BOUND_NOT_COMPILED_OR_EMITTED", "classpathManifestSha256": sha(destination)}


def emit(args):
    validate_case(args.mode, args.kind, args.sets)
    mutation = mutation_for(args, args.mode, args.kind)
    classpath, sources = validate_classpath(args, args.mode, mutation)
    java, firtool = tool(args, "java"), tool(args, "firtool")
    args.out.mkdir(parents=True, exist_ok=False)
    top = top_for(args.mode)
    extra = [] if args.mode == "rob" else [str(args.sets)]
    if args.mode in ("unstaged", "no-window"):
        extra.append(args.mode)
    command = [java, "-Xmx4g", "-XX:ActiveProcessorCount=2", "-Dchisel.project.root=" + str(args.repo_root),
               "-cp", os.pathsep.join(map(str, classpath)), "ooo." + top + "Main", args.out, *extra]
    code, _, record = launch(command, args.repo_root, args.out / "emit.log", args.timeout,
                             {"CHISEL_FIRTOOL_PATH": str(firtool.parent)})
    need(code == 0 and (args.out / (top + ".fir")).is_file(), "component emit failed")
    model = {"schema": SCHEMA, "state": "EMITTED", "scope": "COMPONENT_ONLY", "fullCpu": False,
             "nativeBoard": False, "physicalMetrics": "UNMEASURED", "mode": args.mode, "kind": args.kind,
             "sets": args.sets, "top": top, "hostMacros": macros_for(args.mode, args.sets),
             "sources": sources, "mutation": mutation, "artifacts": inventory(args.out),
             "classpathManifestSha256": sha(args.classpath_manifest),
             "tools": {"java": sha(java), "firtool": sha(firtool)}, "stages": {"emit": record},
             "provenance": "fresh explicit emitter; no implicit compile or host run"}
    write(args.out / "model.json", model)
    return {"status": "EMITTED_NOT_GENERATED_OR_RUN", "modelManifestSha256": sha(args.out / "model.json")}


def generate(args):
    declaration, model = validate_model(args)
    need(declaration.resolve() == (args.model_dir / "model.json").resolve(), "generation requires an owned model.json")
    need(model["state"] == "EMITTED", "generate requires EMITTED state")
    need(not list(args.model_dir.glob(model["top"] + "*.cpp")), "refusing existing generated model")
    gsim = tool(args, "gsim")
    command = [gsim, "--threads=1", "--cpp-max-size-KB=1024", "--dir=" + str(args.model_dir),
               args.model_dir / (model["top"] + ".fir")]
    code, _, record = launch(command, args.repo_root, args.model_dir / "generate.log", args.timeout)
    need(code == 0 and list(args.model_dir.glob(model["top"] + "[0-9]*.cpp")), "GSIM generation failed")
    model.update(state="GENERATED", artifacts=inventory(args.model_dir))
    model["tools"]["gsim"] = sha(gsim)
    model["stages"]["generate"] = record
    write(declaration, model)
    return {"status": "GENERATED_NOT_BUILT_OR_RUN", "modelManifestSha256": sha(declaration)}


def build(args):
    declaration, model = validate_model(args)
    need(declaration.resolve() == (args.model_dir / "model.json").resolve(), "build requires an owned model.json")
    need(model["state"] == "GENERATED" and not (args.model_dir / "run").exists(), "build requires a fresh GENERATED model")
    cxx = tool(args, "cxx")
    units = sorted(args.model_dir.glob(model["top"] + "[0-9]*.cpp"))
    need(units, "no generated GSIM translation units")
    host = args.repo_root / host_for(model["mode"])
    flags = ["-std=c++20", "-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
             "-I" + str(args.model_dir), "-I" + str(host.parent)]
    flags += ["-D" + key + "=" + str(value) for key, value in model["hostMacros"].items()]
    code, _, record = launch([cxx, *flags, *units, host, "-ldl", "-o", args.model_dir / "run"],
                             args.repo_root, args.model_dir / "build.log", args.timeout)
    need(code == 0 and (args.model_dir / "run").is_file(), "host build failed")
    model.update(state="BUILT", artifacts=inventory(args.model_dir))
    model["tools"]["cxx"] = sha(cxx)
    model["stages"]["build"] = record
    write(declaration, model)
    return {"status": "BUILT_NOT_RUN", "modelManifestSha256": sha(declaration)}


def verify_result(mode, kind, code, text):
    need(not any(marker in text for marker in BAD_RUNTIME), "sanitizer failure is not qualification")
    if kind != "positive":
        case = CASES[kind]
        need(code != 0 and case["failure"] in text, "negative control lacks its strict expected failure")
        if case.get("additionalWitness"):
            need(case["additionalWitness"] in text, "negative control lacks live-row stale-owner witness")
        # Only this source negative intentionally trips a named hardware pairing assertion.
        if kind != "stale-capture-enabled":
            need("Assertion failed:" not in text and "Assertion `" not in text,
                 "generic hardware assertion cannot replace the independent negative oracle")
        return "PASS_SOURCE_MUTANT_REJECTED"
    need(code == 0, "positive host did not exit successfully")
    if mode == "rob":
        required = ["ROB_PAYLOAD_RAM_ORACLE_PASS entries=" + str(n) for n in (4, 8, 16, 32)]
        required += ["ROB_COMPLETION_PAYLOAD_ORACLE_PASS", "RETIREMENT_ROB_ORACLE PASS", "ROB_COMPLETION_PAYLOAD_PAIR_PASS"]
    else:
        required = ["COMPACT_FETCH_KEYS_FULL64_PASS" if mode == "keys" else "COMPACT_FETCH_FRONTEND_PAIR_ORACLE_PASS"]
    need(all(marker in text for marker in required), "positive host lacks its full independent oracle markers")
    return "PASS_COMPONENT_ONLY"


def run(args):
    declaration, model = validate_model(args)
    need(model["state"] in ("BUILT", "QUALIFIED_REUSE"), "run needs BUILT or QUALIFIED_REUSE state")
    need("run" in model["artifacts"], "unbound host binary")
    if model["state"] == "QUALIFIED_REUSE":
        q = model.get("qualification", {})
        need(q.get("status") == "PASS_COMPONENT_ONLY" and
             all(re.fullmatch("[0-9a-f]{64}", q.get(key, "")) for key in
                 ("qualificationSha256", "caseReceiptSha256", "compileReceiptSha256")),
             "reuse requires original component qualification/compile/case receipt hashes")
    args.out.mkdir(parents=True, exist_ok=False)
    arguments = [] if model["kind"] == "positive" else CASES[model["kind"]]["arguments"]
    receipt = {"schema": "rob-fetch-public-run-v1", "scope": "COMPONENT_ONLY", "fullCpu": False,
               "nativeBoard": False, "physicalMetrics": "UNMEASURED", "status": "FAIL",
               "mode": model["mode"], "kind": model["kind"], "sets": model["sets"],
               "modelManifestSha256": sha(declaration), "sourceClosure": model["sources"],
               "inputArtifacts": model["artifacts"], "mutation": model.get("mutation"),
               "runnerSha256": sha(Path(__file__)), "reusedQualifiedModel": model["state"] == "QUALIFIED_REUSE",
               "productionRecompiled": False, "gsimRegenerated": False, "hostRebuilt": False}
    try:
        code, text, record = launch([args.model_dir / "run", *arguments], args.out,
                                    args.out / "result.log", args.timeout)
        receipt["run"] = record
        receipt["status"] = verify_result(model["mode"], model["kind"], code, text)
        print(text, end="")
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        receipt["error"] = str(error)
        raise
    finally:
        write(args.out / "receipt.json", receipt)
    return {"status": receipt["status"], "receiptSha256": sha(args.out / "receipt.json"),
            "reusedQualifiedModel": receipt["reusedQualifiedModel"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("mutate", "bind-classpath", "emit", "generate", "build", "run", "verify"))
    parser.add_argument("--repo-root", type=Path, default=HERE.parents[1])
    parser.add_argument("--mode", choices=MODES, default="rob")
    parser.add_argument("--kind", choices=("positive", *CASES), default="positive")
    parser.add_argument("--sets", type=int, default=16)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--mutation-dir", type=Path)
    parser.add_argument("--model-dir", type=Path)
    parser.add_argument("--model-manifest", type=Path)
    parser.add_argument("--qualified-model", help="exact case ID from rob_fetch_qualified_models.json")
    parser.add_argument("--classpath")
    parser.add_argument("--classpath-manifest", type=Path)
    parser.add_argument("--compile-receipt", type=Path)
    parser.add_argument("--timeout", type=int, default=600)
    for name in ("java", "firtool", "gsim", "cxx"):
        parser.add_argument("--" + name, type=Path)
        parser.add_argument("--" + name + "-sha256")
    args = parser.parse_args()
    for name in ("repo_root", "out", "mutation_dir", "model_dir", "model_manifest", "classpath_manifest"):
        if getattr(args, name) is not None:
            setattr(args, name, getattr(args, name).resolve())
    try:
        need(args.timeout > 0, "timeout must be positive")
        if args.stage in ("mutate", "bind-classpath", "emit", "run"):
            need(args.out is not None, "stage requires a fresh --out directory")
        if args.stage == "mutate":
            need(args.kind != "positive", "mutate requires a negative --kind")
            result = create(args.repo_root, args.kind, args.out)
        elif args.stage == "verify":
            _, model = validate_model(args)
            result = {"status": "INPUTS_VERIFIED_NOT_RUN", "state": model["state"]}
        else:
            result = globals()[args.stage.replace("-", "_")](args)
        print(json.dumps(result, sort_keys=True))
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        parser.exit(2, "component stage rejected: " + str(error) + "\n")


if __name__ == "__main__":
    main()
