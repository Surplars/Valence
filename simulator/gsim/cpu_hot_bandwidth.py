#!/usr/bin/env python3
"""Bounded bare-metal physical all-hit measurements using a frozen GSIM .o only.

Never elaborates, generates, or compiles a hardware model. Receipt equivalence is
reported separately from source qualification; current HEAD is not requalified.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PUBLIC_BASELINE = "8e78b5b"
PUBLIC_BASELINE_TREE = "c82f46861725be23b8c4f68630e341b72281c05c"

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)

def inspect_models(directory, baseline):
    candidates = []
    baseline_sources = [p for p in git("ls-tree", "-r", "--name-only", baseline, "src").decode().splitlines() if p.endswith(".scala")]
    for path in sorted(directory.glob("fpga-next-board-selected-*/receipt.json")):
        receipt = json.loads(path.read_text())
        differences = []
        for name, expected in receipt["inputs"].items():
            if not name.startswith(("src/main/", "src/test/")):
                continue
            try:
                contents = git("show", baseline + ":" + name)
                actual = hashlib.sha256(contents).hexdigest()
            except subprocess.CalledProcessError:
                actual = None
            if actual != expected:
                differences.append({"path": name, "model_input_sha256": expected, "baseline_sha256": actual})
        added = [{"path":name, "baseline_sha256":hashlib.sha256(git("show",baseline+":"+name)).hexdigest()}
            for name in baseline_sources if name not in receipt["inputs"]]
        candidates.append({"added_baseline_sources":added,"path": str(path.parent), "git_head": receipt["git_head"],
            "receipt_sha256": sha(path), "plan": receipt["plan"], "differences": differences})
    if not candidates:
        raise RuntimeError("no selected board source receipts found")
    # Minimize source delta, then prefer no additional virtual-precheck opt-in.
    return sorted(candidates, key=lambda c: (len(c["differences"]),
        "--virtual-ram-load-precheck" in c["plan"]["parameters"], c["path"]))

def parse(text):
    result = {"performance": {}, "pipeline": {}, "distributions": {}, "buckets": {}}
    for line in text.splitlines():
        if not line.startswith(("HOT_", "BOARD_IPC ", "DATA_PATH_LEDGER ")):
            continue
        kind, *fields = line.split()
        values = {}
        for field in fields:
            if "=" not in field:
                continue
            name, value = field.split("=", 1)
            try:
                value = float(value) if "." in value else int(value)
            except ValueError:
                pass
            values[name] = value
        if kind == "HOT_RESULT": result["result"] = values
        elif kind == "BOARD_IPC": result["performance"][values.pop("name")] = values
        elif kind == "HOT_PIPELINE": result["pipeline"][values.pop("name")] = values
        elif kind == "HOT_DISTRIBUTION": result["distributions"][values.pop("name")] = values
        elif kind == "HOT_BUCKET": result["buckets"].setdefault(values["name"], {})[values["category"]] = values["cycles"]
        elif kind == "DATA_PATH_LEDGER": result["ownership"] = values
        elif kind == "HOT_PASS": result["pass"] = values
    if "pass" not in result or "result" not in result:
        raise RuntimeError("missing terminal hot result")
    return result

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model-root", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--baseline", default=PUBLIC_BASELINE,
                    help="public baseline commit; local archive commits require an explicit override")
    ap.add_argument("--baseline-tree", default=PUBLIC_BASELINE_TREE,
                    help="exact expected tree; override together with --baseline for a local archive")
    ap.add_argument("--repetitions", type=int, default=4)
    ap.add_argument("--cases", nargs="+", default=[f"{op}-{size}" for size in (4096, 8192) for op in ("read", "write", "copy")])
    args = ap.parse_args()
    if args.repetitions < 2 or args.repetitions > 8:
        ap.error("use 2..8 repetitions for bounded hot replay")
    for case in args.cases:
        if not re.fullmatch(r"(read|write|copy)-(4096|8192)", case):
            ap.error("invalid case " + case)
    out = args.out.resolve()
    if out.exists():
        ap.error("choose a fresh output directory to preserve previous evidence")
    out.mkdir(parents=True)
    baseline = git("rev-parse", args.baseline + "^{commit}").decode().strip()
    baseline_tree = git("rev-parse", baseline + "^{tree}").decode().strip()
    if baseline_tree != args.baseline_tree:
        ap.error("baseline tree mismatch; use an explicit --baseline-tree only for a verified local archive")
    candidates = inspect_models(args.model_root.resolve(), baseline)
    selected = candidates[0]
    checkpoint = Path(selected["path"])
    old_receipt = json.loads((checkpoint / "receipt.json").read_text())
    model = checkpoint / "model"
    board_source = git("show", selected["git_head"]+":src/main/scala/core/ooo/BoardSocTop.scala")
    if hashlib.sha256(board_source).hexdigest()!=old_receipt["inputs"]["src/main/scala/core/ooo/BoardSocTop.scala"]:
        raise RuntimeError("board geometry source differs from frozen model receipt")
    sb_entries = re.findall(r"storeBufferEntries\s*=\s*(\d+)",board_source.decode())
    if sb_entries != ["2"]:
        raise RuntimeError("unexpected selected-profile StoreBuffer geometry")
    hashes = {}
    for name in ("model/BoardSocGsim.h", "model/BoardSocGsim0.o"):
        hashes[name] = sha(checkpoint / name)
        if old_receipt["artifacts"].get(name) != hashes[name]:
            raise RuntimeError("frozen model hash does not match source receipt: " + name)
    inputs = {str(p.relative_to(ROOT)): sha(p) for p in [Path(__file__),
        HERE / "harness/cpu_hot_bandwidth.cpp", HERE / "harness/cpu_hot_bandwidth.h", HERE / "payloads/cpu_hot_bandwidth.S", HERE / "payloads/cpu_hot_bandwidth.ld"]}
    for name in ("board_boot.cpp", "board_ddr_benchmark.h", "board_ddr_multiid.h", "backend_observer.h", "backend_ownership_ledger.h", "data_path_sample.h", "data_path_ownership_ledger.h", "performance_observer.h"):
        p = HERE / "harness" / name
        inputs[str(p.relative_to(ROOT))] = sha(p)
    state = {"schema": "valence-cpu-hot-bandwidth-reuse-v1", "status": "RUNNING", "baseline_commit": baseline, "baseline_tree": baseline_tree,
        "reuse_qualified": True, "current_source_model_qualified": False, "generated_models": 0,
        "model_objects_compiled": 0, "selected_model": selected, "candidate_models": candidates,
        "geometry": {"store_buffer_entries":2, "lsu_slots":2}, "model_artifacts": hashes, "inputs": inputs, "commands": [], "cases": {},
        "working_tree_status": git("status", "--short").decode(),
        "limitations": ["Frozen older board checkpoint; source-different current HEAD is not qualified.",
            "Physical-address means bare M-mode addressing, not a physical FPGA measurement.",
            "100 MHz conversion of simulated cycles, not routed frequency or measured board bandwidth.",
            "Fixed multi-ID DDR host timing; no Linux, Verilator, Vivado, board access, or full-suite run.",
            "Negative tests mutate host evidence/expectations only; they are oracle sensitivity checks, not DUT fault injection."]}
    def save():
        (out / "receipt.json").write_text(json.dumps(state, indent=2) + "\n")
    save()
    def command(name, cmd, timeout=180):
        log = out / (name + ".log")
        start = time.monotonic()
        print("+", " ".join(map(str, cmd)), flush=True)
        with log.open("w") as stream:
            run = subprocess.run(list(map(str, cmd)), cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                timeout=timeout, env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
        state["commands"].append({"command": list(map(str, cmd)), "exit": run.returncode,
            "seconds": time.monotonic()-start, "log": log.name, "log_sha256": sha(log)})
        save()
        if run.returncode:
            raise RuntimeError(log.read_text()[-6000:])
        return log.read_text()
    try:
        cc = shutil.which("riscv64-unknown-elf-gcc")
        objcopy = shutil.which("riscv64-unknown-elf-objcopy")
        nm = shutil.which("riscv64-unknown-elf-nm")
        cxx = shutil.which(os.environ.get("GSIM_CXX", "clang++-19"))
        if not all((cc, objcopy, nm, cxx)):
            raise RuntimeError("existing RISC-V and Clang 19 toolchain required; this runner never installs tools")
        state["toolchain"] = {"cc": subprocess.check_output([cc, "--version"], text=True).splitlines()[0],
            "cxx": subprocess.check_output([cxx, "--version"], text=True).splitlines()[0]}
        for case in args.cases:
            op, size = case.split("-")
            mode = ("read", "write", "copy").index(op)
            directory = out / case
            directory.mkdir()
            defines = ["-DHOT_SB_ENTRIES=2", f"-DHOT_OP={mode}", f"-DHOT_BYTES={size}", f"-DHOT_REPS={args.repetitions}"]
            command(case+"-guest", [cc, "-march=rv64im_zicsr_zifencei", "-mabi=lp64", "-mno-relax", "-nostdlib", "-nostartfiles",
                "-Wl,--no-relax", "-Wl,-T,"+str(HERE/"payloads/cpu_hot_bandwidth.ld"), *defines,
                HERE/"payloads/cpu_hot_bandwidth.S", "-o", directory/"guest.elf"])
            command(case+"-binary", [objcopy, "-O", "binary", directory/"guest.elf", directory/"guest.bin"])
            symbols = {}
            for line in subprocess.check_output([nm, "-n", directory/"guest.elf"], text=True).splitlines():
                fields = line.split()
                if len(fields)==3 and fields[2].startswith("hot_"):
                    symbols[fields[2]] = int(fields[0],16)
            (directory/"cpu_hot_bandwidth_symbols.h").write_text("\n".join(f"#define {name.upper()} {value}ULL" for name,value in symbols.items())+"\n")
            flags = ["-std=c++20", "-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                "-DUART_DIVISOR=1", "-DBOARD_CPU_HZ=100000000", "-DBOARD_UART_BAUD=460800", "-DUART_EXTRA_STOP_BITS=0",
                "-DDDR_MODEL=1", "-DBOARD_DDR_BYTES=2147483648ULL", "-DDDR_MULTI_ID_MODEL=1", "-DDDR_BENCHMARK_MODEL=1",
                "-DDDR_READ_CREDITS=8", "-DDDR_READ_LATENCY=32", "-DDDR_READ_BEAT_GAP=1", "-DBOARD_CYCLE_LIMIT=300000ULL"]
            command(case+"-observer", [cxx, *flags, *defines, "-I"+str(model), "-I"+str(directory),
                HERE/"harness/cpu_hot_bandwidth.cpp", model/"BoardSocGsim0.o", "-ldl", "-o", directory/"run"])
            text = command(case+"-run", [directory/"run", directory/"guest.bin"])
            parsed = parse(text)
            parsed["symbols"] = symbols
            parsed["artifacts"] = {p.name:sha(p) for p in directory.iterdir() if p.is_file()}
            state["cases"][case] = parsed
            save()
            print("PASS", case, json.dumps(parsed["result"]), flush=True)
        # Verify source observer and frozen generated artifacts remained unchanged.
        for name, expected in inputs.items():
            if sha(ROOT/name)!=expected: raise RuntimeError("observer source changed during replay: "+name)
        for name, expected in hashes.items():
            if sha(checkpoint/name)!=expected: raise RuntimeError("reused model changed during replay")
        state["status"]="PASS_CPU_HOT_BANDWIDTH_REUSE"
    except Exception as error:
        state["status"]="FAIL";state["error"]=str(error);save();raise
    save()
    print("PASS receipt="+str(out/"receipt.json"))

if __name__ == "__main__":
    main()
