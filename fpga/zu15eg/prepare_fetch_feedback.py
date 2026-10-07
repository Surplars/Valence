#!/usr/bin/env python3
"""Gate one production RTL export on short acceptance; stage only generated CAD inputs."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipt", type=Path)
    parser.add_argument("tag")
    parser.add_argument("native_directory", type=Path)
    parser.add_argument("--packet-dma", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.tag):
        parser.error("unsafe tag")
    receipt = args.receipt.resolve()
    verified = json.loads(receipt.read_text())
    if verified["status"] != "passed" or verified["profile"] != "staged-fetch-feedback":
        raise RuntimeError("short combined acceptance must pass before CAD")
    if args.packet_dma and not verified.get("packet_dma"):
        raise RuntimeError("packet DMA export requires packet/coherence acceptance")
    for name, digest in verified["source_sha256"].items():
        if sha(root / name) != digest:
            raise RuntimeError("verified input drift: " + name)
    evidence = root / "build/fpga" / args.tag
    evidence.mkdir(parents=True, exist_ok=False)
    soc, core = evidence / "soc-rtl", evidence / "core-rtl"
    with (evidence / "export.log").open("w") as log:
        subprocess.run(["mill", "-i", "IonSoC.test.runMain", "ooo.EthernetTimingMain", str(soc),
                        "rv64gc", "board", "staged-fetch-feedback", *( ["dma"] if args.packet_dma else [])], cwd=root, stdout=log,
                       stderr=subprocess.STDOUT, check=True, timeout=600)
    for name, digest in verified["source_sha256"].items():
        if sha(root / name) != digest:
            raise RuntimeError("verified input drift during export: " + name)
    core.mkdir()
    pending, modules = ["MachineCore"], {}
    while pending:
        name = pending.pop()
        if name in modules:
            continue
        source = soc / (name + ".sv")
        modules[name + ".sv"] = sha(source)
        shutil.copy2(source, core / source.name)
        pending.extend(child for child in re.findall(r"(?m)^\s*(\w+)\s+\w+\s*\(", source.read_text())
                       if (soc / (child + ".sv")).is_file())
    for name, digest in modules.items():
        if sha(soc / name) != digest or sha(core / name) != digest:
            raise RuntimeError("production CPU dependency mismatch")
    native = args.native_directory.resolve()
    native.mkdir(parents=True, exist_ok=False)
    shutil.copytree(core, native / "core-rtl")
    shutil.copytree(soc, native / "soc-rtl")
    scripts = native / "fpga/zu15eg"
    scripts.mkdir(parents=True)
    for name in ("vivado_ethernet_batch.tcl", "cdc_constraints.tcl"):
        shutil.copy2(root / "fpga/zu15eg" / name, scripts / name)
    for name in ("vivado-module-ooc.tcl", "vivado-module-path-details.tcl"):
        shutil.copy2(root / "fpga" / name, scripts.parent / name)
    report = {"profile":"staged-fetch-feedback", "isa":"rv64gc", "issue_width":2,
              "packet_dma":args.packet_dma,
              "short_receipt":str(receipt), "short_receipt_sha256":sha(receipt),
              "export_inputs_sha256":verified["source_sha256"],
              "cpu_modules_sha256":modules,
              "soc_rtl_sha256":{p.name:sha(p) for p in sorted(soc.glob("*.sv"))},
              "native_directory":str(native), "cpu_cut":"same production-pruned CPU as Ethernet wrapper",
              "scope":"RTL export only; no timing, board or bit claim"}
    for output in (evidence / "export-receipt.json", native / "export-receipt.json"):
        output.write_text(json.dumps(report, indent=2)+"\n")
    print(f"PRODUCTION_EXPORT_PASS modules={len(modules)} evidence={evidence}")


if __name__ == "__main__":
    main()
