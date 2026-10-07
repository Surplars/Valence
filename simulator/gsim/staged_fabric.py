#!/usr/bin/env python3
"""One short acceptance batch for the staged two-issue fabric; never invokes Vivado."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
import re
import subprocess
import sys
from run import BUILD, HERE, ROOT, run, setup, test

CHECKS = ("contracts", "fabric", "vm", "board")
COREMARK_SHA256 = "ae05e5be6d30bb8ec111e4734d41407ac31e9de200dd25ac7fef3ee92739e821"


def board_apps(gsim, cxx, output, profile="staged-fabric", clock_hz=50_000_000, baud=115200):
    firmware = output / "firmware"
    run([sys.executable, ROOT / "fpga/firmware/build_coremark.py", "--out", firmware,
         "--iterations", "1", "--clock-hz", "50000000", "--memory", "ddr"],
        log=output / "coremark-build.log")
    run([sys.executable, ROOT / "fpga/firmware/build_ddr_bench.py", "--out", firmware],
        log=output / "ddr-build.log")
    digest = hashlib.sha256((firmware / "coremark_board.bin").read_bytes()).hexdigest()
    if digest != COREMARK_SHA256:
        raise RuntimeError("CoreMark binary differs from the saved same-binary baseline")
    model = output / "board-model"
    model.mkdir(exist_ok=True)
    run(["mill", "-i", "IonSoC.test.runMain", "ooo.BoardSocGsimMain", model,
         "ddr", str(clock_hz), profile, str(baud), "2", "2", "1"],
        log=model / "elaborate.log")
    # Only generated translation units, never input RTL or firmware.
    for old in model.glob("BoardSocGsim[0-9]*.cpp"):
        old.unlink()
    run([gsim, "--threads=1", f"--dir={model}", model / "BoardSocGsim.fir"],
        log=model / "generate.log")
    sources = sorted(model.glob("BoardSocGsim[0-9]*.cpp"))
    if not sources:
        raise RuntimeError("GSIM did not generate the board model")
    flags = ["-std=c++20", "-O1", "-g", "-fsanitize=address,undefined",
             "-fno-sanitize-recover=all", "-I" + str(model)]
    jobs = min(len(sources), max(1, min(8, int(os.environ.get("GSIM_BUILD_JOBS", "4")))))

    def compile_unit(source):
        obj = source.with_suffix(".o")
        run([cxx, *flags, "-c", source, "-o", obj], log=source.with_suffix(".compile.log"))
        return obj

    with ThreadPoolExecutor(max_workers=jobs) as workers:
        objects = list(workers.map(compile_unit, sources))
    defines = ["-DUART_DIVISOR=1", f"-DBOARD_CPU_HZ={clock_hz}", f"-DBOARD_UART_BAUD={baud}",
               "-DUART_EXTRA_STOP_BITS=0", "-DDDR_MODEL=1", "-DAPP_TIMEBASE_HZ=50000000"]
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}
    for driver, image in (("board_coremark", "coremark_board"), ("ddr_bench_app", "ddr_bench")):
        binary = model / driver
        run([cxx, *flags, *defines, *objects, HERE / f"harness/{driver}.cpp", "-ldl", "-o", binary],
            log=model / f"{driver}.compile.log")
        run([binary, firmware / f"{image}.bin"], env=env, log=model / f"{driver}.log", timeout=600)
        print((model / f"{driver}.log").read_text(), end="", flush=True)
    coremark = (model / "board_coremark.log").read_text()
    ddr = (model / "ddr_bench_app.log").read_text()
    ticks = re.search(r"GSIM compact board CoreMark: PASS ticks=(\d+)", coremark)
    ddr_ticks = re.findall(r"^(?:READ\(cold-start\)|WRITE\(\+flush\)|COPY\(payload,\+flush\)|CHASE working_set).*?ticks=(\d+)",
                           ddr, re.MULTILINE)
    if not ticks or len(ddr_ticks) != 4 or "GSIM DDR benchmark application: PASS" not in ddr:
        raise RuntimeError("short board application evidence is incomplete")
    return {"coremark_single_iteration_ticks": int(ticks[1]), "coremark_sha256": digest,
            "ddr_4k_read_write_copy_chase_ticks": list(map(int, ddr_ticks)),
            "generated_board_models": 1, "not_a_coremark_score_or_fpga_bandwidth": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default="20261001")
    parser.add_argument("--only", choices=CHECKS, nargs="+", default=list(CHECKS),
                        help="failure diagnosis only; a subset is not full batch acceptance")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.tag):
        parser.error("tag must contain only letters, digits, underscores or hyphens")
    name = f"staged-fabric-{args.tag}"
    output = BUILD / name
    output.mkdir(parents=True, exist_ok=True)
    report = {"profile": "staged-fabric", "issue_width": 2, "checks_requested": args.only,
              "status": "running", "synthesis_run": False, "routed_timing_verified": False}
    evidence = output / "results.json"
    evidence.write_text(json.dumps(report, indent=2) + "\n")
    try:
        if "contracts" in args.only:
            run(["mill", "-i", "IonSoC.test.testOnly", "ooo.StagedFabricSpec", "ooo.OooParamsSpec"],
                log=output / "contracts.log")
            print((output / "contracts.log").read_text(), end="", flush=True)
        gsim, cxx = setup(False)
        if "fabric" in args.only:
            fabric = test(gsim, cxx, name + "/fabric", "ooo.StagedFabricGsimMain",
                          "StagedFabricGsim", "staged_fabric.cpp")
            env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}
            rejected = subprocess.run([fabric / "run", "--inject-mismatch"], capture_output=True,
                                      text=True, env=env, timeout=60)
            (fabric / "negative.log").write_text(rejected.stdout + rejected.stderr)
            if rejected.returncode != 1 or "fabric response mismatch" not in rejected.stderr:
                raise RuntimeError("independent fabric oracle did not reject corruption")
            print("GSIM staged fabric mismatch injection: PASS", flush=True)
            for registered in (False, True):
                arbiter = test(gsim, cxx, name + ("/arbiter-registered" if registered else "/arbiter-flow"),
                     "ooo.SharedDataGsimMain", "SharedDataGsim", "shared_data.cpp",
                     parameters=("registered-owners",) if registered else (),
                     defines={"REGISTERED_PHYSICAL_OWNERS": int(registered)})
                rejected = subprocess.run([arbiter / "run", "--inject-mismatch"], capture_output=True,
                                          text=True, env=env, timeout=60)
                (arbiter / "negative.log").write_text(rejected.stdout + rejected.stderr)
                if rejected.returncode != 1 or "response data mismatch" not in rejected.stderr:
                    raise RuntimeError("independent arbiter oracle did not reject corruption")
        if "vm" in args.only:
            payload = output / "vm-data"
            run(["riscv64-unknown-elf-gcc", "-march=rv64ia_zicsr", "-mabi=lp64", "-mno-relax",
                 "-nostdlib", "-nostartfiles", "-Wl,--no-relax", "-T", HERE / "payloads/machine-boot.ld",
                 HERE / "payloads/vm-data.S", "-o", payload.with_suffix(".elf")],
                log=output / "vm-build.log")
            run(["riscv64-unknown-elf-objcopy", "-O", "binary", "--only-section=.text",
                 payload.with_suffix(".elf"), payload.with_suffix(".bin")])
            test(gsim, cxx, name + "/vm", "ooo.VmDataPlatformGsimMain", "VmDataPlatformGsim",
                 "vm_data_platform.cpp", parameters=("coherent", "compact", "buffered-response",
                     "registered-physical-owners", "registered-retirement", "registered-load-replay",
                     "early-recovery-issue-block", "staged-fabric"),
                 runtime_args=(payload.with_suffix(".bin"), "--coherent"), defines={})
        if "board" in args.only:
            report.update(board_apps(gsim, cxx, output))
        report["status"] = "passed" if set(args.only) == set(CHECKS) else "partial-pass"
    except (RuntimeError, subprocess.SubprocessError, OSError):
        report["status"] = "failed"
        raise
    finally:
        evidence.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Short staged-fabric batch: {report['status']}; evidence: {evidence}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.SubprocessError, OSError) as error:
        print(f"GSIM staged fabric batch: {error}", file=sys.stderr)
        sys.exit(1)
