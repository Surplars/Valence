#!/usr/bin/env python3
"""Check that native tests reject historical/protocol faults; edits only build copies."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
from run import ROOT, RTL, run

MUTATIONS = {
    "ir-capture-off-by-one": ("if (state == CAPTURE_IR) ir_shift <= 5'b00001;",
                             "if (state == CAPTURE_IR) ir_shift <= 5'b00010;", "IR capture"),
    "dtm-version-two": ("ADDRESS_BITS, 4'h1", "ADDRESS_BITS, 4'h2", "DTMCS wrong"),
    "bypass-two-bits": ("{{(ABITS+33){1'b0}}, tdi};", "{{(ABITS+32){1'b0}}, tdi, dr_shift[0]};", "BYPASS"),
    "busy-not-sticky": ("sticky_status <= 2'b11;", "sticky_status <= 2'b00;", "busy not sticky"),
    "unheld-cdc-payload": ("response_sync <= {response_sync[0], response_toggle};",
                          "response_sync <= {response_sync[0], response_toggle}; request_held <= s_req_payload;", "stalled request unstable"),
    "stub-false-success": ("assign rsp_status = 2'b10;", "assign rsp_status = 2'b00;", "stub falsely reported"),
}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,default=ROOT/"build/jtag/mutations")
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    compiler=shutil.which(os.environ.get("IVERILOG","iverilog"));runtime=shutil.which(os.environ.get("VVP","vvp"))
    if not compiler or not runtime: raise SystemExit("Native simulator unavailable; mutation coverage is unverified")
    source=RTL.read_text();report={}
    for name,(before,after,reason) in MUTATIONS.items():
        if before not in source: raise RuntimeError(f"Mutation anchor missing: {name}")
        directory=args.output/name;directory.mkdir(exist_ok=True)
        mutated=directory/RTL.name;mutated.write_text(source.replace(before,after))
        binary=directory/"run.vvp"
        bench = "dmi_cdc_tb" if name == "unheld-cdc-payload" else "jtag_debug_tb"
        run([compiler,"-g2012","-s",bench,"-o",binary,mutated,
             ROOT/"simulator/jtag"/(bench+".sv")],directory/"compile.log")
        result=subprocess.run([runtime,str(binary)],capture_output=True,text=True,timeout=120)
        (directory/"test.log").write_text(result.stdout+result.stderr)
        detected=result.returncode!=0 and reason in result.stdout+result.stderr
        report[name]={"detected":detected,"exit_code":result.returncode,"expected_diagnostic":reason}
        if not detected: raise RuntimeError(f"Mutation escaped or failed for wrong reason: {name}: {result.stdout}{result.stderr}")
    (args.output/"results.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps(report,indent=2))

if __name__=="__main__":main()
