#!/usr/bin/env python3
"""Three related rename/PRF/frontend changes, one short affected batch; no Vivado."""
import argparse
import json
import re
import subprocess
import sys
from run import BUILD, HERE, run, setup, test
from control_stage import core_payloads, negative, reference
from staged_fabric import board_apps

CHECKS = ("contracts", "payload", "ledger", "prediction", "core", "vm", "board")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default="20261001")
    parser.add_argument("--only", nargs="+", choices=CHECKS, default=list(CHECKS))
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.tag):
        parser.error("invalid tag")
    name = f"rename-stage-{args.tag}"
    output = BUILD / name
    output.mkdir(parents=True, exist_ok=True)
    report = {"profile": "staged-rename", "issue_width": 2, "status": "running",
              "checks_requested": args.only, "synthesis_run": False, "routed_timing_verified": False}
    try:
        if "contracts" in args.only:
            run(["mill", "-i", "IonSoC.test.testOnly", "ooo.RenameTimingSpec", "ooo.ExecuteTimingSpec",
                 "ooo.OooParamsSpec"], log=output / "contracts.log")
            print((output / "contracts.log").read_text(), end="", flush=True)
        gsim, cxx = setup(False)
        if "payload" in args.only:
            pure = test(gsim, cxx, name + "/payload", "ooo.RenameTimingGsimMain", "RenameTimingGsim",
                        "rename_timing.cpp", defines={})
            negative(pure / "run", (), "rename payload/ready oracle mismatch", pure / "negative.log")
        if "ledger" in args.only:
            test(gsim, cxx, name + "/ledger", "ooo.RenameRobGsimMain", "RenameRobGsim", "backend.cpp",
                 parameters=("16", "48", "8", "4", "early-destinations"),
                 defines={"ROB_ENTRIES": 16, "PHYSICAL_REGS": 48, "TAG_BITS": 8, "RECOVERY_WIDTH": 4})
        if "prediction" in args.only:
            packet = test(gsim, cxx, name + "/prediction", "ooo.RenamePacketCoreGsimMain", "IntegerCoreGsim",
                          "rename_packet.cpp", defines={})
            negative(packet / "run", (), "prediction packet architectural oracle mismatch", packet / "negative.log")
        if "core" in args.only:
            ref = reference()
            payloads = core_payloads(output)
            core = test(gsim, cxx, name + "/core", "ooo.IntegerCoreGsimMain", "IntegerCoreGsim", "core.cpp",
                        parameters=("32", "64", "64", "8", "plain", "plain", "plain", "plain", "plain", "0",
                            "registered-branch", "4", "registered-owners", "registered-memory-address",
                            "registered-retirement", "registered-load-replay", "early-recovery-issue-block",
                            "precomplete-mispredicted-branch", "parallel-rename-admission", "registered-memory-requests",
                            "early-ranked-operands", "early-rename-destinations", "parallel-prf-ready",
                            "stable-prediction-metadata"),
                        runtime_args=(ref, *payloads), defines={"ROB_ENTRIES": 32, "PHYSICAL_REGS": 64,
                            "TAG_BITS": 64, "MEMORY_ENTRIES": 8, "REGISTERED_BRANCH_REDIRECT": 1,
                            "REGISTERED_RESPONSE_OWNERS": 1, "REGISTERED_MEMORY_ADDRESS": 1})
            negative(core / "run", (ref, *payloads), "NEMU register mismatch", core / "negative.log")
        if "vm" in args.only:
            payload = output / "vm-data"
            run(["riscv64-unknown-elf-gcc", "-march=rv64ia_zicsr", "-mabi=lp64", "-mno-relax",
                 "-nostdlib", "-nostartfiles", "-Wl,--no-relax", "-T", HERE / "payloads/machine-boot.ld",
                 HERE / "payloads/vm-data.S", "-o", payload.with_suffix(".elf")], log=output / "vm-build.log")
            run(["riscv64-unknown-elf-objcopy", "-O", "binary", "--only-section=.text",
                 payload.with_suffix(".elf"), payload.with_suffix(".bin")])
            test(gsim, cxx, name + "/vm", "ooo.VmDataPlatformGsimMain", "VmDataPlatformGsim",
                 "vm_data_platform.cpp", parameters=("coherent", "compact", "buffered-response",
                     "registered-physical-owners", "registered-retirement", "registered-load-replay",
                     "early-recovery-issue-block", "precomplete-mispredicted-branch", "staged-fabric", "staged-control",
                     "registered-memory-requests", "buffered-translated-response", "staged-execute", "staged-rename"),
                 runtime_args=(payload.with_suffix(".bin"), "--coherent"), defines={})
        if "board" in args.only:
            report.update(board_apps(gsim, cxx, output, profile="staged-rename"))
        report["status"] = "passed" if set(args.only) == set(CHECKS) else "partial-pass"
    except (RuntimeError, subprocess.SubprocessError, OSError):
        report["status"] = "failed"
        raise
    finally:
        (output / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"Short rename-stage batch: {report['status']}; evidence: {output / 'results.json'}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.SubprocessError, OSError) as error:
        print(f"GSIM rename-stage batch: {error}", file=sys.stderr)
        sys.exit(1)
