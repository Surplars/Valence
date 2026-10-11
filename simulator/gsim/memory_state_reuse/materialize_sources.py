#!/usr/bin/env python3
"""Copy exact historical source inputs into an empty namespace; never build or run a DUT."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath


def relative(value):
    path = PurePosixPath(value)
    if not value or "\\" in value or path.is_absolute() or ".." in path.parts or str(path) != value or value == ".":
        raise ValueError("unsafe relative path: " + value)
    return path


def materialize(source_root, output, manifest):
    source_root = Path(source_root).resolve(strict=True)
    output = Path(output)
    if output.is_symlink() or (output.exists() and (not output.is_dir() or any(output.iterdir()))):
        raise ValueError("destination must be absent or an empty directory")
    output = output.resolve()
    if output == source_root or source_root in output.parents:
        raise ValueError("destination must be outside the source checkout")
    rows = manifest["files"]
    prepared, destinations = [], set()
    for row in rows:
        name = str(relative(row["path"]))
        if name in destinations:
            raise ValueError("duplicate destination: " + name)
        destinations.add(name)
        source = (source_root / str(relative(row["source"]))).resolve(strict=True)
        if not source.is_relative_to(source_root):
            raise ValueError("source path escapes checkout")
        data = source.read_bytes()
        if len(data) != row["bytes"] or hashlib.sha256(data).hexdigest() != row["sha256"]:
            raise ValueError("source hash mismatch: " + row["source"])
        if row["mode"] not in ("100644", "100755"):
            raise ValueError("unsupported file mode")
        prepared.append((name, data, row["mode"]))
    # Finish every input/path check before writing any output.
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("destination became occupied")
    for name, data, mode in prepared:
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(data)
        target.chmod(int(mode[-3:], 8))
    return {"status": "PASS_SOURCE_MATERIALIZATION_ONLY", "files": len(prepared),
            "reused_baseline_inputs": sum(row["reused_baseline_input"] for row in rows),
            "bytes": sum(len(data) for _, data, _ in prepared), "output": str(output),
            "DUT_execution": False, "build_or_compile": False}


def main():
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=here.parents[2])
    parser.add_argument("--manifest", type=Path, default=here / "source-inputs.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(materialize(args.source_root, args.output, json.loads(args.manifest.read_text()))))


if __name__ == "__main__":
    main()
