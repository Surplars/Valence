"""Validate an explicit-edge qualification receipt; default GSIM setup is unchanged."""
import hashlib
import json
from pathlib import Path


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def tool_binding(path):
    path = Path(path).resolve()
    receipt = json.loads(path.read_text())
    if receipt["status"] != "PASS_SCOPED_EXPLICIT_CLOCK_EDGE_RESET_RAM_MAILBOX_GSIM_TOOL":
        raise RuntimeError("unqualified explicit-edge tool")
    for name, digest in receipt["artifact_sha256"].items():
        if sha(path.parent / name) != digest:
            raise RuntimeError("qualification artifact changed: " + name)
    source = Path(receipt["source_root"])
    for name, digest in receipt["source_sha256"].items():
        if sha(source / name) != digest:
            raise RuntimeError("qualified tool source changed: " + name)
    tool = Path(receipt["gsim"])
    if sha(tool) != receipt["gsim_sha256"]:
        raise RuntimeError("qualified tool binary changed")
    return tool
