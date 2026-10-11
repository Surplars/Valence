#!/usr/bin/env python3
"""High-latency capacity ablations and real Sv39 adapter/service permission reuse.

No executing-CPU throughput, physical DDR delay, timing or board qualification.
The fixed external service permits 8 reads / 4 writes in ALL four ablations;
this is explicitly wider than the older 4/2 service, not a silent law change.
"""
import argparse
from contextlib import redirect_stdout
import json
import os
import re
import subprocess
import sys
import run as common
import ddr_write_collection as collection
import line_read_channel
from dma_overlap import parse as dma_metrics

sys.dont_write_bytecode = True


def inputs():
    hashes = line_read_channel.inputs()
    for name in ("simulator/gsim/latency_bandwidth.py", "simulator/gsim/test_latency_bandwidth_cli.py",
                 "simulator/gsim/harness/dtlb_write_read_reuse.cpp",
                 "simulator/gsim/harness/virtual_load_test_memory.h",
                 "simulator/gsim/harness/virtual_load_precheck.cpp"):
        hashes[name] = collection.sha(common.ROOT / name)
    return hashes


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tag", required=True)
    args = ap.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.tag):
        ap.error("unsafe tag")
    output = common.BUILD / ("latency-bandwidth-" + args.tag)
    if output.exists():
        ap.error("fresh tag required")
    output.mkdir(parents=True)
    frozen = inputs()
    geometry = {"baseline": (4, 4, 2), "owners-only": (8, 4, 2),
                "ddr-only": (4, 8, 4), "combined": (8, 8, 4)}
    report = {"status": "RUNNING", "source_sha256": frozen,
        "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=common.ROOT, text=True).strip(),
        "scope": __doc__, "dma": {}, "mmu": {}, "negatives": {},
        "geometry": {k: {"dma_owners": g[0], "ddr_slots": g[1], "write_slots": g[2]} for k,g in geometry.items()},
        "service": {"read_capacity": 8, "write_capacity": 4, "delayed_R": 32, "delayed_B": 40,
                    "B_ID_extra": {"even": 17, "odd": 3}, "ready_stall_moduli": [7, 11, 5],
                    "minimal_R_B": 1, "mmu_PTE_delay": 12, "mmu_physical_delay": 16},
        "roof_MiBps_at_assumed_100MHz": 8 * 100000000 / 1048576}
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}
    try:
        gsim, cxx = common.setup(False)
        report["toolchain"] = {**common.LOCK, "compiler": common.compiler()[1], "gsim_sha256": collection.sha(gsim)}
        def fresh(key, main, top, harness, parameters=(), defines=None, runtime_args=()):
            print("Fresh latency gate: " + key, flush=True)
            with (output / (key + "-driver.log")).open("w") as trace, redirect_stdout(trace):
                return common.test(gsim, cxx, output.name + "/" + key, main, top, harness,
                    parameters=parameters, defines=defines or {}, runtime_args=runtime_args, timeout=300)
        def reject(out, name, anchor):
            r = subprocess.run([out / "run", "--" + name], cwd=common.ROOT, env=env,
                capture_output=True, text=True, timeout=120)
            log = r.stdout + r.stderr
            (out / ("negative-" + name + ".log")).write_text(log)
            if not r.returncode or anchor not in log:
                raise RuntimeError("negative did not hit intended oracle: " + name)
            report["negatives"][out.name + ":" + name] = {"exit_code": r.returncode, "anchor": anchor}

        unit = fresh("boundary-8w4", "ooo.LineReadChannelGsimMain", "LineReadChannelGsim", "line_read_channel.cpp",
            parameters=(8,4), defines={"LINE_SHARED_SLOTS":8, "LINE_WRITE_CREDITS":4,
                                      "DMA_SERVICE_READS":8, "DMA_SERVICE_WRITES":4})
        log = (unit / "test.log").read_text()
        if "LINE_READ_CHANNEL_PASS shared_slots=8 write_quota=4" not in log:
            raise RuntimeError("expanded boundary proof missing")
        report["boundary_markers"] = [x for x in log.splitlines() if x.startswith("LINE_")]
        for mutation, anchor in (("line-tag","whole-line independent tag oracle mismatch"),
            ("line-data","whole-line independent byte/error oracle mismatch"),
            ("bad-rid","AXI R response has no live read owner"),
            ("bad-bid","AXI B response has no live write owner"),
            ("early-rlast","AXI read ID or RLAST mismatch")):
            reject(unit, "mutate=" + mutation, anchor)

        for key, (owners,slots,writes) in geometry.items():
            out = fresh(key, "ooo.DmaPipelineGsimMain", "DmaPipelineGsim", "dma_overlap.cpp",
                parameters=(0,owners,1,1,1,slots,writes),
                defines={"DMA_LINE_ENABLED":1,"DMA_LINE_ENTRIES":owners,"DMA_AXI_SLOTS":slots,
                         "DMA_AXI_WRITES":writes,"DMA_SERVICE_READS":8,"DMA_SERVICE_WRITES":4},
                runtime_args=("--transport-only",))
            if "DMA_PIPELINE_TRANSPORT_PASS" not in (out / "test.log").read_text():
                raise RuntimeError("real coherent transport proof missing")
            report["dma"][key] = dma_metrics(out, slots, writes)
            common.run([out / "run", "--protocol-only"], log=out / "protocol.log", env=env, timeout=300)
            if "DMA_PIPELINE_PROTOCOL_PASS" not in (out / "protocol.log").read_text():
                raise RuntimeError("coherence/dirty/error/drain proof missing")
            for mutation, anchor in (("drop-write","DMA independent destination byte oracle mismatch"),
                ("corrupt-write","DMA independent destination byte oracle mismatch"),
                ("early-ack","DMA completion retained independently tagged owner")):
                reject(out, "mutate=" + mutation, anchor)
            print("Completed capacity ablation: " + key, flush=True)
        report["dma_comparison"] = []
        for key, rows in report["dma"].items():
            if len(rows) != 4: raise RuntimeError("incomplete capacity workloads")
            for base,row in zip(report["dma"]["baseline"],rows):
                if any(base[k]!=row[k] for k in ("case","bytes","mode","profile","axi_read_bytes","axi_write_bytes","axi_ar","axi_aw","axi_b")):
                    raise RuntimeError("capacity comparison changed accepted traffic")
                report["dma_comparison"].append({"configuration":key,"bytes":row["bytes"],"profile":row["profile"],
                    "cycles":row["cycles"],"payload_MiBps":row["payload_MiBps"],
                    "gain_fraction":base["cycles"]/row["cycles"]-1,
                    "R_W_duty_each":row["axi_read_bytes"]/8/row["cycles"]})

        for capacity,reuse in ((8,False),(8,True),(16,False),(16,True)):
            side = ("on" if reuse else "off") + str(capacity)
            out = fresh("mmu-"+side,"ooo.DataTlbReuseGsimMain","VirtualLoadPrecheckGsim","dtlb_write_read_reuse.cpp",
                parameters=(int(reuse),capacity),defines={"DTLB_WRITE_READ_REUSE":int(reuse),"DTLB_ENTRIES":capacity})
            log = (out / "test.log").read_text()
            if "DTLB_WRITE_READ_REUSE_PASS" not in log: raise RuntimeError("MMU independent permission proof missing")
            rows = []
            for line in log.splitlines():
                if line.startswith("DTLB_REUSE_METRIC "):
                    row = dict(x.split("=",1) for x in line.split()[1:])
                    rows.append({k:v if k=="case" else int(v) for k,v in row.items()})
            if len(rows)!=2: raise RuntimeError("MMU paired workloads incomplete")
            report["mmu"][side] = rows
            reject(out,"mutate-address","DTLB independent physical operation mismatch")
            reject(out,"mutate-permission","DTLB independent ordered permission/fault mismatch")
            # Reuse this fresh model only: old read-only capacity/context/peek
            # oracle verifies unchanged behavior without another elaboration.
            generated = sorted(out.glob("VirtualLoadPrecheckGsim[0-9]*.cpp"))
            common.run([cxx,"-std=c++20","-O1","-g","-fsanitize=address,undefined","-fno-sanitize-recover=all",
                "-DPRECHECK_ENABLED=1","-DDTLB_ENTRIES="+str(capacity),"-I"+str(out),*generated,
                common.HERE/"harness/virtual_load_precheck.cpp","-ldl","-o",out/"read-regression"],log=out/"read-compile.log")
            common.run([out/"read-regression"],log=out/"read-regression.log",env=env,timeout=120)
            if "DATA_TRANSLATION_CAPACITY_PASS" not in (out/"read-regression.log").read_text():
                raise RuntimeError("read-only replacement regression missing")
            print("Completed real Sv39 adapter/service: " + side, flush=True)
        report["mmu_comparison"] = []
        for off,on in zip(report["mmu"]["off8"]+report["mmu"]["off16"],
                          report["mmu"]["on8"]+report["mmu"]["on16"]):
            if any(off[k]!=on[k] for k in ("case","operations","useful_bytes")):
                raise RuntimeError("MMU traffic changed")
            report["mmu_comparison"].append({"case":off["case"],"off":off,"on":on,
                "gain_fraction":off["cycles"]/on["cycles"]-1,
                "off_useful_MiBps":off["useful_bytes"]*100000000/off["cycles"]/1048576,
                "on_useful_MiBps":on["useful_bytes"]*100000000/on["cycles"]/1048576})
        if inputs()!=frozen: raise RuntimeError("source drift during acceptance")
        report["status"] = "PASS_LATENCY_CAPACITY_AND_SV39_REUSE"
    except BaseException as error:
        report["status"] = "FAILED"; report["error"] = str(error); raise
    finally:
        report["artifacts_sha256"] = {str(p.relative_to(output)):collection.sha(p)
            for p in sorted(output.rglob("*")) if p.is_file() and p.name!="receipt.json"}
        (output/"receipt.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps({"status":report["status"],"receipt":str(output/"receipt.json"),
                      "dma_comparison":report["dma_comparison"],"mmu_comparison":report["mmu_comparison"]},indent=2))


if __name__ == "__main__":
    main()
