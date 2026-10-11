"""Small fail-closed bindings shared by the public bound-store replay commands."""
import hashlib
import json
import os
import shlex
import subprocess
from pathlib import Path

if not __debug__:
    raise SystemExit("Replay gates require Python assertions; do not use python -O")


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1048576), b""):
            h.update(block)
    return h.hexdigest()


def add_paths(parser, root):
    parser.add_argument("--source-root", type=Path, default=root)
    parser.add_argument("--toolchain-root", type=Path,
                        help="Explicit root with bin/mill, gsim-src/build/gsim/gsim and sysroot/usr/bin/clang++-19")
    for name in ("mill", "gsim", "cxx"):
        parser.add_argument("--" + name, type=Path, help="Explicit executable path; overrides --toolchain-root")
    parser.add_argument("--activate", type=Path, help="Optional explicitly bound tool environment script")
    parser.add_argument("--preflight-only", action="store_true", help="Validate inputs without creating output or running tools")


def tool_paths(args, parser):
    defaults = {"mill": "bin/mill", "gsim": "gsim-src/build/gsim/gsim", "cxx": "sysroot/usr/bin/clang++-19"}
    result = {}
    for name, relative in defaults.items():
        path = getattr(args, name) or (args.toolchain_root / relative if args.toolchain_root else None)
        if path is None:
            parser.error("missing tool: supply --" + name + " PATH or --toolchain-root PATH")
        path = path.absolute()
        if not path.is_file() or not os.access(path, os.X_OK):
            parser.error("missing executable for --" + name + ": " + str(path))
        result[name] = path
    if args.activate:
        if not args.activate.is_file():
            parser.error("missing --activate script: " + str(args.activate))
        result["activate"] = args.activate.resolve()
    return result


def command_args(argv, paths):
    argv = list(map(str, argv))
    if "activate" in paths:
        return ["/bin/bash", "--noprofile", "--norc", "-c",
                'source "$1"; shift; exec "$@"', "bound-store-replay", str(paths["activate"]), *argv]
    return argv


def model_artifacts(root, models):
    return {str(p.relative_to(root)): sha(p) for model in models
            for p in sorted((root / model).rglob("*")) if p.is_file()}


def tool_binding(paths):
    return {name: {"path": str(path), "sha256": sha(path)} for name, path in sorted(paths.items())}


def check_tools(binding):
    for name, item in binding.items():
        assert sha(item["path"]) == item["sha256"], "tool drift: " + name


def source_inputs(root, extra=()):
    # Explicit build closure, including untracked publication files; no git HEAD grant.
    root = Path(root).resolve()
    files = set(root.glob("src/**/*.scala")) | set(root.glob("third_party/**/*.scala"))
    for name in ("build.mill", ".mill-version", ".mill-jvm-opts"):
        if not (root / name).is_file():
            raise ValueError("missing source input: " + str(root / name))
        files.add(root / name)
    files.update(Path(p) for p in extra if "__pycache__" not in Path(p).parts)
    files.add(Path(__file__).resolve())
    return {str(p.resolve().relative_to(root)): sha(p) for p in sorted(files) if p.is_file()}


def preflight(args, sources, tools):
    if args.preflight_only:
        print(json.dumps({"status": "PREFLIGHT_ONLY_NO_EXECUTION", "source_inputs": sources,
                          "tools": tool_binding(tools), "qualification_inherited": False}, indent=2))
        return True
    return False


def verified_receipt(directory, expected_sha256):
    path = Path(directory) / "receipt.json"
    if not expected_sha256:
        raise ValueError("external reuse needs --reuse-receipt-sha256 (or --paired-receipt-sha256) and a fresh portable receipt")
    if sha(path) != expected_sha256:
        raise ValueError("external receipt digest mismatch: " + str(path))
    value = json.loads(path.read_text())
    if value.get("schema") != "bound-store-portable-component-v1":
        raise ValueError("historical receipt is evidence only; build fresh models or prepare a separately reviewed model-input bridge")
    if value.get("status") != "PASS_COMPONENT_ONLY":
        raise ValueError("reuse requires a complete successful component receipt")
    return value


def verify_artifacts(model, mapping):
    assert mapping, "empty model artifact binding"
    for name, digest in mapping.items():
        relative = Path(name)
        assert not relative.is_absolute() and ".." not in relative.parts, "unsafe artifact path"
        assert sha(Path(model) / relative) == digest, "model artifact drift: " + name


def verify_model_inputs(model, mapping):
    """External models may not smuggle additional headers, units or objects."""
    verify_artifacts(model, mapping)
    for path in Path(model).rglob("*"):
        if path.is_file() and (path.suffix in (".fir", ".h", ".cpp", ".o", ".d") or path.name == "actual-parameters.json"):
            name = str(path.relative_to(model))
            assert name in mapping, "unbound model input: " + name


def source_revision(root):
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, text=True, capture_output=True)
    return result.stdout.strip() if result.returncode == 0 else None


def record_dependencies(path, cwd, binding):
    names = shlex.split(Path(path).read_text().replace("\\\n", " ").split(":", 1)[1])
    assert names, "empty compiler dependency closure"
    for name in names:
        resolved = (Path(cwd) / name).resolve()
        digest = sha(resolved)
        assert binding.setdefault(str(resolved), digest) == digest, "compiler dependency drift: " + str(resolved)


def check_dependencies(binding):
    assert binding, "reuse needs captured compiler dependencies; build fresh models"
    for name, expected in binding.items():
        assert sha(name) == expected, "compiler dependency drift: " + name
