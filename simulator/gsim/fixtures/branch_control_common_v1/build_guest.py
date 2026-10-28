#!/usr/bin/env python3
"""Reproduce one sealed branch ELF; no install, DUT generation or CPU execution."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def invocation_path(argument):
    # Do NOT resolve the ld.lld symlink to the generic lld executable: argv[0]
    # selects the linker flavor. Hashing bytes may follow links; invocation may not.
    found = shutil.which(argument) if os.sep not in argument else argument
    require(found is not None, "tool not found: " + argument)
    return Path(os.path.abspath(found))


def checked_hash(path, expected, label):
    require(Path(path).is_file() and sha(path) == expected, label + " SHA256 mismatch")


def section_bytes(path, name, expected_type):
    data = Path(path).read_bytes()
    require(len(data) >= 64, "short ELF/object")
    h = struct.unpack_from("<16sHHIQQQIHHHHHH", data)
    require(h[0][:7] == b"\x7fELF\x02\x01\x01" and h[1] == expected_type and h[2] == 243,
            "incorrect ELF/object ABI/type")
    require(h[11] == 64 and 0 < h[12] <= 256 and h[13] < h[12] and h[6] + h[12] * 64 <= len(data), "section table bounds")
    rows = [struct.unpack_from("<IIQQQQIIQQ", data, h[6] + i * 64) for i in range(h[12])]
    string_row = rows[h[13]]
    require(string_row[4] + string_row[5] <= len(data), "section string bounds")
    strings = data[string_row[4]:string_row[4] + string_row[5]]
    result = None
    for row in rows:
        require(row[0] < len(strings), "section name bounds")
        end = strings.find(b"\0", row[0])
        require(end >= 0, "section name termination")
        if strings[row[0]:end].decode() == name:
            require(result is None and row[4] + row[5] <= len(data), "duplicate/truncated section")
            result = data[row[4]:row[4] + row[5]]
        require(row[1] not in (4, 9) or row[5] == 0, "unexpected unresolved relocation")
    require(result is not None, "missing section " + name)
    return result


def check_body(original, linked):
    require(len(original) < len(linked) and linked[:len(original)] == original,
            "original source-body bytes changed")


def load_source_reference():
    spec = importlib.util.spec_from_file_location("branch_portable_source_reference", HERE / "source-reference/source_reference.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", required=True)
    parser.add_argument("--linker", required=True)
    parser.add_argument("--nm", default="nm")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    out = args.out.absolute()
    require(not out.exists() or not any(out.iterdir()), "--out must be fresh/empty; prior evidence is never overwritten")
    out.mkdir(parents=True, exist_ok=True)
    pins = json.loads((HERE / "pinned-inputs.json").read_text())
    receipt = {"status": "RUNNING", "scope": "guest assembly/link and software container/source checks only",
               "CPU_executed": False, "DUT_generated": False, "installed_or_downloaded": False, "commands": []}
    def run(label, command):
        command = list(map(str, command))
        result = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=120)
        (out / (label + ".stdout")).write_bytes(result.stdout)
        (out / (label + ".stderr")).write_bytes(result.stderr)
        receipt["commands"].append({"label": label, "argv": command, "exit_code": result.returncode})
        require(result.returncode == 0, label + " failed; inspect retained stderr")
        return result.stdout
    try:
        for relative, expected in pins["fixture_files"].items():
            checked_hash(HERE / relative, expected, "fixture " + relative)
        for relative, expected in pins["repository_inputs"].items():
            checked_hash(ROOT / relative, expected, "repository " + relative)
        tools = {"compiler": invocation_path(args.cxx), "linker": invocation_path(args.linker), "nm": invocation_path(args.nm)}
        require(tools["linker"].name in ("ld.lld", "ld.lld-19"), "invoke ELF linker as ld.lld/ld.lld-19, never resolved generic lld")
        receipt["tools"] = {}
        for name, path in tools.items():
            pin = pins["tools"][name]
            checked_hash(path, pin["sha256"], name)
            version = run(name + "-version", [path, "--version"]).decode().splitlines()[0]
            require(version == pin["version"], name + " version mismatch")
            receipt["tools"][name] = {"path": str(path), "sha256": sha(path), "version": version}
        flags = ["--target=riscv64-unknown-elf", "-march=rv64i", "-mabi=lp64", "-mno-relax", "-c"]
        source = ROOT / pins["guest"]["original_source"]
        original = out / "original-body.o"
        wrapped = out / "branch-common.o"
        elf, symbols = out / "branch-common.elf", out / "branch-common.symbols"
        run("assemble-original", [tools["compiler"], *flags, source, "-o", original])
        run("assemble-wrapper", [tools["compiler"], *flags, "-I" + str(source.parent), HERE / "guest/branch-common.S", "-o", wrapped])
        run("link", [tools["linker"], "-m", "elf64lriscv", "--no-relax", "-T", HERE / "guest/branch-common.ld", wrapped, "-o", elf])
        symbols.write_bytes(run("symbols", [tools["nm"], "-n", elf]))
        body = section_bytes(original, ".text", 1)
        linked = section_bytes(elf, ".text", 2)
        check_body(body, linked)
        reference = load_source_reference()
        program = reference.SourceProgram(source.read_text())
        container_check = reference.inspect_elf(elf, program)
        require(program.original_end - reference.RAM_BASE == len(body), "original body extent changed")
        checked_hash(elf, pins["guest"]["elf_sha256"], "sealed guest ELF")
        checked_hash(symbols, pins["guest"]["symbols_sha256"], "sealed guest symbol text")
        receipt.update(status="PASS_EXACT_PORTABLE_GUEST_REPRODUCTION", original_body_bytes=len(body),
                       text_bytes=len(linked), elf_sha256=sha(elf), symbols_sha256=sha(symbols),
                       text_sha256=hashlib.sha256(linked).hexdigest(), independent_source_encoding=container_check,
                       pins_sha256=sha(HERE / "pinned-inputs.json"))
    except Exception as error:
        receipt.update(status="FAILED_CLOSED", error=str(error))
        raise
    finally:
        (out / "guest-reproduction.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({key: receipt[key] for key in ("status", "elf_sha256", "symbols_sha256", "original_body_bytes")}))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("BRANCH_GUEST_REPRODUCTION_FAIL " + str(error), file=sys.stderr)
        sys.exit(1)
