#!/usr/bin/env python3
"""Strict, stdlib-only production A1 FIR projection. Never builds or simulates.

This is a bounded structural reader, not a general FIRRTL compiler. Module bodies
are opaque, copied byte-for-byte; only declarations, dependency edges, public
port types, annotations and the selected production assembly are interpreted.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import sys

TOP = "ProductionRealA1CdcFabricFixture"
ROOTS = ("CommonA1CpuTile", "CommonCpuClockBoundary", "CommonMachineFabric",
         "CdcResetRelease", "CdcResetRelease_1")
HOME = "MixedCoherentLineHome"
IDENTITIES = {
    "read-baseline": "47fc1dde76d3e58f2cb6a000e414d9034354656bbc0c2343e59f58b2c96e89e9",
    "probe-acquire": "de666c11bf6d3387967e24eb6b65c76860bbc29152042c82ee6c4e10b89b1698",
}
# Complete metadata pins exclude only the explicitly rehashed source/class/artifact maps.
PROFILE_CONFIG_SHA256 = {'probe-acquire': '019a63cc1a2a40d3224c4555832ca3ba01d8e63536931a990e43be3d90514b03', 'read-baseline': 'a7cb7532d5bf0ffcbcf857e822b7827145de34462d2089c73ccdb4b4e79592af'}
RESOLVED_CONFIG_SHA256 = {'probe-acquire': 'e799a69eee74cbe88d85661ff56afd2f3515c301e18b8be84e02b6045317f7fc', 'read-baseline': '041c7b7797966c3729bc71b77ece3d56d4281a05f688850bfa13d07be46c91c4'}
# Full leaf schema (path, type, direction), not just a leaf count. Updating these
# acceptance pins requires reviewing the new ABI and the wrapper's wiring.
PORT_SCHEMA_SHA256 = "11f35e8c356d4197462bb5348ccdf6375f1ebf0c840eb9f09e9af56a3bdbbe49"
LAYERS = ('  layer Verification, bind, "verification" :\n'
          '    layer Assert, bind, "verification/assert" :\n'
          '      layer Temporal, inline :\n'
          '    layer Assume, bind, "verification/assume" :\n'
          '      layer Temporal, inline :\n'
          '    layer Cover, bind, "verification/cover" :\n'
          '      layer Temporal, inline :\n\n')
SCALA_ROOTS = ("src/main/scala", "src/test/scala", "third_party/berkeley-hardfloat/src/main/scala")
RESOURCE_ROOTS = ("src/main/resources", "src/test/resources", "compile-resources",
                  "third_party/berkeley-hardfloat/src/main/resources",
                  "third_party/berkeley-hardfloat/compile-resources")
BUILD_FILES = ("build.mill", ".mill-version", ".mill-jvm-opts")
NAME = r"[A-Za-z_][A-Za-z_0-9$]*"
MODULE = re.compile(r"^  (public )?(extmodule|module) (" + NAME + r") :(?: @\[.*\])?$", re.M)


class Invalid(ValueError):
    """Unsupported or inconsistent input; never a partial success."""


def require(condition, message):
    if not condition:
        raise Invalid(message)


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha_file(path):
    require(Path(path).is_file(), f"missing regular file: {path}")
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(data)
    return h.hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def digest(value):
    return sha_bytes(canonical(value))


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=unique_object,
                      parse_constant=lambda x: (_ for _ in ()).throw(Invalid(f"nonfinite JSON: {x}")))


def write_json(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write("\n")


def plain(line):
    """Remove only a trailing source locator, never assertion diagnostics."""
    return re.sub(r" @\[[^\n]*\]$", "", line)


@dataclass(frozen=True)
class Type:
    kind: str
    width: int = 0
    fields: tuple = ()
    element: "Type | None" = None
    count: int = 0

    def leaves(self, path, flat, is_input=False):
        if self.kind == "bundle":
            for name, flip, child in self.fields:
                yield from child.leaves(path + "." + name, flat + "__" + name, is_input ^ flip)
        elif self.kind == "vector":
            for index in range(self.count):
                yield from self.element.leaves(f"{path}[{index}]", f"{flat}_{index}", is_input)
        else:
            yield {"path": path, "name": flat, "type": self.kind + (f"<{self.width}>" if self.kind == "UInt" else ""),
                   "width": self.width or 1, "direction": "input" if is_input else "output"}


def parse_type(text):
    """Finite widths, nested bundles/vectors and XOR flip propagation only."""
    tokens = re.findall(NAME + r"|[0-9]+|[{}:,<>\[\]]", text)
    require("".join(tokens) == re.sub(r"\s", "", text), f"unsupported type: {text}")
    index = 0

    def take(expected=None):
        nonlocal index
        require(index < len(tokens), "truncated type")
        token = tokens[index]
        require(expected is None or token == expected, f"expected {expected}, got {token}")
        index += 1
        return token

    def number():
        token = take()
        require(token.isdecimal() and 0 < int(token) <= 1048576, "invalid width/vector length")
        return int(token)

    def parse():
        token = take()
        if token == "{":
            fields = []
            names = set()
            while True:
                name = take()
                flip = name == "flip"
                if flip:
                    name = take()
                require(re.fullmatch(NAME, name) and name not in names, "invalid/duplicate bundle field")
                names.add(name)
                take(":")
                fields.append((name, flip, parse()))
                delimiter = take()
                if delimiter == "}":
                    break
                require(delimiter == ",", "expected bundle separator")
            result = Type("bundle", fields=tuple(fields))
        elif token == "UInt":
            take("<")
            result = Type("UInt", width=number())
            take(">")
        else:
            require(token in ("Clock", "Reset", "AsyncReset"), f"unsupported ground type: {token}")
            result = Type(token)
        while index < len(tokens) and tokens[index] == "[":
            take("[")
            result = Type("vector", element=result, count=number())
            take("]")
        return result

    result = parse()
    require(index == len(tokens), "trailing type tokens")
    return result


def ports(body):
    result = {}
    started_body = False
    for line in body.splitlines()[1:]:
        clean = plain(line)
        match = re.fullmatch(r"    (input|output) (" + NAME + r") : (.+)", clean)
        if match:
            require(not started_body, "port declaration after body")
            direction, name, text = match.groups()
            require(name not in result, f"duplicate port: {name}")
            result[name] = (direction == "input", parse_type(text))
        elif clean.strip():
            require(not re.match(r"\s*(input|output)\b", clean), "unsupported port declaration")
            started_body = True
    require(result, "module has no ports")
    return result


def port_leaves(body, prefix=""):
    return [leaf for name, (inp, typ) in ports(body).items()
            for leaf in typ.leaves(prefix + name, prefix + name, inp)]


def dependencies(body):
    result = {}
    for line in body.splitlines()[1:]:
        clean = plain(line)
        if re.match(r"\s*inst\b", clean):
            match = re.fullmatch(r" +inst (" + NAME + r") of (" + NAME + r")", clean)
            require(match is not None, "unsupported instance declaration")
            require(match[1] not in result, f"duplicate instance: {match[1]}")
            result[match[1]] = match[2]
    return result


def closure(modules, roots):
    result, active = set(), set()

    def visit(name):
        require(name in modules, f"missing module dependency: {name}")
        require(name not in active, f"recursive instance graph: {name}")
        if name in result:
            return
        active.add(name)
        for dependency in dependencies(modules[name]).values():
            visit(dependency)
        active.remove(name)
        result.add(name)

    for root in roots:
        visit(root)
    return result


@dataclass
class Circuit:
    name: str
    annotations: list
    layers: str
    modules: dict


def parse_fir(text):
    require("\r" not in text and "\t" not in text and text.endswith("\n"), "unsupported FIR whitespace")
    header = re.match(r"FIRRTL version 6\.0\.0\ncircuit (" + NAME + r") :%\[", text)
    require(header is not None, "expected annotated FIRRTL 6.0.0 circuit")
    decoder = json.JSONDecoder(object_pairs_hook=unique_object)
    annotations, end = decoder.raw_decode(text, header.end())
    require(isinstance(annotations, list) and text[end:end + 2] == "]\n", "invalid annotation envelope")
    matches = list(MODULE.finditer(text, end + 2))
    require(matches, "no module declarations")
    layers = text[end + 2:matches[0].start()]
    require(layers == LAYERS, "unsupported/missing verification layers")
    modules = {}
    for index, match in enumerate(matches):
        name = match[3]
        require(name not in modules, f"duplicate module: {name}")
        body = text[match.start():matches[index + 1].start() if index + 1 < len(matches) else len(text)]
        for line in body.splitlines()[1:]:
            require(not line or line.startswith("    "), "unsupported top-level FIR declaration")
        modules[name] = body
    require(header[1] in modules, "circuit top missing")
    for annotation in annotations:
        require(isinstance(annotation, dict), "unsupported annotation")
        target = annotation.get("target", "")
        require(re.fullmatch(r"~\|" + NAME + r"(?:>" + NAME + r")?", target), "unsupported annotation target")
        require(target[2:].split(">")[0] in modules, "annotation module missing")
        kind = annotation.get("class")
        expected = {"class", "target", "group"} if kind == "firrtl.transforms.DedupGroupAnnotation" else {"class", "target", "description"}
        require(kind in ("firrtl.transforms.DedupGroupAnnotation", "firrtl.AttributeAnnotation") and set(annotation) == expected,
                "unsupported annotation class/fields")
    # Check every instance, including those outside the selected closure.
    closure(modules, tuple(modules))
    return Circuit(header[1], annotations, layers, modules)


def current_commit(root):
    """Read Git identity without executing Git or changing its index/locks."""
    git = root / ".git"
    if git.is_file():
        value = git.read_text().strip()
        require(value.startswith("gitdir: "), "unsupported gitdir file")
        git = (root / value[8:]).resolve()
    head = (git / "HEAD").read_text().strip()
    if head.startswith("ref: "):
        ref = head[5:]
        require(re.fullmatch(r"refs/[A-Za-z0-9_./-]+", ref) and ".." not in ref, "unsupported Git ref")
        common = git
        if (git / "commondir").is_file():
            common = (git / (git / "commondir").read_text().strip()).resolve()
        candidates = [git / ref, common / ref]
        existing = next((path for path in candidates if path.is_file()), None)
        if existing:
            head = existing.read_text().strip()
        else:
            packed = (common / "packed-refs").read_text().splitlines()
            found = [line.split()[0] for line in packed if line.endswith(" " + ref)]
            require(len(found) == 1, "Git ref not found")
            head = found[0]
    require(re.fullmatch(r"[0-9a-f]{40}", head), "unsupported Git commit")
    return head


def files_below(directory, suffix=None):
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.rglob("*") if p.is_file() and (suffix is None or p.suffix == suffix))


def hashes(paths):
    result = {}
    for path in paths:
        key = str(Path(path).resolve())
        require(key not in result, f"duplicate normalized file: {path}")
        result[key] = sha_file(path)
    return result


def verify_hashes(expected, description):
    require(isinstance(expected, dict) and expected, f"empty {description}")
    for name, value in expected.items():
        require(Path(name).is_absolute() and re.fullmatch(r"[0-9a-f]{64}", value or ""), f"invalid {description} pin")
        require(sha_file(name) == value, f"stale {description}: {name}")


def verify_provenance(emission):
    profile = read_json(emission / "emission-profile.json")
    identity = read_json(emission / "microarchitecture-identity.json")
    resolved = read_json(emission / "resolved-soc-config.json")
    selection = profile.get("fabricDmaExperiment", {}).get("selection")
    require(selection in IDENTITIES, "unsupported fabric experiment selector")
    claimed = identity.get("identitySha256")
    require(claimed == IDENTITIES[selection] and digest({k: v for k, v in identity.items() if k != "identitySha256"}) == claimed,
            "unsupported or stale complete microarchitecture identity")
    require(profile.get("cpuMicroarchitecture") == identity, "profile/identity disagreement")
    expected = {
        "schema": 1, "top": "CommonMachinePlatform", "cpu": "a1", "rtlFormat": "CHIRRTL",
        "clockProfile": "production", "runtimeClockReconfiguration": False,
        "cpuMicroarchitectureProfile": "selected", "programmableRom": True, "vivadoMemories": False,
        "hardwareClocks": True, "independentCpuFabricClocks": True, "independentFixedDomains": False,
        "clockTopology": "legacy-ui-fabric", "memoryCopyDma": True,
        "cpuClockHz": 100000000, "fabricClockHz": 250000000, "ddrUiHz": 250000000,
        "romBytes": 131072, "instructionCacheBytes": 32768, "dataCacheBytes": 32768,
        "cacheWays": 2, "issueWidth": 2, "homeClients": 2, "homeLines": 1024, "homeWays": 4,
        "homeAcquireEntries": 2, "homeWritebackEntries": 2, "ddrSlots": 4, "ddrWriteSlots": 2,
        "heldFifo": "HeldResponseCdcDataFifo", "fifoDepth": 16,
        "a1Resources": {"robEntries": 16, "physicalRegisters": 48, "lsuOwners": 2, "storeBufferEntries": 2},
        "externalHotMaintenanceSupported": False, "oneSidedResetSupported": False,
        "physicalTimingVerified": False, "boardVerified": False,
    }
    for key, value in expected.items():
        require(profile.get(key) == value and type(profile.get(key)) is type(value), f"unsupported profile field: {key}")
    fabric = profile["fabricDmaExperiment"]
    require(fabric.get("defaultEnabled") is False and fabric.get("dmaMaintenanceCompletionFlow") is True
            and fabric.get("dmaReadAcquireOverlap") is True
            and fabric.get("dmaProbeAcquireOverlap") is (selection == "probe-acquire"), "fabric flag mismatch")
    require(fabric.get("effectiveFpgaConfig") == identity["sharedFabricConfig"]
            and isinstance(fabric.get("effectiveFabricCoreParameters"), dict), "fabric config mismatch")
    require(resolved.get("schema") == 1 and resolved.get("configurationFile") is None
            and resolved.get("configurationSha256") is None and resolved.get("cpuIdentitySha256") == claimed
            and resolved.get("fabricDmaExperiment") == fabric, "resolved configuration mismatch")
    require(resolved.get("effective") and all(profile.get(k) == v for k, v in resolved["effective"].items()),
            "resolved effective/profile disagreement")
    require(digest({k: v for k, v in profile.items() if k not in ("sources", "compiledClasspath", "artifacts")})
            == PROFILE_CONFIG_SHA256[selection], "unsupported complete emission metadata")
    require(digest(resolved) == RESOLVED_CONFIG_SHA256[selection], "unsupported complete resolved configuration")
    artifacts = profile.get("artifacts")
    expected_artifacts = {str(emission / name) for name in
                          ("CommonMachinePlatform.fir", "microarchitecture-identity.json", "resolved-soc-config.json")}
    require(isinstance(artifacts, dict) and set(artifacts) == expected_artifacts, "artifact set/path mismatch; use original emission directory")
    verify_hashes(artifacts, "emission artifact")
    sources = profile.get("sources")
    require(isinstance(sources, dict), "missing emission sources")
    receipt_candidates = [Path(name) for name in sources if Path(name).suffix == ".json"]
    require(len(receipt_candidates) == 1, "expected exactly one bound compile receipt")
    receipt_path = receipt_candidates[0]
    receipt = read_json(receipt_path)
    require(receipt.get("schema") == "valence-scala-compile-v1" and type(receipt.get("exit")) is int and receipt.get("exit") == 0,
            "complete successful compile receipt required")
    root = Path(receipt["sourceRoot"])
    require(root.is_absolute() and root.resolve() == root, "noncanonical compile source root")
    require(receipt.get("sourceCommit") == current_commit(root), "stale source commit")
    source_files = [p for name in SCALA_ROOTS for p in files_below(root / name, ".scala")]
    source_files += [p for name in RESOURCE_ROOTS for p in files_below(root / name)]
    source_files += [root / name for name in BUILD_FILES]
    require(receipt.get("sourceInputs") == hashes(source_files), "compile source set/hash mismatch")
    manifest = receipt.get("sourceManifest", {})
    require(set(manifest) == {"path", "sha256"} and Path(manifest["path"]).is_absolute()
            and sha_file(manifest["path"]) == manifest["sha256"], "source manifest pin mismatch")
    require(read_json(manifest["path"]) == receipt["sourceInputs"], "source manifest content mismatch")
    emission_sources = files_below(root / "src/main/scala", ".scala") + files_below(root / "src/test/scala/platform", ".scala")
    emission_sources += [root / "build.mill", receipt_path]
    require(sources == hashes(emission_sources), "emission source set/hash mismatch")
    entries = receipt.get("runClasspathEntries", [])
    require(entries and len(entries) == len(set(entries)), "missing/duplicate classpath entries")
    class_files = []
    for entry in entries:
        path = Path(entry)
        require(path.is_absolute() and path.exists() and path.resolve() == path, "missing/noncanonical classpath entry")
        class_files += files_below(path) if path.is_dir() else [path]
    classes = hashes(class_files)
    require(classes and receipt.get("compiledClasspath") == classes and profile.get("compiledClasspath") == classes,
            "compiled classpath set/hash mismatch")
    return profile, identity, {"receipt": receipt_path, "receiptSha256": sha_file(receipt_path),
                               "sourceManifestSha256": manifest["sha256"], "sourceCommit": receipt["sourceCommit"],
                               "sourceInputsSha256": digest(receipt["sourceInputs"]), "compiledClasspathSha256": digest(classes),
                               "runClasspathEntriesSha256": digest(entries)}


def selected_assembly(body):
    """The production assembly subset being replaced, including indentation.

    Any assignment to a protected aggregate or leaf is included, so an added
    partial connection cannot quietly override the accepted bulk connection.
    """
    protected = ("fabricRelease.", "cpuRelease.", "crossing.cpu", "crossing.fabricClock",
                 "crossing.commonColdReset", "fabric.clock", "fabric.reset", "fabric.io.tile",
                 "fabric.io.transportCpuEmptySynchronized", "fabric.io.fabricTransportEmpty",
                 "fabric.io.ddrReady", "fabric.io.ddrAxi", "io.ddrAxi",
                 "cpu.clock", "cpu.reset", "cpu.io.hold", "cpu.io.inspectRegister")
    result = []
    for line in body.splitlines()[1:]:
        line = plain(line)
        stripped = line.strip()
        if (re.search(r"\b(?:_?started\w*|_?startupReset\w*)\b", line)
                or stripped.startswith(tuple("inst " + x + " of " for x in ("fabricRelease", "cpuRelease", "crossing", "fabric", "cpu")))
                or (stripped.startswith("connect ") and stripped[8:].startswith(protected))):
            result.append(line)
    return result


# Exact statements emitted by the supported production static assembly, without
# source locators. A changed startup law must receive an explicit contract review.
PRODUCTION_ASSEMBLY = [
    '    inst fabricRelease of CdcResetRelease',
    '    connect fabricRelease.clockIn, fabricClock',
    '    connect fabricRelease.asyncReset, commonColdReset',
    '    regreset started : UInt<1>, fabricClock, fabricRelease.resetOut, UInt<1>(0h0)',
    '    node _started_T = and(io.bootEnable, io.ddrReady)',
    '    when _started_T :',
    '      connect started, UInt<1>(0h1)',
    '    when started :',
    '      node _started_T_1 = asUInt(fabricRelease.resetOut)',
    '      node _started_T_2 = eq(_started_T_1, UInt<1>(0h0))',
    '          intrinsic(circt_chisel_ifelsefatal<format = "Assertion failed: DDR readiness lost: platform requires a common cold reset\\n", label = "chisel3_builtin">, fabricClock, io.ddrReady, _started_T_2)',
    '    node _startupReset_T = asUInt(commonColdReset)',
    '    node _startupReset_T_1 = eq(started, UInt<1>(0h0))',
    '    node _startupReset_T_2 = or(_startupReset_T, _startupReset_T_1)',
    '    node startupReset = asAsyncReset(_startupReset_T_2)',
    '    inst cpuRelease of CdcResetRelease_1',
    '    connect cpuRelease.clockIn, cpuClock',
    '    connect cpuRelease.asyncReset, startupReset',
    '    inst crossing of CommonCpuClockBoundary',
    '    connect crossing.cpuClock, cpuClock',
    '    connect crossing.fabricClock, fabricClock',
    '    connect crossing.commonColdReset, startupReset',
    '    inst fabric of CommonMachineFabric',
    '    connect fabric.clock, fabricClock',
    '    connect fabric.reset, fabricRelease.resetOut',
    '    connect fabric.io.tile, crossing.fabric',
    '    connect fabric.io.transportCpuEmptySynchronized, crossing.cpuEmptyInFabric',
    '    connect fabric.io.fabricTransportEmpty, crossing.fabricTransportEmpty',
    '    connect fabric.io.ddrReady, io.ddrReady',
    '    connect fabric.io.ddrAxi.r, io.ddrAxi.r',
    '    connect io.ddrAxi.ar.bits, fabric.io.ddrAxi.ar.bits',
    '    connect io.ddrAxi.ar.valid, fabric.io.ddrAxi.ar.valid',
    '    connect fabric.io.ddrAxi.ar.ready, io.ddrAxi.ar.ready',
    '    connect fabric.io.ddrAxi.b, io.ddrAxi.b',
    '    connect io.ddrAxi.w.bits, fabric.io.ddrAxi.w.bits',
    '    connect io.ddrAxi.w.valid, fabric.io.ddrAxi.w.valid',
    '    connect fabric.io.ddrAxi.w.ready, io.ddrAxi.w.ready',
    '    connect io.ddrAxi.aw.bits, fabric.io.ddrAxi.aw.bits',
    '    connect io.ddrAxi.aw.valid, fabric.io.ddrAxi.aw.valid',
    '    connect fabric.io.ddrAxi.aw.ready, io.ddrAxi.aw.ready',
    '    inst cpu of CommonA1CpuTile',
    '    connect cpu.clock, cpuClock',
    '    connect cpu.reset, cpuRelease.resetOut',
    '    connect crossing.cpu, cpu.io.bus',
    '    connect cpu.io.hold, UInt<1>(0h0)',
    '    connect cpu.io.inspectRegister, UInt<1>(0h0)',
]


def validate_assembly(circuit):
    require(circuit.name == "CommonMachinePlatform", "wrong production circuit")
    require(selected_assembly(circuit.modules[circuit.name]) == PRODUCTION_ASSEMBLY,
            "unsupported production startup/reset/bus/empty wiring")
    require(assertion_inventory(circuit.modules, {circuit.name})["assertionCount"] == 1,
            "unsupported production startup assertion count/layers")
    schema = {name: port_leaves(circuit.modules[name]) for name in ROOTS}
    require(digest(schema) == PORT_SCHEMA_SHA256, "unsupported public port schema (name/type/width/flip)")
    return schema


def assertion_inventory(modules, keep):
    sites, layerblocks = [], []
    allowed = {"input", "output", "node", "connect", "when", "else", "skip", "wire", "reg", "regreset",
               "cmem", "smem", "read", "write", "infer", "invalidate", "inst", "layerblock"}
    for name in sorted(keep):
        body = modules[name]
        require(not body.startswith("  extmodule"), f"external/vendor module in projection: {name}")
        layers = []
        for number, line in enumerate(body.splitlines()[1:], 2):
            stripped = plain(line).strip()
            if not stripped:
                continue
            indent = len(line) - len(line.lstrip())
            while layers and indent <= layers[-1][0]:
                layers.pop()
            if stripped.startswith("layerblock "):
                match = re.fullmatch(r"layerblock (Verification|Assert|Assume|Cover|Temporal) :", stripped)
                require(match, f"unsupported layer block in {name}")
                layers.append((indent, match[1]))
                layerblocks.append({"module": name, "line": number, "path": [x[1] for x in layers]})
            elif stripped.startswith("intrinsic("):
                require(stripped.startswith('intrinsic(circt_chisel_ifelsefatal<format = "')
                        and stripped.endswith(")") and [x[1] for x in layers] == ["Verification", "Assert"],
                        f"unsupported assertion intrinsic/layer in {name}:{number}")
                sites.append({"module": name, "line": number, "sha256": sha_bytes(line.encode()),
                              "statement": line, "layers": [x[1] for x in layers]})
            else:
                require(stripped.split()[0] in allowed, f"unsupported body statement in {name}:{number}")
    require(sites, "no preserved production assertions")
    return {"sites": sites, "layerblocks": layerblocks, "assertionCount": len(sites)}


def bundle_field(body, field):
    p = ports(body)
    require(p.get("io", (None, None))[0] is False, "expected output io bundle")
    typ = p["io"][1]
    require(typ.kind == "bundle", "expected io bundle")
    fields = {name: (flip, child) for name, flip, child in typ.fields}
    require(field in fields, f"missing io field: {field}")
    return fields[field]


def make_wrapper(modules):
    cp = ports(modules[ROOTS[0]])
    bp = ports(modules[ROOTS[1]])
    fp = ports(modules[ROOTS[2]])
    cpu_bus = bundle_field(modules[ROOTS[0]], "bus")
    fabric_bus = bundle_field(modules[ROOTS[2]], "tile")
    require(cpu_bus == (False, bp["cpu"][1]) and fabric_bus == (True, bp["fabric"][1])
            and bp["cpu"] == (True, bp["fabric"][1]) and bp["fabric"][0] is False,
            "bus shape/direction mismatch")
    ports_out = [{"name": name, "direction": "input", "type": typ, "width": 1}
                 for name, typ in (("cpuClock", "Clock"), ("fabricClock", "Clock"),
                                   ("commonColdReset", "AsyncReset"), ("bootEnable", "UInt<1>"))]
    body = ["    inst cpu of CommonA1CpuTile", "    inst crossing of CommonCpuClockBoundary",
            "    inst fabric of CommonMachineFabric", "    inst fabricRelease of CdcResetRelease",
            "    inst cpuRelease of CdcResetRelease_1"]
    connections = []
    endpoints = {}
    for instance, module in (("cpu", ROOTS[0]), ("crossing", ROOTS[1]), ("fabric", ROOTS[2]),
                             ("fabricRelease", ROOTS[3]), ("cpuRelease", ROOTS[4])):
        for leaf in port_leaves(modules[module]):
            endpoints[instance + "." + leaf["path"]] = leaf
    written = set()

    def connect(dst, src, kind, typ=None):
        if dst in endpoints:
            require(endpoints[dst]["direction"] == "input", f"write to instance output: {dst}")
            actual = endpoints[dst]["type"]
            require(typ is None or actual == typ, f"destination type mismatch: {dst}")
            if src in endpoints:
                require(endpoints[src]["type"] == actual or (actual == "Reset" and endpoints[src]["type"] == "AsyncReset"),
                        f"source type mismatch: {src}")
            typ = actual
        require(dst not in written, f"multiple wrapper drivers: {dst}")
        written.add(dst)
        body.append(f"    connect {dst}, {src}")
        connections.append({"destination": dst, "source": src, "type": typ, "kind": kind})

    connect("fabricRelease.clockIn", "fabricClock", "startup")
    connect("fabricRelease.asyncReset", "commonColdReset", "startup")
    body.append("    regreset started : UInt<1>, fabricClock, fabricRelease.resetOut, UInt<1>(0)")
    connect("started", "or(started, and(bootEnable, external__ddrReady))", "startup", "UInt<1>")
    body.append("    node startupReset = asAsyncReset(or(asUInt(commonColdReset), not(started)))")
    for dst, src in (("cpuRelease.clockIn", "cpuClock"), ("cpuRelease.asyncReset", "startupReset"),
                     ("cpu.clock", "cpuClock"), ("cpu.reset", "cpuRelease.resetOut"), ("cpu.io.hold", "UInt<1>(0)"),
                     ("crossing.cpuClock", "cpuClock"), ("crossing.fabricClock", "fabricClock"),
                     ("crossing.commonColdReset", "startupReset"), ("fabric.clock", "fabricClock"),
                     ("fabric.reset", "fabricRelease.resetOut"),
                     ("fabric.io.transportCpuEmptySynchronized", "crossing.cpuEmptyInFabric"),
                     ("fabric.io.fabricTransportEmpty", "crossing.fabricTransportEmpty")):
        connect(dst, src, "startup" if "Empty" not in dst else "empty-feedback")

    def expose(leaf, observation=False):
        direction = "output" if observation else leaf["direction"]
        name, path, typ = leaf["name"], leaf["path"], leaf["type"]
        require(typ.startswith("UInt<"), "unsupported exposed leaf")
        ports_out.append({"name": name, "direction": direction, "type": typ, "width": leaf["width"]})
        connect(path if direction == "input" else name, name if direction == "input" else path,
                "observation" if observation else "public-port", typ)

    for side, target in (("cpu", "cpu.io.bus"), ("fabric", "fabric.io.tile")):
        inp, typ = bp[side]
        for leaf in typ.leaves("crossing." + side, side, inp):
            path = leaf["path"]
            other = path.replace("crossing." + side, target, 1)
            require(endpoints[path]["direction"] != endpoints[other]["direction"], "connected bus directions agree")
            connect(path if leaf["direction"] == "input" else other,
                    other if leaf["direction"] == "input" else path, side + "-bus", leaf["type"])
            expose(leaf, observation=True)
    for p, instance, prefix, excluded in ((fp, "fabric", "external", {"tile", "transportCpuEmptySynchronized", "fabricTransportEmpty"}),
                                          (cp, "cpu", "core", {"bus", "hold"})):
        for name, flip, typ in p["io"][1].fields:
            if name not in excluded:
                for leaf in typ.leaves(instance + ".io." + name, prefix + "__" + name, flip):
                    expose(leaf)
    for name in ("cpuLinkReady", "fabricLinkReady", "cpuTransportEmpty", "fabricTransportEmpty", "cpuEmptyInFabric", "fabricEmptyInCpu"):
        expose({"path": "crossing." + name, "name": name, "type": "UInt<1>", "width": 1, "direction": "output"})
    for name, path in (("started", "started"), ("cpuReset", "asUInt(cpuRelease.resetOut)"),
                       ("fabricReset", "asUInt(fabricRelease.resetOut)"), ("startupReset", "asUInt(startupReset)")):
        expose({"path": path, "name": "observe__" + name, "type": "UInt<1>", "width": 1, "direction": "output"})
    body += ["    layerblock Verification :", "      layerblock Assert :",
             '        intrinsic(circt_chisel_ifelsefatal<format = "Assertion failed: DDR readiness lost: platform requires a common cold reset\\n", label = "chisel3_builtin">, fabricClock, external__ddrReady, and(started, not(asUInt(fabricRelease.resetOut))))']
    require(len({p["name"] for p in ports_out}) == len(ports_out), "flat port name collision")
    require(all(path in written for path, leaf in endpoints.items() if leaf["direction"] == "input"), "unconnected instance input")
    require(all(p["name"] in written for p in ports_out if p["direction"] == "output"), "undriven top output")
    top = "\n".join([f"  public module {TOP} :", *[f'    {p["direction"]} {p["name"]} : {p["type"]}' for p in ports_out], "", *body]) + "\n"
    return top, ports_out, connections


def project(text):
    circuit = parse_fir(text)
    schema = validate_assembly(circuit)
    keep = closure(circuit.modules, ROOTS)
    require(len(keep) == 374, f"unsupported dependency closure size: {len(keep)}")
    assertions = assertion_inventory(circuit.modules, keep)
    top, flat_ports, connections = make_wrapper(circuit.modules)
    retained, excluded = [], []
    for annotation in circuit.annotations:
        (retained if annotation["target"][2:].split(">")[0] in keep else excluded).append(annotation)
    output = (f"FIRRTL version 6.0.0\ncircuit {TOP} :%[" + json.dumps(retained, indent=2) + "]\n" + circuit.layers
              + "".join(body for name, body in circuit.modules.items() if name in keep) + top)
    reparsed = parse_fir(output)
    require(set(reparsed.modules) == keep | {TOP}, "output closure mismatch")
    require(all(reparsed.modules[name] == circuit.modules[name] for name in keep), "copied body changed")
    require(port_leaves(top) == [{**p, "path": p["name"]} for p in flat_ports], "serialized port mismatch")
    binding = {
        "top": TOP, "definitions": len(keep), "totalDefinitions": len(keep) + 1,
        "bodySha256": {name: sha_bytes(circuit.modules[name].encode()) for name in sorted(keep)},
        "rootClosures": {name: sorted(closure(circuit.modules, (name,))) for name in ROOTS},
        "dependencies": {name: dependencies(circuit.modules[name]) for name in sorted(keep)},
        "publicSchemaSha256": digest(schema), "connections": connections,
        "layersSha256": sha_bytes(circuit.layers.encode()), "retainedAnnotations": retained,
        "excludedAnnotations": excluded, "originalAssertionSites": assertions["assertionCount"], "wrapperAssertionSites": 1,
        "productionAssembly": PRODUCTION_ASSEMBLY, "wrapperSha256": sha_bytes(top.encode()),
        "compositionSha256": sha_bytes(output.encode()),
    }
    return output, top, flat_ports, binding, assertions


def inspect(emission):
    emission = Path(emission).resolve()
    before = sha_file(emission / "emission-profile.json")
    profile, identity, provenance = verify_provenance(emission)
    text = (emission / "CommonMachinePlatform.fir").read_text(encoding="utf-8")
    output, top, flat_ports, binding, assertions = project(text)
    # Reject changed inputs during inspection, including every source/class byte.
    again = verify_provenance(emission)
    require(again == (profile, identity, provenance) and before == sha_file(emission / "emission-profile.json"),
            "emission changed during inspection")
    require(sha_bytes(text.encode()) == profile["artifacts"][str(emission / "CommonMachinePlatform.fir")], "FIR changed during read")
    binding.update({"schema": "valence-a1-cdc-fabric-export-v1", "selection": profile["fabricDmaExperiment"]["selection"],
                    "identitySha256": identity["identitySha256"], "cpuPrivateIdentitySha256": digest({k: v for k, v in identity.items()
                         if k not in ("identitySha256", "fabricDmaExperiment", "sharedFabricConfig")}),
                    "emissionProfileSha256": before, "sourceFirSha256": sha_bytes(text.encode()),
                    "provenance": provenance, "runtimeExecuted": False, "loweringExecuted": False,
                    "physicalTimingVerified": False, "boardVerified": False})
    return output, top, flat_ports, binding, assertions


def check_pair(first, second):
    """Both arguments are independently inspected production emission results."""
    a, b = first[3], second[3]
    require((a["selection"], b["selection"]) == ("read-baseline", "probe-acquire"), "pair must be fresh OFF then ON")
    require(a["provenance"] == b["provenance"], "pair source/class/receipt binding differs")
    require(a["cpuPrivateIdentitySha256"] == b["cpuPrivateIdentitySha256"], "pair CPU-private identity differs")
    require(a["identitySha256"] != b["identitySha256"], "combined experiment identities must differ")
    require(a["rootClosures"] == b["rootClosures"], "pair dependency graph differs")
    changed = sorted(name for name in a["bodySha256"] if a["bodySha256"][name] != b["bodySha256"].get(name))
    require(changed == [HOME], f"pair changed unexpected dependency bodies: {changed}")
    for key in ("wrapperSha256", "publicSchemaSha256", "connections", "layersSha256", "retainedAnnotations", "productionAssembly"):
        require(a[key] == b[key], f"pair differs in {key}")
    require(first[2] == second[2], "pair flattened ports differ")
    return {"status": "PASS_SEPARATELY_EMITTED_PAIR_INSPECTION_ONLY", "changedBodies": changed,
            "cpuPrivateIdentitySha256": a["cpuPrivateIdentitySha256"],
            "offSourceFirSha256": a["sourceFirSha256"], "onSourceFirSha256": b["sourceFirSha256"], "runtimeExecuted": False}


def export(emission, out=None, paired_emission=None):
    if out is not None:
        out = Path(out).absolute()
        require(not out.exists() and not out.is_symlink(), "output must not exist")
        require(out.parent.is_dir(), "output parent must already exist")
    result = inspect(emission)
    pair = None
    if paired_emission is not None:
        require(Path(emission).resolve() != Path(paired_emission).resolve(), "pair requires distinct emission directories")
        pair = check_pair(result, inspect(paired_emission))
    if out is not None:
        out.mkdir()  # Atomic no-overwrite gate; never reuse a partially written directory.
        output, top, flat_ports, binding, assertions = result
        binding = dict(binding)
        binding["provenance"] = dict(binding["provenance"])
        binding["provenance"]["receipt"] = os.path.relpath(binding["provenance"]["receipt"], out)
        binding["emissionDirectory"] = os.path.relpath(Path(emission).resolve(), out)
        for name, value in (("fixture.fir", output), ("TOP.fir", top)):
            with (out / name).open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(value)
        write_json(out / "PORTS.json", flat_ports)
        write_json(out / "ASSERTIONS.json", assertions)
        if pair:
            write_json(out / "PAIR.json", pair)
        binding["outputFiles"] = {p.name: sha_file(p) for p in sorted(out.iterdir())}
        write_json(out / "BINDING.json", binding)
    return {"status": "PASS_EXPORT_CHECK_ONLY", "selection": result[3]["selection"],
            "definitions": result[3]["totalDefinitions"], "ports": len(result[2]),
            "compositionSha256": result[3]["compositionSha256"], "pair": pair, "runtimeExecuted": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emission-dir", required=True, type=Path)
    output = parser.add_mutually_exclusive_group(required=True)
    output.add_argument("--out", type=Path)
    output.add_argument("--check-only", action="store_true")
    parser.add_argument("--paired-emission-dir", type=Path,
                        help="optional independently emitted probe-acquire directory; first must be read-baseline")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(export(args.emission_dir, args.out, args.paired_emission_dir), indent=2))
    except (Invalid, OSError, ValueError, KeyError, TypeError, RecursionError) as error:
        print(f"export rejected: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
