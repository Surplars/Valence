#!/usr/bin/env python3
"""Create a one-source negative control; never edit hardware, tests, or GSIM output in place."""
import argparse
import hashlib
import json
from pathlib import Path

CASES = {
    "wrong-writer-map": {
        "file": "src/main/scala/core/ooo/retire/WriterBankedRobCompletionPayload.scala",
        "old": "latestWriter(io.write(writer).bits.index) := (writer == 1).B",
        "new": "latestWriter(io.write(writer).bits.index) := (writer == 0).B",
        "mode": "rob", "failure": "RAW_PAYLOAD_RAM entries=4",
        "arguments": ["--payload-only"],
    },
    "missing-allocation-zero": {
        "file": "src/main/scala/core/ooo/retire/RenameRob.scala",
        "old": "Mux(entries(head).done, payload.io.headTval, 0.U(64.W))",
        "new": "payload.io.headTval",
        "mode": "rob", "failure": "ROB_COMPLETION_PAYLOAD phase=writer-map-and-allocation-zero",
        "arguments": ["--payload-only"],
    },
    "wrong-boundary-borrow": {
        "file": "src/main/scala/core/ooo/frontend/CompactFetchCacheKeys.scala",
        "old": "val high = if (set < offset) boundaryHigh(set)(way) else bases(set)(way)(63, highLow)",
        "new": "val high = if (set < offset && !(set == 1 && offset == 2)) boundaryHigh(set)(way) else bases(set)(way)(63, highLow)",
        "mode": "keys", "failure": "COMPACT_KEYS_FULL64_ORACLE", "arguments": [],
    },
    "stale-capture-enabled": {
        "file": "src/main/scala/core/ooo/platform/memory/InstructionRom.scala",
        "old": "when(!pendingStale) { capturePayload() }",
        "new": "when(true.B) { capturePayload() }",
        "mode": "native", "failure": "compact fetch keys paired",
        "additionalWitness": "STALE_OWNER_LIVE_ROWS set=0 live=2 pending_stale=1 invalidate=0 staged=1",
        "arguments": [],
    },
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def expected(root, kind):
    case = CASES[kind]
    original = (root / case["file"]).read_bytes()
    old, new = case["old"].encode(), case["new"].encode()
    if original.count(old) != 1:
        raise ValueError("source mutation anchor must occur exactly once: " + case["file"])
    mutated = original.replace(old, new, 1)
    record = {
        "schema": "rob-fetch-source-mutant-v1", "kind": kind,
        "sourceRelativePath": case["file"],
        "candidateSourceSha256": digest(original), "mutantSourceSha256": digest(mutated),
        "exactOriginal": case["old"], "exactReplacement": case["new"],
        "expectedFailurePrefix": case["failure"],
        "additionalWitness": case.get("additionalWitness"),
        "runArguments": case["arguments"], "unchangedTestsAndOracle": True,
        "compiled": False, "simulated": False,
    }
    return record, mutated


def verify(root, kind, directory):
    record, mutated = expected(root, kind)
    actual = json.loads((directory / "mutation.json").read_text())
    if actual != record or (directory / record["sourceRelativePath"]).read_bytes() != mutated:
        raise ValueError("source mutation declaration or bytes do not match the production-source change")
    return record


def create(root, kind, out):
    root, out = root.resolve(), out.resolve()
    if out == root or root in out.parents or out in root.parents:
        raise ValueError("mutation output must be a separate, fresh tree outside the repository")
    record, mutated = expected(root, kind)
    out.mkdir(parents=True, exist_ok=False)
    path = out / record["sourceRelativePath"]
    path.parent.mkdir(parents=True)
    path.write_bytes(mutated)
    (out / "mutation.json").write_text(json.dumps(record, indent=2) + "\n")
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=CASES)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(create(args.repo_root, args.kind, args.out), indent=2))
    except (OSError, ValueError) as error:
        parser.exit(2, "source mutation rejected: " + str(error) + "\n")


if __name__ == "__main__":
    main()
