#!/usr/bin/env python3
"""Reuse sealed board models; add passive ownership/address/value observations."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reference-root", type=Path, required=True)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--attempts", nargs="+", type=int, default=[3, 1])
    ap.add_argument("--reuse-passed", type=Path, help="reuse only individually completed, rehashed cases")
    args = ap.parse_args()
    args.reference_root = args.reference_root.resolve()
    out = ROOT / "build/gsim" / args.tag
    out.mkdir(parents=True, exist_ok=False)
    state = {"schema":"valence-passive-prefetch-board-ledger-v1", "status":"RUNNING",
        "source_head":subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip(),
        "inputs":{str(p.relative_to(ROOT)):sha(p) for p in [Path(__file__).resolve(), HERE/"harness/prefetch_board_ledger.h"]},
        "cases":[],"limits":["Passive replay of already-generated hardware; no new RTL build or policy",
            "Host AXI timing is controlled simulation, not physical bandwidth"]}
    def save(): (out/"receipt.json").write_text(json.dumps(state,indent=2)+"\n")
    save()
    try:
        for attempts in args.attempts:
            source = args.reference_root / "build/gsim" / f"fpga-next-board-retention{attempts}-r1"
            receipt = json.loads((source/"receipt.json").read_text())
            assert receipt["status"] == "PASS_FPGA_NEXT_BOARD_SUITE"
            assert receipt["git_head"] == "71dae69300bf953d3d12923a3816fe873f0c4a9e"
            expected_parameters=["--selected",f"--prefetch-candidate-cycles={attempts}"]
            assert receipt["plan"]["parameters"] == expected_parameters or (attempts==1 and receipt["plan"]["parameters"]==["--selected"])
            for path,digest in receipt["inputs"].items():
                assert sha(args.reference_root/path)==digest, f"reference source changed: {path}"
            for path,digest in receipt["artifacts"].items():
                assert sha(source/path)==digest, f"reference artifact changed: {path}"
            base_log=source/receipt["tests"]["steady"]["log"]
            assert sha(base_log)==receipt["tests"]["steady"]["log_sha256"]
            if args.reuse_passed:
                old_path=args.reuse_passed.resolve();old=json.loads(old_path.read_text())
                for path,digest in old["inputs"].items():
                    recorded=subprocess.check_output(["git","show",old["source_head"]+":"+path],cwd=ROOT)
                    assert hashlib.sha256(recorded).hexdigest()==digest,"uncommitted reusable source"
                    if path!=str(Path(__file__).resolve().relative_to(ROOT)):
                        assert sha(ROOT/path)==digest,"reusable harness changed"
                reused=next((c for c in old["cases"] if c["attempts"]==attempts and c.get("status")=="PASS"),None)
                if reused:
                    assert reused["reference_receipt_sha256"]==sha(source/"receipt.json")
                    assert reused["original_rows_equal"]
                    artifact_root=Path(reused.get("artifact_root",old_path.parent))
                    for path,digest in reused["artifacts"].items():assert sha(artifact_root/path)==digest
                    for step in reused["steps"]:
                        assert sha(artifact_root/step["log"])==step["log_sha256"] and step["exit"]==step["expected"]
                    expected_steps={"link","positive","negative-response"}|({"negative-token"} if attempts>1 else set())
                    assert {step["name"] for step in reused["steps"]}==expected_steps
                    reused["artifact_root"]=str(artifact_root)
                    reused["reused_from"]={"receipt":str(old_path),"sha256":sha(old_path),"source_head":old["source_head"],"inputs":old["inputs"]}
                    state["cases"].append(reused);save();print(f"Reused fully rehashed attempts={attempts} case",flush=True);continue
            case=out/str(attempts);case.mkdir()
            result={"attempts":attempts,"reference":str(source),"reference_receipt_sha256":sha(source/"receipt.json"),
                "artifact_root":str(out),
                "reference_source_hashes":receipt["inputs"],"reference_artifact_hashes":receipt["artifacts"],
                "reference_log_sha256":sha(base_log),"steps":[],"artifacts":{}}
            state["cases"].append(result);save()
            harness=(args.reference_root/"simulator/gsim/harness/board_memory_steady.cpp").read_text()
            replacements=[("struct SteadyObserver {\n    Test *test;",'#include "prefetch_board_ledger.h"\nstruct SteadyObserver {\n    Test *test;\n    PrefetchBoardLedger ledger;'),
                ("if(o.active){o.traffic", "o.ledger.sample(d,*o.test,o.active?int(o.region):-1);\n        if(o.active){o.traffic"),
                ('std::cout<<"BOARD_MEMORY_STEADY_PASS', 'observer.ledger.report();\n    std::cout<<"BOARD_MEMORY_STEADY_PASS')]
            for old,new in replacements:
                assert harness.count(old)==1, f"ambiguous original harness hook: {old}"
                harness=harness.replace(old,new)
            wrapper=case/"observed_steady.cpp";wrapper.write_text(harness)
            result["artifacts"][str(wrapper.relative_to(out))]=sha(wrapper)
            command=list(receipt["steps"]["steady-link"]["command"])
            original=str(args.reference_root/"simulator/gsim/harness/board_memory_steady.cpp")
            assert command.count(original)==1
            command[command.index(original)]=str(wrapper)
            command[command.index("-o")+1]=str(case/"observed-steady")
            command += ["-I"+str(args.reference_root/"simulator/gsim/harness"),"-I"+str(HERE/"harness")]
            def run(name, cmd, expected=0, mutation=None):
                log=case/(name+".log"); start=time.monotonic(); env=os.environ.copy()
                env["ASAN_OPTIONS"]="detect_leaks=0"  # Same sanitizer execution contract as the frozen board runner.
                env["PREFETCH_LEDGER_OUTPUT"]=str(case/name)
                if mutation:env["PREFETCH_LEDGER_INJECT"]=mutation
                else:env.pop("PREFETCH_LEDGER_INJECT",None)
                with log.open("w") as f:
                    process=subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT,env=env,timeout=900)
                result["steps"].append({"name":name,"command":cmd,"mutation":mutation,"ASAN_OPTIONS":env["ASAN_OPTIONS"],
                    "exit":process.returncode,"expected":expected,"seconds":time.monotonic()-start,
                    "log":str(log.relative_to(out)),"log_sha256":sha(log)})
                save();assert process.returncode==expected, log.read_text()[-5000:]
                return log.read_text()
            run("link",command)
            binary=case/"observed-steady"
            result["artifacts"][str(binary.relative_to(out))]=sha(binary);save()
            cmd=[str(binary),str(source/"firmware/steady.bin")]
            positive=run("positive",cmd)
            for detail in case.glob("positive-*.csv"):
                result["artifacts"][str(detail.relative_to(out))]=sha(detail)
            original_rows="\n".join(l for l in positive.splitlines() if not l.startswith("PREFETCH_LEDGER"))+"\n"
            assert original_rows==base_log.read_text(), "passive observation changed original output or cycles"
            result["original_rows_equal"]=True
            result["ledger_rows"]=[l for l in positive.splitlines() if l.startswith("PREFETCH_LEDGER")]
            for mutation,anchor in [("response","source ordered response oracle mismatch"),("token","prefetch fill changed token identity")]:
                if mutation=="token" and attempts==1:continue
                text=run("negative-"+mutation,cmd,1,mutation)
                assert anchor in text, text[-1500:]
            # Verify reference objects and local inputs again after replay.
            for path,digest in receipt["artifacts"].items():assert sha(source/path)==digest
            for path,digest in state["inputs"].items():assert sha(ROOT/path)==digest
            result["status"]="PASS";save()
            print("\n".join(result["ledger_rows"]),flush=True)
        state["status"]="PASS";save()
    except Exception as error:
        state["status"]="FAIL";state["error"]=str(error);save();raise
    print(out/"receipt.json",flush=True)

if __name__=="__main__":main()
