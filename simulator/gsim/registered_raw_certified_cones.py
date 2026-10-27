#!/usr/bin/env python3
"""Fail-closed, leaf-level CHIRRTL cones for the registered raw/certified DTA.

This is deliberately NOT a general FIRRTL reader. Accepted input is the emitted
FIRRTL 6 grammar used by this fixture: UInt/SInt/Clock/Reset/AsyncReset, bundles,
vectors, nodes, wires, connect, when/else, reg/regreset, cmem infer/read/write
mports and the known non-driving Chisel assertion intrinsic. Everything else in
the DTA subtree fails. Module boundaries, aggregate aliases, flipped connects,
mux predicates and dynamic-index/control inputs are traversed, not cut points.

The graph conservatively unions all drivers, including overwritten defaults and
constant-disabled arms: no Boolean/mutual-exclusion or constant-folding argument
can establish PASS. Actual reg Q and stored memory contents are the only cuts.
Asynchronous memory read address/enable still affects its data; writes never
become a same-cycle data bypass. Reg clock/reset/init/next are recorded as NEXT
fan-in, not current Q: this proves cycle-local data/control cones, not analog
clock/reset behavior, functional equivalence, or timing. Lowered SV is unsupported.
"""
import argparse
from collections import defaultdict, deque
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re


class Uncertain(ValueError):
    """Unsupported/malformed input, or a missing required proof endpoint."""


def require(ok, why):
    if not ok:
        raise Uncertain(why)


IDENT = r"[A-Za-z_][A-Za-z_0-9$]*"
SCALAR = ("scalar",)
PRIMS = {
    **dict.fromkeys("add sub mul div rem lt leq gt geq eq neq dshl dshr and or xor".split(), 2),
    **dict.fromkeys("asUInt asSInt asClock asAsyncReset cvt neg not andr orr xorr".split(), 1),
    **dict.fromkeys("pad shl shr head tail".split(), 2), "bits": 3,
}


def split(text, delimiter=","):
    """Split only outside aggregates, calls, vectors, widths and quoted strings."""
    result, start, stack, quote, escape = [], 0, [], False, False
    for i, char in enumerate(text):
        if quote:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                quote = False
        elif char == '"':
            quote = True
        elif char in "({[<":
            stack.append(char)
        elif char in ")}]>":
            require(stack and stack.pop() == dict(zip(")}]>", "({[<"))[char], "unbalanced expression: " + text)
        elif char == delimiter and not stack:
            result.append(text[start:i].strip()); start = i + 1
    require(not stack and not quote, "unterminated expression: " + text)
    result.append(text[start:].strip())
    return result


def shape(text):
    text = text.strip()
    if text.startswith("const "):
        text = text[6:]  # Const qualifier changes mutability, never connectivity.
    vector = re.fullmatch(r"(.*)\[(\d+)\]", text)
    if vector:
        count = int(vector[2]); require(0 < count <= 4096, "unsupported vector extent")
        return ("vec", count, shape(vector[1]))
    if text.startswith("{") and text.endswith("}"):
        fields = []
        for field in split(text[1:-1]):
            match = re.fullmatch(rf"(flip\s+)?({IDENT})\s*:\s*(.+)", field)
            require(match is not None, "unsupported bundle field: " + field)
            fields.append((match[2], bool(match[1]), shape(match[3])))
        require(len({f[0] for f in fields}) == len(fields), "duplicate bundle field")
        return ("bundle", tuple(fields))
    require(re.fullmatch(r"(?:UInt|SInt)(?:<\d+>)?|Clock|Reset|AsyncReset", text), "unsupported type: " + text)
    return SCALAR


def leaves(typ, prefix="", flip=False):
    if typ[0] == "scalar":
        return {prefix: flip}
    out = {}
    if typ[0] == "bundle":
        for name, inverted, sub in typ[1]:
            out.update(leaves(sub, prefix + "." + name, flip ^ inverted))
    else:
        for i in range(typ[1]):
            out.update(leaves(typ[2], prefix + f"[{i}]", flip))
    return out


@dataclass
class Value:
    typ: tuple
    deps: dict  # Relative leaf -> set of fully qualified graph vertices.
    targets: dict | None = None  # Present only for assignable references.

    def all(self):
        return set().union(*self.deps.values())


@dataclass
class Module:
    name: str
    body: list
    external: bool = False


def read_modules(text):
    lines = text.splitlines()
    require(lines and lines[0] == "FIRRTL version 6.0.0", "only emitted FIRRTL 6.0.0 CHIRRTL is supported")
    require(len(lines) > 1, "missing circuit")
    header = re.fullmatch(rf"circuit ({IDENT})\s*:(%\[\[)?", lines[1])
    require(header is not None, "unsupported circuit header")
    i = 2
    if header[2]:
        end = next((j for j in range(i, len(lines)) if lines[j] == "]]"), None)
        require(end is not None, "unterminated annotations")
        json.loads("[" + "\n".join(lines[i:end]) + "]")
        i = end + 1
    modules, current = {}, None
    for number, line in enumerate(lines[i:], i + 1):
        # Source locators carry no circuit semantics. Do not strip arbitrary text.
        line = re.sub(r"\s+@\[.*\]$", "", line).rstrip()
        if not line:
            continue
        match = re.fullmatch(rf"  (?:public )?(module|extmodule) ({IDENT})\s*:", line)
        if match:
            require(match[2] not in modules, "duplicate module")
            current = Module(match[2], [], match[1] == "extmodule")
            modules[current.name] = current
        elif current is None:
            require(re.fullmatch(r'\s+layer (Verification|Assert|Assume|Cover|Temporal), (?:bind, "[^"]+"|inline) :', line),
                    "unsupported circuit declaration: " + line)
        else:
            require(line.startswith("    "), "unsupported module boundary: " + line)
            current.body.append((len(line) - len(line.lstrip()), line.strip(), number))
    require(header[1] in modules, "missing circuit top module")
    return header[1], modules


class Cones:
    def __init__(self, text, root_module=None, prefix="adapter"):
        self.top, self.modules = read_modules(text)
        if root_module is None:
            found = []
            def locate(name, path, stack):
                require(name in self.modules and name not in stack, "missing/recursive module: " + name)
                if re.fullmatch(r"DataTranslationAdapter(?:_\d+)?", name):
                    found.append((name, path)); return
                for _, line, _ in self.modules[name].body:
                    m = re.fullmatch(rf"inst ({IDENT}) of ({IDENT})", line)
                    if m:
                        locate(m[2], path + "." + m[1] if path else m[1], stack + [name])
            locate(self.top, "", [])
            require(len(found) == 1, "expected exactly one reachable actual DataTranslationAdapter")
            root_module, prefix = found[0]
        self.root = prefix
        self.graph, self.reasons = defaultdict(set), {}
        self.assigned = set()
        self.symbols, self.instances, self.registers, self.memories = {}, {}, set(), {}
        self.mports, self.reads, self.writes = {}, set(), set()
        self.parse_module(root_module, prefix, [])
        for name, info in self.mports.items():
            kind, memory, dependencies, typ, number = info
            read, write = name in self.reads, name in self.writes
            require(not (read and write), f"read/write mport unsupported: {name}")
            require((kind != "read" or not write) and (kind != "write" or not read), "invalid mport direction")
            require(read or write, "unused/unknown infer mport: " + name)
            if read:
                for suffix in leaves(typ):
                    self.add(name + suffix, dependencies, number)
        self.vertices = set(self.graph) | set().union(*self.graph.values()) if self.graph else set()
        self.vertices.update(v for name, typ in self.symbols.items() for v in (name + x for x in leaves(typ)))

    def add(self, dest, sources, line):
        self.assigned.add(dest)
        self.graph[dest]  # A constant driver is still a defined sink.
        for source in sources:
            self.graph[dest].add(source)
            self.reasons.setdefault((source, dest), line)

    def parse_module(self, name, prefix, stack):
        require(name in self.modules and name not in stack, "missing/recursive module: " + name)
        module = self.modules[name]
        require(not module.external, "black box in DTA cone: " + name)
        self.instances[prefix] = name
        symbols, memories, registers, controls, last_when = {}, {}, set(), [], {}
        def declare(local, typ):
            require(local not in symbols, f"duplicate symbol: {prefix}.{local}")
            symbols[local] = typ; self.symbols[prefix + "." + local] = typ
        def expression(text):
            return self.expression(text, symbols, prefix)
        # Ports/typed declarations dominate all connections; instances use exact
        # child-port names so traversing a port does not require guessed aliases.
        for _, line, number in module.body:
            m = re.fullmatch(rf"(input|output|wire|reg|regreset|cmem) ({IDENT})\s*:\s*(.+)", line)
            if m:
                parts = split(m[3]); typ = shape(parts[0]); declare(m[2], typ)
                expected = 4 if m[1] == "regreset" else 2 if m[1] == "reg" else 1
                require(len(parts) == expected, f"unsupported declaration on line {number}")
                if m[1] in ("reg", "regreset"):
                    registers.add(m[2]); self.registers.add(prefix + "." + m[2])
                if m[1] == "cmem":
                    require(typ[0] == "vec", "cmem must have depth")
                    memories[m[2]] = typ[2]; self.memories[prefix + "." + m[2]] = typ[1]
            m = re.fullmatch(rf"inst ({IDENT}) of ({IDENT})", line)
            if m:
                require(m[2] in self.modules, "unknown instance module: " + m[2])
                fields = []
                for _, port, _ in self.modules[m[2]].body:
                    p = re.fullmatch(rf"(input|output) ({IDENT})\s*:\s*(.+)", port)
                    if p:
                        fields.append((p[2], False, shape(p[3])))
                require(fields, "instance has no recognized ports")
                declare(m[1], ("bundle", tuple(fields)))
                self.parse_module(m[2], prefix + "." + m[1], stack + [name])
        for indent, line, number in module.body:
            try:
                while controls and controls[-1][0] >= indent:
                    controls.pop()
                require(indent == (controls[-1][0] + 2 if controls else 4), "unsupported block indentation")
                last_when = {level: deps for level, deps in last_when.items() if level <= indent}
                control = set().union(*(c[1] for c in controls))
                if line.startswith("when ") and line.endswith(" :"):
                    deps = expression(line[5:-2]).all()
                    last_when[indent] = deps; controls.append((indent, deps)); continue
                if line == "else :":
                    require(indent in last_when, "else without same-level when")
                    controls.append((indent, last_when.pop(indent))); continue
                # A later sibling cannot supply the predicate for an else.
                last_when.pop(indent, None)
                if re.fullmatch(r"layerblock (Verification|Assert|Assume|Cover|Temporal) :", line):
                    controls.append((indent, set())); continue
                if line == "skip":
                    continue
                if line.startswith("intrinsic("):
                    m = re.fullmatch(r'intrinsic\(circt_chisel_ifelsefatal<format = "(?:[^"\\]|\\.)*", label = "chisel3_builtin">, (.*)\)', line)
                    require(m is not None, "unsupported intrinsic")
                    args = split(m[1]); require(len(args) == 3, "unsupported assertion intrinsic arguments")
                    for arg in args:
                        expression(arg)
                    continue  # Known assertion has no result and cannot drive data.
                m = re.fullmatch(rf"(input|output|wire|reg|regreset|cmem) ({IDENT})\s*:\s*(.+)", line)
                if m:
                    if m[1] in ("reg", "regreset"):
                        deps = control | set().union(*(expression(p).all() for p in split(m[3])[1:]))
                        for suffix in leaves(symbols[m[2]]):
                            self.add(prefix + "." + m[2] + suffix + "$NEXT", deps, number)
                    continue
                if re.fullmatch(rf"inst ({IDENT}) of ({IDENT})", line):
                    require(not control, "conditional instance unsupported"); continue
                m = re.fullmatch(rf"(infer|read|write) mport ({IDENT}) = ({IDENT})\[(.+)\], (.+)", line)
                if m:
                    require(m[3] in memories, "mport must use cmem")
                    deps = control | expression(m[4]).all()
                    expression(m[5])  # Validate clock, but it does not drive async read data.
                    declare(m[2], memories[m[3]])
                    self.mports[prefix + "." + m[2]] = (m[1], prefix + "." + m[3], deps, memories[m[3]], number)
                    continue
                m = re.fullmatch(rf"node ({IDENT}) = (.+)", line)
                if m:
                    value = expression(m[2]); declare(m[1], value.typ)
                    for suffix, deps in value.deps.items():
                        self.add(prefix + "." + m[1] + suffix, deps | control, number)
                    continue
                if line.startswith("connect "):
                    args = split(line[8:]); require(len(args) == 2, "unsupported connect")
                    dest = self.expression(args[0], symbols, prefix, writing=True)
                    value = expression(args[1])
                    require(dest.targets is not None and dest.deps.keys() == value.deps.keys(), "connect aggregate mismatch")
                    for suffix, flipped in leaves(dest.typ).items():
                        targets, deps = dest.targets[suffix], value.deps[suffix]
                        if flipped:
                            require(value.targets is not None, "flipped connect needs assignable source")
                            targets, deps = value.targets[suffix], dest.deps[suffix]
                        for target in targets:
                            # Dynamic LHS index dependencies are included in dest.deps.
                            extra = (value.deps[suffix] - value.targets[suffix]) if flipped else (dest.deps[suffix] - dest.targets[suffix])
                            if any(target == prefix + "." + r or target.startswith(prefix + "." + r + ".") or
                                   target.startswith(prefix + "." + r + "[") for r in registers):
                                target += "$NEXT"
                            self.add(target, deps | control | extra, number)
                    continue
                raise Uncertain("unsupported statement: " + line)
            except (Uncertain, KeyError) as error:
                raise Uncertain(f"{prefix} ({name}) line {number}: {error}") from error

    def expression(self, text, symbols, prefix, writing=False):
        text = text.strip()
        if re.fullmatch(r'(?:U|S)Int(?:<\d+>)?\((?:0[hbo][0-9a-fA-F_]+|-?\d+|"[hbo][0-9a-fA-F_]+")\)|-?\d+', text):
            require(not writing, "literal is not assignable"); return Value(SCALAR, {"": set()})
        call = re.fullmatch(rf"({IDENT})\((.*)\)", text)
        if call:
            require(not writing, "expression is not assignable")
            op, parts = call[1], split(call[2])
            require(op in PRIMS or op in ("mux", "validif", "cat"), "unsupported primitive: " + op)
            if op == "cat":
                require(len(parts) >= 2, "cat needs at least two inputs")
            else:
                require(len(parts) == ({"mux": 3, "validif": 2}.get(op, PRIMS.get(op))), "primitive arity: " + op)
            args = [self.expression(p, symbols, prefix) for p in parts]
            if op in ("mux", "validif"):
                require(args[0].typ == SCALAR, "non-scalar selector")
                if op == "mux":
                    require(args[1].typ == args[2].typ, "mux aggregate shape mismatch")
                return Value(args[1].typ, {s: args[0].all() | set().union(*(a.deps[s] for a in args[1:])) for s in args[1].deps})
            require(all(a.typ == SCALAR for a in args), "aggregate primitive unsupported: " + op)
            return Value(SCALAR, {"": set().union(*(a.all() for a in args))})
        match = re.match(IDENT, text)
        require(match is not None and match[0] in symbols, "unknown expression/reference: " + text)
        local = match[0]; name = prefix + "." + local
        require(name not in self.memories, "direct memory reference unsupported; require mport")
        if name in self.mports:
            (self.writes if writing else self.reads).add(name)
        typ, positions, selector = symbols[local], [name], set()
        rest = text[len(local):]
        while rest:
            field = re.match(rf"\.({IDENT})", rest)
            if field:
                require(typ[0] == "bundle", "subfield on non-bundle")
                fields = {n: t for n, _, t in typ[1]}
                require(field[1] in fields, "missing subfield: " + field[1])
                typ = fields[field[1]]; positions = [p + field[0] for p in positions]; rest = rest[len(field[0]):]
            elif rest.startswith("["):
                depth, end = 1, 1
                while end < len(rest) and depth:
                    depth += (rest[end] == "[") - (rest[end] == "]"); end += 1
                require(depth == 0 and typ[0] == "vec", "invalid vector reference")
                index = rest[1:end - 1]
                if re.fullmatch(r"\d+", index):
                    indexes = [int(index)]; require(indexes[0] < typ[1], "out-of-range index")
                else:
                    selection = self.expression(index, symbols, prefix)
                    require(selection.typ == SCALAR, "non-scalar dynamic index")
                    selector |= selection.all(); indexes = range(typ[1])
                positions = [p + f"[{i}]" for p in positions for i in indexes]
                typ, rest = typ[2], rest[end:]
            else:
                raise Uncertain("unsupported reference suffix: " + rest)
        targets = {s: {p + s for p in positions} for s in leaves(typ)}
        return Value(typ, {s: names | selector for s, names in targets.items()}, targets)

    def reachable(self, sources):
        forward = defaultdict(set)
        for dest, deps in self.graph.items():
            for source in deps:
                forward[source].add(dest)
        previous = {s: None for s in sources}; queue = deque(sources)
        while queue:
            source = queue.popleft()
            for dest in sorted(forward[source]):
                if dest not in previous:
                    previous[dest] = source; queue.append(dest)
        return previous

    def path(self, previous, sink):
        out = []
        while previous[sink] is not None:
            source = previous[sink]
            out.append({"from": source, "to": sink, "line": self.reasons[(source, sink)]}); sink = source
        return list(reversed(out))


def check(path, candidate):
    path = Path(path)
    data = path.read_bytes(); cone = Cones(data.decode())
    root = cone.root + "."
    def endpoints(prefix):
        full = root + prefix
        selected = sorted(v for v in cone.vertices if v == full or v.startswith(full + ".") or v.startswith(full + "["))
        require(selected, "missing required endpoint: " + full)
        return selected
    sources = [root + "io.translation.response." + field for field in
               ("valid", "bits.physicalAddress", "bits.pbmt", "bits.pageFault", "bits.accessFault")]
    sources += [root + "translatedReply"]
    require(all(s in cone.vertices for s in sources), "missing required raw response source")
    main, nextline = [], []
    for instance, module in cone.instances.items():
        if re.fullmatch(r"PmpChecker(?:_\d+)?", module):
            parents = [m for p, m in cone.instances.items() if instance.startswith(p + ".")]
            (nextline if any(re.fullmatch(r"NextLineAuthorization(?:_\d+)?", p) for p in parents) else main).append(instance)
    expected = root + ("permission.pmp" if candidate else "legacyPmp")
    require(main == [expected], "expected exactly one main PMP at " + expected + "; found " + str(main))
    checked = [p[len(root):] for p, m in cone.instances.items() if p.startswith(root) and
               re.fullmatch(r"checked(?:_checked)?", p[len(root):])]
    require(len(checked) == 1, "expected exactly one checked queue instance")
    groups = {"head": endpoints("head"), "mainPmpInputs": []}
    for field in ("address", "size", "privilege", "access", "state"):
        groups["mainPmpInputs"] += endpoints(expected[len(root):] + ".io." + field)
    groups["mainPmpDenied"] = endpoints(expected[len(root):] + ".io.denied")
    for field in ("valid", "bits.request", "bits.fault", "bits.pageFault"):
        groups["checked." + field] = endpoints(checked[0] + ".io.enq." + field)
    groups["canonicalStoreCertificate"] = endpoints("io.canonicalStoreCertificate")
    if candidate:
        for field in ("result", "hintRequest", "hintPrivilege", "hintBypassFault", "canonical", "nextAllowed"):
            groups["permission." + field] = endpoints("permission.io." + field)
    next_instances = [p for p, m in cone.instances.items() if re.fullmatch(r"NextLineAuthorization(?:_\d+)?", m)]
    require(len(next_instances) == 1, "expected exactly one separate NextLineAuthorization")
    groups["nextLineInputs"] = []
    for field in ("request", "privilege", "fault", "pmpState"):
        groups["nextLineInputs"] += endpoints(next_instances[0][len(root):] + ".io." + field)
    rows, witnesses = {}, {}
    for source in sources:
        previous = cone.reachable([source]); rows[source] = {}
        for label, sinks in groups.items():
            reached = sorted(set(sinks) & previous.keys()); rows[source][label] = reached
            if reached:
                witnesses[source + " -> " + label] = cone.path(previous, reached[0])
    total = sum(len(hits) for row in rows.values() for hits in row.values())
    require((total == 0) if candidate else (total > 0),
            ("unregistered raw response path" if candidate else "missing positive control path") + ": " + json.dumps(witnesses))
    if not candidate:
        for group in groups:
            require(any(row[group] for row in rows.values()), "control has no positive path to " + group)
    allowed = endpoints("translated.io.enq.valid") + endpoints("translated.io.enq.bits")
    allowed += sorted(v for v in cone.vertices if v.startswith(root) and v.endswith("$NEXT") and
                      re.match(r"(?:waiting|savedRequest|savedPrivilege|savedCanonicalStoreOrigin)(?:[.\[]|\$)", v[len(root):]))
    allowed_hits = {s: sorted(set(allowed) & cone.reachable([s]).keys()) for s in sources}
    require(all(allowed_hits[s] for s in sources), "source did not reach permitted enqueue/NEXT endpoints")
    return {"status": "PASS_REGISTERED_RAW_CUT" if candidate else "PASS_RAW_PATH_POSITIVE_CONTROL",
            "firSha256": hashlib.sha256(data).hexdigest(), "mode": "registered" if candidate else "control",
            "adapter": cone.root, "mainPmpInstances": main, "nextLinePmpInstances": nextline,
            "sources": sources, "sinkGroups": groups, "sourceReachability": rows, "witnesses": witnesses,
            "allowedEnqueueAndNextReachability": allowed_hits,
            "parsedInstances": cone.instances, "registerCuts": sorted(cone.registers), "memoryCuts": cone.memories,
            "vertices": len(cone.vertices), "edges": sum(map(len, cone.graph.values())),
            "limits": ["CHIRRTL 6 only; unsupported syntax fails, no lowered SV claim",
                       "Cycle-local conservative syntactic dependency, not Boolean sensitization or timing",
                       "Register clock/reset/init/NEXT terminate at Q; memory write data terminates at stored contents",
                       "Asynchronous memory address/enable, mux/when/else/dynamic selectors and hierarchy are traversed",
                       "Only actual DTA subtree; walker/translation service outside source boundary are not analyzed"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fir", type=Path, required=True)
    parser.add_argument("--mode", choices=("control", "registered"), required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = check(args.fir, args.mode == "registered")
    except (Uncertain, ValueError) as error:
        result = {"status": "FAIL_OR_UNCERTAIN", "error": str(error)}
    rendered = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered)
    print(rendered, end="")
    return 0 if result["status"].startswith("PASS_") else 1


if __name__ == "__main__":
    raise SystemExit(main())
