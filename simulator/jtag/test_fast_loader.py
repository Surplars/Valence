#!/usr/bin/env python3
"""Host-only stock Tcl + actual OpenOCD/Jim mocks. No adapter config or init."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
STOCK_RUNNER=r'''
import ctypes,sys
lib=ctypes.CDLL("libtcl8.6.so")
lib.Tcl_FindExecutable.argtypes=[ctypes.c_char_p]; lib.Tcl_FindExecutable(b"python3")
lib.Tcl_CreateInterp.restype=ctypes.c_void_p
interp=lib.Tcl_CreateInterp()
lib.Tcl_Init.argtypes=[ctypes.c_void_p]; lib.Tcl_Init.restype=ctypes.c_int
lib.Tcl_EvalFile.argtypes=[ctypes.c_void_p,ctypes.c_char_p]; lib.Tcl_EvalFile.restype=ctypes.c_int
lib.Tcl_GetStringResult.argtypes=[ctypes.c_void_p]; lib.Tcl_GetStringResult.restype=ctypes.c_char_p
rc=lib.Tcl_Init(interp)
if not rc: rc=lib.Tcl_EvalFile(interp,sys.argv[1].encode())
if rc: print(lib.Tcl_GetStringResult(interp).decode(),file=sys.stderr)
sys.exit(bool(rc))
'''


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output",required=True,type=Path)
    args=ap.parse_args(); out=args.output.resolve(); out.mkdir(parents=True,exist_ok=False)
    scripts=["ram-loader-test.tcl","ram-loader-bscan-test.tcl","ram-loader-fast-test.tcl","ram-loader-fast-cost.tcl"]
    sources=[HERE/n for n in ("ram-loader.tcl","ram-loader-bscan.tcl","ram-loader-xczu15eg.tcl","fast_sba_gsim.cpp",
        "upgrade-host.tcl","README-FAST.txt",
        "openocd-ram-loader-bscan.cfg",
        "ram-loader-test-model.tcl","test_fast_loader.py",*scripts)]
    frozen={str(p.relative_to(ROOT)):sha(p) for p in sources}
    results={}; census={}
    for runtime in ("stock-tcl86","openocd-jim"):
        for name in scripts:
            key=runtime+"-"+name.removesuffix(".tcl")
            command=([sys.executable,"-c",STOCK_RUNNER,str(HERE/name)] if runtime=="stock-tcl86" else
                     ["openocd","-f",str(HERE/name),"-c","shutdown"])
            result=subprocess.run(command,cwd=ROOT,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=90)
            (out/(key+".log")).write_text(result.stdout)
            counts=re.findall(r"(\d+) passed, (\d+) failed",result.stdout)
            if result.returncode or not counts or any(int(failed) for passed,failed in counts) or "FAIL " in result.stdout:
                raise RuntimeError(key+" failed:\n"+result.stdout[-5000:])
            passed,failed=map(int,counts[-1]); results[key]={"passed":passed,"failed":failed,"returncode":result.returncode}
            print(key+": "+str(passed)+" passed",flush=True)
            if name=="ram-loader-fast-cost.tcl":
                rows=[]
                for line in result.stdout.splitlines():
                    if not line.startswith("CENSUS "): continue
                    row=dict(item.split("=",1) for item in line.split()[1:])
                    rows.append({k:v if k=="mode" else int(v) for k,v in row.items()})
                census[runtime]=rows
    if census["stock-tcl86"]!=census["openocd-jim"]: raise RuntimeError("interpreter census differs")
    for size in (4096,29296):
        rows={r["mode"]:r for r in census["stock-tcl86"] if r["bytes"]==size}
        if (set(rows)!={"safe","fast"} or rows["fast"]["ir"]>40 or
                rows["fast"]["ir"]+rows["fast"]["dr"] >= .3*(rows["safe"]["ir"]+rows["safe"]["dr"])):
            raise RuntimeError("scan count improvement gate failed")
    # Firmware/RTL are unchanged: reuse the small already-compiled real loader,
    # checking streamed read side effects against its independent byte bus.
    prior_path=ROOT/"build/gsim/i1-bandwidth44-20261018-r2/receipt.json"
    prior=json.loads(prior_path.read_text()); model=prior_path.parent/"jtag-cuts"
    for name,digest in prior["source_sha256"].items():
        if sha(ROOT/name)!=digest: raise RuntimeError("frozen hardware source drift: "+name)
    objects=[model/"I1JtagTimingFixture.h",*model.glob("I1JtagTimingFixture[0-9]*.o")]
    for p in objects:
        if sha(p)!=prior["artifact_sha256"][str(p.relative_to(prior_path.parent))]:
            raise RuntimeError("frozen GSIM artifact drift: "+str(p))
    binary=out/"fast-sba-gsim"
    cmd=["clang++-19","-std=c++20","-O1","-fsanitize=address,undefined","-fno-sanitize-recover=all",
         "-I"+str(model),"-I"+str(ROOT/"simulator/gsim/harness"),
         *map(str,model.glob("I1JtagTimingFixture[0-9]*.o")),str(HERE/"fast_sba_gsim.cpp"),"-o",str(binary)]
    with (out/"gsim-compile.log").open("x") as log:
        subprocess.run(cmd,cwd=ROOT,check=True,stdout=log,stderr=subprocess.STDOUT,timeout=90)
    gsim={}
    for name,args in (("positive",[]),("negative",["--wrong-word"])):
        p=subprocess.run([str(binary),*args],cwd=ROOT,env={**os.environ,"ASAN_OPTIONS":"detect_leaks=0"},
                         text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=30)
        (out/("gsim-"+name+".log")).write_text(p.stdout)
        if ((name=="positive" and (p.returncode or "I1_FAST_SBA_GSIM_PASS cases=48" not in p.stdout)) or
                (name=="negative" and (not p.returncode or "independent streamed RTL readback oracle" not in p.stdout))):
            raise RuntimeError("GSIM "+name+" failed: "+p.stdout[-1500:])
        gsim[name]={"returncode":p.returncode,"tail":p.stdout.strip().splitlines()[-1]}
        print("GSIM "+name+": "+gsim[name]["tail"],flush=True)
    for name,digest in frozen.items():
        if sha(ROOT/name)!=digest: raise RuntimeError("source changed during tests: "+name)
    proof={"status":"PASS_FAST_LOADER_HOST_AND_REUSED_SBA_RTL","results":results,"census":census,"gsim":gsim,
        "gsim_source_receipt_sha256":sha(prior_path),"gsim_objects_sha256":{str(p):sha(p) for p in objects},
        "source_sha256":frozen,"no_adapter_or_init":True,"rtl_changed":False,"board_speed_measured":False,
        "runtime_scope":"libtcl8.6 and actual local OpenOCD0.12 Jim; all scan/bus commands replaced by independent mocks",
        "artifact_sha256":{p.name:sha(p) for p in out.iterdir() if p.is_file()}}
    (out/"receipt.json").write_text(json.dumps(proof,indent=2)+"\n")
    print(json.dumps({"status":proof["status"],"census":census["stock-tcl86"]},indent=2))


if __name__=="__main__": main()
