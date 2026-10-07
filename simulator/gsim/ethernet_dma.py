#!/usr/bin/env python3
"""Short self-designed packet DMA acceptance, including actual coherent memory fabric."""
import argparse
import json
import os
import re
import subprocess
from pathlib import Path
from run import BUILD, HERE, ROOT, run, setup, test
from control_stage import negative
from throughput_perf import sha256


def reject(binary, arguments, message, output, protocol=False):
    result = subprocess.run([str(binary), *map(str, arguments)], capture_output=True, text=True,
        timeout=120, env={**os.environ, "ASAN_OPTIONS":"detect_leaks=0"})
    output.write_text(result.stdout + result.stderr)
    if (result.returncode == 0 or (not protocol and result.returncode != 1) or
            message not in result.stdout + result.stderr):
        raise RuntimeError("negative check failed to reject corruption: " + str(arguments))
    print("Negative check: PASS " + message, flush=True)


def inputs():
    paths = sorted((ROOT / "src/main/scala").rglob("*.scala"))
    paths += sorted((ROOT / "src/test/scala").rglob("*.scala"))
    paths += sorted((ROOT / "third_party/berkeley-hardfloat").rglob("*.scala"))
    paths += [ROOT / "build.mill", HERE / "ethernet_dma.py", HERE / "run.py",
              ROOT / "fpga/firmware/ethernet_dma.h"]
    paths += [HERE / "harness" / name for name in ("ethernet_packet_dma.cpp", "dma.cpp",
              "tilelink_bridge.cpp", "tilelink_burst_ram.cpp", "tilelink_axi4_burst.cpp")]
    return {str(p.relative_to(ROOT)): sha256(p) for p in paths}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--tag", required=True)
    p.add_argument("--reuse", type=Path)
    a = p.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", a.tag): p.error("unsafe tag")
    name = "ethernet-dma-" + a.tag
    output = BUILD / name
    output.mkdir(parents=True, exist_ok=False)
    before = inputs()
    reusable = {}
    if a.reuse:
        old = json.loads(a.reuse.read_text())
        for source_name,digest in old["source_sha256"].items():
            if source_name != "simulator/gsim/ethernet_dma.py" and before.get(source_name) != digest:
                raise RuntimeError("cannot reuse changed input: " + source_name)
        for stem,row in old.items():
            if isinstance(row,dict) and row.get("status")=="passed" and "fir_sha256" in row:
                reusable[stem] = row
    report = {"status": "running", "source_sha256": before, "profile": "staged-fetch-feedback",
              "packet_dma": True, "scope": "short packet/coherence GSIM; not MAC PHY/CDC/board/line-rate/Linux driver",
              "routed_timing_verified": False, "on_board_verified": False}
    try:
        cpu_receipt = BUILD / "fetch-feedback-20261004-r5/receipt.json"
        cpu = json.loads(cpu_receipt.read_text())
        if cpu["status"] != "passed": raise RuntimeError("CPU short baseline did not pass")
        excluded = {"src/main/scala/core/ooo/MachinePlatform.scala",
                    "src/main/scala/core/ooo/BoardSocTop.scala",
                    "src/main/scala/core/ooo/EthernetSocTop.scala"}
        excluded.update("src/main/scala/core/ooo/" + name + ".scala" for name in (
            "OrderedTileLinkBridge", "TileLinkDataRamAdapter", "TileLinkAxi4BurstBridge",
            "TileLinkAxi4Bridge", "SynchronousDataRam", "OrderedAxi4Bridge"))
        protected = {name:digest for name,digest in cpu["source_sha256"].items()
                     if name.startswith("src/main/scala/") and name not in excluded}
        for source_name,digest in protected.items():
            if sha256(ROOT / source_name) != digest: raise RuntimeError("CPU baseline changed: " + source_name)
        report["unchanged_cpu_short_baseline"] = {"receipt": str(cpu_receipt),
            "sha256": sha256(cpu_receipt), "protected_main_source_sha256": protected,
            "note": "saved CPU NEMU/FP/permission evidence; this batch tests new DMA/coherence separately"}
        run(["mill", "-i", "IonSoC.test.testOnly", "ip.EthernetPacketDmaSpec", "ip.DmaParamsSpec",
             "ooo.FetchFeedbackTimingSpec", "ooo.EthernetTimingSpec"], log=output / "scala.log")
        # CHIRRTL-only elaboration cannot detect mixed reset inference. Exercise
        # the actual production CPU + MAC + four CDC FIFO boundary through firtool.
        production = output / "production-rtl"
        run(["mill", "-i", "IonSoC.test.runMain", "ooo.EthernetTimingMain", production,
             "rv64gc", "board", "staged-fetch-feedback", "dma"], log=output / "production-export.log")
        report["production_rtl"] = {p.name: sha256(p) for p in sorted(production.glob("*.sv"))}
        if not report["production_rtl"]:
            raise RuntimeError("production RTL export is empty")
        run(["riscv64-unknown-elf-gcc", "-march=rv64imac_zicsr_zifencei", "-mabi=lp64", "-ffreestanding",
             "-Wall", "-Wextra", "-Werror", "-include", ROOT / "fpga/firmware/ethernet_dma.h", "-x", "c",
             "-c", "/dev/null", "-o", output / "software-api.o"], log=output / "software-api.log")
        gsim, cxx = setup(False)
        for stem, main, top, harness, defines, parameters, runtime, bad_args, anchor in (
            ("packet", "ip.EthernetPacketDmaGsimMain", "EthernetPacketDma", "ethernet_packet_dma.cpp", {}, (), (),
             (), "TX independent byte oracle mismatch"),
            ("coherence", "ip.EthernetDmaCoherenceGsimMain", "EthernetDmaCoherenceGsim", "ethernet_packet_dma.cpp",
             {"COHERENT_DMA": 1}, (), (), (), "TX independent byte oracle mismatch"),
            ("copy", "ip.DmaGsimMain", "MemoryCopyDma", "dma.cpp", {}, (), (), (), "copy data mismatch"),
            ("tl-ordered", "ooo.OrderedTileLinkBridgeGsimMain", "OrderedTileLinkBridge", "tilelink_bridge.cpp",
             {"ALLOW_PARTIAL_WRITES":1, "ORDERED_WRITES":1, "MIXED_ACCESSES":1, "ALLOW_WRITE_ERRORS":1},
             ("mixed", "no-flow", "partial"), (), ("--inject-mismatch",), "TileLink bridge response data, error or order mismatch"),
            ("tl-ram", "ooo.TileLinkBurstRamGsimMain", "TileLinkBurstRamGsim", "tilelink_burst_ram.cpp", {},
             (), ("--partial-only",), ("--partial-inject",), "TileLink burst Get beat, source, data or error mismatch"),
            ("tl-axi", "ooo.TileLinkAxi4BridgeGsimMain", "TileLinkAxi4Bridge", "tilelink_axi4_burst.cpp", {},
             (32,4,"burst",16), ("--partial-only",), ("--partial-inject",), "AXI W data/strobe/WLAST mismatch"),
            ("tl-axi-single", "ooo.TileLinkAxi4BridgeGsimMain", "TileLinkAxi4Bridge", "tilelink_axi4_burst.cpp", {},
             (32,4,"single",16), ("--partial-single",), ("--partial-inject",), "AXI W data/strobe/WLAST mismatch"),
        ):
            if stem in reusable:
                model = a.reuse.resolve().parent / stem
                row = reusable[stem]
                if sha256(model / (top+".fir")) != row["fir_sha256"] or sha256(model / "run") != row["executable_sha256"]:
                    raise RuntimeError("previous model drift: " + stem)
                report[stem] = {**row,"reused_model_directory":str(model)}
                print("BYTE_IDENTICAL_ACCEPTANCE_REUSED " + stem,flush=True)
                continue
            model = test(gsim, cxx, name + "/" + stem, main, top, harness, defines=defines,
                         parameters=parameters, runtime_args=runtime)
            if bad_args: reject(model / "run", bad_args, anchor, model / "negative.log", protocol=stem.startswith("tl-"))
            else: negative(model / "run", (), anchor, model / "negative.log")
            if stem in {"tl-ram", "tl-axi"}:
                run([model / "run"], log=model / "full-beats.log", env={**os.environ,
                    "ASAN_OPTIONS":"detect_leaks=0"}, timeout=120)
            if stem == "tl-axi":
                for bad, message in (("--bad-partial-mask", "TL partial mask outside access"),
                                     ("--bad-partial-control", "TL write burst changed control fields")):
                    reject(model / "run", (bad,), message, model / (bad[2:] + ".log"), protocol=True)
            report[stem] = {"status": "passed", "fir_sha256": sha256(model / (top + ".fir")),
                            "executable_sha256": sha256(model / "run")}
        report["status"] = "passed"
    except BaseException as error:
        report.update(status="failed", failure=str(error))
        raise
    finally:
        if before != inputs(): report.update(status="failed", failure="input drift")
        (output / "receipt.json").write_text(json.dumps(report, indent=2) + "\n")
    if report["status"] != "passed": raise RuntimeError(report["failure"])
    print(f"ETHERNET_DMA_SHORT_PASS receipt={output / 'receipt.json'}", flush=True)


if __name__ == "__main__": main()
