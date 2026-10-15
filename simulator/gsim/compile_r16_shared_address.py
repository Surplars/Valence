#!/usr/bin/env python3
"""Fresh, isolated Scala compilation for the exact R16 gate; never elaborates hardware."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import zipfile

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("r16_gate", HERE / "run_r16_shared_address.py")
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)
TASKS = ("resolvedMvnDeps", "scalaCompilerClasspath", "scalacPluginClasspath")


def source_closure(repo, data):
    gate.validate_repo(repo, data)
    gate.check_hashes(repo, data["freshCompileInputs"])
    main = {str(p.relative_to(repo)) for p in (repo / "src/main/scala").rglob("*.scala")}
    expected = {name for name in data["sources"] if name.startswith("src/main/scala/")}
    gate.need(main == expected, "production Scala source closure changed")
    hf = {str(p.relative_to(repo)) for p in (repo / "third_party/berkeley-hardfloat/src/main/scala").rglob("*.scala")}
    gate.need(hf == {n for n in data["freshCompileInputs"] if n.endswith(".scala")}, "HardFloat source closure changed")
    return {**data["sources"], **data["freshCompileInputs"],
            **{name: data["publicInputs"][name] for name in data.get("publicTestInputs", (gate.NATIVE, gate.FIXTURE))}}


def jar_entry(path, data):
    path = path.resolve()
    gate.need(path.is_file() and path.name in data["freshDependencyJars"], "unexpected dependency JAR: " + str(path))
    gate.need(gate.sha(path) == data["freshDependencyJars"][path.name], "dependency hash mismatch: " + path.name)
    with zipfile.ZipFile(path) as archive:
        gate.need(not any(n.startswith(("soc/", "ooo/", "hardfloat/")) and n.endswith(".class")
                          for n in archive.namelist()), "application or HardFloat fallback in dependency JAR")
    return {"path": str(path), "sha256": gate.sha(path)}


def bind_deps(args, data):
    source_closure(args.repo_root, data)
    metadata = args.mill_metadata_root or args.repo_root / "out/IonSoC/test"
    entries, sources = {}, {}
    for task in TASKS:
        path = metadata / (task + ".json")
        values = gate.read(path)["value"]
        gate.need(isinstance(values, list) and values, "empty Mill dependency resolution: " + task)
        sources[task] = {"sha256": gate.sha(path), "source": str(path.resolve())}
        for ref in values:
            gate.need(isinstance(ref, str) and re.match(r"^(?:qref|ref):v[0-9]+:[^:]+:", ref), "unsupported Mill PathRef")
            p = Path(ref.split(":", 3)[3])
            entry = jar_entry(p, data)
            gate.need(p.name not in entries or entries[p.name] == entry, "duplicate dependency identity")
            entries[p.name] = entry
    gate.need(set(entries) == set(data["freshDependencyJars"]), "resolved dependency JAR closure differs from pinned build.mill")
    gate.need(args.out is not None and not args.out.exists(), "bind-deps requires fresh --out")
    args.out.mkdir(parents=True)
    value = {"schema": "r16-fresh-dependencies-v1", "status": "PINNED_MILL_JARS_BOUND_NOT_COMPILED",
             "catalogSha256": gate.sha(gate.CATALOG), "millMetadata": sources,
             "jars": [entries[k] for k in sorted(entries)], "applicationClasses": False,
             "origin": "Repository Mill resolution metadata; no existing application or HardFloat classes accepted"}
    gate.write(args.out / "dependencies.json", value)
    return {"status": value["status"], "receiptSha256": gate.sha(args.out / "dependencies.json")}


def dependencies(directory, data):
    gate.need(directory is not None, "--deps-dir is required")
    value = gate.read(directory / "dependencies.json")
    gate.need(value.get("schema") == "r16-fresh-dependencies-v1" and
              value.get("status") == "PINNED_MILL_JARS_BOUND_NOT_COMPILED" and
              value.get("applicationClasses") is False and value["catalogSha256"] == gate.sha(gate.CATALOG),
              "unbound fresh dependencies")
    found = [jar_entry(Path(entry["path"]), data) for entry in value["jars"]]
    gate.need(found == value["jars"] and {Path(e["path"]).name for e in found} == set(data["freshDependencyJars"]),
              "dependency manifest changed")
    gate.need(len(found) == len(data["freshDependencyJars"]), "duplicate dependency JAR")
    return [Path(entry["path"]) for entry in found]


def verify(directory, repo, data):
    closure = source_closure(repo, data)
    receipt = gate.read(directory / "classes.json")
    gate.need(receipt.get("schema") == "r16-fresh-classes-v1" and receipt.get("status") == "PASS_FRESH_ISOLATED_CLASSES",
              "fresh class compilation incomplete")
    gate.need(receipt.get("oldApplicationClasspath") is False and receipt.get("productionRecompiled") is True,
              "fresh classes cannot inherit old application classes")
    gate.need(receipt["sources"] == closure and receipt["catalogSha256"] == gate.sha(gate.CATALOG) and
              receipt["compilerSha256"] == gate.sha(Path(__file__)), "fresh source/compiler binding changed")
    deps_dir = Path(receipt["dependenciesDirectory"])
    gate.need(gate.sha(deps_dir / "dependencies.json") == receipt["dependenciesReceiptSha256"], "dependency receipt changed")
    jars = dependencies(deps_dir, data)
    actual = gate.inventory(directory)
    actual.pop("classes.json", None)
    gate.need(actual == receipt["artifacts"], "fresh class/log closure changed")
    entries = []
    for name, role in (("classes-test", "test"), ("classes-main", "main"), ("classes-hardfloat", "dependency")):
        entries.append({"path": name, "role": role, "files": gate.inventory(directory / name)})
    # Reuse the class duplicate/application-fallback check without old class hashes.
    gate.validate_classpath(directory, {"classpath": entries})
    resources = [repo / "src/main/resources", repo / "src/test/resources"]
    present = {str(p.relative_to(repo)): gate.inventory(p) for p in resources if p.exists()}
    gate.need(present == receipt["resources"], "repository resources changed since compile")
    for path in resources:
        gate.need(not path.exists() or not list(path.rglob("*.class")), "application fallback in resources")
    return [directory / "classes-test", directory / "classes-main", directory / "classes-hardfloat",
            *jars, *[p for p in resources if p.exists()]]


def compile_sources(args, data):
    closure = source_closure(args.repo_root, data)
    jars = dependencies(args.deps_dir, data)
    gate.need(args.java is not None and args.java_sha256, "compile requires --java and --java-sha256")
    java = args.java.resolve()
    gate.need(java.is_file() and os.access(java, os.X_OK) and gate.sha(java) == args.java_sha256,
              "explicit Java executable hash mismatch")
    gate.need(args.out is not None and not args.out.exists(), "compile requires fresh --out")
    args.out.mkdir(parents=True)
    receipt = {"schema": "r16-fresh-classes-v1", "status": "FAIL", "sources": closure,
               "oldApplicationClasspath": False, "productionRecompiled": True, "hardwareElaborated": False,
               "catalogSha256": gate.sha(gate.CATALOG), "compilerSha256": gate.sha(Path(__file__)),
               "dependenciesDirectory": str(args.deps_dir.resolve()),
               "dependenciesReceiptSha256": gate.sha(args.deps_dir / "dependencies.json"),
               "java": {"path": str(java), "sha256": args.java_sha256}, "commands": []}
    try:
        code, version, row = gate.launch([java, "-version"], args.repo_root, args.out / "java-version.log", args.timeout)
        receipt["commands"].append(row)
        gate.need(code == 0 and re.search(r'version "21[.\"]', version), "repository flow requires JDK 21")
        plugin = next(p for p in jars if p.name == "chisel-plugin_2.13.17-7.3.0.jar")
        tests = [gate.local(args.repo_root, n) for n in data["sources"] if n.startswith("src/test/scala/")]
        tests += [gate.local(gate.PUBLIC_ROOT, n) for n in data.get("publicTestInputs", (gate.NATIVE, gate.FIXTURE))]
        phases = [("hardfloat", [gate.local(args.repo_root, n) for n in data["freshCompileInputs"] if n.endswith(".scala")], jars),
                  ("main", [gate.local(args.repo_root, n) for n in data["sources"] if n.startswith("src/main/scala/")],
                   [args.out / "classes-hardfloat", *jars]),
                  ("test", tests, [args.out / "classes-main", args.out / "classes-hardfloat", *jars])]
        for phase, sources, cp in phases:
            destination = args.out / ("classes-" + phase)
            destination.mkdir()
            command = [java, "-Xmx4g", "-XX:ActiveProcessorCount=2", "-Dchisel.project.root=" + str(args.repo_root),
                       "-cp", os.pathsep.join(map(str, jars)), "scala.tools.nsc.Main", "-language:reflectiveCalls",
                       "-deprecation", "-feature", "-Xcheckinit", "-Ymacro-annotations", "-Xplugin:" + str(plugin),
                       "-classpath", os.pathsep.join(map(str, cp)), "-d", destination, *sorted(sources)]
            code, _, row = gate.launch(command, args.repo_root, args.out / ("compile-" + phase + ".log"), args.timeout)
            row["phase"] = phase
            receipt["commands"].append(row)
            gate.need(code == 0 and list(destination.rglob("*.class")), "isolated " + phase + " compile failed")
        gate.need(source_closure(args.repo_root, data) == closure, "source changed during compile")
        dependencies(args.deps_dir, data)
        gate.need(gate.sha(java) == args.java_sha256, "Java changed during compile")
        receipt["resources"] = {str(p.relative_to(args.repo_root)): gate.inventory(p)
                                 for p in (args.repo_root / "src/main/resources", args.repo_root / "src/test/resources") if p.exists()}
        receipt["artifacts"] = gate.inventory(args.out)
        receipt["status"] = "PASS_FRESH_ISOLATED_CLASSES"
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        receipt["error"] = str(error)
        raise
    finally:
        gate.write(args.out / "classes.json", receipt)
    verify(args.out, args.repo_root, data)
    return {"status": receipt["status"], "classCount": sum(1 for p in args.out.rglob("*.class")),
            "receiptSha256": gate.sha(args.out / "classes.json"), "hardwareElaborated": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("bind-deps", "compile", "verify"))
    parser.add_argument("--repo-root", type=Path, default=gate.PUBLIC_ROOT)
    parser.add_argument("--mill-metadata-root", type=Path)
    parser.add_argument("--deps-dir", type=Path)
    parser.add_argument("--classes-dir", type=Path)
    parser.add_argument("--java", type=Path)
    parser.add_argument("--java-sha256")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()
    for key in ("repo_root", "mill_metadata_root", "deps_dir", "classes_dir", "out"):
        if getattr(args, key) is not None:
            setattr(args, key, getattr(args, key).resolve())
    try:
        gate.need(args.timeout > 0, "positive timeout required")
        data = gate.catalog()
        if args.stage == "bind-deps":
            result = bind_deps(args, data)
        elif args.stage == "compile":
            result = compile_sources(args, data)
        else:
            gate.need(args.classes_dir is not None, "verify requires --classes-dir")
            verify(args.classes_dir, args.repo_root, data)
            result = {"status": "FRESH_CLASSES_VERIFIED_NOT_ELABORATED"}
        print(json.dumps(result, sort_keys=True))
    except (OSError, ValueError, KeyError, StopIteration, zipfile.BadZipFile, subprocess.SubprocessError) as error:
        parser.exit(2, "fresh R16 compile rejected: " + str(error) + "\n")


if __name__ == "__main__":
    main()
