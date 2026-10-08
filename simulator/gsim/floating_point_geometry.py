#!/usr/bin/env python3
"""Census normalized production FP RTL in its actual emitted hierarchy.

Counts ports/register geometry/operators, not mapped LUTs, BRAMs, DSPs or timing.
CPU oracle fixtures intentionally have extra observational reads and must fail
this production-memory contract if presented as board evidence.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rtl", required=True, type=Path)
    parser.add_argument("--top", required=True)
    parser.add_argument("--expect", choices=("memory", "baseline"), default="memory")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    root = args.rtl.resolve()
    modules, files, hashes = {}, {}, {}
    for path in sorted(root.rglob("*.sv")):
        data = path.read_bytes()
        hashes[str(path.relative_to(root))] = sha(data)
        text = re.sub(r"/\*.*?\*/|//[^\n]*", "", data.decode(), flags=re.S)
        for match in re.finditer(r"\bmodule\s+(\w+)\b(.*?)\bendmodule\b", text, re.S):
            name = match.group(1)
            if name in modules and modules[name] != match.group(0):
                raise RuntimeError("ambiguous normalized module " + name)
            modules[name] = match.group(0)
            files[name] = str(path.relative_to(root))
    if args.top not in modules:
        raise RuntimeError("requested top absent from emitted RTL")
    children = {name: [(kind, instance) for kind, instance in
        re.findall(r"^\s*(\w+)\s+(\w+)\s*\(", body, re.M) if kind in modules]
        for name, body in modules.items()}
    todo = [(args.top, args.top)]
    states, reachable, seen_count = [], set(), 0
    while todo:
        kind, path = todo.pop()
        reachable.add(kind)
        seen_count += 1
        if seen_count > 100000:
            raise RuntimeError("cyclic or unexpectedly large module hierarchy")
        if re.fullmatch(r"FloatingPointState(?:_\d+)?", kind):
            body = modules[kind]
            memories = [(child, instance) for child, instance in children[kind]
                if re.search(r"\breg\s+\[63:0\]\s+Memory\[0:31\]", modules[child])]
            valid_regs = re.findall(r"\breg\s+initialized_(\d+)\s*;", body)
            valid_reset = re.findall(r"\binitialized_\d+\s*<=\s*1'h0\s*;", body)
            entry = {"path": path, "module": kind, "file": files[kind],
                     "validity_ff_count": len(valid_regs), "validity_reset_count": len(valid_reset)}
            if args.expect == "baseline":
                if memories or valid_regs:
                    raise RuntimeError("baseline unexpectedly has committed payload RAM")
                entry["payload_memory"] = None
            else:
                if len(memories) != 1 or len(valid_regs) != 32 or len(valid_reset) != 32:
                    raise RuntimeError("FP committed payload/validity geometry changed: " + path)
                memory, instance = memories[0]
                mem = modules[memory]
                readers = sorted(set(re.findall(r"\b(R\d+)_addr\b", mem)))
                writers = sorted(set(re.findall(r"\b(W\d+)_addr\b", mem)))
                asynchronous = re.findall(r"\bassign\s+(R\d+)_data\s*=", mem)
                if readers != ["R0", "R1", "R2"] or writers != ["W0"] or sorted(asynchronous) != readers:
                    raise RuntimeError("production FP RAM must have exactly 3 asynchronous reads and 1 write")
                if re.search(r"\breset\b|\binitial\b|\bfor\s*\(", mem):
                    raise RuntimeError("payload RAM unexpectedly has reset/initialization logic")
                if len(re.findall(r"Memory\[W0_addr\]\s*<=\s*W0_data", mem)) != 1:
                    raise RuntimeError("payload write geometry changed")
                for lane in range(3):
                    if not re.search(r"\.R\d+_addr\s*\(io_issue_bits_sources_" + str(lane) + r"\)", body):
                        raise RuntimeError("read port no longer binds directly to an architectural operand")
                for binding in (r"\.W0_addr\s*\(committedAddress\)",
                                r"\.W0_data\s*\(committedValue\)",
                                r"\.W0_en\s*\(\|committedMask\)"):
                    if not re.search(binding, body):
                        raise RuntimeError("queued committed write/flush independence binding changed")
                if len(re.findall(r"\? committedValue", body)) != 3:
                    raise RuntimeError("all three operand ports must forward the queued committed value")
                entry["payload_memory"] = {"path": path + "/" + instance, "module": memory,
                    "file": files[memory], "depth": 32, "width": 64,
                    "read_ports": readers, "read_latency": 0, "write_ports": writers,
                    "write_clock": "W0_clk", "payload_reset": False,
                    "committed_forward_ports": 3, "younger_flush_gates_write": False}
            states.append(entry)
        todo.extend((child, path + "/" + instance) for child, instance in children[kind])
    if not states:
        raise RuntimeError("no production FloatingPointState instance reachable from requested top")
    # Operators are counted once per reachable module definition. Resource
    # mapping requires technology synthesis; this is intentionally only census.
    multipliers = [{"module": name, "file": files[name], "expression": line.strip()}
        for name in sorted(reachable) for line in modules[name].splitlines() if " * " in line]
    result = {"status": "PASS_NORMALIZED_FP_GEOMETRY", "rtl_root": str(root), "top": args.top,
        "expect": args.expect, "states": states, "reachable_module_count": len(reachable),
        "reachable_multiplier_expressions": multipliers, "file_sha256": hashes,
        "normalized_sha256": sha("\n".join(re.sub(r"\s+", " ", modules[n]).strip()
            for n in sorted(reachable)).encode()),
        "limits": "Pre-synthesis production RTL geometry only; no mapped LUT/RAM/DSP or timing claim."}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print("FP_NORMALIZED_GEOMETRY_PASS " + str(args.output))


if __name__ == "__main__":
    main()
