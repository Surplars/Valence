#!/usr/bin/env python3
"""Report-driven RV64M/fetch/MDIO batch: short independent oracles, no long Linux."""
import argparse
import json
import os
from pathlib import Path
from run import BUILD, HERE, ROOT, run, setup, test
from control_stage import core_payloads, negative, reference
import throughput_perf as perf


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--reuse-units", type=Path)
    args = parser.parse_args()
    if not args.tag.replace("-", "").replace("_", "").isalnum():
        parser.error("unsafe tag")
    name = "native-timing-" + args.tag
    out = BUILD / name
    out.mkdir(parents=True, exist_ok=False)
    inputs = sorted((ROOT / "src/main/scala").rglob("*.scala"))
    inputs += sorted((ROOT / "src/test/scala").rglob("*.scala"))
    inputs += [ROOT/"build.mill", Path(__file__), HERE/"run.py", HERE/"control_stage.py",
               HERE/"throughput_perf.py", *sorted((HERE/"harness").glob("*"))]
    inputs = [p for p in inputs if p.is_file()]
    def hashes():
        return {str(p.relative_to(ROOT)): perf.sha256(p) for p in inputs}
    before = hashes()
    receipt = {"status":"RUNNING", "source_sha256":before, "checks":{}, "issue_width":2,
               "profile":"staged-fetch-feedback", "registered_muldiv_operands":True,
               "scope":"M-unit arithmetic/latency/II/kill/hold; mixed fetch; Clause22; short real CPU NEMU",
               "not_covered":["Linux", "F/D timing", "physical PHY", "independent CPU clocks", "board STA"],
               "bit_generated":False}
    env = {**os.environ, "ASAN_OPTIONS":"detect_leaks=0"}
    try:
        gsim, cxx = setup(False)
        if args.reuse_units:
            prior = json.loads(args.reuse_units.read_text())
            changes = [n for n, h in prior["source_sha256"].items() if before.get(n) != h]
            expected = {"mul-legacy","div-legacy","mul-captured","div-captured",
                        "fetch2-mixed","fetch2-plain","fetch4-mixed","mdio"}
            if (prior["status"] != "FAILED" or set(prior["checks"]) != expected or
                changes != [str(Path(__file__).relative_to(ROOT))]):
                raise RuntimeError("unit reuse is not a runner-only repair after completed oracles")
            receipt["checks"].update(prior["checks"])
            receipt["reused_units_receipt"] = str(args.reuse_units.resolve())
            receipt["reused_units_receipt_sha256"] = perf.sha256(args.reuse_units)
        for registered in (() if args.reuse_units else (False, True)):
            suffix = "captured" if registered else "legacy"
            for stem, main_name, top, harness, define, marker in (
                ("mul", "ooo.PipelinedMultiplyGsimMain", "PipelinedMultiplyGsim", "pipelined_mul.cpp",
                 "REGISTERED_MULTIPLY_OPERANDS", "pipelined arithmetic mismatch"),
                ("div", "ooo.MultiplyDivideGsimMain", "MultiplyDivide", "muldiv.cpp",
                 "REGISTERED_MULDIV_OPERANDS", "arithmetic mismatch")):
                model = test(gsim,cxx,name+"/"+stem+"-"+suffix,main_name,top,harness,
                    parameters=(("registered",) if registered else ()), defines={define:int(registered)})
                negative(model/"run", (), marker, model/"negative.log")
                receipt["checks"][stem+"-"+suffix] = (model/"test.log").read_text().strip()
        for width, compressed in (() if args.reuse_units else ((2,True),(2,False),(4,True))):
            stem = "fetch%d-%s" % (width, "mixed" if compressed else "plain")
            model = test(gsim,cxx,name+"/"+stem,"ooo.RegisteredFetchPacketGsimMain",
                "RegisteredFetchPacketGsim","registered_fetch_packet.cpp",
                parameters=(str(width),"parallel-validation","hints32","split-cursor",
                            "mixed" if compressed else "plain"),
                defines={"FETCH_WIDTH":width,"COMPRESSED":int(compressed),"HINT_ENTRIES":32})
            negative(model/"run", (), "fetch packet oracle mismatch", model/"negative.log")
            receipt["checks"][stem] = (model/"test.log").read_text().strip()
        if not args.reuse_units:
            model = test(gsim,cxx,name+"/mdio","ip.MdioClause22GsimMain","MdioClause22","mdio_clause22.cpp",
                         defines={})
            receipt["checks"]["mdio"] = (model/"test.log").read_text().strip()
        old = json.loads(args.baseline.read_text())
        baseline = old["profiles"]["staged-fetch-feedback"]
        # A firmware-only runtime recheck reuses its prior hardware directory.
        origin = old.get("runtime_recheck", {}).get("previous_receipt", str(args.baseline))
        frozen = Path(origin).resolve().parent/"core"
        if (old["status"] != "passed" or baseline["model_fir_sha256"] != perf.sha256(frozen/"IntegerCoreGsim.fir")
            or baseline["executable_sha256"] != perf.sha256(frozen/"run")
            or old["source_sha256"]["simulator/gsim/harness/core.cpp"] != perf.sha256(HERE/"harness/core.cpp")):
            raise RuntimeError("frozen CPU baseline/hash mismatch")
        ref = reference()
        payloads = core_payloads(out)
        # This frozen receipt has no separate reference hash. Replay its exact
        # executable against the pinned current NEMU and demand identical rows;
        # record the reference digest explicitly in THIS receipt.
        keys = perf.EXPECTED_KEYS | {("throughput_hint_alias_loop",1)}
        run([frozen/"run",ref,*payloads,"--throughput-short"],env=env,log=out/"baseline.log",timeout=180)
        baseline_rows = perf.parse_measurements((out/"baseline.log").read_text(),13,keys)
        if baseline_rows != baseline["measurements"]:
            raise RuntimeError("baseline replay changed")
        model = test(gsim,cxx,name+"/core","ooo.ThroughputPerfGsimMain","IntegerCoreGsim","core.cpp",
            parameters=("staged-fetch-feedback",),runtime_args=(ref,*payloads,"--throughput-short"),
            defines={**perf.DEFINES,"REGISTERED_FETCH_PACKET":1,"FETCH_HINT_ALIAS_BENCH":1},
            timeout=180,run_log="throughput.log")
        for mode in ("--timing-smoke","--pipeline-recovery"):
            run([model/"run",ref,*payloads,mode],env=env,log=model/(mode[2:]+".log"),timeout=180)
            receipt["checks"][mode[2:]] = (model/(mode[2:]+".log")).read_text().strip()
        negative(model/"run", (ref,*payloads), "NEMU register mismatch", model/"negative.log")
        rows = perf.parse_measurements((model/"throughput.log").read_text(),13,keys)
        receipt["comparisons"] = perf.compare_measurements(baseline_rows, rows)
        receipt["core"] = {"fir_sha256":perf.sha256(model/"IntegerCoreGsim.fir"),
                           "executable_sha256":perf.sha256(model/"run"),"measurements":rows}
        receipt["baseline_receipt_sha256"] = perf.sha256(args.baseline)
        receipt["reference_sha256"] = perf.sha256(ref)
        receipt["status"] = "PASS_NATIVE_TIMING_SHORT"
    except BaseException as error:
        receipt.update(status="FAILED",failure=str(error))
        raise
    finally:
        if before != hashes():
            receipt.update(status="FAILED",failure="source drift during verification")
        (out/"receipt.json").write_text(json.dumps(receipt,indent=2)+"\n")
    if receipt["status"] != "PASS_NATIVE_TIMING_SHORT":
        raise RuntimeError(receipt["failure"])
    print(receipt["status"], "receipt="+str(out/"receipt.json"),flush=True)


if __name__ == "__main__":
    main()
