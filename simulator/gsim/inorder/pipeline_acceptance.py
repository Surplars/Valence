#!/usr/bin/env python3
"""Batched real 5/7/8-stage acceptance: affected units, CPU ledgers and matched short O3; no synthesis."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "simulator/gsim"))
import run as common
sys.path.insert(0, str(ROOT / "simulator/gsim/inorder"))
from soc_acceptance import sources, sha
from ca_acceptance import FLAGS

PROFILES = {
    "compact5": ["IF", "ID", "EX", "MEM", "WB"],
    "balanced7": ["IF", "ID", "EX", "ADDR", "MEM", "CMP", "WB"],
    "fpga8": ["IF", "ID", "RF", "EX", "ADDR", "MEM", "CMP", "WB"],
}

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--firmware", required=True, type=Path)
    ap.add_argument("--reuse-evidence", type=Path,
                    help="Reuse ONLY hash-identical models/checks completed before a failed batch; rerun changed drivers")
    args = ap.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.tag):
        ap.error("safe fresh tag required")
    output = ROOT / "build/gsim" / ("inorder-pipeline-" + args.tag)
    if output.exists():
        ap.error("refusing to overwrite evidence")
    output.mkdir(parents=True)
    def frozen_sources():
        result = sources()
        for name in ("src/main/resources/inorder/bootrom.hex", "simulator/gsim/inorder/opensbi_i1.dts"):
            result[name] = sha(ROOT / name)
        return result
    frozen = frozen_sources()
    receipt = {
        "status": "RUNNING", "source_sha256": frozen, "checks": {}, "benchmarks": {}, "streams": {},
        "profiles": PROFILES, "soc_flags": FLAGS, "cpu_hz_reference_only": 100000000,
        "ooo_modified": False, "physical_qualified": False, "linux_boot_qualified": False,
        "formal_coremark": False, "target_hz_not_qualified": [200000000, 300000000],
        "cache": {"i_bytes": 2048, "d_bytes": 2048, "line_bytes": 64, "ways": 1,
                  "write": "precise write-through, no-write-allocate"},
        "atomic_contract": "single hart exclusive runtime writer; no live external DMA/coherence",
        "coremark_contract": "One identical RV64IM -O3 binary, standard 2000 bytes, one short iteration. "
            "Independent instruction/register/memory oracle and official CRCs. Not a >=10s score.",
    }
    def save():
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    save()
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}
    try:
        gs = Path("/home/openion/Valence/simulator/build/gsim-src")
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=gs, text=True).strip()
        if revision != common.LOCK["revision"] or subprocess.check_output(
                ["git", "status", "--porcelain", "--untracked-files=no"], cwd=gs, text=True):
            raise RuntimeError("GSIM pin/cleanliness mismatch")
        gsim = gs / "build/gsim/gsim"
        cxx, version = common.compiler()
        receipt["tools"] = {"gsim_revision": revision, "gsim_sha256": sha(gsim), "cxx": version}
        prior = None
        if args.reuse_evidence:
            prior = json.loads(args.reuse_evidence.read_text())
            if prior["tools"] != receipt["tools"] or prior["profiles"] != PROFILES or prior["soc_flags"] != FLAGS:
                raise RuntimeError("reuse tool/configuration mismatch")
            receipt["reuse_receipt"] = {"path": str(args.reuse_evidence.resolve()), "sha256": sha(args.reuse_evidence)}
        def prior_file(relative):
            path = args.reuse_evidence.parent / relative
            if not path.is_file() or prior["artifact_sha256"].get(relative) != sha(path):
                raise RuntimeError("reuse artifact drift: " + relative)
            return path
        driver_dependencies = {}
        model_identical = {}
        firmware = json.loads(args.firmware.read_text())
        for name, digest in firmware["source_sha256"].items():
            if sha(ROOT / name) != digest:
                raise RuntimeError("firmware source drift: " + name)
        for name, digest in firmware["files_sha256"].items():
            if sha(args.firmware.parent / name) != digest:
                raise RuntimeError("firmware artifact drift: " + name)
        receipt["firmware_manifest"] = {"path": str(args.firmware.resolve()), "sha256": sha(args.firmware)}
        common.run(["mill", "-i", "OrbitalI1.test.testOnly", "inorder.FiveStageConfigSpec"],
                   log=output / "scala.log")
        options = ["-std=c++20", "-O1", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
        def model(name, entry, top, flags=(), width=64):
            print("BUILD", name, flush=True)
            out = output / name
            out.mkdir()
            common.run(["mill", "-i", "OrbitalI1.test.runMain", "inorder." + entry, out, width, *flags],
                       log=out / "elaborate.log")
            fir_key = name + "/" + top + ".fir"
            reusable = bool(prior and prior["artifact_sha256"].get(fir_key) == sha(out / (top + ".fir")))
            model_identical[out] = reusable
            if reusable:
                # Re-elaboration proves exact CHIRRTL identity, independent of the old Python build recipe.
                old = args.reuse_evidence.parent / name
                for path in old.iterdir():
                    if path.is_file() and path.suffix in (".o", ".h", ".cpp"):
                        shutil.copy2(prior_file(name + "/" + path.name), out / path.name)
                receipt.setdefault("reused_models", {})[name] = "EXACT_FIR_TOOL_AND_ARTIFACT_HASH_IDENTITY"
                print("REUSE identical model", name, flush=True)
            else:
                common.run([gsim, "--threads=1", f"--dir={out}", out / (top + ".fir")],
                           log=out / "generate.log")
            objects = []
            for source in sorted(out.glob(top + "[0-9]*.cpp")):
                obj = source.with_suffix(".o")
                if not obj.is_file():
                    common.run([cxx, *options, "-I" + str(out), "-c", source, "-o", obj],
                               log=obj.with_suffix(".log"), timeout=900)
                objects.append(obj)
            def driver(name, source, defines=()):
                binary = out / name
                dependencies = {}
                def collect(path):
                    key = str(path.relative_to(ROOT))
                    if key in dependencies:
                        return
                    dependencies[key] = sha(path)
                    for include in re.findall(r'(?m)^#include "([^"]+)"', path.read_text()):
                        included = path.parent / include
                        if included.is_file():
                            collect(included)
                collect(ROOT / "simulator/gsim/harness" / source)
                driver_dependencies[binary] = dependencies
                common.run([cxx, *options, f"-DDUT_XLEN={width}", *defines, "-I" + str(out),
                            *objects, ROOT / "simulator/gsim/harness" / source, "-o", binary],
                           log=out / (name + "-compile.log"), timeout=900)
                return binary
            return out, driver
        def check(name, binary, argv=(), negative=None, timeout=240):
            print("RUN", name, flush=True)
            log = binary.parent / (name + ".log")
            same_inputs = bool(prior and model_identical[binary.parent] and name in prior["checks"] and
                all(prior["source_sha256"].get(p) == h for p, h in driver_dependencies[binary].items()))
            for arg in argv:
                path = Path(str(arg))
                if path.is_file() and prior:
                    if path.resolve().is_relative_to(output.resolve()):
                        key = str(path.resolve().relative_to(output.resolve()))
                        same_inputs = same_inputs and prior["artifact_sha256"].get(key) == sha(path)
                    elif path.resolve().is_relative_to(ROOT):
                        key = str(path.resolve().relative_to(ROOT))
                        same_inputs = same_inputs and (
                            prior["source_sha256"].get(key) == sha(path) or
                            prior.get("firmware_manifest") == receipt.get("firmware_manifest"))
                    else:
                        same_inputs = False
            if negative:
                same_inputs = same_inputs and prior is not None and name + "-negative" in prior["checks"]
            if same_inputs:
                key = str(log.relative_to(output))
                shutil.copy2(prior_file(key), log)
                result = log.read_text().strip()
                if result != prior["checks"][name]:
                    raise RuntimeError("reused result/log mismatch")
                receipt["checks"][name] = result
                if negative:
                    key = str(log.with_name(name + "-negative.log").relative_to(output))
                    shutil.copy2(prior_file(key), output / key)
                    receipt["checks"][name + "-negative"] = prior["checks"][name + "-negative"]
                receipt.setdefault("reused_checks", {})[name] = {
                    "source": str(args.reuse_evidence.resolve()),
                    "basis": "exact newly elaborated FIR, pinned tool, recursive driver and input artifact hashes",
                    "fresh_run": False,
                }
                print("REUSE qualified identical check", name, flush=True)
                save()
                return result
            common.run([binary, *argv], log=log, env=env, timeout=timeout)
            result = log.read_text().strip()
            receipt["checks"][name] = result
            print(result, flush=True)
            save()
            if negative:
                flag, message = negative
                bad = subprocess.run([str(binary), *map(str, argv), flag], env=env,
                                     capture_output=True, text=True, timeout=timeout, cwd=ROOT)
                log.with_name(name + "-negative.log").write_text(bad.stdout + bad.stderr)
                if bad.returncode == 0 or message not in bad.stdout + bad.stderr:
                    raise RuntimeError("negative control not rejected: " + name)
                receipt["checks"][name + "-negative"] = "PASS_REJECTED_INDEPENDENT_MUTATION"
                save()
            return result
        # Independent modified range/permission/atomic modules. Unchanged C expansion is not redundantly rerun.
        out, build_driver = model("pmp-csr", "FiveStagePrivilegeMain", "FiveStagePrivilegeHarness")
        check("pmp-csr", build_driver("run", "five_stage_privilege.cpp"),
              negative=("--wrong-delegation", "independent delegated vector oracle"))
        for width in (32, 64):
            out, build_driver = model("atomic" + str(width), "FiveStageAtomicMain", "FiveStageAtomicMemory",
                                      width=width)
            check("atomic" + str(width), build_driver("run", "five_stage_atomic.cpp"),
                  negative=("--wrong-amo", "independent LR_SC_AMO result oracle"))
        for registers in (False, True):
            name = "route-registers" if registers else "route-memory"
            out, build_driver = model(name, "FiveStageRouteMain", "FiveStageTileLinkRoute",
                                      ["--registers"] if registers else [])
            binary = build_driver("run", "five_stage_route.cpp", ["-DALLOW_REGISTERS=" + str(int(registers))])
            check(name, binary, negative=("--wrong-route", "independent route destination oracle"))
        out, build_driver = model("bootrom", "FiveStageBootRomMain", "FiveStageBootRomHarness",
                                  ["src/main/resources/inorder/bootrom.hex"])
        check("bootrom", build_driver("run", "five_stage_boot_rom.cpp"),
              ["src/main/resources/inorder/bootrom.hex"],
              ("--wrong-rom", "ROM held reply/data/deny oracle"))
        here = ROOT / "simulator/gsim/inorder"
        def payload(name, source, linker, isa):
            common.run(["riscv64-unknown-elf-gcc", "-march=" + isa, "-mabi=lp64",
                        "-mcmodel=medany", "-mno-relax", "-nostdlib", "-nostartfiles", "-Wl,--no-relax",
                        "-T" + str(here / linker), here / source, "-o", output / (name + ".elf")],
                       log=output / (name + "-build.log"))
            common.run(["riscv64-unknown-elf-objcopy", "-O", "binary", output / (name + ".elf"),
                        output / (name + ".bin")], log=output / (name + "-objcopy.log"))
            return output / (name + ".bin")
        ca = payload("ca", "ca_smoke.S", "soc_link.ld", "rv64imac_zicsr_zifencei")
        privileged = payload("privileged", "privilege_smoke.S", "privilege_link.ld", "rv64i_zicsr_zifencei")
        stream = payload("stream", "privilege_throughput.S", "soc_link.ld", "rv64i_zicsr_zifencei")
        for profile in PROFILES:
            out, build_driver = model("soc-" + profile, "FiveStageSocGsimMain", "FiveStageSoc",
                                      [*FLAGS, "--pipeline=" + profile])
            binary = build_driver("ca", "five_stage_ca_soc.cpp", ["-DI1_HAS_ROM=1"])
            check(profile + "-ca-cross-page", binary, [ca],
                  ("--wrong-result", "independent C/A completion/alias/boundary oracle"))
            check(profile + "-ca-page-end", binary, [ca, "--compressed-boundary"])
            binary = build_driver("privilege", "five_stage_privilege_soc.cpp", ["-DI1_HAS_ROM=1"])
            check(profile + "-privilege", binary, [privileged])
            for mode in ("bare", "sv39"):
                result = check(profile + "-" + mode + "-stream", binary, [stream, "--" + mode + "-throughput"])
                receipt["streams"][profile + "-" + mode] = result
                save()
            if profile == "fpga8":
                binary = build_driver("opensbi", "five_stage_opensbi.cpp", ["-DI1_HAS_ROM=1"])
                segments = [args.firmware.parent / s["file"] for s in firmware["segments"]]
                check("fpga8-stock-opensbi-s-handoff", binary, segments,
                      ("--wrong-handoff", "independent stock OpenSBI handoff ledger oracle"), timeout=360)
        for profile in PROFILES:
            for width in (32, 64):
                out, build_driver = model("core-" + profile + "-" + str(width), "FiveStageMain", "FiveStageCore",
                    ["--pipeline=" + profile, "--dsp-tiled", "--early-memory-issue"], width)
                binary = build_driver("run", "five_stage_early_memory.cpp",
                                      ["-DDUT_PIPELINE_STAGES=" + str(len(PROFILES[profile]))])
                check(profile + "-integer" + str(width), binary,
                      negative=("--inject-store-mismatch", "independent store intent data mismatch"))
        # Removable bypass and M hardware: the deepest pipeline still executes and drains correctly.
        out, build_driver = model("core-fpga8-small", "FiveStageMain", "FiveStageCore",
            ["--pipeline=fpga8", "--no-m", "--no-memory-bypass", "--early-memory-issue"])
        check("fpga8-no-m-no-bypass", build_driver("run", "five_stage_early_memory.cpp",
            ["-DDUT_HAS_M=0", "-DDUT_MEM_BYPASS=0", "-DDUT_PIPELINE_STAGES=8"]))
        # One O3 standard binary and one common memory service law; no OoO rerun.
        coremark = Path("/home/openion/Valence/simulator/build/coremark-src")
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=coremark, text=True).strip()
        if revision != "1f483d5b8316753a742cbf5590caf5bd0a4e4777" or subprocess.check_output(
                ["git", "status", "--porcelain", "--untracked-files=no"], cwd=coremark, text=True):
            raise RuntimeError("CoreMark pin/cleanliness mismatch")
        port = here / "coremark_port"
        old = ROOT / "simulator/gsim/payloads/coremark_port"
        cflags = ["-O3", "-march=rv64im_zicsr_zifencei", "-mabi=lp64", "-mcmodel=medany",
                  "-mno-relax", "-msmall-data-limit=0", "-ffreestanding", "-fno-builtin",
                  "-fno-stack-protector", "-nostdlib", "-nostartfiles", "-DITERATIONS=1",
                  "-DPERFORMANCE_RUN=1", "-DTOTAL_DATA_SIZE=2000",
                  '-DCOMPILER_FLAGS="-O3 -march=rv64im_zicsr_zifencei -mabi=lp64"']
        guest = [coremark / f for f in ("core_list_join.c", "core_main.c", "core_matrix.c",
                                      "core_state.c", "core_util.c")]
        common.run(["riscv64-unknown-elf-gcc", *cflags, "-I" + str(port), "-I" + str(coremark),
                    "-T" + str(old / "link.ld"), old / "start.S", *guest, port / "core_portme.c", "-lgcc",
                    "-o", output / "coremark.elf"], log=output / "coremark-build.log")
        common.run(["riscv64-unknown-elf-objcopy", "-O", "binary", output / "coremark.elf",
                    output / "coremark.bin"], log=output / "coremark-objcopy.log")
        symbols = subprocess.check_output(["riscv64-unknown-elf-nm", "-n", output / "coremark.elf"], text=True)
        (output / "coremark-symbols.txt").write_text(symbols)
        values = {line.split()[-1]: int(line.split()[0], 16) for line in symbols.splitlines()
                  if len(line.split()) == 3}
        receipt["coremark_payload"] = {"sha256": sha(output / "coremark.bin"), "flags": cflags,
                                       "source_revision": revision}
        fast = ["--dsp-tiled", "--early-memory-issue", "--overlap-write-lookup",
                "--icache=2048", "--dcache=2048", "--predictor=128"]
        for profile in PROFILES:
            out, build_driver = model("coremark-" + profile, "FiveStageCachedMain", "FiveStageCachedCore",
                                      [*fast, "--pipeline=" + profile])
            binary = build_driver("run", "five_stage_coremark.cpp")
            for delay in (1, 12):
                name = profile + "-O3-l" + str(delay)
                argv = [output / "coremark.bin", hex(values["coremark_validation_errors"]),
                        hex(values["coremark_elapsed_ticks"]), hex(values["coremark_crcs"]), delay]
                result = check(name, binary, argv,
                    ("--inject", "independent register oracle mismatch") if delay == 12 else None)
                if not result.startswith("MATCHED_COREMARK_PASS "):
                    raise RuntimeError("missing independent CoreMark/CRC gate")
                result = json.loads(result.split(" ", 1)[1])
                result["roi_ipc"] = result["roi_instructions"] / result["roi_ticks"]
                receipt["benchmarks"][name] = result
                save()
        cohort = list(receipt["benchmarks"].values())
        if len({(r["trace_fnv64"], r["retired"], r["crcfinal"], r["roi_instructions"]) for r in cohort}) != 1:
            raise RuntimeError("architectural stream drift between pipeline profiles")
        receipt["frequency_break_even"] = {
            profile: {str(delay): receipt["benchmarks"][profile + "-O3-l" + str(delay)]["roi_ticks"] /
                      receipt["benchmarks"]["compact5-O3-l" + str(delay)]["roi_ticks"] for delay in (1, 12)}
            for profile in PROFILES
        }
        if frozen_sources() != frozen:
            raise RuntimeError("source drift during batched pipeline acceptance")
        receipt["status"] = "PASS_PARAMETERIZED_5_7_8_STAGE_SHORT_ONLY"
    except BaseException as error:
        receipt["status"] = "FAIL"
        receipt["error"] = repr(error)
        raise
    finally:
        receipt["artifact_sha256"] = {str(p.relative_to(output)): sha(p) for p in output.rglob("*")
                                      if p.is_file() and p.name != "receipt.json"}
        save()
        print(json.dumps({"status": receipt["status"], "receipt": str(output / "receipt.json")}), flush=True)
if __name__ == "__main__":
    main()
