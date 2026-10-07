#!/usr/bin/env python3
"""One affected two-issue ROM/fabric batch; one reused exact-clock board model."""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from run import BUILD, HERE, ROOT, run, setup, test
from control_stage import core_payloads, negative, reference
from retire_stage import reject
from staged_fabric import board_apps

PROFILE = "staged-rom-boundary"
CHECKS = ("contracts", "queues", "routing", "vm", "vm-fetch", "board")
CONTROL_CHECKS = ("contracts", "prediction", "credits", "memory-payload", "packet-pmp", "core", "vm", "vm-fetch", "board")
THROUGHPUT_CHECKS = ("contracts", "pipelines", "vm", "vm-fetch", "board")


def hardware_sources():
    return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted((ROOT / "src/main/scala").rglob("*.scala"))}


def feedback_inputs():
    manifest = "simulator/gsim/config/throughput_feedback_inputs.json"
    paths = [manifest, *json.loads((ROOT / manifest).read_text())]
    if len(paths) != len(set(paths)) or any(not re.fullmatch(
            r"(?:src/test/scala/ooo|simulator/gsim)/[A-Za-z0-9_./-]+", path) or
            any(part in ("", ".", "..") for part in path.split("/")) for path in paths):
        raise RuntimeError("invalid exact affected test-input manifest")
    return {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in paths}


def strict_negative(binary, arguments, flag, markers, output):
    result = subprocess.run([binary, *arguments, flag], capture_output=True, text=True,
        timeout=120, env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
    text = result.stdout + result.stderr
    output.write_text(text)
    if (result.returncode != 1 or not all(marker in text for marker in markers) or
            re.search(r"AddressSanitizer|UndefinedBehaviorSanitizer|runtime error:|\bPASS\b", text)):
        raise RuntimeError("negative control must exit 1 on the independent oracle, not pass or crash")
    print(f"Strict negative oracle: PASS {flag}", flush=True)
    return result.returncode


def oracle_text(path):
    text = path.read_text()
    if re.search(r"AddressSanitizer|UndefinedBehaviorSanitizer|runtime error:|\bFAIL\b", text):
        raise RuntimeError(f"positive oracle contains failure or sanitizer diagnostics: {path}")
    return text


def oracle_summary(path, marker, integer_fields, enums=None):
    enums = enums or {}
    lines = [line for line in oracle_text(path).splitlines() if line.startswith(marker + " ")]
    if len(lines) != 1:
        raise RuntimeError(f"missing or duplicate positive oracle summary: {path}")
    fields = {}
    for token in lines[0][len(marker) + 1:].split():
        match = re.fullmatch(r"([A-Za-z][A-Za-z0-9_]*)=([A-Za-z0-9_|.-]+)", token)
        if not match or match[1] in fields:
            raise RuntimeError(f"invalid or duplicate oracle field: {path}: {token}")
        fields[match[1]] = match[2]
    if set(fields) != set(integer_fields) | set(enums):
        raise RuntimeError(f"oracle summary has unexpected or missing fields: {path}")
    for field in integer_fields:
        if not re.fullmatch(r"[0-9]+", fields[field]):
            raise RuntimeError(f"oracle counter is not a nonnegative integer: {path}: {field}")
        fields[field] = int(fields[field])
    if any(fields[field] != value for field, value in enums.items()):
        raise RuntimeError(f"oracle boundary or configuration differs: {path}")
    return fields


def require_counters(counts, positive=(), exact=None):
    if any(counts[field] <= 0 for field in positive) or any(
            counts[field] != value for field, value in (exact or {}).items()):
        raise RuntimeError("independent oracle coverage counters incomplete")


def authorization_ledger_counts(path, aliases):
    counts = oracle_summary(path, "GSIM authorization ledger: PASS",
        ("headSystems", "activeShrinks", "duplicateRetainOne", "externalHeadTies",
         "trapPriority", "ownerChecks", "rawWaw", "x0", "validHoles", "capacity", "aliases"))
    require_counters(counts,
        ("headSystems", "activeShrinks", "duplicateRetainOne", "ownerChecks"),
        {"externalHeadTies": 2, "trapPriority": 1, "rawWaw": 1, "x0": 1,
         "validHoles": 2, "capacity": 2, "aliases": aliases})
    return counts


def authorization_machine_counts(path):
    integer_fields = ("programs", "offers", "blocked", "lsuCollision", "mulCollision",
        "repeatRollback", "commitHolds", "protectedReleases", "acks", "cycles")
    summary = oracle_summary(path, "GSIM authorization machine: PASS", integer_fields,
        {"oracle": "SystemModel", "irqBoundary": "DIRECT-IRQ"})
    counts = {field: summary[field] for field in integer_fields}
    require_counters(counts, integer_fields, {"programs": 24})
    if (counts["acks"] < 24 or counts["protectedReleases"] < 24 or
            counts["offers"] < max(counts["blocked"], counts["acks"])):
        raise RuntimeError("authorization completion/release coverage incomplete")
    cases = {}
    for line in oracle_text(path).splitlines():
        if not line.startswith("AUTHORIZATION_CASE"):
            continue
        match = re.fullmatch(r"AUTHORIZATION_CASE memory=([01]) delay=([0-9]+) "
            r"cycles=([0-9]+) blocked=([0-9]+) lsu=([0-9]+) mul=([0-9]+) rollback=([0-9]+)", line)
        if not match:
            raise RuntimeError(f"malformed authorization case witness: {path}")
        memory, delay, *values = map(int, match.groups())
        key = f"{memory}|{delay}"
        if key in cases:
            raise RuntimeError(f"duplicate authorization case witness: {path}: {key}")
        case = dict(zip(("cycles", "blocked", "lsu", "mul", "rollback"), values))
        if (case["cycles"] <= 0 or case["blocked"] > case["cycles"] or any(
                case[field] > case["blocked"] for field in ("lsu", "mul", "rollback"))):
            raise RuntimeError(f"invalid authorization case counters: {path}: {key}")
        cases[key] = case
    if set(cases) != {f"{memory}|{delay}" for memory in (0, 1) for delay in range(1, 13)}:
        raise RuntimeError(f"authorization oracle requires exactly 24 legal phase cases: {path}")
    for field, summary_field in (("cycles", "cycles"), ("blocked", "blocked"),
            ("lsu", "lsuCollision"), ("mul", "mulCollision"), ("rollback", "repeatRollback")):
        if sum(case[field] for case in cases.values()) != counts[summary_field]:
            raise RuntimeError(f"authorization case/summary totals differ: {path}: {field}")
    return counts, cases


def fixture_receipt(parameters, defines, runtime_args, negative_flags):
    return {"parameters": list(parameters), "defines": dict(defines),
            "runtime_args": [str(argument) for argument in runtime_args],
            "positive_exit_code": 0, "negative_flags": dict(negative_flags)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default="20261002")
    parser.add_argument("--profile", choices=(PROFILE, "staged-control-heads", "staged-throughput"), default=PROFILE)
    parser.add_argument("--only", choices=tuple(dict.fromkeys(CHECKS + CONTROL_CHECKS + THROUGHPUT_CHECKS)), nargs="+")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.tag):
        parser.error("invalid tag")
    throughput = args.profile == "staged-throughput"
    control_heads = throughput or args.profile == "staged-control-heads"
    required = THROUGHPUT_CHECKS if throughput else CONTROL_CHECKS if control_heads else CHECKS
    args.only = args.only or list(required)
    name = ("throughput-" if throughput else "control-heads-" if control_heads else "rom-boundary-") + args.tag
    output = BUILD / name
    output.mkdir(parents=True, exist_ok=True)
    evidence = output / "results.json"
    if evidence.exists():
        parser.error("tag already has results; preserve evidence and use a fresh tag")
    report = {"profile": args.profile, "issue_width": 2, "cpu_hz": 100_000_000,
              "uart_baud": 460800, "checks_requested": args.only, "status": "running",
              "routed_timing_verified": False, "on_board_verified": False}
    if throughput:
        report["hardware_source_sha256"] = hardware_sources()
        report["feedback_inputs_sha256"] = feedback_inputs()
    try:
        if "contracts" in args.only:
            specs = ["ooo.RomBoundaryTimingSpec", "ooo.RequestCaptureTimingSpec", "ooo.OooParamsSpec"]
            if control_heads:
                specs += ["ooo.ControlHeadsTimingSpec", "ooo.ReturnTimingSpec"]
            if throughput:
                specs += ["ooo.ThroughputTimingSpec", "ooo.FrontendSelectTimingSpec",
                          "ooo.FrontendFeedbackTimingSpec", "ooo.InstructionPermissionTimingSpec",
                          "ooo.SharedPhysicalSourceDecodeSpec"]
            run(["mill", "-i", "IonSoC.test.testOnly", *specs], log=output / "contracts.log")
            print((output / "contracts.log").read_text(), end="", flush=True)
        gsim, cxx = setup(False)
        if "pipelines" in args.only:
            side = test(gsim, cxx, name + "/side-issue", "ooo.SideIssueTimingGsimMain",
                "SideIssueTimingGsim", "side_issue_timing.cpp", defines={})
            report["side_issue_negative_exit_code"] = strict_negative(side / "run", (),
                "--inject-mismatch", ("side issue timing oracle mismatch",), side / "negative.log")
            side_fields = ("cycles", "ready_checks", "wake_reserve_collisions", "owner_replacements",
                "same_packet_raw", "alias_init", "blocked_units", "dual_classes", "store_grants",
                "age_wrap", "resets", "store_candidates", "store_invariant_pairs", "alu_promise_changes",
                "late_store_grant_changes", "head_excluded", "partial_address", "known_data_wait",
                "unused_sources", "prepared_excluded", "class_excluded", "control_held", "candidate_age_wrap")
            side_counts = oracle_summary(side / "test.log", "SIDE_ISSUE_TIMING_PASS", side_fields)
            require_counters(side_counts, side_fields, {"cycles": 6000, "resets": 2,
                "same_packet_raw": 750, "alias_init": 750, "store_candidates": 6000,
                "store_invariant_pairs": 4500, "alu_promise_changes": 4500})
            side_minimum = {"ready_checks": 30001, "wake_reserve_collisions": 501,
                "owner_replacements": 1001, "blocked_units": 2001, "dual_classes": 4001,
                "store_grants": 3001, "age_wrap": 51, "late_store_grant_changes": 2250,
                "head_excluded": 750, "partial_address": 1500, "known_data_wait": 1500,
                "unused_sources": 1500, "prepared_excluded": 750, "class_excluded": 1500,
                "control_held": 750, "candidate_age_wrap": 51}
            if any(side_counts[field] < minimum for field, minimum in side_minimum.items()):
                raise RuntimeError("independent store/late-credit witness thresholds incomplete")
            report["side_store_counts"] = side_counts
            report["side_store_negative_exit_code"] = strict_negative(side / "run", (),
                "--inject-store-candidate", ("side issue timing oracle mismatch: store candidate semantics",),
                side / "store-negative.log")
            report["side_store_oracle_verified"] = True
            report["side_issue_oracles_verified"] = True
            report["raw_fault_counts"] = {}
            report["raw_fault_negative_exit_codes"] = {}
            report["raw_fault_fixtures"] = {}
            raw_fault_fields = ("physical", "cases", "cycles", "mask0", "mask1", "mask2", "mask3",
                "pressure0", "pressure1", "pressure2", "patterns", "wakeModes", "accepted", "aliases",
                "blocked", "noFreeFaultAccepted", "noFreeFullBlocked", "wakeReserveCollision", "readyChecks",
                "rawForward", "faultSuppressedRaw", "aliasWithoutFree")
            for physical in (40, 48):
                key = str(physical)
                parameters = (key,)
                defines = {"PHYSICAL_REGS": physical}
                raw_fault = test(gsim, cxx, name + "/raw-fault-" + key,
                    "ooo.RenameFaultCandidatesGsimMain", "RenameFaultCandidatesGsim",
                    "rename_fault_candidates.cpp", parameters=parameters, defines=defines)
                counts = oracle_summary(raw_fault / "test.log", "GSIM raw-fault rename: PASS", raw_fault_fields)
                cycles = 2880 if physical == 40 else 5184
                exact = {"physical": physical, "cases": 288, "cycles": cycles,
                    "mask0": 72, "mask1": 72, "mask2": 72, "mask3": 72,
                    "pressure0": 96, "pressure1": 96, "pressure2": 96,
                    "patterns": 12, "wakeModes": 2, "readyChecks": cycles * 32}
                exact.update({"noFreeFullBlocked": 0} if physical == 40 else
                    {"noFreeFaultAccepted": 0, "aliasWithoutFree": 0})
                positive = tuple(field for field in raw_fault_fields if field not in
                    ("noFreeFaultAccepted", "noFreeFullBlocked", "aliasWithoutFree")) + (
                    ("noFreeFaultAccepted", "aliasWithoutFree") if physical == 40 else ("noFreeFullBlocked",))
                require_counters(counts, positive, exact)
                code = strict_negative(raw_fault / "run", (), "--inject-mismatch",
                    ("independent raw-fault rename oracle mismatch",), raw_fault / "negative.log")
                report["raw_fault_counts"][key] = counts
                report["raw_fault_negative_exit_codes"][key] = code
                report["raw_fault_fixtures"][key] = fixture_receipt(parameters, defines, (),
                    {"--inject-mismatch": code})
            report["raw_fault_oracles_verified"] = True
            report["instruction_permission_negative_exit_codes"] = {}
            for width, retimed, aligned in ((2, True, False), (2, True, True),
                                           (4, True, True), (2, False, False)):
                key = f"{width}-{int(retimed)}-{int(aligned)}"
                permission = test(gsim, cxx, name + "/instruction-permission-" + key,
                    "ooo.InstructionPermissionGsimMain", "InstructionPermissionGsim",
                    "instruction_permission.cpp", parameters=(str(width),) +
                    (("retimed",) if retimed else ()) + (("aligned",) if aligned else ()),
                    defines={"PACKET_WORDS": width, "RETIMED_PERMISSIONS": int(retimed),
                        "ALIGNED_PACKET": int(aligned)})
                report["instruction_permission_negative_exit_codes"][key] = strict_negative(
                    permission / "run", (), "--inject-mismatch",
                    ("independent I-fetch permission oracle mismatch",), permission / "negative.log")
            report["instruction_permission_oracles_verified"] = True
            report["shared_physical_counts"] = {}
            report["shared_physical_negative_exit_codes"] = {}
            report["shared_physical_fixtures"] = {}
            for entries, registers, shared in ((16, 48, True), (16, 48, False), (32, 64, True)):
                key = f"{entries}-{registers}-{int(shared)}"
                parameters = (str(entries), str(registers), str(shared).lower(), "3")
                defines = {"ROB_ENTRIES": entries, "PHYSICAL_REGS": registers,
                           "SHARED_DECODE_CLIENTS": 3}
                operands = test(gsim, cxx, name + "/physical-shared-" + key,
                    "ooo.PhysicalOperandsGsimMain", "PhysicalOperandsGsim", "physical_operands.cpp",
                    parameters=parameters, defines=defines)
                counts = oracle_summary(operands / "test.log", "GSIM physical operand payload: PASS",
                    ("rob", "physical", "vectors", "empty", "dual", "invalidUnselected",
                     "sharedClients", "independentOwnerVectors"))
                require_counters(counts, ("empty", "dual"),
                    {"rob": entries, "physical": registers, "sharedClients": 3,
                     "vectors": 57921 if entries == 16 else 153185,
                     "invalidUnselected": entries * 2, "independentOwnerVectors": entries * 64})
                if counts["empty"] + counts["dual"] != counts["vectors"]:
                    raise RuntimeError("physical oracle vector coverage does not partition empty/dual")
                report["shared_physical_counts"][key] = {
                    field: value for field, value in counts.items() if field not in ("rob", "physical")}
                report["shared_physical_negative_exit_codes"][key] = {
                    "normal": strict_negative(operands / "run", (), "--inject-mismatch",
                        ("physical operand oracle mismatch",), operands / "negative.log"),
                    "shared": strict_negative(operands / "run", (), "--inject-shared-mismatch",
                        ("shared physical operand oracle mismatch",), operands / "shared-negative.log")}
                report["shared_physical_fixtures"][key] = fixture_receipt(parameters, defines, (),
                    {"normal": "--inject-mismatch", "shared": "--inject-shared-mismatch"})
            report["shared_physical_oracles_verified"] = True
            execution = test(gsim, cxx, name + "/execution-slot", "ooo.IssueExecuteStageGsimMain",
                "IssueExecuteStageGsim", "issue_execute_stage.cpp", defines={})
            negative(execution / "run", (), "execution stage oracle mismatch", execution / "negative.log")
            for width in (2, 4):
                for compressed in (False, True):
                    suffix = str(int(compressed)) if width == 2 else f"4-{int(compressed)}"
                    packet = test(gsim, cxx, name + "/fetch-packet-" + suffix,
                        "ooo.RegisteredFetchPacketGsimMain", "RegisteredFetchPacketGsim",
                        "registered_fetch_packet.cpp", parameters=(str(width),) + (() if compressed else ("plain",)),
                        defines={"FETCH_WIDTH": width, "COMPRESSED": int(compressed)})
                    negative(packet / "run", (), "fetch packet oracle mismatch", packet / "negative.log")
            selection = test(gsim, cxx, name + "/frontend-select", "ooo.FrontendSelectGsimMain",
                "FrontendSelectGsim", "frontend_select.cpp", defines={})
            reject(selection / "run", "--inject-shifted-lookup",
                "adjacent fetch tag full64 selected-set oracle mismatch", selection / "shifted-negative.log")
            for width in (2, 4):
                offsets = test(gsim, cxx, name + f"/fetch-offsets-{width}", "ooo.FetchOffsetsGsimMain",
                    "FetchOffsetsGsim", "fetch_offsets.cpp",
                    parameters=(str(width), "stable-fault-metadata", "aligned-fetch-pmp", "raw-fetch-presence",
                        "parallel-fetch-tags", "parallel-alignment"),
                    defines={"FETCH_WIDTH": width, "STABLE_FAULT_METADATA": 1,
                        "ALIGNED_FETCH_PMP": 1, "RAW_FETCH_PRESENCE": 1})
                negative(offsets / "run", (), "mixed-length instruction mismatch", offsets / "negative.log")
            ledger_flags = ("fast-head-trap", "fast-head-system", "tentative-sources",
                "early-destinations", "parallel-ranks", "early-architectural-destinations")
            ledger_parameters = ("16", "48", "64", "4", *ledger_flags)
            ledger_defines = {"ROB_ENTRIES": 16, "PHYSICAL_REGS": 48, "TAG_BITS": 64,
                "RECOVERY_WIDTH": 4, "FAST_HEAD_TRAP": 1, "FAST_HEAD_SYSTEM": 1}
            ledger = test(gsim, cxx, name + "/head-trap-ledger", "ooo.RenameRobGsimMain",
                "RenameRobGsim", "backend.cpp", parameters=ledger_parameters,
                runtime_args=("--head-trap-short",), defines=ledger_defines)
            report["head_trap_ledger_counts"] = oracle_summary(ledger / "test.log",
                "GSIM trusted head-trap ledger: PASS", ("headTraps", "activeRollbackShrinks",
                "emptyRequests", "duplicateZeroBoundary", "dualCommits", "rejectedCompletions",
                "seeds", "randomCycles"))
            require_counters(report["head_trap_ledger_counts"], ("headTraps", "activeRollbackShrinks",
                "emptyRequests", "duplicateZeroBoundary", "dualCommits", "rejectedCompletions"),
                {"seeds": 2, "randomCycles": 3000})
            report["head_trap_ledger_negative_exit_code"] = strict_negative(ledger / "run", (),
                "--inject-head-trap-mismatch", ("GSIM trusted head-trap ledger: FAIL",
                "head trap acceptance oracle mismatch"), ledger / "negative.log")
            run([ledger / "run", "--authorization-short"],
                env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"},
                log=ledger / "authorization.log", timeout=120)
            report["head_system_ledger_counts"] = {
                "candidate": authorization_ledger_counts(ledger / "authorization.log", 0)}
            report["head_system_ledger_negative_exit_codes"] = {
                "candidate": {
                    "system": strict_negative(ledger / "run", (), "--inject-head-system-mismatch",
                        ("GSIM authorization ledger: FAIL", "head system acceptance oracle mismatch"),
                        ledger / "system-negative.log"),
                    "source": strict_negative(ledger / "run", (), "--inject-tentative-source-mismatch",
                        ("GSIM authorization ledger: FAIL", "same-packet source mapping"),
                        ledger / "sources-negative.log")}}
            report["head_system_ledger_fixtures"] = {
                "candidate": fixture_receipt(ledger_parameters, ledger_defines,
                    ("--authorization-short",), {"system": "--inject-head-system-mismatch",
                    "source": "--inject-tentative-source-mismatch"})}
            # move-alias must be the first optional emitter argument (index 5).
            alias_flags = tuple(flag for flag in ledger_flags if flag not in
                ("early-destinations", "parallel-ranks", "early-architectural-destinations"))
            alias_parameters = ("16", "36", "64", "4", "move-alias", *alias_flags)
            alias_defines = {**ledger_defines, "PHYSICAL_REGS": 36, "MOVE_ALIAS": 1}
            alias = test(gsim, cxx, name + "/authorization-ledger-alias", "ooo.RenameRobGsimMain",
                "RenameRobGsim", "backend.cpp", parameters=alias_parameters,
                runtime_args=("--authorization-short",), defines=alias_defines)
            report["head_system_ledger_counts"]["alias"] = authorization_ledger_counts(
                alias / "test.log", 3)
            report["head_system_ledger_negative_exit_codes"]["alias"] = {
                "system": strict_negative(alias / "run", (), "--inject-head-system-mismatch",
                    ("GSIM authorization ledger: FAIL", "head system acceptance oracle mismatch"),
                    alias / "system-negative.log"),
                "source": strict_negative(alias / "run", (), "--inject-tentative-source-mismatch",
                    ("GSIM authorization ledger: FAIL", "same-packet source mapping"),
                    alias / "sources-negative.log")}
            report["head_system_ledger_fixtures"]["alias"] = fixture_receipt(
                alias_parameters, alias_defines, ("--authorization-short",),
                {"system": "--inject-head-system-mismatch", "source": "--inject-tentative-source-mismatch"})
            report["head_system_ledger_oracle_verified"] = True
            ref = reference()
            machine_defines = {"REGISTERED_FETCH_PACKET": 1, "ROB_ENTRIES": 16,
                "PHYSICAL_REGS": 48, "TAG_BITS": 64, "MEMORY_ENTRIES": 2,
                "BRANCH_ENTRIES": 32, "SYSTEM_AUTHORIZATION_FIXTURE": 1}
            machine = test(gsim, cxx, name + "/head-trap-machine",
                "ooo.AuthorizationMachineCoreGsimMain", "MachineCoreGsim", "machine.cpp",
                runtime_args=(ref, "--head-trap-short"), defines=machine_defines)
            report["head_trap_machine_counts"] = oracle_summary(machine / "test.log",
                "GSIM head trap short: PASS", ("programs", "interrupts", "traps", "empty",
                "memoryIrq", "storeIrq", "priority", "mret", "csr", "held", "fastHeadTraps",
                "emptyTrapEvents", "cycles", "registeredFetchPacket"),
                {"irqBoundary": "DIRECT-IRQ", "oracle": "SystemModel"})
            require_counters(report["head_trap_machine_counts"],
                ("csr", "fastHeadTraps", "emptyTrapEvents", "cycles"),
                {"programs": 8, "interrupts": 8, "traps": 10, "empty": 2, "memoryIrq": 2,
                 "storeIrq": 2, "priority": 2, "mret": 10, "registeredFetchPacket": 1})
            if report["head_trap_machine_counts"]["held"] < 80:
                raise RuntimeError("head trap short lost held-response coverage")
            report["head_trap_machine_negative_exit_code"] = strict_negative(machine / "run",
                (ref, "--head-trap-short"), "--inject-interrupt",
                ("GSIM head trap short negative: oracle rejected injected interrupt cause",
                 "GSIM MachineCore: FAIL trap metadata"), machine / "negative.log")
            run([machine / "run", ref, "--authorization-short"],
                env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"},
                log=machine / "authorization.log", timeout=120)
            counts, cases = authorization_machine_counts(machine / "authorization.log")
            report["authorization_machine_counts"] = {"candidate": counts}
            report["authorization_machine_cases"] = {"candidate": cases}
            report["authorization_machine_negative_exit_code"] = strict_negative(machine / "run",
                (ref, "--authorization-short"), "--inject-system-redirect",
                ("GSIM MachineCore: FAIL system redirect architectural oracle mismatch",),
                machine / "authorization-negative.log")
            generic_parameters = ("generic-system",)
            generic = test(gsim, cxx, name + "/authorization-machine-generic",
                "ooo.AuthorizationMachineCoreGsimMain", "MachineCoreGsim", "machine.cpp",
                parameters=generic_parameters, runtime_args=(ref, "--authorization-short"),
                defines=machine_defines)
            counts, cases = authorization_machine_counts(generic / "test.log")
            report["authorization_machine_counts"]["generic"] = counts
            report["authorization_machine_cases"]["generic"] = cases
            report["authorization_machine_fixture_options"] = {}
            report["authorization_machine_fixtures"] = {}
            for kind, model, parameters in (("candidate", machine, ()),
                                           ("generic", generic, generic_parameters)):
                report["authorization_machine_fixture_options"][kind] = oracle_summary(
                    model / "elaborate.log", "AUTHORIZATION_MACHINE_FIXTURE", (),
                    {"headSystem": "true" if kind == "candidate" else "false",
                     "tentativeSources": "true", "sharedDecode": "true",
                     "irqBoundary": "DIRECT-IRQ", "oracle": "SystemModel",
                     "fixture": "legal-fence-flush-backpressure"})
                report["authorization_machine_fixtures"][kind] = fixture_receipt(
                    parameters, machine_defines, (ref, "--authorization-short"),
                    {"system": "--inject-system-redirect"} if kind == "candidate" else {})
            report["authorization_machine_oracle_verified"] = True
            candidate_cases = report["authorization_machine_cases"]["candidate"]
            generic_cases = report["authorization_machine_cases"]["generic"]
            differences = {key: {"candidate": candidate_cases[key]["cycles"],
                                "generic": generic_cases[key]["cycles"]}
                for key in candidate_cases if candidate_cases[key]["cycles"] != generic_cases[key]["cycles"]}
            report["authorization_machine_cycle_differences"] = differences
            report["authorization_machine_cycles_equal"] = not differences
            report["authorization_machine_scope"] = (
                "Legal external FENCE.I backpressure; independent SystemModel; "
                "DIRECT-IRQ; not production registered IMSIC")
            if differences:
                report["engineering_review_required"] = True
                report["failure"] = "Authorization cut changed same-stimulus case cycle counts"
                raise RuntimeError(report["failure"])
            report["frontend_feedback_oracles_verified"] = True
            report["head_trap_ledger_oracle_verified"] = True
            report["head_trap_machine_oracle_verified"] = True
            report["head_trap_machine_scope"] = "DIRECT-IRQ/SystemModel; not production registered IMSIC"
        if "prediction" in args.only:
            for width, compressed, delayed in ((2, True, False), (2, True, True), (4, False, True)):
                parameters = (str(width),) + (() if compressed else ("plain",)) + (() if delayed else ("direct",))
                prediction = test(gsim, cxx, name + f"/prediction-{width}-{int(compressed)}-{int(delayed)}",
                    "ooo.PredictionTrainingGsimMain", "PredictionTrainingGsim", "prediction_training.cpp",
                    parameters=parameters, defines={"TRAIN_WIDTH": width, "COMPRESSED": int(compressed),
                        "DELAYED_TRAINING": int(delayed)})
                negative(prediction / "run", (), "prediction training oracle mismatch", prediction / "negative.log")
        if "credits" in args.only:
            credits = test(gsim, cxx, name + "/credits", "ooo.DataTimingGsimMain", "DataTimingGsim",
                "data_timing.cpp", parameters=("registered-payload", "register-head"),
                defines={"REGISTERED_PAYLOAD": 1})
            negative(credits / "run", (), "data response oracle mismatch", credits / "negative.log")
        if "memory-payload" in args.only:
            for entries in (16, 32):
                planner = test(gsim, cxx, name + f"/planner-{entries}", "ooo.MemoryPreparationSelectorGsimMain",
                    "MemoryPreparationSelectorGsim", "memory_preparation.cpp", parameters=(str(entries), "parallel"),
                    defines={"ROB_ENTRIES": entries})
                negative(planner / "run", (), "memory preparation oracle mismatch", planner / "negative.log")
            operands = test(gsim, cxx, name + "/operands", "ooo.PhysicalOperandsGsimMain", "PhysicalOperandsGsim",
                "physical_operands.cpp", parameters=("16", "48"), defines={"ROB_ENTRIES": 16, "PHYSICAL_REGS": 48})
            negative(operands / "run", (), "physical operand oracle mismatch", operands / "negative.log")
        if "packet-pmp" in args.only:
            pmp = test(gsim, cxx, name + "/packet-pmp", "ooo.PmpCheckerGsimMain", "PmpCheckerGsim",
                "pmp_checker.cpp", parameters=("packet",), defines={})
            negative(pmp / "run", (), "PMP oracle mismatch", pmp / "negative.log")
        if "core" in args.only:
            ref = reference()
            payloads = core_payloads(output)
            core = test(gsim, cxx, name + "/core", "ooo.ControlHeadsCoreGsimMain", "IntegerCoreGsim", "core.cpp",
                runtime_args=(ref, *payloads, "--timing-smoke"), defines={"ROB_ENTRIES": 16, "PHYSICAL_REGS": 48,
                    "TAG_BITS": 64, "MEMORY_ENTRIES": 2, "REGISTERED_BRANCH_REDIRECT": 1,
                    "REGISTERED_RESPONSE_OWNERS": 1, "REGISTERED_MEMORY_ADDRESS": 1,
                    "BRANCH_ENTRIES": 32, "STORE_BUFFER_ENTRIES": 2, "DELAYED_PREDICTION_TRAINING": 1})
            negative(core / "run", (ref, *payloads), "NEMU register mismatch", core / "negative.log")
        if "queues" in args.only:
            fifo = test(gsim, cxx, name + "/queues", "ooo.RomBoundaryGsimMain", "RomBoundaryGsim",
                        "rom_boundary.cpp", defines={})
            negative(fifo / "run", (), "independent FIFO oracle mismatch", fifo / "negative.log")
            fabric = test(gsim, cxx, name + "/fabric", "ooo.StagedFabricGsimMain", "StagedFabricGsim",
                          "staged_fabric.cpp", parameters=("direct-memory-response", "register-head"), defines={})
            negative(fabric / "run", (), "fabric response mismatch", fabric / "negative.log")
        if "routing" in args.only:
            routing = test(gsim, cxx, name + "/crossbar", "ip.TileLinkCrossbarGsimMain",
                           "TileLinkCrossbarGsim", "tilelink_crossbar.cpp",
                           parameters=("prefix-decode", "raw-replies", "raw-requests"), defines={})
            reject(routing / "run", "--inject-mismatch", "TileLink crossbar D source, data or owner mismatch",
                   routing / "mismatch-negative.log")
            reject(routing / "run", "--inject-wrong-source", "Two-master TileLink response has no matching source",
                   routing / "source-negative.log")
        if "vm" in args.only:
            payload = output / "vm-data"
            run(["riscv64-unknown-elf-gcc", "-march=rv64ia_zicsr", "-mabi=lp64", "-mno-relax",
                 "-nostdlib", "-nostartfiles", "-Wl,--no-relax", "-T", HERE / "payloads/machine-boot.ld",
                 HERE / "payloads/vm-data.S", "-o", payload.with_suffix(".elf")], log=output / "vm-build.log")
            run(["riscv64-unknown-elf-objcopy", "-O", "binary", "--only-section=.text",
                 payload.with_suffix(".elf"), payload.with_suffix(".bin")])
            parameters = ("coherent", "compact", "buffered-response", "registered-physical-owners",
                "registered-retirement", "registered-load-replay", "early-recovery-issue-block",
                "precomplete-mispredicted-branch", "registered-memory-requests", "buffered-translated-response")
            parameters += tuple("staged-" + stage for stage in ("fabric", "control", "execute", "rename", "retire",
                "redirect", "preparation", "payload", "return", "fetch-address", "fetch-control", "recovery-control",
                "execute-select", "frontend-select", "sensitive-paths", "decode-align", "rank-legality",
                "word-destination", "request-capture", "rom-boundary"))
            if control_heads:
                parameters += ("staged-control-heads",)
            if throughput:
                parameters += ("staged-throughput",)
            test(gsim, cxx, name + "/vm", "ooo.VmDataPlatformGsimMain", "VmDataPlatformGsim",
                 "vm_data_platform.cpp", parameters=parameters, runtime_args=(payload.with_suffix(".bin"), "--coherent"),
                 defines={})
        if "vm-fetch" in args.only:
            images = []
            for suffix, definitions in (("", []), ("-cross", ["-DCROSS_PAGE=1"])):
                stem = output / ("vm-instruction" + suffix)
                run(["riscv64-unknown-elf-gcc", *definitions, "-march=rv64imac_zicsr", "-mabi=lp64", "-mno-relax",
                     "-nostdlib", "-nostartfiles", "-Wl,--no-relax", "-T", HERE / "payloads/machine-boot.ld",
                     HERE / "payloads/vm-instruction.S", "-o", stem.with_suffix(".elf")], log=output / (stem.name + ".log"))
                run(["riscv64-unknown-elf-objcopy", "-O", "binary", "--only-section=.text",
                     stem.with_suffix(".elf"), stem.with_suffix(".bin")])
                image = stem.with_suffix(".bin")
                data = image.read_bytes()
                image.write_bytes(data.ljust((len(data) + 3) & ~3, b"\0"))
                images.append(image)
            parameters = ("fetch-addresses", "fetch-control", "frontend-select", "sensitive-paths", "decode-align",
                          "rank-legality", "request-capture", "rom-boundary")
            if control_heads:
                parameters += ("control-heads",)
            if throughput:
                parameters += ("throughput",)
            test(gsim, cxx, name + "/vm-fetch", "ooo.VmInstructionPlatformGsimMain", "VmInstructionPlatformGsim",
                 "vm_instruction_platform.cpp", parameters=parameters,
                 runtime_args=images, defines={})
        if "board" in args.only:
            report.update(board_apps(gsim, cxx, output, profile=args.profile, clock_hz=100_000_000, baud=460800))
            # Keep the saved application BINs for cycle comparison. Their 50 MHz
            # reporting constants do not turn this into a real 100 MHz score.
            report["same_binary_application_reporting_timebase_hz"] = 50_000_000
            firmware = output / "boot-firmware"
            run([sys.executable, ROOT / "fpga/firmware/build.py", "--out", firmware, "--ddr",
                 "--cpu-hz", "100000000"], log=output / "boot-firmware.log")
            # CPU-only throughput work reuses the short application model; the
            # unchanged UART download protocol has separate accepted evidence.
            # Do not repeat the 16M-cycle UART transfer on each CPU candidate.
            if throughput:
                report["uart_protocol_retested"] = False
                report["required_separate_evidence"] = ["throughput_perf", "pipeline_oracles"]
                report["status"] = "passed" if set(args.only) == set(required) else "partial-pass"
                return
            model = output / "board-model"
            binary = model / "board_boot"
            run([cxx, "-std=c++20", "-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                 "-DUART_DIVISOR=1", "-DBOARD_CPU_HZ=100000000", "-DBOARD_UART_BAUD=460800",
                 "-DUART_EXTRA_STOP_BITS=0", "-DDDR_MODEL=1", "-I" + str(model),
                 *sorted(model.glob("BoardSocGsim[0-9]*.o")), HERE / "harness/board_boot.cpp", "-ldl", "-o", binary],
                log=model / "board_boot.compile.log")
            run([binary, firmware / "bootrom.bin", firmware / "sample_app.bin"],
                env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}, log=model / "board_boot.log", timeout=600)
            print((model / "board_boot.log").read_text(), end="", flush=True)
        report["status"] = "passed" if set(args.only) == set(required) else "partial-pass"
    except (RuntimeError, subprocess.SubprocessError, OSError):
        report["status"] = "failed"
        raise
    finally:
        changed = throughput and (hardware_sources() != report["hardware_source_sha256"] or
                                 feedback_inputs() != report["feedback_inputs_sha256"])
        if changed:
            report["status"] = "failed"
            report["failure"] = "Hardware or feedback test input changed during acceptance"
        evidence.write_text(json.dumps(report, indent=2) + "\n")
        if changed:
            raise RuntimeError(report["failure"])
    print(f"ROM boundary short batch: {report['status']}; evidence: {evidence}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.SubprocessError, OSError) as error:
        print(f"GSIM ROM boundary: {error}", file=sys.stderr)
        sys.exit(1)
