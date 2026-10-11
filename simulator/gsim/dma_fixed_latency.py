#!/usr/bin/env python3
"""Fixed external delay robustness check of qualified, hash-identical RTL models.

No re-elaboration/synthesis: verifies every original input plus generated FIR,
headers and C++ against a passing primary receipt before rebuilding only the
independent host driver. Original ID-skew results are retained, not overwritten.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import run as common
import latency_bandwidth
import ddr_write_collection as collection
from dma_overlap import parse


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tag",required=True)
    ap.add_argument("--receipt",type=lambda s: common.ROOT / s,required=True)
    args=ap.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+",args.tag): ap.error("unsafe tag")
    origin=json.loads(args.receipt.read_text())
    if origin["status"]!="PASS_LATENCY_CAPACITY_AND_SV39_REUSE": ap.error("passing primary receipt required")
    if any(collection.sha(common.ROOT/k)!=v for k,v in origin["source_sha256"].items()):
        raise RuntimeError("primary source drift; cannot reuse generated model")
    frozen=latency_bandwidth.inputs()
    for name in ("simulator/gsim/dma_fixed_latency.py","simulator/gsim/harness/dma_fixed_latency.cpp"):
        frozen[name]=collection.sha(common.ROOT/name)
    output=common.BUILD/("dma-fixed-latency-"+args.tag)
    if output.exists(): ap.error("fresh tag required")
    output.mkdir(parents=True)
    report={"status":"RUNNING","source_sha256":frozen,
        "primary_receipt":str(args.receipt),"primary_receipt_sha256":collection.sha(args.receipt),
        "scope":__doc__,"service":{"R_delay":32,"B_delay":40,"ID_skew":False,
                                    "read_capacity":8,"write_capacity":4,"ready_stall_moduli":[7,11,5]},
        "models":{},"negatives":{},"roof_MiBps_at_assumed_100MHz":8*100000000/1048576}
    env={**os.environ,"ASAN_OPTIONS":"detect_leaks=0"}
    try:
        gsim,cxx=common.setup(False)
        if collection.sha(gsim)!=origin["toolchain"]["gsim_sha256"] or common.compiler()[1]!=origin["toolchain"]["compiler"]:
            raise RuntimeError("primary toolchain changed")
        report["toolchain"]=origin["toolchain"]
        for key,geometry in origin["geometry"].items():
            print("Verified RTL reuse, fixed service: "+key,flush=True)
            source=args.receipt.parent/key; out=output/key; out.mkdir()
            copied={}
            files=sorted(p for p in source.iterdir() if p.suffix in (".fir",".h",".cpp"))
            if not files: raise RuntimeError("missing generated model")
            for path in files:
                digest=collection.sha(path); relative=str(path.relative_to(args.receipt.parent))
                if origin["artifacts_sha256"].get(relative)!=digest: raise RuntimeError("generated artifact drift: "+relative)
                shutil.copy2(path,out/path.name); copied[path.name]=digest
            defines={"DMA_LINE_ENABLED":1,"DMA_LINE_ENTRIES":geometry["dma_owners"],
                "DMA_AXI_SLOTS":geometry["ddr_slots"],"DMA_AXI_WRITES":geometry["write_slots"],
                "DMA_SERVICE_READS":8,"DMA_SERVICE_WRITES":4}
            common.run([cxx,"-std=c++20","-O1","-g","-fsanitize=address,undefined","-fno-sanitize-recover=all",
                *[f"-D{k}={v}" for k,v in defines.items()],"-I"+str(out),*sorted(out.glob("DmaPipelineGsim[0-9]*.cpp")),
                common.HERE/"harness/dma_fixed_latency.cpp","-ldl","-o",out/"run"],log=out/"compile.log")
            common.run([out/"run"],log=out/"test.log",env=env,timeout=120)
            if "DMA_FIXED_LATENCY_PASS" not in (out/"test.log").read_text(): raise RuntimeError("missing fixed-law proof")
            rows=parse(out,geometry["ddr_slots"],geometry["write_slots"])
            if len(rows)!=2: raise RuntimeError("incomplete fixed-service traffic")
            report["models"][key]={"geometry":geometry,"generated_sha256":copied,"measurements":rows}
            for mutation,anchor in (("drop-write","DMA independent destination byte oracle mismatch"),
                ("corrupt-write","DMA independent destination byte oracle mismatch"),
                ("early-ack","DMA completion retained independently tagged owner")):
                r=subprocess.run([out/"run","--mutate="+mutation],cwd=common.ROOT,env=env,capture_output=True,text=True,timeout=120)
                log=r.stdout+r.stderr; (out/("negative-"+mutation+".log")).write_text(log)
                if not r.returncode or anchor not in log: raise RuntimeError("fixed-service negative missed oracle: "+mutation)
                report["negatives"][key+":"+mutation]={"exit_code":r.returncode,"anchor":anchor}
        report["comparison"]=[]
        for key,model in report["models"].items():
            for base,row in zip(report["models"]["baseline"]["measurements"],model["measurements"]):
                if any(base[k]!=row[k] for k in ("case","bytes","mode","profile","axi_read_bytes","axi_write_bytes","axi_ar","axi_aw","axi_b")):
                    raise RuntimeError("fixed-service comparison changed traffic")
                report["comparison"].append({"configuration":key,"bytes":row["bytes"],"cycles":row["cycles"],
                    "payload_MiBps":row["payload_MiBps"],"gain_fraction":base["cycles"]/row["cycles"]-1,
                    "R_W_duty_each":row["axi_read_bytes"]/8/row["cycles"]})
        if any(collection.sha(common.ROOT/k)!=v for k,v in frozen.items()): raise RuntimeError("source drift during fixed-law acceptance")
        report["status"]="PASS_FIXED_AXI_LATENCY_ABLATIONS"
    except BaseException as error:
        report["status"]="FAILED"; report["error"]=str(error); raise
    finally:
        report["artifacts_sha256"]={str(p.relative_to(output)):collection.sha(p)
            for p in sorted(output.rglob("*")) if p.is_file() and p.name!="receipt.json"}
        (output/"receipt.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps({"status":report["status"],"receipt":str(output/"receipt.json"),"comparison":report["comparison"]},indent=2))


if __name__=="__main__": main()
