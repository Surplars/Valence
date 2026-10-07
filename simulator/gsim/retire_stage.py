#!/usr/bin/env python3
"""Related two-issue timing candidates, one affected short batch; no Vivado."""
import argparse
import json
import os
import re
import subprocess
import sys
from run import BUILD, HERE, run, setup, test
from control_stage import core_payloads, negative, reference
from staged_fabric import board_apps

CHECKS = ("contracts", "branch", "ras", "ledger", "prediction", "core", "vm", "board")
PREPARATION_CHECKS = ("contracts", "preparation", "pmp", "fetch", "prediction", "core", "vm", "board")
PAYLOAD_CHECKS = ("contracts", "selection", "fetch", "prediction", "core", "vm", "board")
RETURN_CHECKS = ("contracts", "operands", "credits", "fabric", "prediction", "core", "vm", "board")
FETCH_ADDRESS_CHECKS = ("contracts", "decode", "routing", "fetch-bridge", "line-cache", "prediction", "core", "vm", "vm-fetch", "board")
FETCH_CONTROL_CHECKS = ("contracts", "qualification", "routing", "rom", "prediction", "core", "vm", "vm-fetch", "board")
RECOVERY_CONTROL_CHECKS = ("contracts", "recovery", "ledger", "prediction", "core", "system", "vm", "board")
EXECUTE_SELECT_CHECKS = ("contracts", "selection", "execute-selection", "prediction", "core", "system", "vm", "board")
FRONTEND_SELECT_CHECKS = ("contracts", "frontend-selection", "fetch", "prediction", "core", "system", "vm", "vm-fetch", "board")
SENSITIVE_PATHS_CHECKS = ("contracts", "source-qualification", "fetch-requests", "execute-selection",
                         "prediction", "core", "system", "vm", "vm-fetch", "board")
REQUEST_CAPTURE_CHECKS = ("contracts", "fetch-requests", "home-qualification", "vm", "vm-fetch", "board")
WORD_DESTINATION_CHECKS = ("contracts", "execute-selection", "ledger", "prediction", "core", "system", "vm", "board")
RANK_LEGALITY_CHECKS = ("contracts", "decode-legality", "rename-selection", "execute-selection",
                       "ledger", "prediction", "core", "system", "vm", "vm-fetch", "board")
DECODE_ALIGN_CHECKS = ("contracts", "decode-legality", "alignment", "fetch", "fetch-requests",
                       "execute-selection", "prediction", "core", "system", "vm", "vm-fetch", "board")


def reject(binary, argument, diagnostic, log, runtime=()):
    # Existing TL harnesses deliberately terminate on assertions (not always rc=1).
    result = subprocess.run([binary, *runtime, argument], capture_output=True, text=True, timeout=120,
                            env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
    log.write_text(result.stdout + result.stderr)
    if result.returncode == 0 or diagnostic not in result.stdout + result.stderr:
        raise RuntimeError(f"negative protocol/oracle check failed: {diagnostic}")
    print(f"Negative protocol/oracle: PASS {diagnostic}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default="20261002")
    parser.add_argument("--profile", choices=("staged-retire", "staged-redirect", "staged-preparation", "staged-payload", "staged-return", "staged-fetch-address", "staged-fetch-control", "staged-recovery-control", "staged-execute-select", "staged-frontend-select", "staged-sensitive-paths", "staged-decode-align", "staged-rank-legality", "staged-word-destination", "staged-request-capture"),
                        default="staged-retire")
    parser.add_argument("--only", nargs="+",
                        choices=tuple(dict.fromkeys(CHECKS + PREPARATION_CHECKS + PAYLOAD_CHECKS + RETURN_CHECKS + FETCH_ADDRESS_CHECKS + FETCH_CONTROL_CHECKS + RECOVERY_CONTROL_CHECKS + EXECUTE_SELECT_CHECKS + FRONTEND_SELECT_CHECKS + SENSITIVE_PATHS_CHECKS + DECODE_ALIGN_CHECKS + RANK_LEGALITY_CHECKS + REQUEST_CAPTURE_CHECKS + ("capture",))))
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.tag):
        parser.error("invalid tag")
    request_capture = args.profile == "staged-request-capture"
    word_destination = request_capture or args.profile == "staged-word-destination"
    rank_legality = word_destination or args.profile == "staged-rank-legality"
    decode_align = rank_legality or args.profile == "staged-decode-align"
    sensitive_paths = decode_align or args.profile == "staged-sensitive-paths"
    frontend_select = sensitive_paths or args.profile == "staged-frontend-select"
    execute_select = frontend_select or args.profile == "staged-execute-select"
    recovery_control = execute_select or args.profile == "staged-recovery-control"
    fetch_control = recovery_control or args.profile == "staged-fetch-control"
    fetch_address = fetch_control or args.profile == "staged-fetch-address"
    return_stage = fetch_address or args.profile == "staged-return"
    payload = return_stage or args.profile == "staged-payload"
    preparation = payload or args.profile == "staged-preparation"
    redirect = preparation or args.profile == "staged-redirect"
    checks = REQUEST_CAPTURE_CHECKS if request_capture else WORD_DESTINATION_CHECKS if word_destination else RANK_LEGALITY_CHECKS if rank_legality else DECODE_ALIGN_CHECKS if decode_align else SENSITIVE_PATHS_CHECKS if sensitive_paths else FRONTEND_SELECT_CHECKS if frontend_select else EXECUTE_SELECT_CHECKS if execute_select else RECOVERY_CONTROL_CHECKS if recovery_control else FETCH_CONTROL_CHECKS if fetch_control else FETCH_ADDRESS_CHECKS if fetch_address else RETURN_CHECKS if return_stage else PAYLOAD_CHECKS if payload else PREPARATION_CHECKS if preparation else CHECKS + (("capture",) if redirect else ())
    if args.only is None:
        args.only = list(checks)
    if "capture" in args.only and not redirect:
        parser.error("capture checks require staged-redirect")
    if not set(args.only) <= set(checks):
        parser.error("requested checks do not belong to this candidate")
    name = f"{'request-capture' if request_capture else 'word-destination' if word_destination else 'rank-legality' if rank_legality else 'decode-align' if decode_align else 'sensitive-paths' if sensitive_paths else 'frontend-select' if frontend_select else 'execute-select' if execute_select else 'recovery-control' if recovery_control else 'fetch-control' if fetch_control else 'fetch-address' if fetch_address else 'return' if return_stage else 'payload' if payload else 'preparation' if preparation else 'redirect' if redirect else 'retire'}-stage-{args.tag}"
    output = BUILD / name
    output.mkdir(parents=True, exist_ok=True)
    report = {"profile": args.profile, "issue_width": 2, "status": "running",
              "checks_requested": args.only, "synthesis_run": False, "routed_timing_verified": False}
    (output / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    try:
        if "contracts" in args.only:
            suites = (["ooo.FetchControlTimingSpec", "ooo.FetchAddressTimingSpec", "ooo.ReturnTimingSpec", "ooo.OooParamsSpec"] if fetch_control else ["ooo.FetchAddressTimingSpec", "ooo.ReturnTimingSpec", "ooo.OooParamsSpec"] if fetch_address else ["ooo.RetireTimingSpec", "ooo.RenameTimingSpec",
                 "ooo.ExecuteTimingSpec", "ooo.OooParamsSpec"] +
                (["ooo.RedirectTimingSpec"] if redirect else []) +
                (["ooo.PreparationTimingSpec"] if preparation else []) +
                (["ooo.PayloadTimingSpec"] if payload else []) +
                (["ooo.ReturnTimingSpec", "ooo.DataTimingSpec"] if return_stage else []))
            if recovery_control:
                suites.append("ooo.RecoveryControlTimingSpec")
            if execute_select:
                suites.append("ooo.ExecuteSelectTimingSpec")
            if frontend_select:
                suites.append("ooo.FrontendSelectTimingSpec")
            if sensitive_paths:
                suites.append("ooo.SensitivePathsTimingSpec")
            if decode_align:
                suites.append("ooo.DecodeAlignTimingSpec")
            if rank_legality:
                suites.append("ooo.RankLegalityTimingSpec")
            if word_destination:
                suites.append("ooo.WordDestinationTimingSpec")
            if request_capture:
                suites.append("ooo.RequestCaptureTimingSpec")
            run(["mill", "-i", "IonSoC.test.testOnly", *suites], log=output / "contracts.log")
            print((output / "contracts.log").read_text(), end="", flush=True)
        gsim, cxx = setup(False)
        if "decode-legality" in args.only:
            legality = test(gsim, cxx, name + "/decode-legality", "ooo.DecodeAlignGsimMain",
                            "DecodeAlignGsim", "decode_align.cpp",
                            parameters=(("parallel-bit-legality",) if rank_legality else ()), defines={})
            negative(legality / "run", (), "parallel legality class oracle mismatch", legality / "negative.log")
        if "rename-selection" in args.only:
            ranks = test(gsim, cxx, name + "/rename-selection", "ooo.RenameTimingGsimMain",
                         "RenameTimingGsim", "rename_timing.cpp", parameters=("parallel-ranks",), defines={})
            negative(ranks / "run", (), "rename payload/ready oracle mismatch", ranks / "negative.log")
        if "alignment" in args.only:
            for width in (2, 4):
                aligned = test(gsim, cxx, name + f"/alignment-{width}", "ooo.FetchAlignmentGsimMain",
                               "FetchAlignmentGsim", "fetch_alignment.cpp", parameters=(str(width),),
                               defines={"FETCH_WIDTH": width})
                negative(aligned / "run", (), "parallel fetch alignment data oracle mismatch",
                         aligned / "negative.log")
        if "source-qualification" in args.only:
            source = test(gsim, cxx, name + "/source-qualification", "ooo.PredictionSourceGsimMain",
                          "PredictionSourceQualification", "prediction_sources.cpp", defines={})
            negative(source / "run", (), "prediction source priority oracle mismatch", source / "negative.log")
        if "fetch-requests" in args.only:
            for words in (2, 4):
                requests = test(gsim, cxx, name + f"/fetch-requests-{words}", "ooo.InstructionRequestGsimMain",
                                "InstructionRequestGsim", "instruction_requests.cpp",
                                parameters=(str(words),) + (("flow-through",) if decode_align else ()) +
                                (("independent-capture",) if request_capture else ()),
                                defines={"PACKET_WORDS": words, "FLOW_THROUGH": int(decode_align)})
                negative(requests / "run", (), "instruction request oracle mismatch", requests / "negative.log")
        if "home-qualification" in args.only:
            for base, size in (("80010000", 65536), ("80200000", 536870912),
                               ("f000000000001000", 4096)):
                home = test(gsim, cxx, name + "/home-" + base, "ooo.HomeQualificationGsimMain",
                            "HomeQualificationGsim", "home_qualification.cpp",
                            parameters=(base, str(size)), defines={"HOME_BASE": "0x" + base + "ULL",
                                                               "HOME_BYTES": str(size) + "ULL"})
                negative(home / "run", (), "home qualification oracle mismatch", home / "negative.log")
        if "frontend-selection" in args.only:
            frontend = test(gsim, cxx, name + "/frontend-selection", "ooo.FrontendSelectGsimMain",
                            "FrontendSelectGsim", "frontend_select.cpp", defines={})
            negative(frontend / "run", (), "frontend control encoding oracle mismatch", frontend / "negative.log")
            reject(frontend / "run", "--inject-qualification", "AUIPC qualification full64 arithmetic oracle mismatch",
                   frontend / "qualification-negative.log")
            reject(frontend / "run", "--inject-lookup", "parallel fetch tag selected-set oracle mismatch",
                   frontend / "lookup-negative.log")
        if "execute-selection" in args.only:
            execution = test(gsim, cxx, name + "/execute-selection", "ooo.ExecuteSelectGsimMain",
                             "ExecuteSelectGsim", "execute_select.cpp",
                             parameters=(("parallel-address-sums",) if sensitive_paths else ()) +
                             (("parallel-minmax-results",) if decode_align else ()) +
                             (("parallel-minmax-word-results",) if rank_legality else ()) +
                             (("early-alu-word-results",) if word_destination else ()), defines={})
            negative(execution / "run", (), "execute selection arithmetic oracle mismatch",
                     execution / "negative.log")
            reject(execution / "run", "--inject-payload", "completion payload oracle mismatch",
                   execution / "payload-negative.log")
        if "recovery" in args.only:
            for entries in (16, 32):
                recovery = test(gsim, cxx, name + f"/recovery-{entries}", "ooo.RecoveryControlGsimMain",
                                "RecoveryControlGsim", "recovery_control.cpp", parameters=(str(entries),),
                                defines={"ROB_ENTRIES": entries})
                negative(recovery / "run", (), "recovery control oracle mismatch", recovery / "negative.log")
        if "qualification" in args.only:
            qualification = test(gsim, cxx, name + "/qualification", "ooo.DirectPredictionGsimMain",
                                 "DirectPredictionGsim", "direct_prediction.cpp", defines={})
            negative(qualification / "run", (), "direct prediction qualification oracle mismatch",
                     qualification / "negative.log")
        if "rom" in args.only:
            test(gsim, cxx, name + "/rom", "ooo.BoardRomGsimMain", "BoardRomGsim", "board_rom.cpp",
                 parameters=("buffered-replies",), defines={})
            credits = test(gsim, cxx, name + "/rom-credits", "ooo.BoardRomGsimMain", "BoardRomGsim",
                           "rom_reply_credit.cpp", parameters=("buffered-replies", "credit-test"), defines={})
            negative(credits / "run", (), "ROM reply credit oracle mismatch", credits / "negative.log")
        if "decode" in args.only:
            for width, geometry, base, first, second in (
                    (32, "small", "0x80010000ULL", 2048, 2048),
                    (64, "small", "0x80010000ULL", 2048, 2048),
                    (32, "ddr", "0x80000000ULL", 2097152, 536870912),
                    (64, "ddr", "0x80000000ULL", 2097152, 536870912),
                    (64, "high", "0xf000000000001000ULL", 1024, 2048)):
                decode = test(gsim, cxx, name + f"/decode-{width}-{geometry}", "ip.AddressDecoderGsimMain",
                              "TwoBankAddressDecoder", "address_decode.cpp", parameters=(str(width), geometry),
                              defines={"ADDRESS_WIDTH": width, "DECODER_BASE": base,
                                       "BANK_BYTES": first, "SECOND_BYTES": second})
                negative(decode / "run", (), "static address decode oracle mismatch", decode / "negative.log")
        if "routing" in args.only:
            for label, main, model, harness, cases in (
                    ("router", "ip.TileLinkRouterGsimMain", "TileLinkRouterGsim", "tilelink_router.cpp",
                     (("--inject-mismatch", "TileLink router response data, source or route mismatch"),
                      ("--inject-wrong-owner", "TileLink bank response has no matching source"))),
                    ("crossbar", "ip.TileLinkCrossbarGsimMain", "TileLinkCrossbarGsim", "tilelink_crossbar.cpp",
                     (("--inject-mismatch", "TileLink crossbar D source, data or owner mismatch"),
                      ("--inject-wrong-source", "Two-master TileLink response has no matching source")))):
                routing = test(gsim, cxx, name + "/" + label, main, model, harness,
                               parameters=("prefix-decode",) + (("raw-replies",) if fetch_control else ()), defines={})
                for argument, diagnostic in cases:
                    reject(routing / "run", argument, diagnostic, routing / (argument[2:] + ".log"))
        if "fetch-bridge" in args.only:
            bridge = test(gsim, cxx, name + "/fetch-bridge", "ooo.InstructionTileLinkBridgeGsimMain",
                          "InstructionTileLinkBridge", "tilelink_fetch.cpp", parameters=("parallel-addresses",), defines={})
            for argument, diagnostic in (("--inject-mismatch", "TileLink fetch packet data or alignment mismatch"),
                                         ("--inject-wrong-source", "instruction TileLink response has no matching Get")):
                reject(bridge / "run", argument, diagnostic, bridge / (argument[2:] + ".log"))
        if "line-cache" in args.only:
            for width, prefetch in ((2, False), (4, False), (2, True), (4, True)):
                line_cache = test(gsim, cxx, name + f"/line-cache-{width}-{'prefetch' if prefetch else 'demand'}",
                     "ooo.InstructionLineCacheGsimMain", "InstructionLineCacheGsim",
                     "instruction_line_prefetch.cpp" if prefetch else "instruction_line_cache.cpp",
                     parameters=("prefetch" if prefetch else "plain", str(width), "parallel-addresses"),
                     defines={"PACKET_WORDS": width})
                if prefetch:
                    negative(line_cache / "run", (), "prefetched instruction line returned wrong code",
                             line_cache / "negative.log")
        if "vm-fetch" in args.only:
            images = []
            for suffix, definitions in (("", []), ("-cross", ["-DCROSS_PAGE=1"])):
                image = output / ("vm-instruction" + suffix)
                run(["riscv64-unknown-elf-gcc", *definitions, "-march=rv64imac_zicsr", "-mabi=lp64", "-mno-relax",
                     "-nostdlib", "-nostartfiles", "-Wl,--no-relax", "-T", HERE / "payloads/machine-boot.ld",
                     HERE / "payloads/vm-instruction.S", "-o", image.with_suffix(".elf")],
                    log=output / (image.name + "-build.log"))
                run(["riscv64-unknown-elf-objcopy", "-O", "binary", "--only-section=.text",
                     image.with_suffix(".elf"), image.with_suffix(".bin")])
                binary = image.with_suffix(".bin")
                contents = binary.read_bytes()
                binary.write_bytes(contents.ljust((len(contents) + 3) & ~3, b"\0"))
                images.append(binary)
            test(gsim, cxx, name + "/vm-fetch", "ooo.VmInstructionPlatformGsimMain", "VmInstructionPlatformGsim",
                 "vm_instruction_platform.cpp", parameters=("fetch-addresses",) +
                 (("fetch-control",) if fetch_control else ()) +
                 (("frontend-select",) if frontend_select else ()) +
                 (("sensitive-paths",) if sensitive_paths else ()) +
                 (("decode-align",) if decode_align else ()) + (("rank-legality",) if rank_legality else ()) +
                 (("request-capture",) if request_capture else ()), runtime_args=images, defines={})
        if "operands" in args.only:
            for entries, registers in ((16, 48), (32, 64)):
                operands = test(gsim, cxx, name + f"/operands-{entries}-{registers}", "ooo.PhysicalOperandsGsimMain",
                                "PhysicalOperandsGsim", "physical_operands.cpp", parameters=(str(entries), str(registers)),
                                defines={"ROB_ENTRIES": entries, "PHYSICAL_REGS": registers})
                negative(operands / "run", (), "physical operand oracle mismatch", operands / "negative.log")
        if "credits" in args.only:
            for registered in (False, True):
                credits = test(gsim, cxx, name + f"/credits-{'registered' if registered else 'flow'}",
                               "ooo.DataTimingGsimMain", "DataTimingGsim", "data_timing.cpp",
                               parameters=(("registered-payload",) if registered else ()),
                               defines={"REGISTERED_PAYLOAD": int(registered)})
                negative(credits / "run", (), "data response oracle mismatch", credits / "negative.log")
        if "fabric" in args.only:
            fabric = test(gsim, cxx, name + "/fabric", "ooo.StagedFabricGsimMain", "StagedFabricGsim",
                          "staged_fabric.cpp", parameters=("direct-memory-response",), defines={})
            negative(fabric / "run", (), "fabric response mismatch", fabric / "negative.log")
        if "selection" in args.only:
            for entries in (16, 32):
                selection = test(gsim, cxx, name + f"/selection-{entries}", "ooo.IssueSelectionGsimMain",
                                 "IssueSelectionGsim", "issue_selection.cpp", parameters=(str(entries),) +
                                 (("parallel-ranks",) if execute_select else ()),
                                 defines={"ROB_ENTRIES": entries})
                negative(selection / "run", (), "issue selection payload oracle mismatch", selection / "negative.log")
        if "preparation" in args.only:
            for entries in (16, 32):
                planner = test(gsim, cxx, name + f"/preparation-{entries}",
                               "ooo.MemoryPreparationSelectorGsimMain", "MemoryPreparationSelectorGsim",
                               "memory_preparation.cpp", parameters=(str(entries),), defines={"ROB_ENTRIES": entries})
                negative(planner / "run", (), "memory preparation oracle mismatch", planner / "negative.log")
        if "pmp" in args.only:
            pmp = test(gsim, cxx, name + "/pmp", "ooo.PmpCheckerGsimMain", "PmpCheckerGsim",
                       "pmp_checker.cpp", parameters=("aligned-word",), defines={"ALIGNED_WORD_PMP": 1})
            negative(pmp / "run", (), "PMP oracle mismatch", pmp / "negative.log")
        if "fetch" in args.only:
            for width in (2, 4):
                fetch = test(gsim, cxx, name + f"/fetch-{width}", "ooo.FetchOffsetsGsimMain", "FetchOffsetsGsim",
                             "fetch_offsets.cpp", parameters=(str(width), "stable-fault-metadata", "aligned-fetch-pmp") +
                             (("raw-fetch-presence",) if payload else ()) +
                             (("parallel-fetch-tags",) if frontend_select else ()) +
                             (("parallel-alignment",) if decode_align else ()),
                             defines={"FETCH_WIDTH": width, "STABLE_FAULT_METADATA": 1})
                negative(fetch / "run", (), "mixed-length instruction mismatch", fetch / "negative.log")
            test(gsim, cxx, name + "/fetch-pmp", "ooo.FpgaFetchGsimMain", "FpgaFetchGsim",
                 "fpga_fetch_pmp.cpp", parameters=("compressed-cache", "stable-fault-metadata", "aligned-fetch-pmp") +
                 (("raw-fetch-presence",) if payload else ()) +
                             (("parallel-fetch-tags",) if frontend_select else ()) +
                             (("parallel-alignment",) if decode_align else ()),
                 defines={"RAW_FETCH_PRESENCE": 1} if payload else {})
            negative(BUILD / name / "fetch-pmp/run", (), "fetch PMP mask oracle mismatch",
                     BUILD / name / "fetch-pmp/negative.log")
        if "capture" in args.only:
            capture = test(gsim, cxx, name + "/capture", "ooo.RedirectCaptureGsimMain", "RedirectCaptureGsim",
                           "redirect_capture.cpp", defines={})
            negative(capture / "run", (), "redirect capture oracle mismatch", capture / "negative.log")
        if "branch" in args.only:
            branch = test(gsim, cxx, name + "/branch", "ooo.RetireTimingGsimMain", "RetireTimingGsim",
                          "retire_timing.cpp", parameters=(("carry-compare",) if redirect else ()), defines={})
            negative(branch / "run", (), "branch compare/result oracle mismatch", branch / "negative.log")
        if "ras" in args.only:
            ras = test(gsim, cxx, name + "/ras", "ooo.ReturnStackGsimMain", "ReturnStackGsim",
                       "return_stack.cpp", parameters=("parallel-control",), defines={})
            negative(ras / "run", (), "return stack oracle mismatch", ras / "negative.log")
        if "ledger" in args.only:
            for tags in ((8, 64) if recovery_control else (8,)):
                test(gsim, cxx, name + f"/ledger-{tags}", "ooo.RenameRobGsimMain", "RenameRobGsim", "backend.cpp",
                     parameters=("16", "48", str(tags), "4", "early-destinations", "separate-retire-fault") +
                     (("parallel-recovery-admission",) if recovery_control else ()) +
                     (("parallel-ranks",) if rank_legality else ()) +
                     (("early-architectural-destinations",) if word_destination else ()),
                     defines={"ROB_ENTRIES": 16, "PHYSICAL_REGS": 48, "TAG_BITS": tags, "RECOVERY_WIDTH": 4})
        if "prediction" in args.only:
            packet = test(gsim, cxx, name + "/prediction", "ooo.RetirePacketCoreGsimMain", "IntegerCoreGsim",
                          "rename_packet.cpp", parameters=((args.profile,) if redirect else ()), defines={})
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
                            "stable-prediction-metadata", "separate-branch-retire-fault",
                            "early-redirect-capture" if redirect else "balanced-branch-compare") +
                            (("parallel-memory-preparation",) if preparation else ()) +
                            (("parallel-issue-payload",) if payload else ()) +
                            (("one-hot-physical-operands",) if return_stage and not fetch_address else ()) +
                            (("parallel-prediction-qualification",) if fetch_control else ()) +
                            (("parallel-recovery-admission", "parallel-redirect-tokens") if recovery_control else ()) +
                            (("parallel-issue-ranks", "parallel-alu-results", "parallel-completion-payload")
                             if execute_select else ()) +
                            (("parallel-frontend-control", "parallel-auipc-qualification") if frontend_select else ()) +
                            (("parallel-prediction-sources", "parallel-address-sums") if sensitive_paths else ()) +
                            (("parallel-decode-legality", "parallel-minmax-results") if decode_align else ()) +
                            (("parallel-bit-legality", "parallel-rename-ranks", "parallel-minmax-word-results")
                             if rank_legality else ()) +
                            (("early-architectural-destinations", "early-alu-word-results")
                             if word_destination else ()),
                        # Keep the original ISA/NEMU oracle and port geometry.
                        runtime_args=(ref, *payloads), defines={"ROB_ENTRIES": 32, "PHYSICAL_REGS": 64,
                            "TAG_BITS": 64, "MEMORY_ENTRIES": 8, "REGISTERED_BRANCH_REDIRECT": 1,
                            "REGISTERED_RESPONSE_OWNERS": 1, "REGISTERED_MEMORY_ADDRESS": 1})
            negative(core / "run", (ref, *payloads), "NEMU register mismatch", core / "negative.log")
        if "system" in args.only:
            ref = reference()
            system = test(gsim, cxx, name + "/system", "ooo.RecoveryMachineCoreGsimMain",
                          "MachineCoreGsim", "machine.cpp", parameters=(args.profile,),
                          runtime_args=(ref,), defines={})
            negative(system / "run", (ref,), "commit data/nextPC", system / "negative.log")
            reject(system / "run", "--inject-interrupt", "trap metadata",
                   system / "interrupt-negative.log", runtime=(ref,))
        if "vm" in args.only:
            vm_payload = output / "vm-data"
            run(["riscv64-unknown-elf-gcc", "-march=rv64ia_zicsr", "-mabi=lp64", "-mno-relax",
                 "-nostdlib", "-nostartfiles", "-Wl,--no-relax", "-T", HERE / "payloads/machine-boot.ld",
                 HERE / "payloads/vm-data.S", "-o", vm_payload.with_suffix(".elf")], log=output / "vm-build.log")
            run(["riscv64-unknown-elf-objcopy", "-O", "binary", "--only-section=.text",
                 vm_payload.with_suffix(".elf"), vm_payload.with_suffix(".bin")])
            test(gsim, cxx, name + "/vm", "ooo.VmDataPlatformGsimMain", "VmDataPlatformGsim",
                 "vm_data_platform.cpp", parameters=("coherent", "compact", "buffered-response",
                     "registered-physical-owners", "registered-retirement", "registered-load-replay",
                     "early-recovery-issue-block", "precomplete-mispredicted-branch", "staged-fabric", "staged-control",
                     "registered-memory-requests", "buffered-translated-response", "staged-execute", "staged-rename",
                     "staged-retire") + (("staged-redirect",) if redirect else ()) +
                     (("staged-preparation",) if preparation else ()) + (("staged-payload",) if payload else ()) +
                     (("staged-return",) if return_stage else ()) + (("staged-fetch-address",) if fetch_address else ()) +
                     (("staged-fetch-control",) if fetch_control else ()) +
                     (("staged-recovery-control",) if recovery_control else ()) +
                     (("staged-execute-select",) if execute_select else ()) +
                     (("staged-frontend-select",) if frontend_select else ()) +
                     (("staged-sensitive-paths",) if sensitive_paths else ()) +
                     (("staged-decode-align",) if decode_align else ()) +
                     (("staged-rank-legality",) if rank_legality else ()) +
                     (("staged-word-destination",) if word_destination else ()) +
                     (("staged-request-capture",) if request_capture else ()),
                 runtime_args=(vm_payload.with_suffix(".bin"), "--coherent"), defines={})
        if "board" in args.only:
            report.update(board_apps(gsim, cxx, output, profile=args.profile))
        report["status"] = "passed" if set(args.only) == set(checks) else "partial-pass"
    except (RuntimeError, subprocess.SubprocessError, OSError):
        report["status"] = "failed"
        raise
    finally:
        (output / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"Short {args.profile} batch: {report['status']}; evidence: {output / 'results.json'}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.SubprocessError, OSError) as error:
        print(f"GSIM retire-stage batch: {error}", file=sys.stderr)
        sys.exit(1)
