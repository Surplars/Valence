#!/usr/bin/env python3
"""Recompute passive board attribution from sealed token/address CSV artifacts."""
import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import subprocess

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def rows(path):
    with Path(path).open() as stream:
        return [{k:int(v) for k,v in row.items()} for row in csv.DictReader(stream)]
def main():
    ap=argparse.ArgumentParser();ap.add_argument("receipt",type=Path);ap.add_argument("output",type=Path)
    args=ap.parse_args(); original=json.loads(args.receipt.read_text());assert original["status"]=="PASS"
    root=Path(__file__).resolve().parents[2];out=args.receipt.parent
    for path,digest in original["inputs"].items():assert sha(root/path)==digest
    evidence={"schema":"valence-passive-prefetch-attribution-v1","status":"PASS",
        "source_head":subprocess.check_output(["git","rev-parse","HEAD"],cwd=root,text=True).strip(),
        "reducer_sha256":sha(__file__),"runner_receipt":str(args.receipt.resolve()),
        "runner_receipt_sha256":sha(args.receipt),"replay":original,"derived":{},
        "limits":["Per-token/value assertions observe already-generated RTL; no new model or policy.",
            "Source-range read reduction includes cache replacement/residency effects, not only overlap.",
            "Physical PPA, physical bandwidth, and unbounded external-backpressure trap latency are unmeasured."]}
    for case in original["cases"]:
        artifacts=Path(case.get("artifact_root",out))
        for path,digest in case["artifacts"].items():assert sha(artifacts/path)==digest
        for step in case["steps"]:assert sha(artifacts/step["log"])==step["log_sha256"]
        folder=artifacts/str(case["attempts"])
        tokens=rows(folder/"positive-tokens.csv"); addresses=rows(folder/"positive-source-reads.csv")
        hits=rows(folder/"positive-first-hits.csv")
        assert [t["id"] for t in tokens]==list(range(1,len(tokens)+1))
        for token in tokens:
            assert token["address"]%64==0 and token["allocated"]>0 and token["filled"]>token["allocated"]
            assert (token["address"]>>6)&255 == token["index"]&255
            if token["consumed"]:assert token["consumed"]>token["filled"]
            if token["reported_useful"]:assert token["consumed"] and not token["consumer_write"]
            if token["consumed"] and not token["reported_useful"] and not token["consumer_write"]:
                assert token["consumed"]>=token["flush_before_consume"]>token["filled"]
            if token["evicted"]:assert token["evicted"]>token["filled"]
            if token["consumed"] and token["evicted"]:assert token["evicted"]>token["consumed"]
            if token["exact_copy_destination"]:
                assert token["address"]==0x80400000+(token["evicting_address"]&~63)-0x81400040+64
        derived={}
        for region in [0,1,3]:
            summary=[]
            total_reads=Counter({r["address"]:r["read_requests"] for r in addresses if r["region"]==region and r["pass"]==-1})
            accumulated=Counter()
            for p in range(3):
                read=Counter({r["address"]:r["read_requests"] for r in addresses if r["region"]==region and r["pass"]==p})
                accumulated.update(read)
                cohort=[t for t in tokens if t["region"]==region and t["pass"]==p]
                old=[h for h in hits if h["region"]==region and h["pass"]==p and
                    (h["fill_region"]!=region or h["fill_pass"]!=p)]
                summary.append({"pass":p,"source_reads":sum(read.values()),"unique_source_read_lines":len(read),
                    "allocated_tokens":len(cohort),"unique_allocated_addresses":len({t["address"] for t in cohort}),
                    "consumed_tokens":sum(bool(t["consumed"]) for t in cohort),
                    "read_fill_to_first_consumption_cycles":dict(Counter(t["consumed"]-t["filled"] for t in cohort
                        if t["consumed"] and not t["consumer_write"])),
                    "unused_evicted_tokens":sum(bool(t["evicted"] and not t["consumed"]) for t in cohort),
                    "exact_copy_destination_evictions":sum(t["exact_copy_destination"] and not t["consumed"] for t in cohort),
                    "earlier_fill_first_hits":len(old),"earlier_fill_hit_ways":dict(Counter(h["index"]>>8 for h in old)),
                    "earlier_fill_unique_addresses":len({h["address"] for h in old}),
                    "earlier_fill_was_before_roi":sum(h["fill_region"]==-1 for h in old)})
            assert accumulated==total_reads,"per-pass AXI accounting does not match ROI accounting"
            derived[str(region)]={"source_reads":sum(total_reads.values()),"unique_source_read_lines":len(total_reads),"passes":summary}
        evidence["derived"][str(case["attempts"])]=derived
    if "1" in evidence["derived"] and "3" in evidence["derived"]:
        old,new=evidence["derived"]["1"]["0"],evidence["derived"]["3"]["0"]
        reuse_delta=sum(p["earlier_fill_first_hits"] for p in new["passes"])-sum(p["earlier_fill_first_hits"] for p in old["passes"])
        read_delta=old["source_reads"]-new["source_reads"]
        assert reuse_delta==read_delta,"source read difference is not explained by observed earlier-fill hits"
        evidence["read_source_reduction_explained_by_earlier_fills"]={"fewer_source_reads":read_delta,"additional_earlier_fill_hits":reuse_delta}
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(evidence,indent=2)+"\n")
    print(json.dumps(evidence["derived"],indent=2));print(args.output,sha(args.output))

if __name__=="__main__":main()
