#!/usr/bin/env python3
"""Source-bound modeled I1 bridge/CPU bandwidth, plus XCI-derived interface ceilings."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "simulator/gsim"))
import run as common
sys.path.insert(0, str(ROOT / "simulator/gsim/inorder"))
from soc_acceptance import sha

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--receipt", type=Path, required=True)
    ap.add_argument("--mig-xci", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    prior = json.loads(args.receipt.read_text())
    if prior["status"] != "PASS_I1_PARAMETERIZED_FD_JTAG_TIMING_CUTS_SHORT_ONLY":
        ap.error("exact passing I1 timing-cut source/model required")
    for name, digest in prior["source_sha256"].items():
        if sha(ROOT / name) != digest:
            raise RuntimeError("source drift: " + name)
    model = args.receipt.parent / "timing-axi"
    files = [p for p in model.glob("TileLinkAxi4Bridge*") if p.suffix in (".fir", ".o", ".h", ".cpp")]
    for p in files:
        if sha(p) != prior["artifact_sha256"][str(p.relative_to(args.receipt.parent))]:
            raise RuntimeError("model artifact drift: " + str(p))
    xci_hash = sha(args.mig_xci)
    params = json.loads(args.mig_xci.read_text())["ip_inst"]["parameters"]["component_parameters"]
    selected = {name: params["C0.DDR4_" + name][0]["value"] for name in
                ("TimePeriod", "PhyClockRatio", "DataWidth", "AxiDataWidth", "AxiAddressWidth", "InputClockPeriod")}
    if selected["PhyClockRatio"] != "4:1":
        ap.error("review new MIG/UI ratio before deriving a ceiling")
    ck_hz = 1e12 / int(selected["TimePeriod"])
    ui_hz = ck_hz / 4
    axi_bytes = int(selected["AxiDataWidth"]) / 8
    output = args.output.resolve()
    if output.exists():
        ap.error("fresh evidence required")
    output.mkdir(parents=True)
    source = ROOT / "fpga/inorder/tests/axi_bandwidth.cpp"
    cxx, identity = common.compiler()
    binary = output / "run"
    common.run([cxx, "-std=c++20", "-O1", "-fsanitize=address,undefined",
                "-fno-sanitize-recover=all", "-I" + str(model),
                *sorted(model.glob("TileLinkAxi4Bridge[0-9]*.o")), source, "-o", binary],
               log=output / "compile.log", timeout=900)
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}
    matrix = []
    for latency in (0, 12, 32, 64):
        for stalls in (0, 1):
            for high in (0, 1):
                log = output / (f"l{latency}-s{stalls}-h{high}.log")
                common.run([binary, latency, stalls, high], env=env, log=log, timeout=60)
                text = log.read_text().strip()
                if not text.startswith("I1_BRIDGE_BANDWIDTH_PASS "):
                    raise RuntimeError("missing independent bridge bandwidth PASS")
                matrix.append(json.loads(text.split(" ", 1)[1]))
    bad = subprocess.run([str(binary), "12", "1", "1", "--inject"], cwd=ROOT, env=env,
                         capture_output=True, text=True, timeout=60)
    (output / "negative.log").write_text(bad.stdout + bad.stderr)
    if bad.returncode == 0 or "independent bridge bandwidth data/metadata oracle" not in bad.stdout + bad.stderr:
        raise RuntimeError("bandwidth independent negative not rejected")
    cpu = {}
    paired = {}
    nominal = prior["cpu_hz"]
    for mode in ("bare", "sv39"):
        measured = json.loads(prior["checks"]["fd-" + mode + "-stream"].split(" ", 1)[1])
        cpu[mode] = {"bytes": measured["bytes"], "cycles": {}, "mib_s_at_nominal_100mhz_only": {}}
        for operation in ("read", "write", "copy"):
            ticks = measured[operation + "_ticks"]
            cpu[mode]["cycles"][operation] = ticks
            cpu[mode]["mib_s_at_nominal_100mhz_only"][operation] = measured["bytes"] * nominal / ticks / 1048576
        cpu[mode]["copy_scope"] = "payload; logical read+write traffic is twice payload, not actual AXI bytes"
        if prior.get("fast_data_translation"):
            off = json.loads(prior["checks"]["fd-auth-off-" + mode + "-stream"].split(" ", 1)[1])
            for field in ("bytes", "axi_reads", "axi_writes"):
                if off[field] != measured[field]:
                    raise RuntimeError("paired CPU proof changed byte geometry or AXI traffic: " + field)
            paired[mode] = {
                "off_cycles": {op: off[op + "_ticks"] for op in ("read", "write", "copy")},
                "on_cycles": cpu[mode]["cycles"],
                "throughput_gain_percent": {
                    op: (off[op + "_ticks"] / measured[op + "_ticks"] - 1) * 100
                    for op in ("read", "write", "copy")},
                "same_axi_reads": measured["axi_reads"], "same_axi_writes": measured["axi_writes"],
                "oracle": "both models passed independent whole-buffer bytes and READ checksum",
                "scope": "only fast-data-translation differs; total retirement includes BootROM UART polling, "
                         "not a same-retirement-stream CoreMark comparison"}
    if sha(args.mig_xci) != xci_hash:
        raise RuntimeError("MIG XCI changed while measuring")
    receipt = {"status": "PASS_I1_MODELED_BANDWIDTH_NOT_BOARD", "hardware_qualified": False,
        "timing_qualified": False, "formal_benchmark": False,
        "gsim_receipt_sha256": sha(args.receipt), "compiler": identity,
        "source_sha256": {str(source.relative_to(ROOT)): sha(source),
                          str(Path(__file__).relative_to(ROOT)): sha(Path(__file__))},
        "mig_xci_sha256": xci_hash, "mig_parameters": selected,
        "theory": {"dram_ck_hz": ck_hz, "dram_mt_s": 2 * ck_hz / 1e6, "ui_hz": ui_hz,
                   "ddr_wire_bytes_per_second": 2 * ck_hz * int(selected["DataWidth"]) / 8,
                   "mig_axi_bytes_per_second": ui_hz * axi_bytes,
                   "cpu_axi_bytes_per_second_if_one_beat_per_cycle": {
                       str(hz): 8 * hz for hz in (100000000, 200000000, 300000000)},
                   "end_to_end_ceiling_before_overheads": {
                       str(hz): min(8 * hz, ui_hz * axi_bytes) for hz in (100000000, 200000000, 300000000)},
                   "clock_warning": "100MHz is the GSIM nominal timebase. 200/300MHz are targets/projections, NOT board clock claims",
                   "exclusions": "refresh, DDR timing/turnaround, arbitration, CDC, TL whole-line buffering, CPU stalls, instructions"},
        "bridge_read_matrix": matrix, "cpu": cpu, "paired_data_auth": paired,
        "data_auth_microbench": prior.get("data_auth_benchmarks", {}),
        "negative": "PASS_REJECTED_INDEPENDENT_DATA_CORRUPTION",
        "ownership": "two bridge transaction slots, one write credit, 64B lines; unchanged blocking I/D cache owners",
        "scope": "slave modeled in CPU cycles; NOT a MIG simulator or hardware DDR/network bandwidth test"}
    shutil.copy2(args.mig_xci, output / "mig-config.xci")
    receipt["artifact_sha256"] = {str(p.relative_to(output)): sha(p) for p in output.rglob("*") if p.is_file()}
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"theory": receipt["theory"], "cpu": cpu, "bridge": matrix}, indent=2))
if __name__ == "__main__":
    main()
