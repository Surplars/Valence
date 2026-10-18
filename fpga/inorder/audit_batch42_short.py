#!/usr/bin/env python3
"""Rehash batch42; allow only the two existing Home registers to change encoding."""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
from audit_batch39_short import declarations
from board_short_proof import sha, bandwidth42_flags, bandwidth42_audit, validate_bandwidth42

ROOT = Path(__file__).resolve().parents[2]


def normalize_home_encoding(lines):
    state = "regreset state : UInt<13>, clock, reset, UInt<13>(0h1)"
    resume = "reg resume : UInt<13>, clock"
    if lines.count(state) != 1 or lines.count(resume) != 1:
        raise ValueError("exact one-hot Home state and retained resume registers required")
    return ["regreset state : UInt<4>, clock, reset, UInt<4>(0h0)" if x == state else
            "reg resume : UInt<4>, clock" if x == resume else x for x in lines]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--receipt",type=Path,required=True)
    path = ap.parse_args().receipt.resolve()
    receipt = json.loads(path.read_text()); bandwidth42_flags(receipt)
    baseline_path = Path(receipt["baseline"])
    if sha(baseline_path) != receipt["baseline_sha256"]:
        raise ValueError("baseline receipt drift")
    baseline = json.loads(baseline_path.read_text())
    for name,digest in receipt["source_sha256"].items():
        if sha(ROOT/name) != digest:
            raise ValueError("current source drift: "+name)
    for record,parent in ((receipt,path.parent),(baseline,baseline_path.parent)):
        for name,digest in record["artifact_sha256"].items():
            if sha(parent/name) != digest:
                raise ValueError("artifact drift: "+str(parent/name))
    old,new = (parent/"cpu/FiveStageSoc.fir" for parent in (baseline_path.parent,path.parent))
    old_regs,new_regs = (declarations(p,r"\s*reg(?:reset)?\s") for p in (old,new))
    old_mem,new_mem = (declarations(p,r"\s*[cs]mem\s") for p in (old,new))
    audit = dict(status="PASS_BATCH42_SHORT_NO_REGRESSION_PHYSICAL_PENDING",
        receipt_sha256=sha(path),baseline_sha256=sha(baseline_path),auditor_sha256=sha(Path(__file__)),
        sources_rehashed=len(receipt["source_sha256"]),artifacts_rehashed=len(receipt["artifact_sha256"]),
        checks=len(receipt["checks"]),performance_gates=len(receipt["performance_gates"]),
        identical_stream_cases=sum(x["old"] == x["new"] for x in receipt["stream_comparison"].values()),
        coremark_identical=receipt["coremark_comparison"]["old"] == receipt["coremark_comparison"]["new"],
        register_declarations_before=len(old_regs),register_declarations_after=len(new_regs),
        register_structure_equal_after_home_encoding=Counter(old_regs) == Counter(normalize_home_encoding(new_regs)),
        home_encoding_control_bit_growth=18,memory_structure_equal=Counter(old_mem) == Counter(new_mem),
        memory_declarations=len(new_mem),directory_write_ports=len(declarations(new,r"\s*write mport\s+.*directoryBanks")),
        new_payload_ram_bits=0,multiclock_changed=False,physical_qualified=False,bit_generated=False)
    bandwidth42_audit(receipt,audit,sha(path))
    output = path.parent/"batch42-final-audit.json"
    if output.exists():
        raise ValueError("preserve existing audit")
    output.write_text(json.dumps(audit,indent=2)+"\n")
    validate_bandwidth42(receipt,path,ROOT)
    print(json.dumps(audit,indent=2))


if __name__ == "__main__":
    main()
