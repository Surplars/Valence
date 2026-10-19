#!/usr/bin/env python3
"""Reuse exact-FIR matching short models for precise faults/C/A/coherent CPU completion."""
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
sys.path.insert(0, str(Path(__file__).resolve().parent))
from soc_acceptance import sources, sha


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--models-receipt", type=Path, required=True)
    ap.add_argument("--tag", required=True)
    args = ap.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.tag):
        ap.error("safe fresh tag required")
    prior = json.loads(args.models_receipt.read_text())
    if prior["status"] != "PASS_I1_TLC_CPU_SHORT_ONLY_PHYSICAL_PENDING":
        ap.error("passing model qualification required")
    output = ROOT / "build/gsim" / ("i1-coherent-completion-" + args.tag)
    output.mkdir(parents=True, exist_ok=False)
    frozen = sources()
    receipt = {"status": "RUNNING", "checks": {}, "source_sha256": frozen,
               "model_receipt": str(args.models_receipt.resolve()),
               "model_receipt_sha256": sha(args.models_receipt),
               "physical_qualified": False, "cpu_target_hz": 300000000,
               "scope": "exact-FIR model reuse, actual CPU precise exceptions/C/A/LRSC/AMO and byte oracles"}

    def save():
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")

    save()
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}
    try:
        cxx, version = common.compiler()
        if version != prior["tools"]["cxx"]:
            raise RuntimeError("compiler provenance changed")
        payloads = {}
        here = ROOT / "simulator/gsim/inorder"
        for name, source, linker, march in (
                ("privilege", "privilege_smoke.S", "privilege_link.ld", "rv64i_zicsr_zifencei"),
                ("ca", "ca_smoke.S", "soc_link.ld", "rv64imac_zicsr_zifencei")):
            elf = output / (name + ".elf")
            common.run(["riscv64-unknown-elf-gcc", "-march=" + march, "-mabi=lp64",
                        "-mcmodel=medany", "-mno-relax", "-nostdlib", "-nostartfiles", "-Wl,--no-relax",
                        "-T" + str(here / linker), here / source, "-o", elf], log=output / (name + "-build.log"))
            payloads[name] = elf.with_suffix(".bin")
            common.run(["riscv64-unknown-elf-objcopy", "-O", "binary", elf, payloads[name]],
                       log=output / (name + "-objcopy.log"))
        for name in ("cpu-legacy", "cpu-coherent"):
            out = output / name
            out.mkdir()
            common.run(["mill", "-i", "OrbitalI1.test.runMain", "inorder.FiveStageSocGsimMain", out, 64,
                        *prior["cpu_flags"][name]], log=out / "elaborate.log")
            previous = args.models_receipt.parent / name
            for path in [previous / "FiveStageSoc.fir", previous / "FiveStageSoc.h",
                         *sorted(previous.glob("FiveStageSoc[0-9]*.cpp"))]:
                if sha(path) != prior["artifact_sha256"][name + "/" + path.name]:
                    raise RuntimeError("reused model artifact drift: " + str(path))
            if sha(out / "FiveStageSoc.fir") != sha(previous / "FiveStageSoc.fir"):
                raise RuntimeError("fresh exact-FIR mismatch")
            for kind, driver in (("privilege", "five_stage_privilege_soc.cpp"), ("ca", "five_stage_ca_soc.cpp")):
                binary = out / kind
                common.run([cxx, "-std=c++20", "-O1", "-fsanitize=address,undefined",
                            "-fno-sanitize-recover=all", "-DDUT_XLEN=64", "-I" + str(previous),
                            *(["-DI1_COHERENT_READBACK"] if name == "cpu-coherent" else []),
                            *sorted(previous.glob("FiveStageSoc[0-9]*.cpp")),
                            ROOT / "simulator/gsim/harness" / driver, "-o", binary],
                           log=out / (kind + "-compile.log"), timeout=900)
                options = [()] if kind == "privilege" else [(), ("--compressed-boundary",)]
                for index, flags in enumerate(options):
                    key = name + "-" + kind + "-" + str(index)
                    common.run([binary, payloads[kind], *flags], log=out / (key + ".log"),
                               env=env, timeout=180)
                    receipt["checks"][key] = (out / (key + ".log")).read_text().strip()
                    print(receipt["checks"][key], flush=True)
                    save()
                bad = subprocess.run([str(binary), str(payloads[kind]), "--wrong-result"],
                                     capture_output=True, text=True, env=env, timeout=180)
                (out / (kind + "-negative.log")).write_text(bad.stdout + bad.stderr)
                marker = ("independent privileged SoC result ledger oracle" if kind == "privilege" else
                          "independent C/A completion/alias/boundary oracle")
                if bad.returncode == 0 or marker not in bad.stdout + bad.stderr:
                    raise RuntimeError("independent result mutation was not rejected")
                receipt["checks"][name + "-" + kind + "-negative"] = "PASS_REJECTED_BYTE_ORACLE_MUTATION"
        if sources() != frozen:
            raise RuntimeError("source drift during supplemental checks")
        receipt["status"] = "PASS_I1_TLC_PRECISE_FAULTS_CA_SHORT_ONLY"
    except Exception as error:
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
