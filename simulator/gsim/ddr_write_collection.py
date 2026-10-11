#!/usr/bin/env python3
"""Fresh paired TL/AXI write-collection component gate, not CPU/DDR/STA evidence."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import run as common
from dma_overlap import parse as dma_metrics

sys.dont_write_bytecode = True


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inputs():
    paths = list((common.ROOT / "src").rglob("*.scala"))
    paths += list((common.ROOT / "third_party/berkeley-hardfloat/src/main/scala").rglob("*.scala"))
    paths += [common.ROOT / name for name in ("build.mill", ".mill-version",
        "simulator/gsim/config/toolchain.json", "simulator/gsim/run.py",
        "simulator/gsim/ddr_write_collection.py",
        "simulator/gsim/harness/tilelink_axi4_mixed.cpp",
        "simulator/gsim/harness/tilelink_axi4_write_pipeline.cpp",
        "simulator/gsim/harness/tilelink_axi4_write_collection.h",
        "simulator/gsim/dma_overlap.py",
        "simulator/gsim/harness/dma_overlap.cpp",
        "simulator/gsim/harness/dma_overlap_metrics.h",
        "simulator/gsim/harness/dma_pipeline_ddr.h")]
    return {str(p.relative_to(common.ROOT)): sha(p) for p in sorted(set(paths))}


def metrics(log):
    rows = []
    for line in log.read_text().splitlines():
        if not line.startswith("WRITE_PIPELINE_PASS "):
            continue
        row = {k: float(v) if "." in v else int(v)
               for k, v in (item.split("=", 1) for item in line.split()[1:])}
        writes = row["transactions"] if not row["mixed"] else row["transactions"] // 2
        reads = row["transactions"] - writes
        row["accepted_a_beats"] = writes * row["beats"] + reads
        row["a_channel_active_fraction"] = row["accepted_a_beats"] / row["cycles"]
        row["a_acceptance_when_offered"] = row["accepted_a_beats"] / (row["accepted_a_beats"] + row["a_stalls"])
        row["r_channel_active_fraction"] = row["rbeats"] / row["cycles"]
        row["w_channel_active_fraction"] = row["wbeats"] / row["cycles"]
        row["combined_wire_fraction_of_two_channels"] = (row["rbeats"] + row["wbeats"]) / (2 * row["cycles"])
        row["write_payload_MiBps_at_assumed_100MHz"] = row["wbeats"] * 8 * 100000000 / row["cycles"] / 1048576
        rows.append(row)
    if len(rows) != 11:
        raise RuntimeError("missing complete matched pipeline metric rows")
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--preflight-only", action="store_true")
    ap.add_argument("--bridge-only", action="store_true", help="omit the separate real coherent-DMA pair")
    args = ap.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.tag):
        ap.error("unsafe tag")
    output = common.BUILD / ("ddr-write-collection-" + args.tag)
    if output.exists():
        ap.error("choose a fresh tag; this gate never reuses an existing model")
    plan = {"serial": {"slots": 1, "writes": 0, "unordered": False},
            "shared": {"slots": 4, "writes": 2, "unordered": True}}
    if args.preflight_only:
        print(json.dumps({"status": "PREFLIGHT_ONLY", "output": str(output), "pairs": plan,
                          "max_burst_beats": 16, "coherent_dma_pair": not args.bridge_only,
                          "source_files": len(inputs())}, indent=2))
        return
    if shutil.disk_usage(common.ROOT).free < 512 * 1024 * 1024:
        raise RuntimeError("less than 512 MiB free before bounded component gate")
    frozen = inputs()
    output.mkdir(parents=True)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=common.ROOT, text=True).strip()
    report = {"status": "RUNNING", "git_head": head, "source_sha256": frozen,
              "scope": "Fresh paired TL/AXI bridges with external byte/ownership/credit oracle, "
                       "plus a separate real coherent-DMA pair unless bridge-only is selected. "
                       "No executing CPU, physical MIG, FPGA frequency, native CDC or board qualification.",
              "geometry": {"max_burst_beats": 16, "RAM_base": "0x80200000",
                           "RAM_bytes": 2147483648, "AXI_data_bits": 64, "assumed_clock_hz": 100000000},
              "pairs": {}, "negative_controls": {}}
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}
    try:
        gsim, cxx = common.setup(False)
        report["toolchain"] = {**common.LOCK, "compiler": common.compiler()[1],
                               "gsim_binary_sha256": sha(gsim)}
        for name, cfg in plan.items():
            report["pairs"][name] = {"configuration": cfg}
            for flow in (False, True):
                side = "on" if flow else "off"
                key = name + "-" + side
                defines = {"WRITE_COLLECTION_FLOW": int(flow)}
                if cfg["unordered"]:
                    defines["UNORDERED_TL"] = 1
                out = common.test(gsim, cxx, output.name + "/" + key,
                    "ooo.TileLinkAxi4OutstandingGsimMain", "TileLinkAxi4Bridge",
                    "tilelink_axi4_write_pipeline.cpp",
                    parameters=(cfg["slots"], 16, 3, cfg["writes"], int(cfg["unordered"]), 3, int(flow)),
                    defines=defines, timeout=120)
                report["pairs"][name][side] = {"metrics": metrics(out / "test.log")}
                tests = [("--collection-gaps", "WRITE_COLLECTION_ALL_PASS"),
                         ("--mixed-contract", "OUTSTANDING_ALL_PASS")]
                if cfg["unordered"]:
                    tests += [("--denied-tail", "DENIED_WRITE_TAIL_RECOVERY_PASS"),
                              ("--reset-skew", "RESET_SKEW_PASS")]
                for argument, marker in tests:
                    log = out / (argument[2:] + ".log")
                    common.run([out / "run", argument], log=log, env=env, timeout=120)
                    if marker not in log.read_text():
                        raise RuntimeError("missing positive marker: " + argument)
                for argument, anchor in (
                    ("--inject-w", "pipeline independent W pairing/data mismatch"),
                    ("--inject-credit", "collection consumed unaccepted A beat"),
                    ("--inject-data", "independent TL data oracle mismatch"),
                    ("--bad-id", "AXI read ID or RLAST mismatch" if cfg["slots"] == 1
                     else "AXI R response has no live read owner"),
                    ("--bad-bid", "AXI write response ID mismatch" if cfg["slots"] == 1
                     else "AXI B response has no live write owner"),
                    ("--bad-last", "AXI read ID or RLAST mismatch")):
                    result = subprocess.run([out / "run", argument], cwd=common.ROOT, env=env,
                                            capture_output=True, text=True, timeout=120)
                    text = result.stdout + result.stderr
                    (out / ("negative-" + argument[2:] + ".log")).write_text(text)
                    if result.returncode == 0 or anchor not in text:
                        raise RuntimeError("negative control not rejected at the intended check: " + argument)
                    report["negative_controls"][key + argument] = {
                        "rejected": True, "exit_code": result.returncode, "anchor": anchor}
            comparisons = []
            for off, on in zip(report["pairs"][name]["off"]["metrics"], report["pairs"][name]["on"]["metrics"]):
                axes = ("beats", "prepare", "stress", "mixed", "transactions", "wbeats", "rbeats")
                if any(off[k] != on[k] for k in axes):
                    raise RuntimeError("mismatched paired workload/accepted traffic")
                comparisons.append({**{k: off[k] for k in axes},
                    "off_cycles": off["cycles"], "on_cycles": on["cycles"],
                    "cycle_reduction_fraction": 1 - on["cycles"] / off["cycles"],
                    "throughput_gain_fraction": off["cycles"] / on["cycles"] - 1,
                    "off_a_active_fraction": off["a_channel_active_fraction"],
                    "on_a_active_fraction": on["a_channel_active_fraction"],
                    "off_r_active_fraction": off["r_channel_active_fraction"],
                    "on_r_active_fraction": on["r_channel_active_fraction"],
                    "off_w_active_fraction": off["w_channel_active_fraction"],
                    "on_w_active_fraction": on["w_channel_active_fraction"],
                    "aw_during_collection": on["aw_during_collection"],
                    "w_during_collection": on["w_during_collection"]})
            report["pairs"][name]["comparison"] = comparisons
        if not args.bridge_only:
            report["coherent_dma"] = {"line_entries": 4, "yield_cycles": 0}
            for flow in (False, True):
                side = "on" if flow else "off"
                out = common.test(gsim, cxx, output.name + "/dma-" + side,
                    "ooo.DmaPipelineGsimMain", "DmaPipelineGsim", "dma_overlap.cpp",
                    parameters=(0, 4, int(flow)), defines={"DMA_LINE_ENABLED": 1, "DMA_LINE_ENTRIES": 4},
                    runtime_args=("--transport-only",), timeout=300)
                if "DMA_PIPELINE_TRANSPORT_PASS" not in (out / "test.log").read_text():
                    raise RuntimeError("missing real coherent-DMA transport marker")
                report["coherent_dma"][side] = dma_metrics(out)
                common.run([out / "run", "--protocol-only"], log=out / "protocol.log", env=env, timeout=300)
                if "DMA_PIPELINE_PROTOCOL_PASS" not in (out / "protocol.log").read_text():
                    raise RuntimeError("missing real coherent-DMA protocol marker")
                for mutation, anchor in (
                    ("drop-write", "DMA independent destination byte oracle mismatch"),
                    ("corrupt-write", "DMA independent destination byte oracle mismatch"),
                    ("early-ack", "DMA completion retained independently tagged owner")):
                    result = subprocess.run([out / "run", "--mutate=" + mutation], cwd=common.ROOT,
                                            env=env, capture_output=True, text=True, timeout=120)
                    text = result.stdout + result.stderr
                    (out / ("negative-" + mutation + ".log")).write_text(text)
                    if result.returncode == 0 or anchor not in text:
                        raise RuntimeError("DMA negative control not rejected: " + mutation)
                    report["negative_controls"]["dma-" + side + "/" + mutation] = {
                        "rejected": True, "exit_code": result.returncode, "anchor": anchor}
            report["coherent_dma"]["comparison"] = []
            for off, on in zip(report["coherent_dma"]["off"], report["coherent_dma"]["on"]):
                if any(off[k] != on[k] for k in ("case", "bytes", "entries", "mode", "profile")):
                    raise RuntimeError("coherent-DMA paired workload changed")
                report["coherent_dma"]["comparison"].append({
                    **{k: off[k] for k in ("bytes", "profile")},
                    "off_cycles": off["cycles"], "on_cycles": on["cycles"],
                    "cycle_reduction_fraction": 1 - on["cycles"] / off["cycles"],
                    "throughput_gain_fraction": off["cycles"] / on["cycles"] - 1})
        if inputs() != frozen:
            raise RuntimeError("source drift during gate")
        report["status"] = "PASS_COMPONENT_ONLY" if args.bridge_only else "PASS_COMPONENT_AND_COHERENT_DMA"
    except Exception as error:
        report["status"] = "FAILED"
        report["error"] = str(error)
        raise
    finally:
        report["artifacts_sha256"] = {
            str(p.relative_to(output)): sha(p) for p in sorted(output.rglob("*"))
            if p.is_file() and p.name != "receipt.json"}
        (output / "receipt.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "receipt": str(output / "receipt.json"),
                      "comparison": {name: data["comparison"] for name, data in report["pairs"].items()},
                      "coherent_dma": report.get("coherent_dma", {}).get("comparison")}, indent=2))


if __name__ == "__main__":
    main()
