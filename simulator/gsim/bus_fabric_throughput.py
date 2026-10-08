#!/usr/bin/env python3
"""Board-topology backing-fabric throughput oracle; no full-board coherence claim."""
import argparse, hashlib, json, os, re, subprocess
from pathlib import Path
import run as common

TOP = "BusFabricThroughputGsim"
def hashes():
    files = sorted((common.ROOT / "src/main/scala").rglob("*.scala")) + [
        common.ROOT / "src/test/scala/ooo/BusFabricThroughputGsim.scala",
        common.HERE / "harness/bus_fabric_throughput.cpp", Path(__file__)]
    return {str(p.relative_to(common.ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
def metrics(text):
    return [dict(re.findall(r"([a-z_]+)=([a-zA-Z0-9_.+-]+)", line)) for line in text.splitlines()
            if line.startswith(("BUS_FABRIC_PASS ", "BUS_FABRIC_MASTER ", "BUS_FABRIC_STALLS "))]
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--tag",required=True); ap.add_argument("--baseline",type=Path)
    args=ap.parse_args(); out=common.BUILD/("bus-fabric-throughput-"+args.tag);out.mkdir(parents=True,exist_ok=False)
    report={"status":"RUNNING","source_sha256":hashes(),"scope":"actual nested arbiters, registered boundaries and crossbar; synthetic disjoint backing traffic; excludes upstream CPU/cache/DMA maintenance, physical MIG/CDC/timing and application IPC"}
    try:
        cxx,version=common.compiler(); gsim=common.SOURCE/"build/gsim/gsim"
        revision=subprocess.check_output(["git","rev-parse","HEAD"],cwd=common.SOURCE,text=True).strip()
        assert revision==common.LOCK["revision"] and gsim.is_file()
        report["toolchain"]={"gsim_revision":revision,"cxx":version}
        d=common.test(gsim,cxx,str(out.relative_to(common.BUILD)/"model"),"ooo.BusFabricThroughputGsimMain",TOP,
                      "bus_fabric_throughput.cpp",defines={},timeout=180)
        result=(d/"test.log").read_text();assert "BUS_FABRIC_ALL_PASS" in result
        negative=subprocess.run([d/"run","--inject-data"],capture_output=True,text=True,timeout=180,
            env={**os.environ,"ASAN_OPTIONS":"detect_leaks=0"})
        output=negative.stdout+negative.stderr;(d/"negative.log").write_text(output)
        assert negative.returncode!=0 and "BUS_FABRIC_FAIL" in output and "independent" in output,output
        assert hashes()==report["source_sha256"],"source drift"
        report.update(status="PASS",metrics=metrics(result),log=result,negative={"status":"PASS","returncode":negative.returncode,"output":output})
        if args.baseline:
            old=json.loads((args.baseline/"receipt.json").read_text());assert old["status"]=="PASS"
            changed=sorted(k for k in old["source_sha256"].keys()|report["source_sha256"].keys()
                if old["source_sha256"].get(k)!=report["source_sha256"].get(k))
            assert changed==["src/main/scala/core/ooo/TileLinkAxi4OutstandingBridge.scala"],changed
            pairs=[]
            for a,b in zip(old["metrics"],report["metrics"]):
                if "cycles" not in a:continue
                assert all(a[k]==b[k] for k in ["mode","requests","per_master","ar","aw","rbeats","wbeats","b","dbeats","rom_requests","errors","useful_read_bytes","useful_write_bytes"])
                pairs.append({"mode":a["mode"],"baseline":a,"candidate":b,"cycle_reduction_pct":100*(1-int(b["cycles"])/int(a["cycles"]))})
            report["comparison"]={"changed_sources":changed,"cases":pairs}
            (out/"comparison.json").write_text(json.dumps(report["comparison"],indent=2)+"\n")
    except BaseException as e:report.update(status="FAIL",error=str(e));raise
    finally:(out/"receipt.json").write_text(json.dumps(report,indent=2)+"\n")
if __name__=="__main__":main()
