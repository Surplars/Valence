#!/usr/bin/env python3
"""Reuse frozen batch44 GSIM objects for firmware smoke; no RTL generation or synthesis."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--firmware",required=True,type=Path)
    ap.add_argument("--output",required=True,type=Path)
    ap.add_argument("--proof",type=Path,default=ROOT/"build/gsim/i1-bandwidth44-20261018-r2/receipt.json")
    args=ap.parse_args()
    fw=args.firmware.resolve(); proof=json.loads(args.proof.read_text()); model=args.proof.parent/"cpu"
    manifest=json.loads((fw/"manifest.json").read_text())
    for name,digest in manifest["source_sha256"].items():
        if sha(ROOT/name)!=digest: raise RuntimeError("firmware source drift: "+name)
    for name,digest in manifest["files_sha256"].items():
        if sha(fw/name)!=digest: raise RuntimeError("firmware artifact drift: "+name)
    if proof["status"]!="PASS_I1_BANDWIDTH44_AFFECTED_SHORT_ONLY":
        raise RuntimeError("source-qualified batch44 model required")
    for name,digest in proof["source_sha256"].items():
        if sha(ROOT/name)!=digest: raise RuntimeError("hardware source drift: "+name)
    for p in [model/"FiveStageSoc.h", *model.glob("FiveStageSoc[0-9]*.o")]:
        if sha(p)!=proof["artifact_sha256"][str(p.relative_to(args.proof.parent))]:
            raise RuntimeError("frozen GSIM object drift: "+str(p))
    out=args.output.resolve(); out.mkdir(parents=True,exist_ok=False)
    binary=out/"check-menu"
    compile_cmd=["clang++-19","-std=c++20","-O1","-fsanitize=address,undefined","-fno-sanitize-recover=all",
        "-DDUT_XLEN=64","-DI1_COHERENT_READBACK=1","-I"+str(model),"-I"+str(ROOT/"simulator/gsim/harness"),
        *map(str,model.glob("FiveStageSoc[0-9]*.o")),str(HERE/"check_menu.cpp"),"-o",str(binary)]
    with (out/"compile.log").open("x") as log:
        subprocess.run(compile_cmd,check=True,stdout=log,stderr=subprocess.STDOUT)
    env={**os.environ,"ASAN_OPTIONS":"detect_leaks=0"}
    checks={}
    for kind,variant,extra in (("short","smoke",[]),("negative","smoke",["--wrong-result"]),("uart","menu",["--uart"])):
        stem="i1_diag_"+variant+"_cpu300_o3"
        symbols=subprocess.check_output(["riscv64-unknown-elf-nm",str(fw/(stem+".elf"))],text=True)
        address=next(int(row.split()[0],16) for row in symbols.splitlines() if row.endswith(" diag_receipt"))
        command=[str(binary),str(fw/(stem+".bin")),hex(address),*extra]
        started=time.monotonic()
        with (out/(kind+".log")).open("x") as log:
            result=subprocess.run(command,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=240)
        text=(out/(kind+".log")).read_text()
        if kind=="negative":
            if result.returncode==0 or "independent Bare/Sv39 checksum oracle" not in text:
                raise RuntimeError("negative checksum not rejected: "+text[-2000:])
        elif result.returncode or ("I1_MENU_SHORT_PASS" if kind=="short" else "I1_MENU_UART_PASS") not in text:
            raise RuntimeError(kind+" failed: "+text[-2000:])
        checks[kind]={"returncode":result.returncode,"elapsed_seconds":round(time.monotonic()-started,3),"tail":text.strip().splitlines()[-1]}
        print(kind+": "+checks[kind]["tail"],flush=True)
    receipt={"status":"PASS_I1_MENU_FIRMWARE_SHORT_ONLY","checks":checks,
        "firmware_manifest_sha256":sha(fw/"manifest.json"),"hardware_receipt_sha256":sha(args.proof),
        "scope":"Real CPU/S-mode/nonidentity Sv39/32KiB caches/TL-C/AXI; one CoreMark iteration and shipping UART banner. Not formal score, DMA, physical UART CDC or board success.",
        "source_sha256":{str(p.relative_to(ROOT)):sha(p) for p in HERE.iterdir() if p.is_file()},
        "artifact_sha256":{p.name:sha(p) for p in out.iterdir() if p.is_file()}}
    (out/"receipt.json").write_text(json.dumps(receipt,indent=2)+"\n")


if __name__=="__main__": main()
