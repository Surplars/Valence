#!/usr/bin/env python3
"""Bounded production-board RV64GC smoke, not Linux or FPGA qualification."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import run as common

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def reusable_model(path, current, profile="staged-throughput"):
    """Only firmware/runner may differ; never reuse across DUT/harness changes."""
    previous = json.loads(path.read_text())
    if previous.get("timing_profile", "staged-throughput") != profile:
        raise RuntimeError("Reusable model timing profile differs")
    if (previous["status"] != "PASS_BOARD_FUNCTIONAL_SMOKE" or
            previous["isa"] != "rv64imafdc_zicsr_zifencei" or
            previous["issue_width"] != 2 or previous["clock_profile_hz"] != 100000000 or
            previous["uart_baud"] != 460800):
        raise RuntimeError("Reusable model has a different profile or did not pass")
    runtime = {"fpga/firmware/rv64gc_smoke.S", "simulator/gsim/rv64gc_board.py"}
    if set(previous["source_sha256"]) != set(current):
        raise RuntimeError("Hardware input set changed; generate a fresh model")
    for name, sha in previous["source_sha256"].items():
        if name not in runtime and current[name] != sha:
            raise RuntimeError("DUT/harness input changed; cannot reuse: " + name)
    for mapping in (previous["files"], previous["gsim_models_sha256"]):
        for name, sha in mapping.items():
            if name not in runtime and digest(common.ROOT / name) != sha:
                raise RuntimeError("Reusable binary/model artifact changed: " + name)
    fir = [common.ROOT / name for name in previous["files"] if Path(name).name == "BoardSocGsim.fir"]
    if len(fir) != 1:
        raise RuntimeError("Expected one reusable board model")
    return fir[0].parent, {"receipt":str(path), "receipt_sha256":digest(path),
                          "allowed_runtime_changes":sorted(runtime)}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--profile", choices=("staged-throughput", "staged-gmac-ready", "staged-ethernet", "staged-fetch-feedback", "staged-fetch-turnover"), default="staged-throughput")
    parser.add_argument("--reuse-model", type=Path,
                        help="previous passed receipt; refuses any DUT/harness/model drift")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.tag):
        parser.error("Unsafe tag")
    output = common.BUILD / ("rv64gc-board-" + args.tag)
    if output.exists():
        parser.error("Output exists; choose a fresh tag")
    output.mkdir(parents=True)
    source = common.ROOT / "fpga/firmware"
    inputs = [p for base in ("src/main/scala", "third_party/berkeley-hardfloat/src/main/scala")
              for p in sorted((common.ROOT / base).rglob("*.scala"))]
    inputs += [common.ROOT / "src/test/scala/ooo/BoardSocGsimMain.scala",
               common.HERE / "harness/board_boot.cpp", common.HERE / "harness/rv64gc_board.cpp",
               common.HERE / "rv64gc_board.py", source / "rv64gc_smoke.S", source / "sample_app.ld",
               common.ROOT / "build.mill", common.HERE / "run.py"]
    before = {str(p.relative_to(common.ROOT)):digest(p) for p in inputs}
    (output / "inputs.json").write_text(json.dumps(before, indent=2)+"\n")
    elf, image = output / "rv64gc_smoke.elf", output / "rv64gc_smoke.bin"
    common.run(["riscv64-unknown-elf-gcc", "-march=rv64gc", "-mabi=lp64d",
        "-mcmodel=medany", "-mno-relax", "-nostdlib", "-nostartfiles",
        "-Wl,--no-relax", "-Wl,--build-id=none", "-Wl,--defsym=BOARD_RAM_BYTES=536870912",
        "-T" + str(source / "sample_app.ld"), source / "rv64gc_smoke.S", "-o", elf],
        log=output / "firmware-build.log")
    common.run(["riscv64-unknown-elf-objcopy", "-O", "binary", elf, image])
    reused = None
    positive_log = output / "test.log"
    if args.reuse_model:
        directory, reused = reusable_model(args.reuse_model.resolve(), before, args.profile)
        common.run([directory / "run", image],
            env={**os.environ, "ASAN_OPTIONS":"detect_leaks=0"}, log=positive_log, timeout=120)
    else:
        gsim, cxx = common.setup(False)
        directory = common.test(gsim, cxx, "rv64gc-board-" + args.tag + "-model",
            "ooo.BoardSocGsimMain", "BoardSocGsim", "rv64gc_board.cpp",
            parameters=("ddr", "100000000", args.profile, "460800", "2", "2", "1", "rv64gc"),
            runtime_args=(image,), defines={"UART_DIVISOR":1, "BOARD_CPU_HZ":100000000,
            "BOARD_UART_BAUD":460800, "UART_EXTRA_STOP_BITS":0, "DDR_MODEL":1},
            sanitizer=True, timeout=120)
        positive_log.write_text((directory / "test.log").read_text())
    negative = subprocess.run([str(directory / "run"), str(image), "--inject-mismatch"],
        env={**os.environ, "ASAN_OPTIONS":"detect_leaks=0"},
        capture_output=True, text=True, timeout=120)
    (output / "negative.log").write_text(negative.stdout + negative.stderr)
    if negative.returncode != 1 or "firmware independent anchor/context failure" not in negative.stderr:
        raise RuntimeError("Board negative control did not reject the intended wrong ISA anchor")
    if before != {str(p.relative_to(common.ROOT)):digest(p) for p in inputs}:
        raise RuntimeError("Sources changed during board batch; receipt withheld")
    receipt = {"status":"PASS_BOARD_FUNCTIONAL_SMOKE", "isa":"rv64imafdc_zicsr_zifencei",
        "issue_width":2, "clock_profile_hz":100000000, "uart_baud":460800, "timing_profile":args.profile,
        "source_sha256":before, "negative_control":{"exit":1,"reason":negative.stderr.strip()},
        "log":positive_log.read_text(), "reused_model":reused,
        "fp_virtual_context":{"mode":"Sv39", "context_va":"0x40220000", "context_pa":"0x80220000",
                              "root_pa":"0x80210000", "integer_identity_view_checked":True},
        "files":{str(p.relative_to(common.ROOT)):digest(p) for p in
            (source / "rv64gc_smoke.S", elf, image,
             common.HERE / "harness/rv64gc_board.cpp", common.HERE / "rv64gc_board.py",
             directory / "BoardSocGsim.fir", directory / "run")},
        "gsim_models_sha256":{str(p.relative_to(common.ROOT)):digest(p) for p in sorted(directory.iterdir())
                              if p.suffix in (".cpp", ".h")},
        "limitations":["No FPGA timing/CDC qualification", "No Linux floating-point scheduling test",
                       "Not exhaustive ISA compliance; numeric independent oracle is in floating_point_full.py"]}
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2)+"\n")
    print(receipt["log"], end="")

if __name__ == "__main__":
    main()
