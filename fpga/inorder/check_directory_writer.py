#!/usr/bin/env python3
"""Stage an isolated directory-leaf inference proof, never synthesize a CPU/board."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inspect_leaf(text):
    arrays = re.findall(r"reg\s+\[(\d+):0\]\s+Memory\s*\[0:(\d+)\];", text)
    ports = sorted(set(re.findall(r"\bW(\d+)_addr\b", text)))
    writes = re.findall(r"Memory\[W\d+_addr\]\s*<=", text)
    if arrays != [("19", "255")] or ports != ["0"] or len(writes) != 1:
        raise ValueError("board directory must remain 256x20, exactly one physical write port")
    if not re.search(r'module directoryBanks_256x20\s*\(', text):
        raise ValueError("exact CPU directory memory leaf required")
    return {"width": 20, "depth": 256, "write_ports": 1,
            "read_ports": len(set(re.findall(r"\bR(\d+)_data\b", text)))}


TCL = r'''# Directory leaf only: no CPU, board implementation or bit generation.
set root [file dirname [file normalize [info script]]]
set_param general.maxThreads 4
read_verilog -sv [file join $root directoryBanks_256x20.sv]
synth_design -top directoryBanks_256x20 -part xczu15eg-ffvb1156-2-i -mode out_of_context
create_clock -name directory_write -period 3.333 [get_ports W0_clk]
report_utilization -file [file join $root utilization.rpt]
set ff [get_cells -hier -filter {REF_NAME =~ FD*}]
set ram [get_cells -hier -filter {REF_NAME =~ RAM* && REF_NAME !~ RAMB*}]
if {[llength $ff] != 0 || [llength $ram] == 0} {
    error "Directory did not map to LUTRAM: FFs=[llength $ff] LUTRAMs=[llength $ram]"
}
set f [open [file join $root primitive-counts.txt] w]
puts $f "PASS_SINGLE_WRITER_LUTRAM FFs=[llength $ff] LUTRAM_PRIMITIVES=[llength $ram]"
close $f
puts "PASS_SINGLE_WRITER_LUTRAM NO_CPU_SYNTHESIS NO_BOARD_IMPLEMENTATION"
'''


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--receipt", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()
    receipt = json.loads(args.receipt.read_text())
    if receipt["status"] != "PASS_I1_BANDWIDTH38_AFFECTED_SHORT_ONLY":
        ap.error("complete affected short batch38 PASS required")
    for name, digest in receipt["source_sha256"].items():
        if sha(ROOT / name) != digest:
            ap.error("source drift: " + name)
    fir = args.receipt.parent / "cpu/FiveStageSoc.fir"
    if sha(fir) != receipt["artifact_sha256"]["cpu/FiveStageSoc.fir"]:
        ap.error("tested CPU FIR drift")
    out = args.output.resolve()
    if out.parent != Path("/mnt/e/VM/Share/Valence-rtl") or not out.name.startswith("orbital-i1-directory38-"):
        ap.error("explicit fresh isolated directory38 output required")
    out.mkdir(exist_ok=False)
    raw = out / "raw"
    raw.mkdir()
    firtool = Path.home() / ".cache/llvm-firtool/1.135.0/bin/firtool"
    if "CIRCT firtool-1.135.0" not in subprocess.check_output([firtool, "--version"], text=True):
        raise RuntimeError("pinned firtool required")
    with (out / "firtool.log").open("w") as log:
        subprocess.run([firtool, fir, "--split-verilog", "--preserve-values=named",
            "--lowering-options=disallowLocalVariables", "-o", raw],
            stdout=log, stderr=subprocess.STDOUT, check=True)
    leaf = raw / "directoryBanks_256x20.sv"
    text = leaf.read_text()
    geometry = inspect_leaf(text)
    if geometry["read_ports"] != 6:
        raise RuntimeError("all six original directory read ports must remain present")
    # Same physical hint as export_board_cpu.py. No behavioral or port edits.
    text, count = re.subn(r"(?m)^(\s*)(reg\s+\[19:0\]\s+Memory\s*\[0:255\];)",
        r'\1(* ram_style = "distributed" *)\n\1\2', text)
    if count != 1:
        raise RuntimeError("exact directory memory-array attribute binding required")
    annotated = out / leaf.name
    annotated.write_text(text)
    (out / "prove_directory.tcl").write_text(TCL)
    (out / "staged-proof.json").write_text(json.dumps({
        "status": "STAGED_ONLY_NOT_YET_SYNTHESIZED", "scope": "single exact memory leaf only",
        "short_receipt": str(args.receipt), "short_receipt_sha256": sha(args.receipt),
        "cpu_fir_sha256": sha(fir), "raw_leaf_sha256": sha(leaf),
        "annotated_leaf_sha256": sha(annotated), "geometry": geometry,
        "proof_tool_sha256": sha(Path(__file__)),
        "tcl_sha256": sha(out / "prove_directory.tcl"), "firtool_sha256": sha(firtool),
        "board_qualified": False, "cpu_timing_qualified": False}, indent=2) + "\n")
    print(json.dumps(geometry))


if __name__ == "__main__":
    main()
