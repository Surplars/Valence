#!/usr/bin/env python3
"""Native edge-accurate JTAG tests; no install, retired simulator, or hardware access."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
RTL = ROOT / "src/main/resources/debug/ValenceJtagDebugPort.sv"

def run(command, log):
    result = subprocess.run(list(map(str, command)), text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=120)
    log.write_text(result.stdout)
    if result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}): {' '.join(map(str,command))}\n{result.stdout}")
    return result.stdout

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "build/jtag/native")
    args = parser.parse_args()
    output = args.output.resolve(); output.mkdir(parents=True, exist_ok=True)
    report = {"status": "running", "native_multiclock_verified": False,
              "physical_cdc_signoff": False, "hart_debug_implemented": False,
              "rtl_sha256": hashlib.sha256(RTL.read_bytes()).hexdigest()}
    iverilog = shutil.which(os.environ.get("IVERILOG", "iverilog"))
    vvp = shutil.which(os.environ.get("VVP", "vvp"))
    if not iverilog or not vvp:
        report.update(status="blocked", blocker="Icarus Verilog and vvp not found. No tool was installed.")
        (output / "results.json").write_text(json.dumps(report, indent=2)+"\n")
        print(json.dumps(report, indent=2)); return 77
    try:
        report["iverilog"] = run([iverilog,"-V"],output/"version.log").splitlines()[0]
        for name in ("jtag_debug", "dmi_cdc", "dtm_completion"):
            run([iverilog,"-g2012","-Wall","-s",name+"_tb","-o",output/(name+".vvp"),
                 RTL,ROOT/"simulator/jtag"/(name+"_tb.sv")],output/(name+"-compile.log"))
            result=run([vvp,output/(name+".vvp")],output/(name+".log"))
            if "PASS" not in result: raise RuntimeError("Missing explicit test PASS")
            print(result, end="")
            report[name]=result.strip().splitlines()
        for bits in (1, 7, 32):
            name=f"parameters-{bits}"
            run([iverilog,"-g2012","-Wall","-s","jtag_parameters_tb",
                 "-Pjtag_parameters_tb.ABITS="+str(bits),"-o",output/(name+".vvp"),
                 RTL,ROOT/"simulator/jtag/jtag_parameters_tb.sv"],output/(name+"-compile.log"))
            result=run([vvp,output/(name+".vvp")],output/(name+".log"))
            if "PASS" not in result: raise RuntimeError("Missing parameter-test PASS")
            print(result,end=""); report[name]=result.strip()
        census={}
        for name,enabled,external in (("off",0,0),("stub",1,0),("external",1,1)):
            path=output/(name+"-census.vvp")
            run([iverilog,"-g2012","-s","ValenceJtagDebugPort","-PValenceJtagDebugPort.ENABLE="+str(enabled),
                 "-PValenceJtagDebugPort.EXTERNAL_DMI="+str(external),"-o",path,RTL],output/(name+"-census.log"))
            text=path.read_text()
            variables=re.findall(r'\.var(?:/\w+)?\s+"([^"]+)",\s*(-?\d+)\s+(-?\d+)',text)
            census[name]={"elaborated_variables":len(variables),
                          "elaborated_variable_bits":sum(abs(int(hi)-int(lo))+1 for _,hi,lo in variables),
                          "simulation_processes":len(re.findall(r'^\s*\.thread ',text,re.M)),
                          "note":"Icarus elaboration census; not synthesis, LUT/FF area, Fmax or routed PPA."}
        if census["off"]["elaborated_variable_bits"] or census["off"]["simulation_processes"]:
            raise RuntimeError("Disabled implementation retained storage/processes")
        report.update(status="passed",native_multiclock_verified=True,census=census)
    except Exception as error:
        report.update(status="failed",error=str(error)); raise
    finally:
        (output / "results.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps(report,indent=2)); return 0

if __name__ == "__main__":
    sys.exit(main())
