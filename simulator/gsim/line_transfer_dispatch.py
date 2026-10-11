#!/usr/bin/env python3
"""Fresh paired home/line dispatch gate. No executing CPU or STA qualification."""
import argparse
from contextlib import redirect_stdout
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import run as common
import ddr_write_collection as collection
from dma_overlap import parse as dma_metrics

sys.dont_write_bytecode = True


def inputs():
    hashes = collection.inputs()
    for name in ("simulator/gsim/line_transfer_dispatch.py",
                 "simulator/gsim/harness/line_fill.cpp", "simulator/gsim/harness/line_write.cpp",
                 "simulator/gsim/test_line_transfer_dispatch_cli.py",
                 "fpga/next/export.py", "simulator/gsim/fpga_next_board.py"):
        hashes[name] = collection.sha(common.ROOT / name)
    return hashes


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tag", required=True)
    args = ap.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.tag):
        ap.error("unsafe tag")
    output = common.BUILD / ("line-transfer-dispatch-" + args.tag)
    if output.exists():
        ap.error("requires a fresh output tag; no model reuse")
    output.mkdir(parents=True)
    frozen = inputs()
    report = {"status": "RUNNING", "git_head": subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=common.ROOT, text=True).strip(), "source_sha256": frozen,
        "scope": "Independent line engines and real coherent-DMA/cache/home/TL/AXI integration; "
                 "not executing CPU, real MIG, timing or board proof.",
        "geometry": {"line_owners": 4, "shared_axi_slots": 4, "write_slots": 2,
                     "ddr_write_collection_flow": True, "line_dispatch_flow": "paired OFF/ON",
                     "assumed_clock_hz": 100000000}, "pairs": {}, "negatives": {}}
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}
    try:
        gsim, cxx = common.setup(False)
        report["toolchain"] = {**common.LOCK, "compiler": common.compiler()[1],
                               "gsim_sha256": collection.sha(gsim)}
        for flow in (False, True):
            side = "on" if flow else "off"
            report["pairs"][side] = {}
            for kind, main, top, harness in (
                ("read", "ooo.TileLinkLineFillGsimMain", "TileLinkLineFillGsim", "line_fill.cpp"),
                ("write", "ooo.TileLinkLineWriteGsimMain", "TileLinkLineWriteGsim", "line_write.cpp"),
                ("dma", "ooo.DmaPipelineGsimMain", "DmaPipelineGsim", "dma_overlap.cpp")):
                key = side + "-" + kind
                print("Fresh paired dispatch gate: " + key, flush=True)
                defines = {"LINE_DISPATCH_FLOW": int(flow)} if kind != "dma" else {
                    "DMA_LINE_ENABLED": 1, "DMA_LINE_ENTRIES": 4}
                params = (int(flow),) if kind != "dma" else (0, 4, 1, int(flow))
                # Keep detailed events in WSL logs instead of flooding the UI.
                with (output / (key + "-driver.log")).open("w") as trace, redirect_stdout(trace):
                    out = common.test(gsim, cxx, output.name + "/" + key, main, top, harness,
                        parameters=params, defines=defines,
                        runtime_args=("--transport-only",) if kind == "dma" else (), timeout=300)
                if kind == "dma":
                    if "DMA_PIPELINE_TRANSPORT_PASS" not in (out / "test.log").read_text():
                        raise RuntimeError("missing real transport proof")
                    report["pairs"][side][kind] = dma_metrics(out)
                    common.run([out / "run", "--protocol-only"], log=out / "protocol.log", env=env, timeout=300)
                    if "DMA_PIPELINE_PROTOCOL_PASS" not in (out / "protocol.log").read_text():
                        raise RuntimeError("missing real dirty/probe/error/ordering protocol proof")
                    negative = [("--mutate=drop-write", "DMA independent destination byte oracle mismatch"),
                                ("--mutate=corrupt-write", "DMA independent destination byte oracle mismatch"),
                                ("--mutate=early-ack", "DMA completion retained independently tagged owner")]
                else:
                    log = (out / "test.log").read_text()
                    marker = "GSIM TileLink line " + ("fill" if kind == "read" else "write") + ": PASS"
                    if marker not in log:
                        raise RuntimeError("missing independent line proof")
                    report["pairs"][side][kind] = {"markers": [line for line in log.splitlines()
                                                               if line.startswith("LINE_")]}
                    negative = [("--inject-get", "line fill independent stalled Get oracle mismatch")] \
                        if kind == "read" else [("--inject-mismatch", "line write oracle mismatch")]
                for arg, anchor in negative:
                    result = subprocess.run([out / "run", arg], cwd=common.ROOT, env=env,
                                            capture_output=True, text=True, timeout=120)
                    log = result.stdout + result.stderr
                    (out / ("negative-" + re.sub(r"[^A-Za-z0-9_-]", "_", arg) + ".log")).write_text(log)
                    if result.returncode == 0 or anchor not in log:
                        raise RuntimeError("negative missed its intended oracle: " + arg)
                    report["negatives"][key + arg] = {"rejected": True, "exit_code": result.returncode,
                                                     "anchor": anchor}
                print("Completed " + key, flush=True)
        comparisons = []
        for off, on in zip(report["pairs"]["off"]["dma"], report["pairs"]["on"]["dma"]):
            if any(off[k] != on[k] for k in ("case", "bytes", "entries", "mode", "profile")):
                raise RuntimeError("DMA workload changed between sides")
            if any(off[k] != on[k] for k in ("axi_read_bytes", "axi_write_bytes", "axi_ar", "axi_aw", "axi_b")):
                raise RuntimeError("accepted AXI traffic changed between sides")
            comparisons.append({"bytes": off["bytes"], "profile": off["profile"],
                "off_cycles": off["cycles"], "on_cycles": on["cycles"],
                "off_payload_MiBps": off["payload_MiBps"], "on_payload_MiBps": on["payload_MiBps"],
                "throughput_gain_fraction": off["cycles"] / on["cycles"] - 1,
                "off_A_accepted_duty": off["occupancy"]["tlA"] / off["cycles"],
                "on_A_accepted_duty": on["occupancy"]["tlA"] / on["cycles"],
                "off_R_W_accepted_duty_each": off["axi_read_bytes"] / 8 / off["cycles"],
                "on_R_W_accepted_duty_each": on["axi_read_bytes"] / 8 / on["cycles"]})
        report["comparison"] = comparisons
        if inputs() != frozen:
            raise RuntimeError("source drift during acceptance")
        report["status"] = "PASS_LINE_ENGINES_AND_COHERENT_DMA"
    except Exception as error:
        report["status"] = "FAILED"
        report["error"] = str(error)
        raise
    finally:
        report["artifacts_sha256"] = {str(p.relative_to(output)): collection.sha(p)
            for p in sorted(output.rglob("*")) if p.is_file() and p.name != "receipt.json"}
        (output / "receipt.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "receipt": str(output / "receipt.json"),
                      "comparison": report["comparison"]}, indent=2))


if __name__ == "__main__":
    main()
