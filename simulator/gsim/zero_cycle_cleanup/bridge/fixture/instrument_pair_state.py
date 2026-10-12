#!/usr/bin/env python3
"""Read-only state taps and exact pair assertions for emitted fixture CHIRRTL.

No DUT memory/register is initialized or changed. Each scalar retained register
leaf and every cmem word/leaf is observed through a separate output. This includes
Queue payloads, local response locks, RR state, inactive owners and invalid data.
The observer adds memory READ ports only, so its output is simulation-only and
must never be used for the native resource/cone audit.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re


def split_fields(text):
    depth = 0
    start = 0
    result = []
    for i, c in enumerate(text):
        if c in "{[<":
            depth += 1
        elif c in "}]>":
            depth -= 1
        elif c == "," and depth == 0:
            result.append(text[start:i].strip())
            start = i + 1
    result.append(text[start:].strip())
    return result


def leaves(kind, suffix=""):
    kind = kind.strip()
    vector = re.fullmatch(r"(.+)\[(\d+)\]", kind)
    if vector:
        return [leaf for i in range(int(vector[2]))
                for leaf in leaves(vector[1], suffix + f"[{i}]")]
    if kind.startswith("{") and kind.endswith("}"):
        result = []
        for field in split_fields(kind[1:-1]):
            match = re.fullmatch(r"(?:flip\s+)?(\w+)\s*:\s*(.+)", field)
            if not match:
                raise ValueError("unrecognized aggregate field: " + field)
            result.extend(leaves(match[2], suffix + "." + match[1]))
        return result
    if not re.fullmatch(r"(?:UInt|SInt)<\d+>", kind):
        raise ValueError("state leaf needs known integer width: " + kind)
    return [(suffix, kind)]


def symbol(path):
    return "bpProof__" + re.sub(r"[^a-zA-Z0-9_]", "_", path)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input", type=Path)
    ap.add_argument("output", type=Path)
    ap.add_argument("--manifest", required=True, type=Path)
    args = ap.parse_args()
    original = args.input.read_text()
    if "bpProof__" in original:
        raise ValueError("refusing to instrument an already instrumented input")
    headers = list(re.finditer(r"^  (?:public )?module (\w+)\s*:.*$", original, re.M))
    if not headers:
        raise ValueError("no CHIRRTL modules")
    prefix = original[:headers[0].start()]
    modules = {}
    order = []
    for i, header in enumerate(headers):
        name = header[1]
        end = headers[i + 1].start() if i + 1 < len(headers) else len(original)
        modules[name] = original[header.start():end].rstrip() + "\n"
        order.append(name)
    top = "BridgePayloadEnablePairGsim"
    if top not in modules:
        raise ValueError("input is not the bridge pair fixture")
    taps = {}
    new_modules = {}

    def instrument(name):
        if name in taps:
            return taps[name]
        body = modules[name]
        ports, statements, observations = [], [], {}

        def expose(path, expr, kind, category):
            port = symbol(path)
            if port in [x[0] for x in observations.values()]:
                raise ValueError("observer symbol collision: " + path)
            ports.append(f"    output {port} : {kind}")
            statements.append(f"    connect {port}, {expr}")
            observations[path] = (port, kind, category)

        # This narrow parser fails closed if an unfamiliar retained-state form
        # appears; it never silently omits synchronous memories or unknown widths.
        if re.search(r"^\s+(?:smem|mem)\s", body, re.M):
            raise ValueError("unexpected non-cmem retained memory in " + name)
        for line in body.splitlines():
            line = line.split(" @[")[0]
            reg = re.match(r"\s+(?:reg|regreset)\s+(\w+)\s*:\s*(.+)", line)
            if reg:
                kind = split_fields(reg[2])[0]
                for suffix, leaf_kind in leaves(kind):
                    expose(reg[1] + suffix, reg[1] + suffix, leaf_kind, "register")
            mem = re.match(r"\s+cmem\s+(\w+)\s*:\s*(.+)", line)
            if mem:
                vector = re.fullmatch(r"(.+)\[(\d+)\]", mem[2].strip())
                if not vector:
                    raise ValueError("cannot find memory depth: " + line)
                count = int(vector[2])
                if count > 256:
                    raise ValueError("unexpected memory size in focused fixture")
                for row in range(count):
                    port = symbol(mem[1] + f"_read_{row}")
                    statements.append(f"    read mport {port} = {mem[1]}[UInt<{max(1, (count - 1).bit_length())}>({row})], clock")
                    for suffix, leaf_kind in leaves(vector[1]):
                        category = "payload" if mem[1].startswith("payloadBanks_") else "queue_memory"
                        expose(mem[1] + f"[{row}]" + suffix, port + suffix, leaf_kind, category)
        for instance, child in re.findall(r"^\s+inst (\w+) of (\w+)", body, re.M):
            if child not in modules:
                raise ValueError("unhandled external module: " + child)
            for path, (port, kind, category) in instrument(child).items():
                expose(instance + "." + path, instance + "." + port, kind, category)
        lines = body.splitlines()
        insert = 1
        while insert < len(lines) and (lines[insert].startswith("    input ") or
                                      lines[insert].startswith("    output ")):
            insert += 1
        lines[insert:insert] = ports
        new_modules[name] = "\n".join(lines + statements) + "\n\n"
        taps[name] = observations
        return observations

    top_body = modules[top]
    inst = dict(re.findall(r"^\s+inst (\w+) of (\w+)", top_body, re.M))
    if "reference" not in inst or "candidate" not in inst:
        raise ValueError("top must instantiate reference and candidate directly")
    off = instrument(inst["reference"])
    on = instrument(inst["candidate"])
    if set(off) != set(on):
        raise ValueError("OFF/ON retained state differs: " + repr(set(off) ^ set(on)))
    state_nodes, payload_nodes, rows = [], [], []
    statements = []
    for i, path in enumerate(sorted(off)):
        ref_port, kind, category = off[path]
        cand_port, cand_kind, cand_category = on[path]
        if (kind, category) != (cand_kind, cand_category):
            raise ValueError("OFF/ON state type mismatch: " + path)
        node = f"bpProof__equal_{i}"
        statements.append(f"    node {node} = eq(reference.{ref_port}, candidate.{cand_port})")
        (payload_nodes if category == "payload" else state_nodes).append(node)
        rows.append({"path": path, "type": kind, "category": category})
        statements.append(f'    assert(clock, {node}, not(asUInt(reset)), '
                          f'"paired retained {category} mismatch: {path}")')

    def combine(nodes, stem):
        if not nodes:
            raise ValueError("empty equality category " + stem)
        stage = 0
        while len(nodes) > 1:
            next_nodes = []
            for i in range(0, len(nodes), 2):
                if i + 1 == len(nodes):
                    next_nodes.append(nodes[i])
                else:
                    name = f"bpProof__{stem}_{stage}_{i}"
                    statements.append(f"    node {name} = and({nodes[i]}, {nodes[i+1]})")
                    next_nodes.append(name)
            nodes = next_nodes
            stage += 1
        return nodes[0]

    state_count, payload_count = len(state_nodes), len(payload_nodes)
    if payload_count != 64:
        raise ValueError(f"expected 4 * 8 * 2 full 72-bit payload words, found {payload_count}")
    statements += [f"    connect proofStateEqual, {combine(state_nodes, 'state')}",
                   f"    connect proofPayloadEqual, {combine(payload_nodes, 'payload')}",
                   f"    connect proofStateLeaves, UInt<32>({state_count})",
                   f"    connect proofPayloadWords, UInt<32>({payload_count})"]
    top_lines = top_body.splitlines()
    insert = 1
    while insert < len(top_lines) and (top_lines[insert].startswith("    input ") or
                                      top_lines[insert].startswith("    output ")):
        insert += 1
    top_lines[insert:insert] = ["    output proofStateEqual : UInt<1>",
                              "    output proofPayloadEqual : UInt<1>",
                              "    output proofStateLeaves : UInt<32>",
                              "    output proofPayloadWords : UInt<32>"]
    new_modules[top] = "\n".join(top_lines + statements) + "\n"
    output = prefix + "".join(new_modules.get(name, modules[name]) for name in order)
    args.output.write_text(output)
    args.manifest.write_text(json.dumps({
        "input_sha256": hashlib.sha256(original.encode()).hexdigest(),
        "output_sha256": hashlib.sha256(output.encode()).hexdigest(),
        "state_leaves_per_side": state_count,
        "payload_words_per_side": payload_count,
        "payload_bits_per_side": 64 * 72,
        "comparison": "Exact scalar equality every non-reset cycle, including inactive/invalid state",
        "initialization": "No initialization added. GSIM deterministic initial storage only; not a formal proof.",
        "leaves": rows}, indent=2) + "\n")
    print(json.dumps({"state_leaves_per_side": state_count, "payload_words_per_side": payload_count}))


if __name__ == "__main__":
    main()
