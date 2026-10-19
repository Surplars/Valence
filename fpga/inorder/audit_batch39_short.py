#!/usr/bin/env python3
"""Rehash a complete batch39 short result and measure exact retained CPU state."""
import argparse
import json
from pathlib import Path
import re
from board_short_proof import (sha, bandwidth39_flags, bandwidth39_audit,
    validate_bandwidth39)

ROOT = Path(__file__).resolve().parents[2]


def declarations(path, pattern):
    return [re.sub(r" @\[.*", "", line.strip()) for line in path.read_text().splitlines()
            if re.match(pattern, line)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args()
    path = args.receipt.resolve()
    receipt = json.loads(path.read_text())
    bandwidth39_flags(receipt)
    baseline_path = Path(receipt["baseline"])
    if sha(baseline_path) != receipt["baseline_sha256"]:
        raise ValueError("frozen baseline receipt drift")
    baseline = json.loads(baseline_path.read_text())
    for name, digest in receipt["source_sha256"].items():
        if sha(ROOT/name) != digest:
            raise ValueError("current source drift: "+name)
    for record, parent in ((receipt, path.parent), (baseline, baseline_path.parent)):
        for name, digest in record["artifact_sha256"].items():
            if sha(parent/name) != digest:
                raise ValueError("frozen artifact drift: "+str(parent/name))
    old = baseline_path.parent/"cpu/FiveStageSoc.fir"
    new = path.parent/"cpu/FiveStageSoc.fir"
    old_regs, new_regs = (declarations(p, r"\s*reg(?:reset)?\s") for p in (old, new))
    old_mem, new_mem = (declarations(p, r"\s*[cs]mem\s") for p in (old, new))
    writers = declarations(new, r"\s*write mport\s+.*directoryBanks")
    audit = dict(status="PASS_BATCH39_SHORT_NO_REGRESSION_PHYSICAL_PENDING",
        receipt_sha256=sha(path), baseline_sha256=sha(baseline_path),
        auditor_sha256=sha(Path(__file__)), sources_rehashed=len(receipt["source_sha256"]),
        artifacts_rehashed=len(receipt["artifact_sha256"]), checks=len(receipt["checks"]),
        performance_gates=len(receipt["performance_gates"]),
        identical_stream_cases=sum(row["old"]==row["new"] for row in receipt["stream_comparison"].values()),
        coremark_identical=receipt["coremark_comparison"]["old"]==receipt["coremark_comparison"]["new"],
        register_declarations_before=len(old_regs), register_declarations_after=len(new_regs),
        register_declarations_equal=old_regs==new_regs, memory_structure_equal=old_mem==new_mem,
        memory_declarations=len(new_mem), directory_write_ports=len(writers), new_payload_ram_bits=0,
        multiclock_changed=False, physical_qualified=False, bit_generated=False)
    bandwidth39_audit(receipt, audit, sha(path))
    output = path.parent/"batch39-final-audit.json"
    if output.exists():
        raise ValueError("preserve existing audit evidence")
    output.write_text(json.dumps(audit, indent=2)+"\n")
    try:
        validate_bandwidth39(receipt, path, ROOT)
    except Exception as error:
        audit.update(status="FAIL", error=repr(error))
        output.write_text(json.dumps(audit, indent=2)+"\n")
        raise
    print(json.dumps(audit, indent=2))


if __name__ == "__main__":
    main()
