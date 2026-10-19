#!/usr/bin/env python3
"""Short batched I1 privileged/MMU acceptance; no Vivado, OoO simulation or long OS boot."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "simulator/gsim"))
import run as common
sys.path.insert(0, str(ROOT / "simulator/gsim/inorder"))
from soc_acceptance import sources, sha

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tag", required=True)
    args = ap.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.tag):
        ap.error("safe unique tag required")
    output = ROOT / "build/gsim" / ("five-stage-privilege-" + args.tag)
    if output.exists():
        ap.error("refusing to overwrite evidence")
    output.mkdir(parents=True)
    frozen = sources()
    receipt = {"status": "RUNNING", "source_sha256": frozen, "checks": {}, "physical_qualified": False,
        "scope": "Five-stage I1 only: M/S/U, delegation, PMP, Sv39/Svade, PLIC M/S; short independent and CPU tests",
        "profile": {"xlen": 64, "pmp_writable": 4, "pmp_csr_bank": 16, "pa_bits": 36, "itlb": 4, "dtlb": 4,
                    "asid_bits": 0, "ad_policy": "Svade", "icache": 2048, "dcache": 2048},
        "ooo_modified": False, "linux_boot_qualified": False, "pipeline": ["IF", "ID", "EX", "MEM", "WB"]}
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
        common.run(["mill", "-i", "OrbitalI1.test.testOnly", "inorder.FiveStageConfigSpec"],
                   log=output / "scala.log")
        def model(name, entry, top, driver, flags=(), defines=()):
            print("BUILD", name, flush=True)
            out = output / name
            out.mkdir()
            common.run(["mill", "-i", "OrbitalI1.test.runMain", entry, out, 64, *flags],
                       log=out / "elaborate.log")
            common.run([gsim, "--threads=1", f"--dir={out}", out / (top + ".fir")], log=out / "generate.log")
            common.run([cxx, "-std=c++20", "-O1", "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                        "-DDUT_XLEN=64", "-I" + str(out), *sorted(out.glob(top + "[0-9]*.cpp")), *defines,
                        ROOT / "simulator/gsim/harness" / driver, "-o", out / "run"],
                       log=out / "compile.log", timeout=900)
            return out
        def check(name, out, argv=(), negative=None):
            common.run([out / "run", *argv], log=out / (name + ".log"), env=env, timeout=180)
            receipt["checks"][name] = (out / (name + ".log")).read_text().strip()
            print(receipt["checks"][name], flush=True)
            if negative:
                bad_args, message = negative
                bad = subprocess.run([str(out / "run"), *map(str, bad_args)], env=env,
                                     capture_output=True, text=True, timeout=180)
                (out / (name + "-negative.log")).write_text(bad.stdout + bad.stderr)
                if bad.returncode == 0 or message not in bad.stdout + bad.stderr:
                    raise RuntimeError("negative control failed: " + name)
                receipt["checks"][name + "-negative"] = "PASS_REJECTED_INDEPENDENT_MUTATION"
        out = model("privilege", "inorder.FiveStagePrivilegeMain", "FiveStagePrivilegeHarness",
                    "five_stage_privilege.cpp")
        check("privilege", out, negative=(["--wrong-delegation"], "independent delegated vector oracle"))
        out = model("translation", "inorder.FiveStageTranslationMain", "FiveStageTranslationHarness",
                    "five_stage_translation.cpp")
        check("translation", out, negative=(["--wrong-page"], "independent Sv39/PMP/page-vs-access fault oracle"))
        out = model("instruction-translation", "inorder.FiveStageTranslationMain", "FiveStageTranslationHarness",
                    "five_stage_translation.cpp", ["--instruction"], ["-DI1_INSTRUCTION_TRANSLATION"])
        check("instruction-translation", out,
              negative=(["--wrong-page"], "independent Sv39/PMP/page-vs-access fault oracle"))
        out = model("cache-boundary", "inorder.FiveStageCacheMain", "FiveStageWordCache",
                    "five_stage_cache.cpp", ["--dcache=512", "--overlap-write-lookup"])
        check("cache-boundary", out)
        out = model("plic", "inorder.FiveStagePlicMain", "FiveStagePlicHarness", "five_stage_plic.cpp")
        check("plic", out, negative=(["--wrong-claim"], "PLIC reply payload/side-effect oracle"))
        here = ROOT / "simulator/gsim/inorder"
        def payload(name, source, linker):
            common.run(["riscv64-unknown-elf-gcc", "-march=rv64i_zicsr_zifencei", "-mabi=lp64",
                        "-mcmodel=medany", "-mno-relax", "-nostdlib", "-nostartfiles", "-Wl,--no-relax",
                        "-T" + str(here / linker), here / source, "-o", output / (name + ".elf")],
                       log=output / (name + "-build.log"))
            common.run(["riscv64-unknown-elf-objcopy", "-O", "binary", output / (name + ".elf"),
                        output / (name + ".bin")], log=output / (name + "-objcopy.log"))
            return output / (name + ".bin")
        image = payload("privileged", "privilege_smoke.S", "privilege_link.ld")
        fast = ["--icache=2048", "--dcache=2048", "--predictor=64",
                "--early-memory-issue", "--overlap-write-lookup", "--soc-no-bootrom"]
        out = model("soc-privileged", "inorder.FiveStageSocMain", "FiveStageSoc",
                    "five_stage_privilege_soc.cpp", [*fast, "--sv39", "--pmp=4"])
        check("soc-privileged", out, [image],
              negative=([image, "--wrong-result"], "independent privileged SoC result ledger oracle"))
        stream = payload("stream", "privilege_throughput.S", "soc_link.ld")
        check("stream-bare", out, [stream, "--bare-throughput"])
        check("stream-sv39", out, [stream, "--sv39-throughput"])
        baseline = payload("baseline", "soc_smoke.S", "soc_link.ld")
        out = model("soc-m-only", "inorder.FiveStageSocMain", "FiveStageSoc", "five_stage_soc.cpp", fast)
        check("soc-m-only", out, [baseline])
        # Removability/width checks only; no claim these additional profiles were behaviorally validated.
        for name, width, options in (("rv32-su-pmp", 32, ["--supervisor", "--pmp=4"]),
                                     ("rv64-stripped", 64, ["--no-m"])):
            out = output / name
            out.mkdir()
            common.run(["mill", "-i", "OrbitalI1.test.runMain", "inorder.FiveStageCachedMain",
                        out, width, *options], log=out / "elaborate.log")
            fir = (out / "FiveStageCachedCore.fir").read_text()
            if name == "rv64-stripped" and ("module FiveStageAddressTranslation" in fir or
                                           "module FiveStagePmp" in fir):
                raise RuntimeError("disabled translation/protection hardware did not disappear")
            receipt["checks"][name] = "PASS_ELABORATION_ONLY"
        if sources() != frozen:
            raise RuntimeError("source drift during acceptance")
        receipt["status"] = "PASS_I1_MSU_PMP_SV39_PLIC_S_SHORT_ONLY"
    except Exception as error:
        receipt["status"] = "FAIL"; receipt["error"] = repr(error)
        raise
    finally:
        receipt["artifact_sha256"] = {str(p.relative_to(output)): sha(p) for p in output.rglob("*") if p.is_file()}
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2))
        print(json.dumps({"status": receipt["status"], "receipt": str(output / "receipt.json")}), flush=True)
if __name__ == "__main__":
    main()
