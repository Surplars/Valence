#!/usr/bin/env python3
"""Native Windows CDC-only xsim short test, with an independent negative scoreboard."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("rtl",type=Path)
    p.add_argument("output",type=Path)
    p.add_argument("--vivado-bin",type=Path,default=Path(r"E:\Xilinx\2025.1\Vivado\bin"))
    a=p.parse_args()
    if a.output.exists(): p.error("use a fresh output directory")
    a.output.mkdir(parents=True)
    here=Path(__file__).resolve().parent
    inputs=[*sorted(a.rtl.glob("*.sv")),here/"cdc_tb.sv",here/"cdc_run.tcl"]
    before={str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in inputs}
    for f in inputs: shutil.copy2(f,a.output/f.name)
    def run(tool,args,log):
        r=subprocess.run([str(a.vivado_bin/(tool+".bat")),*args],cwd=a.output,
            capture_output=True,text=True,timeout=90)
        (a.output/log).write_text(r.stdout+r.stderr)
        return r
    report={"status":"RUNNING","scope":"CDC modules only; not CPU/board timing",
        "input_sha256":before,"tool_bin":str(a.vivado_bin)}
    try:
        for tool,args,log in (("xvlog",["--sv",*[f.name for f in inputs if f.suffix==".sv"]],"compile.log"),
            ("xelab",["cdc_tb","--snapshot","cdc_short","--debug","typical","--timescale","1ns/1ps"],"elaborate.log")):
            r=run(tool,args,log)
            if r.returncode: raise RuntimeError(log+": "+(r.stdout+r.stderr)[-1500:])
        positive=run("xsim",["cdc_short","-tclbatch","cdc_run.tcl"],"positive.log")
        text=positive.stdout+positive.stderr
        if positive.returncode or "CDC_SHORT_PASS cases=4 requests=1200 beats=16384 coordinated_reset=1" not in text:
            raise RuntimeError("CDC positive failed: "+text[-1500:])
        negative=run("xsim",["cdc_short","-tclbatch","cdc_run.tcl","-testplusarg","inject"],"negative.log")
        bad=negative.stdout+negative.stderr
        if "CDC FIFO independent scoreboard mismatch" not in bad or "CDC_SHORT_PASS" in bad:
            raise RuntimeError("CDC negative control did not reject corruption")
        report.update(status="PASS_CDC_SHORT_RTL",positive=text,negative=bad,
            coordinated_reset_only=True,physical_cdc_constraints_verified=False)
    except Exception as error:
        report.update(status="FAIL_CDC_SHORT_RTL",failure=str(error))
        raise
    finally:
        if before!={str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in inputs}:
            report.update(status="FAIL_INPUT_DRIFT")
        (a.output/"receipt.json").write_text(json.dumps(report,indent=2)+"\n")
    print(report["status"])

if __name__=="__main__": main()
