#!/usr/bin/env python3
"""Export a fresh, hash-bound bare-core batch only after current short GSIM acceptance."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stamp_ram_attribute(text, style):
    """Propagate an elaborated RF resource choice to CIRCT's split RAM LEAF only.

    Attribute-only; no logic, latency, ports, enables or RDW semantics are changed.
    UG912 says hierarchy RAM_STYLE does not propagate to nested hierarchy.
    Reject a changed compiler memory shape instead of guessing another array.
    """
    if style not in ("block", "distributed"):
        raise ValueError("unsupported explicit RAM style")
    pattern = r"(?m)^module bank_32x64\("
    if len(re.findall(pattern, text)) != 1 or len(re.findall(r"reg\s+\[63:0\]\s+Memory\[0:31\];", text)) != 1:
        raise RuntimeError("CIRCT RAM leaf shape drift; explicit review required")
    if "ram_style" in text:
        raise RuntimeError("unexpected existing RAM leaf attribute")
    return re.sub(pattern, f'(* ram_style = "{style}" *)\nmodule bank_32x64(', text)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--receipt", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()
    receipt_path = args.receipt.resolve()
    receipt = json.loads(receipt_path.read_text())
    if receipt["status"] != "PASS_FIVE_STAGE_INTEGER_FOUNDATION_ONLY" or len(receipt["variants"]) != 6:
        ap.error("current complete short acceptance required")
    for name, digest in receipt["source_sha256"].items():
        if sha(ROOT / name) != digest:
            ap.error("source drift since acceptance: " + name)
    for name, digest in receipt["artifacts_sha256"].items():
        if sha(receipt_path.parent / name) != digest:
            ap.error("acceptance artifact drift: " + name)
    output = args.output.resolve()
    if output.exists():
        ap.error("fresh output directory required")
    output.mkdir(parents=True)
    profiles = {"rv64-dsp": [], "rv64-no-m": ["--no-m"], "rv64-lutram": ["--rf-distributed"]}
    resource_annotations = {}
    for name, flags in profiles.items():
        target = output / name
        target.mkdir()
        with (target / "export.log").open("w") as log:
            subprocess.run(["mill", "-i", "OrbitalI1.test.runMain", "inorder.FiveStageRtlMain",
                            str(target), "64", *flags], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        leaf = target / "bank_32x64.sv"
        parent = (target / "SynchronousRegisterFile.sv").read_text()
        if len(re.findall(r"bank_32x64\s+bank(?:_1)?_ext\s*\(", parent)) != 2:
            raise RuntimeError("exact two-bank RF instance binding changed")
        raw = leaf.read_text()
        raw_folder = target / "raw-memory-leaf"
        raw_folder.mkdir()
        shutil.copyfile(leaf, raw_folder / leaf.name)
        style = "distributed" if "--rf-distributed" in flags else "block"
        leaf.write_text(stamp_ram_attribute(raw, style))
        resource_annotations[name] = {"file": leaf.name, "style": style,
            "raw_sha256": sha(raw_folder / leaf.name), "stamped_sha256": sha(leaf),
            "change": "RAM_STYLE on exact split memory leaf; behavior unchanged"}
        sv = "\n".join(p.read_text() for p in target.glob("*.sv"))
        if "ram_style = \"" not in sv:
            raise RuntimeError("RAM resource attributes missing in actual RTL")
        if name == "rv64-no-m" and re.search(r"module\s+FiveStageMulDiv", sv):
            raise RuntimeError("disabled M still has a multiply/divide module")
    for name in ("ooc.xdc", "synth_ooc.tcl"):
        shutil.copyfile(Path(__file__).parent / name, output / name)
    manifest = {"status": "PASS_BARE_CORE_RTL_EXPORT_ONLY", "gsim_receipt_sha256": sha(receipt_path),
        "acceptance_sources_sha256": receipt["source_sha256"], "profiles": profiles,
        "resource_annotations": resource_annotations,
        "exporter_sources_sha256": {str(Path(__file__).relative_to(ROOT)): sha(Path(__file__)),
            "fpga/inorder/synth_ooc.tcl": sha(Path(__file__).parent / "synth_ooc.tcl"),
            "fpga/inorder/ooc.xdc": sha(Path(__file__).parent / "ooc.xdc")},
        "part": "xczu15eg-ffvb1156-2-i", "design_target_mhz_not_qualified": 200,
        "scope": "Bare five-stage core without caches/MMU/FPU/SoC/peripherals. "
                 "OOC synthesis is not routed frequency/board qualification.",
        "files_sha256": {str(p.relative_to(output)): sha(p) for p in sorted(output.rglob("*")) if p.is_file()}}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"status": manifest["status"], "output": str(output)}, indent=2))


if __name__ == "__main__":
    main()
