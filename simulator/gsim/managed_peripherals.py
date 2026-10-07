#!/usr/bin/env python3
"""Batch CMU/UART/native-GMAC integration; necessary short tests, never CPU/bit."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from run import BUILD, HERE, ROOT, run, setup, test


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag",required=True)
    args=parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+",args.tag):parser.error("unsafe tag")
    name="managed-peripherals-"+args.tag
    output=BUILD/name
    output.mkdir(parents=True,exist_ok=False)
    paths=list((ROOT/"src/main/scala").rglob("*.scala"))
    paths+=list((ROOT/"src/test/scala/ip").glob("ManagedPeripherals*.scala"))
    paths += [HERE/"harness"/f for f in ("managed_peripherals.cpp","gmii_reference.h",
        "uart_formats.cpp","self_gmac_dma.cpp")]
    paths += [Path(__file__),HERE/"run.py",HERE/"config/toolchain.json",ROOT/"build.mill"]
    before={str(p.relative_to(ROOT)):digest(p) for p in sorted(paths)}
    report={"status":"RUNNING","source_sha256":before,"scope":"real managed UART/GMAC/DMA adapter",
        "single_clock_only":True,"physical_gate_verified":False,"board_verified":False,"bit_generated":False}
    try:
        run(["mill","-i","IonSoC.test.testOnly","ip.ManagedPeripheralsSpec"],log=output/"scala.log")
        run(["mill","-i","IonSoC.test.runMain","ip.ManagedPeripheralsRtlMain",output/"rtl"],
            log=output/"rtl-export.log")
        gsim,cxx=setup(False)
        model=test(gsim,cxx,name+"/integration","ip.ManagedPeripheralsGsimMain","ManagedPeripheralGsim",
            "managed_peripherals.cpp")
        report["integration"]={"summary":(model/"test.log").read_text().strip(),
            "fir_sha256":digest(model/"ManagedPeripheralGsim.fir"),"executable_sha256":digest(model/"run")}
        report["negative_checks"]={}
        for flag,marker in (("uart","managed UART first-character independent oracle mismatch"),
            ("frame","managed GMAC independent wire oracle mismatch")):
            result=subprocess.run([str(model/"run"),"--inject-"+flag],capture_output=True,text=True,
                timeout=60,env={**os.environ,"ASAN_OPTIONS":"detect_leaks=0"})
            (model/("negative-"+flag+".log")).write_text(result.stdout+result.stderr)
            if result.returncode!=1 or marker not in result.stderr:raise RuntimeError("negative did not reject: "+flag)
            report["negative_checks"][flag]="passed"
        # Existing unmodified four-credit DMA protocol plus UART formats are
        # affected regression boundaries, not full CPU/NEMU acceptance.
        for stem,main,top,harness in (("uart-formats","ip.UartGsimMain","UartConsole","uart_formats.cpp"),
            ("dma","ip.SelfGmacDmaGsimMain","SelfGmacDmaGsim","self_gmac_dma.cpp")):
            model=test(gsim,cxx,name+"/"+stem,main,top,harness)
            report[stem]={"summary":(model/"test.log").read_text().strip()}
        report["status"]="PASS_MANAGED_PERIPHERALS_SINGLE_CLOCK"
    except BaseException as error:
        report.update(status="FAILED",failure=str(error));raise
    finally:
        if before!={str(p.relative_to(ROOT)):digest(p) for p in sorted(paths)}:
            report.update(status="FAILED",failure="input drift during verification")
        report["rtl_sha256"]={str(p.relative_to(output)):digest(p) for p in sorted((output/"rtl").glob("*.sv"))}
        (output/"receipt.json").write_text(json.dumps(report,indent=2)+"\n")
    if report["status"]!="PASS_MANAGED_PERIPHERALS_SINGLE_CLOCK":raise RuntimeError(report["failure"])
    print(report["status"],"receipt="+str(output/"receipt.json"),flush=True)


if __name__=="__main__":main()
