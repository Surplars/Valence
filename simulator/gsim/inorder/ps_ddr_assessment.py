#!/usr/bin/env python3
"""Focused PS DDR wiring and cold-launch contract; not a PS DDR/PHY board test."""
import argparse, hashlib, json, os, subprocess, sys
from pathlib import Path
R=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(R/"simulator/gsim"))
from gsim_clock_edge_epoch import tool_binding

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument("--output",type=Path,required=True);ap.add_argument("--tool-receipt",type=Path,required=True)
    args=ap.parse_args();o=args.output.resolve();g=tool_binding(args.tool_receipt)
    if o.exists() or not o.is_relative_to(R/"build"): ap.error("fresh output within build/ required")
    o.mkdir(parents=True)
    names=["integration/spinor/src/main/scala/I1SpinorPsDdr.scala",
           "integration/spinor/src/test/scala/I1PsDdrMain.scala","src/main/scala/ip/bus/ClockDomainCrossing.scala",
           "src/main/scala/ip/axi/Axi4MemoryPort.scala","simulator/gsim/harness/i1_ps_ddr.cpp",
           "simulator/gsim/inorder/ps_ddr_assessment.py","build.mill"]
    sources={n:sha(R/n) for n in names}
    receipt={"status":"RUNNING","source_sha256":sources,"commands":[],"board_qualified":False}
    def run(argv,log,negative=False):
        argv=list(map(str,argv));receipt["commands"].append({"argv":argv,"log":log})
        with (o/log).open("w") as f:
            p=subprocess.run(argv,cwd=R,stdout=f,stderr=subprocess.STDOUT,
                env={**os.environ,"ASAN_OPTIONS":"detect_leaks=0","GSIM_CLOCK_EDGES":"1"})
        text=(o/log).read_text()
        if negative:
            if p.returncode!=1 or "independent PS physical address oracle" not in text: raise RuntimeError(log)
        elif p.returncode: raise RuntimeError(log+"\n"+text[-4000:])
        return text
    try:
        run(["mill","-i","SpinorHost.test.runClasspath"],"scala-compile.log")
        v=json.loads((R/"out/SpinorHost/test/runClasspath.json").read_text())["value"]
        cp=os.pathsep.join(str(p) for s in v if (p:=Path(s.split(":",3)[3])).exists())
        receipt["class_sha256"]={str(p.relative_to(R)):sha(p) for module in ["OrbitalI1","SpinorHost","SpinorHost/test"]
            for p in (R/"out"/module/"compile.dest/classes").rglob("*.class")}
        c="clang++-19";receipt["gsim_sha256"]=sha(g)
        receipt["qualified_tool_receipt_sha256"]=sha(args.tool_receipt)
        run(["java","-cp",cp,"spinor_integration.I1PsDdrMain",o],"elaborate.log")
        top="I1PsDdrFixture"
        run([g,"--threads=1","--dir="+str(o),o/(top+".fir")],"generate.log")
        run([c,"-std=c++20","-O1","-g","-fsanitize=address,undefined","-fno-sanitize-recover=all",
             "-I"+str(o),*sorted(o.glob(top+"[0-9]*.cpp")),R/"simulator/gsim/harness/i1_ps_ddr.cpp","-o",o/"run"],"compile.log")
        receipt["summary"]=run([o/"run"],"positive.log").strip()
        run([o/"run","--bad-base"],"negative.log",True)
        assert sources=={n:sha(R/n) for n in names},"source changed after compilation"
        receipt["status"]="PASS_PS_DDR_CHANNELS_COLD_LAUNCH_AND_NEGATIVE"
    except BaseException as e: receipt.update(status="FAIL",error=repr(e));raise
    finally:
        receipt["artifact_sha256"]={p.name:sha(p) for p in o.iterdir() if p.is_file() and p.name!="receipt.json"}
        (o/"receipt.json").write_text(json.dumps(receipt,indent=2)+"\n")
    print(receipt["status"],receipt["summary"],flush=True)
if __name__=="__main__":main()
