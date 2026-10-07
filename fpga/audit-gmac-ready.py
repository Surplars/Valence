#!/usr/bin/env python3
"""Freeze/collect the frontend+CDC candidate; report-only, no CAD or simulation."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"simulator/gsim"))

def require(ok,reason):
    if not ok: raise RuntimeError(reason)

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def load(path): return json.loads(path.read_text())

def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value

def sv_hashes(path): return {str(f.relative_to(path)):sha(f) for f in sorted(path.rglob("*.sv"))}

def audit(a):
    batch=a.batch.resolve()
    freeze=batch/"candidate-inputs.json"
    inputs=[p for d in ("src/main/scala","third_party/berkeley-hardfloat/src/main/scala")
        for p in sorted((ROOT/d).rglob("*.scala"))]
    inputs += [ROOT/p for p in ("src/test/scala/ooo/GmacReadyCoreTimingMain.scala",
        "src/test/scala/ooo/ClockDomainCdcMain.scala","src/test/scala/ooo/ThroughputPerfGsim.scala",
        "src/test/scala/ooo/PmpCheckerGsim.scala","src/test/scala/ooo/RegisteredFetchPacketGsim.scala",
        "simulator/gsim/harness/core.cpp","simulator/gsim/harness/registered_fetch_packet.cpp",
        "simulator/gsim/harness/pmp_checker.cpp","fpga/zu15eg/cdc_tb.sv",
        "fpga/zu15eg/cdc_constraints.tcl","fpga/zu15eg/review_cdc_checkpoint.tcl")]
    current={str(p.relative_to(ROOT)):sha(p) for p in inputs}
    require(sv_hashes(batch/"core-rtl")==sv_hashes(batch/"core-rtl-sourcecheck-r2"),
        "Platform-only reset correction changed CPU RTL")
    require(sv_hashes(batch/"core-rtl")==sv_hashes(a.native/"core-rtl"),"Native CPU RTL drift")
    require(sv_hashes(batch/"cdc-rtl")==sv_hashes(a.native/"cdc-rtl"),"Native CDC RTL drift")
    if a.freeze:
        require(not freeze.exists(),"Freeze already exists")
        freeze.write_text(json.dumps({"source_sha256":current,"isa":"rv64gc","issue_width":2,
            "cpu_period_ns":10,"cdc_mac_period_ns":8,"rtl_sha256":sv_hashes(batch/"core-rtl"),
            "cdc_rtl_sha256":sv_hashes(batch/"cdc-rtl")},indent=2)+"\n")
    require(load(freeze)["source_sha256"]==current,"Candidate source drift")
    frontend_path=ROOT/"build/gsim/gmac-ready-20261004-r1/receipt.json"
    board_path=ROOT/"build/gsim/rv64gc-board-20261004-gmac-ready-r2/receipt.json"
    frontend,board=load(frontend_path),load(board_path)
    require(frontend["status"]=="PASS_SHORT_FUNCTIONAL_AND_IPC","Frontend receipt not passed")
    require(board["status"]=="PASS_BOARD_FUNCTIONAL_SMOKE" and board["timing_profile"]=="staged-gmac-ready",
        "Current board smoke not passed")
    for name,value in board["source_sha256"].items(): require(sha(ROOT/name)==value,"Board DUT drift: "+name)
    for name,value in board["files"].items(): require(sha(ROOT/name)==value,"Board artifact drift: "+name)
    for name,value in board["gsim_models_sha256"].items(): require(sha(ROOT/name)==value,"Board model drift")
    # Exactly one platform-only reset-loop correction postdates the bare-core
    # test. It is independently covered by the new exact-board receipt, and all
    # actual CPU RTL hashes above are identical. No arbitrary exception is allowed.
    corrections=[]
    platform="src/main/scala/core/ooo/MachinePlatform.scala"
    replacement=("    // UART's async local reset must not be overwritten by the CPU-domain reset\n"
        "    // loop. With CDC disabled the old reset/hold behavior remains identical.\n"
        "    for (module <- Seq(core, frontend, rom, dma, shared, timer) ++\n"
        "        (if (peripheralClockHz == 0) Seq(uart) else Seq.empty) ++\n")
    original="    for (module <- Seq(core, frontend, rom, uart, dma, shared, timer) ++\n"
    for name,value in frontend["hardware_source_sha256"].items():
        if sha(ROOT/name)==value: continue
        require(name==platform,"Frontend source drift: "+name)
        text=(ROOT/name).read_text()
        require(text.count(replacement)==1,"Unexpected platform reset correction")
        restored=text.replace(replacement,original).encode()
        require(hashlib.sha256(restored).hexdigest()==value,"Platform changed beyond reset-loop correction")
        corrections.append({"file":name,"kind":"UART-only reset override exclusion; CPU RTL identical; new board smoke passed"})
    for profile,value in frontend["profiles"].items():
        model=frontend_path.parent/profile
        for name,digest in value["models_sha256"].items(): require(sha(model/name)==digest,"Frontend model drift")
        require(sha(ROOT/"simulator/gsim/harness/core.cpp")==value["harness_sha256"],"NEMU harness drift")
    perf=module("perf_report",ROOT/"simulator/gsim/throughput_perf.py")
    parsed=[perf.parse_measurements((frontend_path.parent/p/"throughput.log").read_text(),13,
        perf.EXPECTED_KEYS|{("throughput_hint_alias_loop",1)}) for p in frontend["profiles"]]
    require(perf.compare_measurements(*parsed)==frontend["comparisons"],"IPC accounting changed")
    cdc=load(a.xsim/"receipt.json")
    require(cdc["status"]=="PASS_CDC_SHORT_RTL","CDC RTL smoke not passed")
    for name,digest in cdc["input_sha256"].items():
        require(sha(a.xsim/Path(name.replace("\\","/")).name)==digest,"CDC input archive drift")
    require(sha(ROOT/"fpga/zu15eg/cdc_tb.sv")==sha(a.xsim/"cdc_tb.sv"),"CDC scoreboard drift")
    collector=module("module_collect",ROOT/"fpga/collect-fp-module-results.py")
    collector.TOPS=["MachineCore"]
    candidate=collector.collect(a.native/"reports",a.native/"core-rtl")["modules"]["MachineCore"]
    baseline=collector.collect(ROOT/"build/fpga/fpu-rv64gc-20261004/candidate-reports",
        ROOT/"build/fpga/fpu-rv64gc-20261004/candidate-core-rtl")["modules"]["MachineCore"]
    review=a.native/"cdc-review-r3"
    skew=(review/"bus_skew.rpt").read_text()
    rows=re.findall(r"Slow\s+8\.000\s+([0-9.]+)\s+(-?[0-9.]+)",skew)
    require(len(rows)==4 and all(float(slack)>=0 for _,slack in rows),"CDC skew incomplete/failed")
    hold=(review/"internal_hold.rpt").read_text()
    hold_slack=re.search(r"Slack \(MET\)\s*:\s*([0-9.]+)ns",hold)
    require(hold_slack,"CDC internal hold failed")
    timing=(review/"timing.rpt").read_text()
    require("checking unconstrained_internal_endpoints (0)" in timing,"CDC endpoint unconstrained")
    complete="GMAC_READY_BATCH_COMPLETE" in (a.native/"vivado.log").read_text()
    status="PENDING_CPU_ROUTE"
    if candidate["status"]!="PENDING":
        require(complete,"Native batch has not completed")
        checker=module("core_report",ROOT/"fpga/audit-rv64gc-evidence.py")
        candidate["timing_summary"]=checker.check_core_report(
            (a.native/"reports/MachineCore/post_route_timing.rpt").read_text())
        status="PASS_INTERNAL_10NS_BOUNDARY_UNQUALIFIED" if candidate["status"]=="INTERNAL_SETUP_HOLD_MET" else "FAIL_INTERNAL_CPU_TIMING"
    return {"status":status,"issue_width":2,"isa":"rv64gc","period_ns":10,
        "source_sha256":current,"cpu_baseline":baseline,"cpu_candidate":candidate,
        "frontend_comparisons":frontend["comparisons"],"platform_only_correction":corrections,
        "proofs":{str(p):sha(p) for p in (freeze,frontend_path,board_path,a.xsim/"receipt.json")},
        "cdc":{"rtl_short_pass":True,"internal_hold_ns":float(hold_slack[1]),
            "skew_ns":[float(n) for n,_ in rows],"cdc_report_sha256":sha(review/"cdc.rpt"),
            "warnings_not_waived":True,"boundary_hold_qualified":False,"coordinated_reset_only":True},
        "limits":["No wholeSoC/board 100MHz qualification for this candidate",
            "No GMAC/IP/PHY integration, Ethernet DMA or Linux network driver",
            "No new bit; existing user GUI/project and integer bit untouched",
            "Bare conflict microbenchmark gain is not CoreMark/Linux gain"]}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--batch",type=Path,default=ROOT/"build/fpga/gmac-ready-20261004")
    p.add_argument("--native",type=Path,required=True)
    p.add_argument("--xsim",type=Path,required=True)
    p.add_argument("--freeze",action="store_true")
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    require(not a.output.exists(),"Preserve old audits; use fresh output")
    report=audit(a)
    a.output.write_text(json.dumps(report,indent=2)+"\n")
    print(report["status"])

if __name__=="__main__": main()
