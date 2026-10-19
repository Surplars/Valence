#!/usr/bin/env python3
"""Short integrated C/A + stock OpenSBI boot, exact ROM/caches/MMU/PLIC profile; no synthesis."""
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
FLAGS = ["--c", "--a", "--sv39", "--pmp=8", "--tlb=4", "--icache=2048", "--dcache=2048",
         "--predictor=128", "--dsp-tiled", "--early-memory-issue", "--overlap-write-lookup"]

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--units", required=True, type=Path)
    ap.add_argument("--firmware", required=True, type=Path)
    args = ap.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.tag):
        ap.error("safe fresh tag required")
    output = ROOT / "build/gsim" / ("five-stage-ca-soc-" + args.tag)
    if output.exists():
        ap.error("fresh evidence required")
    output.mkdir(parents=True)
    frozen = sources()
    frozen["src/main/resources/inorder/bootrom.hex"] = sha(ROOT / "src/main/resources/inorder/bootrom.hex")
    frozen["simulator/gsim/inorder/opensbi_i1.dts"] = sha(ROOT / "simulator/gsim/inorder/opensbi_i1.dts")
    receipt = {"status": "RUNNING", "source_sha256": frozen, "checks": {}, "flags": FLAGS,
               "pipeline": ["IF", "ID", "EX", "MEM", "WB"], "xlen": 64, "cpu_hz": 100000000,
               "uart_baud": 460800, "icache_bytes": 2048, "dcache_bytes": 2048,
               "atomic_contract": "single hart exclusive runtime writer; no live external DMA/coherence qualification",
               "linux_boot_qualified": False, "physical_qualified": False, "ooo_modified": False}
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}
    try:
        units = json.loads(args.units.read_text())
        if units["status"] != "PASS_I1_C_A_MODULES_SHORT_ONLY":
            raise RuntimeError("passing C/A units required")
        for name, digest in units["source_sha256"].items():
            if sha(ROOT / name) != digest:
                raise RuntimeError("C/A unit source drift: " + name)
        for name, digest in units["artifact_sha256"].items():
            if sha(args.units.parent / name) != digest:
                raise RuntimeError("C/A unit artifact drift: " + name)
        firmware = json.loads(args.firmware.read_text())
        for name, digest in firmware["source_sha256"].items():
            if sha(ROOT / name) != digest:
                raise RuntimeError("firmware source drift: " + name)
        for name, digest in firmware["files_sha256"].items():
            if sha(args.firmware.parent / name) != digest:
                raise RuntimeError("firmware artifact drift: " + name)
        receipt["module_receipt"] = {"path": str(args.units.resolve()), "sha256": sha(args.units)}
        receipt["firmware_manifest"] = {"path": str(args.firmware.resolve()), "sha256": sha(args.firmware)}
        gs = Path("/home/openion/Valence/simulator/build/gsim-src")
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=gs, text=True).strip()
        if revision != common.LOCK["revision"] or subprocess.check_output(
                ["git", "status", "--porcelain", "--untracked-files=no"], cwd=gs, text=True):
            raise RuntimeError("GSIM pin/cleanliness mismatch")
        gsim = gs / "build/gsim/gsim"
        cxx, version = common.compiler()
        receipt["tools"] = {"gsim_revision": revision, "gsim_sha256": sha(gsim), "cxx": version}
        out = output / "soc"
        out.mkdir()
        print("BUILD exact C/A ROM SoC", flush=True)
        common.run(["mill", "-i", "OrbitalI1.test.runMain", "inorder.FiveStageSocGsimMain", out, 64, *FLAGS],
                   log=out / "elaborate.log")
        common.run([gsim, "--threads=1", f"--dir={out}", out / "FiveStageSoc.fir"], log=out / "generate.log")
        objects = []
        for source in sorted(out.glob("FiveStageSoc[0-9]*.cpp")):
            obj = source.with_suffix(".o")
            common.run([cxx, "-std=c++20", "-O1", "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                        "-I" + str(out), "-c", source, "-o", obj], log=obj.with_suffix(".log"), timeout=900)
            objects.append(obj)
        def driver(name, file):
            binary = out / name
            common.run([cxx, "-std=c++20", "-O1", "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                        "-DDUT_XLEN=64", "-DI1_HAS_ROM=1", "-I" + str(out), *objects,
                        ROOT / "simulator/gsim/harness" / file, "-o", binary], log=out / (name + "-compile.log"))
            return binary
        def check(name, binary, argv, negative=None):
            print("RUN", name, flush=True)
            common.run([binary, *argv], log=out / (name + ".log"), env=env, timeout=240)
            receipt["checks"][name] = (out / (name + ".log")).read_text().strip()
            print(receipt["checks"][name], flush=True)
            if negative:
                bad = subprocess.run([str(binary), *map(str, argv), negative[0]], env=env,
                                     capture_output=True, text=True, timeout=240, cwd=ROOT)
                (out / (name + "-negative.log")).write_text(bad.stdout + bad.stderr)
                if bad.returncode == 0 or negative[1] not in bad.stdout + bad.stderr:
                    raise RuntimeError("negative control failed: " + name)
                receipt["checks"][name + "-negative"] = "PASS_REJECTED_INDEPENDENT_MUTATION"
        here = ROOT / "simulator/gsim/inorder"
        def payload(name, source, linker, isa):
            common.run(["riscv64-unknown-elf-gcc", "-march=" + isa, "-mabi=lp64",
                        "-mcmodel=medany", "-mno-relax", "-nostdlib", "-nostartfiles", "-Wl,--no-relax",
                        "-T" + str(here / linker), here / source, "-o", output / (name + ".elf")],
                       log=output / (name + "-build.log"))
            common.run(["riscv64-unknown-elf-objcopy", "-O", "binary", output / (name + ".elf"),
                        output / (name + ".bin")], log=output / (name + "-objcopy.log"))
            return output / (name + ".bin")
        image = payload("ca", "ca_smoke.S", "soc_link.ld", "rv64imac_zicsr_zifencei")
        run = driver("ca-run", "five_stage_ca_soc.cpp")
        check("ca-cross-page32", run, [image],
              ("--wrong-result", "independent C/A completion/alias/boundary oracle"))
        check("ca-page-end16", run, [image, "--compressed-boundary"])
        run = driver("privilege-run", "five_stage_privilege_soc.cpp")
        image = payload("privileged", "privilege_smoke.S", "privilege_link.ld", "rv64i_zicsr_zifencei")
        check("privilege-regression", run, [image])
        image = payload("stream", "privilege_throughput.S", "soc_link.ld", "rv64i_zicsr_zifencei")
        check("bare-stream", run, [image, "--bare-throughput"])
        check("sv39-stream", run, [image, "--sv39-throughput"])
        run = driver("opensbi-run", "five_stage_opensbi.cpp")
        segments = [args.firmware.parent / s["file"] for s in firmware["segments"]]
        check("stock-opensbi-s-handoff", run, segments,
              ("--wrong-handoff", "independent stock OpenSBI handoff ledger oracle"))
        current = sources()
        current["src/main/resources/inorder/bootrom.hex"] = sha(ROOT / "src/main/resources/inorder/bootrom.hex")
        current["simulator/gsim/inorder/opensbi_i1.dts"] = sha(ROOT / "simulator/gsim/inorder/opensbi_i1.dts")
        if current != frozen:
            raise RuntimeError("source drift during integrated acceptance")
        receipt["status"] = "PASS_I1_RV64IMAC_ROM_OPENSBI_S_SHORT_ONLY"
    except Exception as error:
        receipt["status"] = "FAIL"; receipt["error"] = repr(error)
        raise
    finally:
        receipt["artifact_sha256"] = {str(p.relative_to(output)): sha(p) for p in output.rglob("*") if p.is_file()}
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2))
        print(json.dumps({"status": receipt["status"], "receipt": str(output / "receipt.json")}), flush=True)
if __name__ == "__main__":
    main()
