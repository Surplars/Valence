#!/usr/bin/env python3
"""Fresh independent dual-ingress/whole-line gate and matched real coherent DMA."""
import argparse
from contextlib import redirect_stdout
import json
import os
import re
import subprocess
import sys
import run as common
import ddr_write_collection as collection
from dma_overlap import parse as dma_metrics

sys.dont_write_bytecode = True


def inputs():
    hashes = collection.inputs()
    for name in ("simulator/gsim/line_read_channel.py",
                 "simulator/gsim/harness/line_read_channel.cpp",
                 "simulator/gsim/test_line_read_channel_cli.py",
                 "fpga/next/export.py", "simulator/gsim/fpga_next_board.py"):
        hashes[name] = collection.sha(common.ROOT / name)
    return hashes


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tag", required=True)
    args = ap.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.tag):
        ap.error("unsafe tag")
    output = common.BUILD / ("line-read-channel-" + args.tag)
    if output.exists():
        ap.error("fresh tag required; no stale model reuse")
    output.mkdir(parents=True)
    frozen = inputs()
    report = {"status": "RUNNING", "git_head": subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=common.ROOT, text=True).strip(), "source_sha256": frozen,
        "scope": "Independent two-ingress byte/tag/credit/hazard/error oracle plus real coherent "
                 "DMA/atomic/cache/home/memory integration. No executing CPU, physical MIG, timing or board proof.",
        "geometry": {"line_owners": 4, "shared_axi_slots": 4, "write_slots": 2,
                     "max_burst_beats": 16, "ddr_write_collection_flow": True,
                     "line_dispatch_flow": True, "line_read_channel": "paired OFF/ON",
                     "assumed_clock_hz": 100000000, "axi_data_bits": 64,
                     "whole_line_response_bits": 512},
        "roof_MiBps": {"AXI_one_way_64b_100MHz": 8 * 100000000 / 1048576,
                       "legacy_shared_A_D_copy": (64 / 9) * 100000000 / 1048576},
        "pairs": {}, "negatives": {}}
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}
    try:
        gsim, cxx = common.setup(False)
        report["toolchain"] = {**common.LOCK, "compiler": common.compiler()[1],
                               "gsim_sha256": collection.sha(gsim)}

        def fresh(key, main, top, harness, parameters=(), defines=None, runtime_args=()):
            print("Fresh line channel gate: " + key, flush=True)
            with (output / (key + "-driver.log")).open("w") as trace, redirect_stdout(trace):
                out = common.test(gsim, cxx, output.name + "/" + key, main, top, harness,
                    parameters=parameters, defines=defines or {}, runtime_args=runtime_args, timeout=300)
            return out

        def reject(out, name, args, anchor):
            r = subprocess.run([out / "run", *args], cwd=common.ROOT, env=env,
                               capture_output=True, text=True, timeout=120)
            log = r.stdout + r.stderr
            (out / ("negative-" + name + ".log")).write_text(log)
            if r.returncode == 0 or anchor not in log:
                raise RuntimeError("negative missed intended oracle: " + name)
            report["negatives"][out.name + ":" + name] = {
                "rejected": True, "exit_code": r.returncode, "anchor": anchor}

        unit = fresh("two-ingress", "ooo.LineReadChannelGsimMain", "LineReadChannelGsim", "line_read_channel.cpp")
        unit_log = (unit / "test.log").read_text()
        if "LINE_READ_CHANNEL_PASS" not in unit_log:
            raise RuntimeError("missing independent dual-ingress proof")
        report["boundary_markers"] = [x for x in unit_log.splitlines() if x.startswith("LINE_")]
        for name, anchor in (
            ("line-tag", "whole-line independent tag oracle mismatch"),
            ("line-data", "whole-line independent byte/error oracle mismatch"),
            ("bad-rid", "AXI R response has no live read owner"),
            ("bad-bid", "AXI B response has no live write owner"),
            ("early-rlast", "AXI read ID or RLAST mismatch")):
            reject(unit, name, ["--mutate=" + name], anchor)
        print("Completed independent boundary and five negative controls", flush=True)
        for flow in (False, True):
            side = "on" if flow else "off"
            out = fresh(side + "-dma", "ooo.DmaPipelineGsimMain", "DmaPipelineGsim", "dma_overlap.cpp",
                parameters=(0, 4, 1, 1, int(flow)), defines={"DMA_LINE_ENABLED": 1, "DMA_LINE_ENTRIES": 4},
                runtime_args=("--transport-only",))
            if "DMA_PIPELINE_TRANSPORT_PASS" not in (out / "test.log").read_text():
                raise RuntimeError("missing real coherent transport proof")
            report["pairs"][side] = dma_metrics(out)
            common.run([out / "run", "--protocol-only"], log=out / "protocol.log", env=env, timeout=300)
            if "DMA_PIPELINE_PROTOCOL_PASS" not in (out / "protocol.log").read_text():
                raise RuntimeError("missing dirty/probe/error/ordering/drain proof")
            for name, anchor in (
                ("drop-write", "DMA independent destination byte oracle mismatch"),
                ("corrupt-write", "DMA independent destination byte oracle mismatch"),
                ("early-ack", "DMA completion retained independently tagged owner")):
                reject(out, name, ["--mutate=" + name], anchor)
            print("Completed " + side + " DMA and protocol checks", flush=True)
        if len(report["pairs"]["off"]) != 4 or len(report["pairs"]["on"]) != 4:
            raise RuntimeError("incomplete matched workload")
        comparisons = []
        for off, on in zip(report["pairs"]["off"], report["pairs"]["on"]):
            if any(off[k] != on[k] for k in ("case", "bytes", "entries", "mode", "profile",
                "axi_read_bytes", "axi_write_bytes", "axi_ar", "axi_aw", "axi_b")):
                raise RuntimeError("paired accepted traffic or service changed")
            if off["line_channel"] or not on["line_channel"]:
                raise RuntimeError("selection did not reach actual transport")
            if on["occupancy"]["readChannelRequests"] != on["axi_ar"] or \
                    on["occupancy"]["readChannelResults"] != on["axi_ar"]:
                raise RuntimeError("whole-line request/result count mismatch")
            comparisons.append({"bytes": off["bytes"], "profile": off["profile"],
                "off_cycles": off["cycles"], "on_cycles": on["cycles"],
                "off_payload_MiBps": off["payload_MiBps"], "on_payload_MiBps": on["payload_MiBps"],
                "throughput_gain_fraction": off["cycles"] / on["cycles"] - 1,
                "off_R_W_accepted_duty_each": off["axi_read_bytes"] / 8 / off["cycles"],
                "on_R_W_accepted_duty_each": on["axi_read_bytes"] / 8 / on["cycles"],
                "off_TL_A_accepted_duty": off["occupancy"]["tlA"] / off["cycles"],
                "on_TL_A_accepted_duty": on["occupancy"]["tlA"] / on["cycles"],
                "on_line_read_request_duty": on["occupancy"]["readChannelRequests"] / on["cycles"]})
        report["comparison"] = comparisons
        if inputs() != frozen:
            raise RuntimeError("source drift during acceptance")
        report["status"] = "PASS_DUAL_INGRESS_AND_COHERENT_DMA"
    except BaseException as error:
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
