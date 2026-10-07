#!/usr/bin/env python3
"""Only changed RV64M integration cases, reusing an exact accepted CPU model."""
import argparse
import json
import os
from pathlib import Path
from run import HERE, ROOT, compiler, run
from control_stage import reference
import throughput_perf as perf


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("short_receipt",type=Path)
    args=parser.parse_args()
    old=json.loads(args.short_receipt.read_text())
    assert old["status"]=="PASS_NATIVE_TIMING_SHORT"
    for relative,sha in old["source_sha256"].items():
        assert perf.sha256(ROOT/relative)==sha,"accepted input drift: "+relative
    model=args.short_receipt.resolve().parent/"core"
    assert perf.sha256(model/"IntegerCoreGsim.fir")==old["core"]["fir_sha256"]
    out=args.short_receipt.resolve().parent/"rv64m-core"
    out.mkdir(exist_ok=False)
    inputs=[*model.glob("IntegerCoreGsim*.cpp"),model/"IntegerCoreGsim.h",
            HERE/"harness/muldiv_core_short.cpp",HERE/"harness/core.cpp",Path(__file__)]
    hashes={str(p):perf.sha256(p) for p in inputs}
    result={"status":"RUNNING","base_receipt_sha256":perf.sha256(args.short_receipt),
            "input_sha256":hashes,"scope":"same real CPU; RV64M only; per-retirement NEMU"}
    try:
        cxx,_=compiler()
        flags={**perf.DEFINES,"REGISTERED_FETCH_PACKET":1,"FETCH_HINT_ALIAS_BENCH":1}
        run([cxx,"-std=c++20","-O1","-g","-fsanitize=address,undefined",
             "-fno-sanitize-recover=all",*[f"-D{k}={v}" for k,v in flags.items()],
             "-I"+str(model),*model.glob("IntegerCoreGsim*.cpp"),
             HERE/"harness/muldiv_core_short.cpp","-ldl","-o",out/"run"],log=out/"compile.log")
        ref=reference()
        assert perf.sha256(ref)==old["reference_sha256"]
        run([out/"run",ref],env={**os.environ,"ASAN_OPTIONS":"detect_leaks=0"},
            log=out/"test.log",timeout=120)
        text=(out/"test.log").read_text()
        assert "GSIM short RV64M CPU + NEMU: PASS" in text
        result.update(status="PASS_RV64M_CORE_SHORT",summary=text,
                      executable_sha256=perf.sha256(out/"run"))
    except BaseException as error:
        result.update(status="FAILED",failure=str(error));raise
    finally:
        if hashes!={str(p):perf.sha256(p) for p in inputs}:
            result.update(status="FAILED",failure="input drift")
        (out/"receipt.json").write_text(json.dumps(result,indent=2)+"\n")
    if result["status"]!="PASS_RV64M_CORE_SHORT":raise RuntimeError(result["failure"])
    print(result["summary"],flush=True)


if __name__=="__main__":main()
