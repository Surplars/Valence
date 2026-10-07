#!/usr/bin/env python3
"""Affected-only 2 GiB address/range regression; no Linux simulation or CAD."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from run import BUILD, ROOT, HERE, run, setup, test

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--reuse-record", type=Path,
                        help="reuse passed unchanged models from a partial run, with exact hashes")
    args = parser.parse_args()
    if not re.fullmatch("[A-Za-z0-9_-]+", args.tag):
        parser.error("unsafe tag")
    name = "ddr2g-" + args.tag
    out = BUILD / name
    out.mkdir(parents=True, exist_ok=False)
    paths = sorted((ROOT / "src").rglob("*.scala")) + [
        Path(__file__), HERE / "run.py", *[HERE / "harness" / n for n in (
            "tilelink_axi4_burst.cpp", "ddr2g_dma.cpp", "dma.cpp", "address_decode.cpp")]]
    before = {str(p.relative_to(ROOT)): sha(p) for p in paths}
    previous = json.loads(args.reuse_record.read_text()) if args.reuse_record else {}
    record = dict(status="running", capacity_bytes=0x80000000,
        ram_base="0x80200000", end_exclusive="0x100200000",
        source_sha256=before, board_verified=False, routed_timing_verified=False,
        scope="bridge/window/decoder/generic DMA plus production RTL export, not Linux or whole CPU runtime")
    try:
        gsim, cxx = setup(False)
        rows = (
            ("axi2g", "ooo.TileLinkAxi4BridgeGsimMain", "TileLinkAxi4Bridge",
             "tilelink_axi4_burst.cpp", (32,4,"burst",16,0x80200000,0x80000000),
             {"DDR_2G":1}, ("--ddr2g",), ("--partial-inject",), "AXI W data/strobe/WLAST mismatch"),
            ("axi-legacy", "ooo.TileLinkAxi4BridgeGsimMain", "TileLinkAxi4Bridge",
             "tilelink_axi4_burst.cpp", (32,4,"burst",16), {}, (),
             ("--partial-inject",), "AXI W data/strobe/WLAST mismatch"),
            ("dma2g", "ip.DmaGsimMain", "MemoryCopyDma", "ddr2g_dma.cpp",
             (0x80200000,0x80000000), {}, (), ("--inject-mismatch",), "DDR2G DMA independent data oracle"),
            ("dma-legacy", "ip.DmaGsimMain", "MemoryCopyDma", "dma.cpp",
             (), {}, (), ("--inject-mismatch",), "copy data mismatch"),
            ("decode2g", "ip.AddressDecoderGsimMain", "TwoBankAddressDecoder", "address_decode.cpp",
             (64,"ddr2g"), {"ADDRESS_WIDTH":64, "DECODER_BASE":"0x80000000ULL",
                           "BANK_BYTES":2097152,"SECOND_BYTES":"0x80000000ULL"}, (),
             ("--inject-mismatch",), "static address decode oracle mismatch"),
        )
        for stem, main, top, harness, params, defines, runtime, negative, message in rows:
            old = previous.get(stem, {})
            protected = [str(p.relative_to(ROOT)) for p in paths
                         if str(p.relative_to(ROOT)).startswith("src/") or p == HERE / "run.py" or
                         p == HERE / "harness" / harness]
            if old.get("status") == "passed" and all(
                    before[key] == previous["source_sha256"].get(key) for key in protected):
                model = args.reuse_record.parent / stem
                if sha(model/(top+".fir")) != old["fir_sha256"] or sha(model/"run") != old["executable_sha256"]:
                    raise RuntimeError("sealed unchanged model drift: "+stem)
                record[stem] = {**old, "reused_from": str(model)}
                print("UNCHANGED_ADDRESS_MODEL_REUSED "+stem,flush=True)
                continue
            model = test(gsim,cxx,name+"/"+stem,main,top,harness,
                         parameters=params,defines=defines,runtime_args=runtime)
            result = subprocess.run([str(model/"run"), *negative], capture_output=True, text=True,
                                    timeout=120,env={**os.environ,"ASAN_OPTIONS":"detect_leaks=0"})
            (model/"negative.log").write_text(result.stdout+result.stderr)
            if result.returncode == 0 or message not in result.stdout+result.stderr:
                raise RuntimeError("independent negative control not rejected: "+stem)
            record[stem] = dict(status="passed",fir_sha256=sha(model/(top+".fir")),
                executable_sha256=sha(model/"run"),negative_oracle_rejected=True,
                log=(model/"test.log").read_text())
        production = out / "production-rtl"
        run(["mill","-i","IonSoC.test.runMain","ooo.ManagedBoardSocMain",production,
             100000000,"staged-fetch-feedback",460800,"rv64gc",50000000,50000000,250000000,
             0x80000000],log=out/"production-export.log",timeout=300)
        record["production_rtl"] = {p.name:sha(p) for p in production.glob("*.sv")}
        if not record["production_rtl"]:
            raise RuntimeError("empty production RTL export")
        if before != {str(p.relative_to(ROOT)):sha(p) for p in paths}:
            raise RuntimeError("sources changed during address regression")
        record["status"]="passed"
    except Exception as error:
        record.update(status="failed",error=str(error))
        raise
    finally:
        (out/"receipt.json").write_text(json.dumps(record,indent=2)+"\n")
    print("DDR2G_SHORT_PASS "+str(out/"receipt.json"),flush=True)

if __name__ == "__main__":
    main()
