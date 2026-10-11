#!/usr/bin/env python3
"""Bounded actual-machine CSR/range publication qualification; preflight by default."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import run as common

TOP = "PmpCsrPublicationGsim"
EMITTER = "ooo.PmpCsrPublicationGsimMain"
HARNESS = "pmp_csr_publication.cpp"
ANCHOR = "PMP publication oracle mismatch"
MUTATIONS = (
    ("stale-raw-decode", "nextPmpState.addr := pmpAddrWrite", "nextPmpState.addr := pmpAddr"),
    ("drop-tor-predecessor", "when(pmpCfg(i + 1)(4, 3) === 1.U) { enables(i + 1) := true.B }",
     "when(false.B) { enables(i + 1) := true.B }"),
)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def cases():
    return [(f"entries-{n}-" + ("registered" if registered else "live"), n, registered)
            for n in (0, 8, 16) for registered in (False, True) if n or not registered]


def structure(fir):
    """Pre-mapping declared structure, never a synthesized FF/LUT/fanout result."""
    text = Path(fir).read_text()
    regs = re.findall(r"(?m)^\s*regreset (pmpRegion(?:Low|End|Active)_\d+) : UInt<(\d+)>", text)
    return {"derived_registers": len(regs), "derived_declared_bits": sum(int(w) for _, w in regs),
            "register_names": [name for name, _ in regs], "mapped_resources": None,
            "declared_local_enable_load_upper_bound": 131,
            "csr_update_path": "captured CSR operand/readValue -> RW/RS/RC -> filtered next cfg/addr -> shared range decode -> derived D",
            "csr_update_path_timing": "UNMEASURED", "mapped_enable_fanout": None,
            "physical_qualification": False}


def classpath(key):
    values = json.loads((common.ROOT / "out/IonSoC/test" / (key + ".json")).read_text())["value"]
    result = [value.split(":", 3)[3] for value in values]
    optional = {common.ROOT / module / resource
                for module in ("", "third_party/berkeley-hardfloat")
                for resource in ("compile-resources", "src/main/resources", "src/test/resources")}
    if not result or any(not Path(p).exists() and Path(p) not in optional for p in result):
        raise RuntimeError("missing exact compiled classpath: " + key)
    return result


def mutate(out, gsim, cxx, name, old, new):
    """Use the established private class-overlay mutation flow; never edit passed source/classes."""
    directory = out / ("mutant-" + name)
    classes = directory / "classes"
    classes.mkdir(parents=True)
    source = common.ROOT / "src/main/scala/core/ooo/MachineSystemUnit.scala"
    original = source.read_text()
    if original.count(old) != 1:
        raise RuntimeError("mutation anchor drift: " + name)
    mutated = directory / source.name
    mutated.write_text(original.replace(old, new))
    cp = ":".join(classpath("runClasspath"))
    compiler_cp = ":".join(classpath("scalaCompilerClasspath"))
    plugin = next(p for p in classpath("scalacPluginClasspath") if "chisel-plugin" in p)
    java = shutil.which("java")
    if not java:
        raise RuntimeError("Java runtime unavailable for isolated mutation compile")
    common.run([java, "-cp", compiler_cp, "scala.tools.nsc.Main", "-classpath", cp, "-Xplugin:" + plugin,
                "-language:reflectiveCalls", "-d", classes, mutated], log=directory / "compile-overlay.log")
    model = directory / "model"
    model.mkdir()
    common.run([java, "-cp", str(classes) + ":" + cp, EMITTER, model, "entries=16", "registered"],
               log=directory / "elaborate.log")
    common.run([gsim, "--threads=1", "--cpp-max-size-KB=1024", "--dir=" + str(model), model / (TOP + ".fir")],
               log=directory / "generate.log")
    common.run([cxx, "-std=c++20", "-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                "-DPMP_ENTRIES=16", "-I" + str(model), *sorted(model.glob(TOP + "[0-9]*.cpp")),
                common.HERE / "harness" / HARNESS, "-ldl", "-o", model / "run"], log=directory / "compile.log")
    result = subprocess.run([model / "run"], capture_output=True, text=True, timeout=120,
                            env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
    log = result.stdout + result.stderr
    (directory / "negative.log").write_text(log)
    if result.returncode != 1 or ANCHOR not in log:
        raise RuntimeError("actual-source mutant was not rejected by the publication oracle: " + name)
    return {"status": "REJECTED", "exit": result.returncode, "anchor": ANCHOR,
            "mutated_source_sha256": sha(mutated), "log": log}


def main():
    ap = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--build-run", action="store_true")
    a = ap.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", a.tag):
        ap.error("unsafe tag")
    if not a.build_run:
        print(json.dumps({"status": "PREFLIGHT_ONLY", "models": cases(),
                          "source_mutants": [m[0] for m in MUTATIONS], "synthesis": False,
                          "physical_qualification": False}, indent=2))
        return
    out = common.BUILD / a.tag
    out.mkdir(parents=True, exist_ok=False)
    files = sorted((common.ROOT / "src").rglob("*.scala")) + [
        common.ROOT / "build.mill", common.ROOT / ".mill-version", common.HERE / "run.py",
        common.HERE / "config/toolchain.json", Path(__file__), common.HERE / "harness" / HARNESS,
        common.HERE / "harness/pmp_csr_oracle.h"]
    before = {str(p.relative_to(common.ROOT)): sha(p) for p in files}
    receipt = {"status": "RUNNING", "inputs": before, "cases": {}, "mutants": {},
               "synthesis": False, "physical_qualification": False}
    try:
        common.SOURCE = Path(os.environ.get("VALENCE_GSIM_SOURCE", str(common.SOURCE))).resolve()
        gsim, cxx = common.setup(False)
        receipt["toolchain"] = {**json.loads((common.BUILD / "toolchain-used.json").read_text()),
                                "gsim_binary_sha256": sha(gsim), "gsim_source": str(common.SOURCE), "cxx": str(cxx)}
        for name, entries, registered in cases():
            parameters = (f"entries={entries}",) + (("registered",) if registered else ())
            model = common.test(gsim, cxx, a.tag + "/" + name, EMITTER, TOP, HARNESS,
                                parameters=parameters, defines={"PMP_ENTRIES": entries}, timeout=120,
                                gsim_options=("--cpp-max-size-KB=1024",))
            negative = subprocess.run([model / "run", "--inject-mismatch"], capture_output=True, text=True,
                                      timeout=120, env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
            log = negative.stdout + negative.stderr
            (model / "negative.log").write_text(log)
            if negative.returncode != 1 or ANCHOR not in log:
                raise RuntimeError("oracle negative control did not reject intended mismatch: " + name)
            facts = structure(model / (TOP + ".fir"))
            expected = entries * 131 if registered else 0
            if facts["derived_declared_bits"] != expected:
                raise RuntimeError("actual machine CSR range-register structure differs: " + name)
            receipt["cases"][name] = {"status": "PASS", "log": (model / "test.log").read_text(),
                                       "structure": facts, "negative_exit": negative.returncode,
                                       "parameters": parameters, "fir_sha256": sha(model / (TOP + ".fir"))}
            (out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        for entries in (8, 16):
            live = receipt["cases"][f"entries-{entries}-live"]["log"]
            registered = receipt["cases"][f"entries-{entries}-registered"]["log"]
            if live != registered:
                raise RuntimeError("matched cycle/CSR/flush coverage changed")
        for mutation in MUTATIONS:
            receipt["mutants"][mutation[0]] = mutate(out, gsim, cxx, *mutation)
        if before != {str(p.relative_to(common.ROOT)): sha(p) for p in files}:
            raise RuntimeError("source changed during qualification")
        receipt["status"] = "PASS"
    except Exception as error:
        receipt["status"] = "FAIL"
        receipt["error"] = str(error)
        raise
    finally:
        (out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    main()
