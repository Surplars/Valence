#!/usr/bin/env python3
"""Matched, bounded CommonA1 CPU retirement fixture; preflight unless opted in.

--build-run builds one actual full-tile model per fetch profile and reuses that
model for the six ROM/RAM cases and sampled-observation negative controls.
--oracle-only compiles only the independent C++ oracle, never a hardware model.
Source the already prepared toolchain environment first. This runner never sets
up tools, changes presets, runs a broad regression, or makes a frequency claim.
"""

import argparse
import hashlib
import itertools
import json
import os
from pathlib import Path
import re
import resource
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
import run as common


BASE = "combined-branch"
MAIN = "platform.CommonA1CpuRetirementGsimMain"
TOP = "CommonA1CpuRetirementGsim"
FIXTURE = "src/test/scala/platform/CommonA1CpuRetirementGsim.scala"
HOST = common.HERE / "harness/a1_common_cpu_retirement.cpp"
PROFILES = {"legacy": (1, False), "single-page": (1, True), "dual-slot": (2, True)}
CASES = tuple(itertools.product(("independent_alu", "dependent_chain", "branches"), ("rom", "ram")))
METRIC_PREFIX = "A1_COMMON_CPU_METRIC "
PASS = "A1_COMMON_CPU_RETIREMENT_PASS"
ORACLE_PASS = "A1_COMMON_CPU_ORACLE_PASS"
NEGATIVES = {
    "--inject-retirement-data": "A1_RETIREMENT_NEGATIVE_REACHED",
    "--inject-manager-source": "A1_MANAGER_NEGATIVE_REACHED",
}
REJECTIONS = {"--inject-retirement-data": "data pc=", "--inject-manager-source": "D source has no accepted Get"}
COUNTERS = (
    "work_cycles", "retired", "accepted_instructions", "virtual_fetch_requests",
    "physical_fetch_requests", "tl_requests", "tl_beats", "drain_cycles",
    "inspection_cycles", "dual_commit_cycles", "bootstrap_cycles", "roi_cycles",
    "bootstrap_retired", "roi_retired",
)
SCOPE = {
    "dut": "actual CommonA1CpuTile, fixed CombinedBranch base; not decoded-input backend",
    "programs": "three bounded integer programs, each in ROM and RAM",
    "execution": "M-mode/Bare only; RAM entry uses the fixed ROM bootstrap",
    "retained": "real 32 KiB L1I and L1D, two-wide backend, ROB16/PRF48, VM/PMP/FPU",
    "not_qualified": [
        "VM translations, PMP protection, FPU semantics or ISA compliance",
        "Common fabric, real ROM/DDR service timing, CDC, Linux or board operation",
        "routed timing, MHz/Fmax, PPA, general workload speedup or full regression",
    ],
    "cycle_scope": "work is boot-inclusive start-to-terminal; bootstrap, ROI, drain and inspection are separate",
    "roi_scope": "RAM ROI begins the cycle after final bootstrap retirement through terminal trap; ROM has no bootstrap",
    "comparison_scope": "same program and placement only; ROM and RAM ROI entry states are not matched",
    "negative_scope": "sampled observation mutations; not modified DUT implementations",
}


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def digest_json(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def source_inputs():
    """Hash actual Mill inputs, fixture/host dependencies and build entry points.

    Re-enumerate on every call so adding/removing a source is input drift too.
    All test Scala sources are included because IonSoC.test compiles them even
    when this fixture is the only runMain target.
    """
    required = [common.ROOT / name for name in (
        FIXTURE, "simulator/gsim/harness/a1_common_cpu_retirement.cpp",
        "simulator/gsim/a1_common_cpu_retirement.py", "simulator/gsim/run.py",
        "build.mill", ".mill-version", ".mill-jvm-opts",
        "simulator/gsim/config/toolchain.json", "simulator/gsim/config/opensbi.json",
    )]
    for path in required:
        if not path.is_file():
            raise RuntimeError("required fixture/build input missing: " + str(path))
    files = set(required)
    for directory in ("src/main/scala", "src/test/scala", "third_party/berkeley-hardfloat/src/main/scala"):
        root = common.ROOT / directory
        found = list(root.rglob("*.scala"))
        if not found:
            raise RuntimeError("required Scala source tree missing or empty: " + str(root))
        files.update(found)
    for pattern in ("*.h", "*.hpp", "*.inc"):
        files.update((common.HERE / "harness").rglob(pattern))
    files.update((common.HERE / "config").rglob("*.json"))
    for name in ("Makefile", ".gitmodules", "project/build.properties", "project/plugins.sbt"):
        path = common.ROOT / name
        if path.is_file():
            files.add(path)
    return {str(path.relative_to(common.ROOT)): sha(path) for path in sorted(files)}


def git(source, *args):
    return subprocess.check_output(["git", *args], cwd=source, text=True, timeout=30)


def executable_binding(command):
    found = shutil.which(str(command))
    if not found:
        raise RuntimeError("prepared tool not on PATH: " + str(command))
    path = Path(found).resolve(strict=True)
    return {"command": str(command), "path": str(path), "sha256": sha(path)}


def tool_sources(source):
    names = set(git(source, "ls-files", "-z", "--cached", "--others", "--exclude-standard").split("\0"))
    gitlinks = {}
    for entry in git(source, "ls-files", "--stage", "-z").split("\0"):
        if entry:
            metadata, name = entry.split("\t", 1)
            mode, revision, _ = metadata.split()
            if mode == "160000":
                gitlinks[name] = revision
    hashes = {}
    for name in sorted(names - {""}):
        path = source / name
        if name in gitlinks:
            entry = {"index_gitlink": gitlinks[name], "initialized": (path / ".git").exists()}
            if entry["initialized"]:
                entry.update(revision=git(path, "rev-parse", "HEAD").strip(),
                             status=git(path, "status", "--porcelain", "--untracked-files=all"),
                             sources=tool_sources(path))
            else:
                entry["present_files"] = {str(p.relative_to(path)): sha(p)
                                          for p in sorted(path.rglob("*")) if p.is_file()}
            hashes[name] = entry
        elif path.is_file():
            hashes[name] = sha(path)
        elif not path.exists():
            hashes[name] = "MISSING"
        else:
            raise RuntimeError("cannot bind non-file GSIM dependency: " + str(path))
    return hashes


def tool_binding(hardware):
    cxx, version = common.compiler()
    result = {"compiler": {**executable_binding(cxx), "version": version}}
    if not hardware:
        return result
    gsim = common.SOURCE / "build/gsim/gsim"
    if not gsim.is_file():
        raise RuntimeError("prebuilt GSIM missing; prepare the toolchain separately: " + str(gsim))
    revision = git(common.SOURCE, "rev-parse", "HEAD").strip()
    if revision != common.LOCK["revision"]:
        raise RuntimeError("prepared GSIM revision differs from the repository toolchain pin")
    # Prepared/qualified local patches are allowed, but never hidden by a clean
    # upstream revision label. Bind every tracked and nonignored untracked file.
    source_hashes = tool_sources(common.SOURCE)
    result.update(
        mill=executable_binding("mill"), java=executable_binding("java"),
        gsim={"path": str(gsim.resolve()), "sha256": sha(gsim), "source": str(common.SOURCE),
              "revision": revision, "pinned_revision": common.LOCK["revision"],
              "working_tree_status": git(common.SOURCE, "status", "--porcelain", "--untracked-files=all"),
              "source_sha256": source_hashes, "source_manifest_sha256": digest_json(source_hashes),
              "patch_policy": "record prepared local changes exactly; no installation or implicit tool qualification"},
    )
    return result


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field: " + key)
        result[key] = value
    return result


def read_json(text):
    def invalid(value):
        raise ValueError("non-finite JSON number: " + value)
    return json.loads(text, object_pairs_hook=unique_object, parse_constant=invalid)


def check_log(text):
    if any(marker in text for marker in ("Sanitizer", "runtime error:")):
        raise RuntimeError("sanitizer diagnostic cannot count as oracle acceptance/rejection")


def metrics(log):
    text = Path(log).read_text()
    check_log(text)
    if text.splitlines().count(PASS) != 1:
        raise RuntimeError("missing or duplicate full-tile retirement acceptance marker")
    if any(marker in text for marker in NEGATIVES.values()):
        raise RuntimeError("positive execution reached a negative-control mutation")
    rows = []
    seen = set()
    for line in text.splitlines():
        if not line.startswith(METRIC_PREFIX):
            continue
        row = read_json(line[len(METRIC_PREFIX):])
        if not isinstance(row, dict):
            raise RuntimeError("metric must be a JSON object")
        key = (row.get("name"), row.get("placement"))
        if key not in CASES or key in seen:
            raise RuntimeError("unknown or duplicate program/placement metric: " + str(key))
        for field in COUNTERS:
            value = row.get(field)
            if type(value) is not int or value < 0:
                raise RuntimeError("missing/noninteger/negative metric " + field + " in " + str(key))
        if not row["work_cycles"] or not row["retired"] or not row["roi_cycles"] or not row["roi_retired"]:
            raise RuntimeError("empty completed CPU workload: " + str(key))
        if row["bootstrap_retired"] + row["roi_retired"] != row["retired"]:
            raise RuntimeError("boot-inclusive retirement accounting mismatch: " + str(key))
        if row["bootstrap_cycles"] + row["roi_cycles"] != row["work_cycles"]:
            raise RuntimeError("boot-inclusive cycle accounting mismatch: " + str(key))
        if row["bootstrap_retired"] != (2 if row["placement"] == "ram" else 0):
            raise RuntimeError("unexpected fixed RAM bootstrap retirement count: " + str(key))
        if row["placement"] == "rom" and row["bootstrap_cycles"] != 0:
            raise RuntimeError("ROM workload incorrectly includes bootstrap cycles")
        if row["retired"] > 2 * row["work_cycles"] or row["dual_commit_cycles"] > row["work_cycles"]:
            raise RuntimeError("two-wide retirement counters exceed measured work interval")
        seen.add(key)
        rows.append(row)
    if seen != set(CASES):
        raise RuntimeError("expected exactly six complete ROM/RAM program measurements")
    return sorted(rows, key=lambda row: CASES.index((row["name"], row["placement"])))


def oracle_cases(text):
    rows = {}
    prefix = "A1_COMMON_CPU_ORACLE_CASE "
    for line in text.splitlines():
        if not line.startswith(prefix):
            continue
        fields = unique_object(item.split("=", 1) for item in line[len(prefix):].split())
        key = (fields.get("name"), fields.get("placement"))
        if key not in CASES or key in rows:
            raise RuntimeError("unknown or duplicate independent oracle case")
        count = int(fields["retired"])
        if not 400 <= count < 1000 or not re.fullmatch(r"0x[0-9a-f]+", fields.get("trap_pc", "")):
            raise RuntimeError("incomplete independent oracle program result")
        rows[key] = {**fields, "retired": count}
    if set(rows) != set(CASES):
        raise RuntimeError("independent oracle must complete all six ROM/RAM programs")
    for name in {case[0] for case in CASES}:
        if rows[name, "ram"]["retired"] != rows[name, "rom"]["retired"] + 2:
            raise RuntimeError("independent oracle RAM bootstrap does not add exactly two retirements")
    return [rows[case] for case in CASES]


def load_parameters(model):
    result = {}
    for kind, filename in (("config", "effective-config.json"), ("core", "effective-parameters.json")):
        value = read_json((model / filename).read_text())
        if not isinstance(value, dict) or not value or any(type(item) is not str for item in value.values()):
            raise RuntimeError(filename + " must contain all actual flat stringified case-class fields")
        result[kind] = value
    result["geometry"] = read_json((model / "effective-geometry.json").read_text())
    return result


def parameter_changes(effective):
    if set(effective) != set(PROFILES):
        raise RuntimeError("all three actual effective configurations are required")
    expected_geometry = {"instructionCacheBytes": 32768, "dataCacheBytes": 32768, "cacheWays": 2,
                         "isaProfile": "rv64gc", "robEntries": 16, "physicalRegs": 48, "lsuEntries": 4,
                         "dataTranslationEntries": 16, "pmpEntries": 16, "virtualMemoryLevels": 3,
                         "fpEnabled": True, "romBytes": 128 * 1024, "ramBase": str(0x80200000),
                         "ramBytes": str(2 * 1024 * 1024 * 1024)}
    for profile, (slots, aligned) in PROFILES.items():
        config, core = effective[profile]["config"], effective[profile]["core"]
        geometry = effective[profile].get("geometry")
        if not isinstance(geometry, dict):
            raise RuntimeError("actual derived geometry artifact missing")
        for field, value in expected_geometry.items():
            if geometry.get(field) != value or type(geometry.get(field)) is not type(value):
                raise RuntimeError(f"{profile} actual geometry.{field} is not {value}")
        if geometry != effective["legacy"]["geometry"]:
            raise RuntimeError("actual geometry changed between matched fetch profiles")
        expected_config = {"fetchTransactionSlots": str(slots), "alignedFetchSinglePage": str(aligned).lower(),
                           "completionTopology": "dual-owner", "branchResolutionTopology": "execution-mailbox"}
        expected_core = {"alignedFetchSinglePage": str(aligned).lower(), "robEntries": "16", "physicalRegs": "48",
                         "renameWidth": "2", "completionWidth": "2", "commitWidth": "2", "memoryEntries": "4",
                         "storeBufferEntries": "2", "pmpEntries": "16", "virtualMemoryLevels": "3"}
        for kind, actual, expected in (("config", config, expected_config), ("core", core, expected_core)):
            for field, value in expected.items():
                if actual.get(field) != value:
                    raise RuntimeError(f"{profile} actual {kind}.{field} is not {value}")
    comparisons = {}
    for before, after in itertools.combinations(PROFILES, 2):
        pair = {}
        for kind in ("config", "core"):
            old, new = effective[before][kind], effective[after][kind]
            if old.keys() != new.keys():
                raise RuntimeError("effective parameter fields differ between profiles")
            changes = {key: [old[key], new[key]] for key in sorted(old) if old[key] != new[key]}
            allowed = ("fetchTransactionSlots", "alignedFetchSinglePage") if kind == "config" else ("alignedFetchSinglePage",)
            expected = {key: [old[key], new[key]] for key in allowed if old[key] != new[key]}
            if changes != expected:
                raise RuntimeError(f"{before} to {after} changed {kind} beyond the explicit fetch knobs: {changes}")
            pair[kind] = changes
        comparisons[before + "_to_" + after] = pair
    return comparisons


def comparisons(cases):
    if set(cases) != set(PROFILES):
        raise RuntimeError("all three completed profiles are required for cycle comparisons")
    indexed = {profile: {(row["name"], row["placement"]): row for row in rows} for profile, rows in cases.items()}
    if any(set(rows) != set(CASES) for rows in indexed.values()):
        raise RuntimeError("mismatched CPU program/placement sets")
    result = []
    for name, placement in CASES:
        rows = {profile: indexed[profile][name, placement] for profile in PROFILES}
        for field in ("retired", "bootstrap_retired", "roi_retired"):
            if len({row[field] for row in rows.values()}) != 1:
                raise RuntimeError(f"different architectural {field} for {name}/{placement}")
        pairs = []
        for before, after in itertools.combinations(PROFILES, 2):
            delta = {field: {"before": rows[before][field], "after": rows[after][field],
                             "delta_after_minus_before": rows[after][field] - rows[before][field]}
                     for field in ("work_cycles", "bootstrap_cycles", "roi_cycles", "drain_cycles", "inspection_cycles")}
            pairs.append({"before_profile": before, "after_profile": after, "cycles": delta})
        result.append({"name": name, "placement": placement, "retired": rows["legacy"]["retired"],
                       "roi_retired": rows["legacy"]["roi_retired"], "pairs": pairs})
    return result


def negative(binary, flag, marker, log, timeout):
    with log.open("x") as stream:
        result = subprocess.run([str(binary), flag], stdout=stream, stderr=subprocess.STDOUT,
                                timeout=timeout, env=runtime_env())
    text = log.read_text()
    check_log(text)
    reached = len(re.findall(r"(?<!\S)" + re.escape(marker) + r"(?!\S)", text))
    if result.returncode <= 0 or reached != 1 or PASS in text or ORACLE_PASS in text:
        raise RuntimeError("negative control did not reach and reject its sampled mutation: " + flag)
    if "A1_COMMON_CPU_RETIREMENT_FAIL " not in text:
        raise RuntimeError("negative control exited without the host's checked rejection")
    if marker + " " + REJECTIONS[flag] not in text:
        raise RuntimeError("negative control reached an unrelated rejection: " + flag)
    if any(other != marker and other in text for other in NEGATIVES.values()):
        raise RuntimeError("negative control reached the wrong mutation")
    return {"status": "REJECTED", "flag": flag, "returncode": result.returncode,
            "marker": marker, "rejection": REJECTIONS[flag], "log_sha256": sha(log),
            "scope": "sampled observation mutation"}


def runtime_env():
    return {**os.environ, "ASAN_OPTIONS": "detect_leaks=0:halt_on_error=1",
            "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"}


def save_receipt(out, report):
    temporary = out / "receipt.json.tmp"
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    temporary.replace(out / "receipt.json")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--build-run", action="store_true", help="explicitly build/run three hardware models")
    action.add_argument("--oracle-only", action="store_true", help="compile/run the independent host oracle only")
    parser.add_argument("--tag", help="fresh filesystem-safe evidence directory name, required for either action")
    parser.add_argument("--base", choices=[BASE], default=BASE, help="fixed non-fetch configuration for all models")
    parser.add_argument("--timeout", type=int, choices=(180, 300), default=300, help="bounded host runtime per invocation")
    args = parser.parse_args()
    if args.tag is not None and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}", args.tag):
        parser.error("tag must be a fresh filesystem-safe label of at most 96 characters")
    execute = args.build_run or args.oracle_only
    if execute and not args.tag:
        parser.error("execution requires a fresh --tag; existing directories are never reused")
    before = source_inputs()
    if not execute:
        print(json.dumps({"status": "PREFLIGHT_ONLY", "base": args.base, "profiles": PROFILES,
                          "cases": CASES, "source_count": len(before), "inputs_sha256": digest_json(before),
                          "scope": SCOPE, "build_or_simulation_started": False}, indent=2))
        return
    out = common.BUILD / args.tag
    out.mkdir(parents=True, exist_ok=False)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    report = {"schema": "a1-common-cpu-retirement-v1", "status": "RUNNING", "base": args.base,
              "mode": "hardware" if args.build_run else "oracle-only", "profiles": PROFILES,
              "scope": SCOPE, "inputs_before": before, "inputs_before_sha256": digest_json(before),
              "host_source_sha256": sha(HOST), "cases": {}, "negative_controls": {},
              "effective_parameters": {}, "timeout_seconds": args.timeout}
    tools_before = None
    try:
        report["source_revision"] = git(common.ROOT, "rev-parse", "HEAD").strip()
        report["source_working_tree_status"] = git(common.ROOT, "status", "--porcelain", "--untracked-files=all")
        tools_before = tool_binding(args.build_run)
        report["tools_before"] = tools_before
        save_receipt(out, report)
        cxx = tools_before["compiler"]["command"]
        if args.oracle_only:
            binary = out / "oracle"
            command = [cxx, "-std=c++20", "-O1", "-g", "-fsanitize=address,undefined",
                       "-fno-sanitize-recover=all", "-DA1_COMMON_ORACLE_ONLY=1", HOST, "-o", binary]
            report["oracle_compile_command"] = list(map(str, command))
            common.run(command, log=out / "compile.log", timeout=180)
            common.run([binary, "--oracle-only"], log=out / "oracle.log", timeout=30, env=runtime_env())
            text = (out / "oracle.log").read_text()
            check_log(text)
            if text.splitlines().count(ORACLE_PASS) != 1 or PASS in text:
                raise RuntimeError("independent host-only acceptance marker absent or hardware marker present")
            report["oracle_cases"] = oracle_cases(text)
            report["status"] = "PASS_HOST_ORACLE_ONLY_NO_HARDWARE"
            report["oracle_binary_sha256"] = sha(binary)
            for flag, marker in NEGATIVES.items():
                report["negative_controls"][flag] = negative(
                    binary, flag, marker, out / (flag[2:] + ".log"), 30)
        else:
            for profile in PROFILES:
                if source_inputs() != before or tool_binding(True) != tools_before:
                    raise RuntimeError("source or tool input drift before profile " + profile)
                model = common.test(Path(tools_before["gsim"]["path"]), cxx, args.tag + "/" + profile,
                                    MAIN, TOP, HOST.name, parameters=(profile, args.base),
                                    defines={}, timeout=args.timeout)
                report["effective_parameters"][profile] = load_parameters(model)
                report["cases"][profile] = metrics(model / "test.log")
                report["negative_controls"][profile] = []
                for flag, marker in NEGATIVES.items():
                    report["negative_controls"][profile].append(
                        negative(model / "run", flag, marker, model / (flag[2:] + ".log"), args.timeout))
                report.setdefault("models", {})[profile] = {
                    "emitter": MAIN, "top": TOP, "parameters": [profile, args.base],
                    "fir_sha256": sha(model / (TOP + ".fir")), "executable_sha256": sha(model / "run"),
                    "positive_invocations": 1, "cases_per_model": len(CASES), "negative_invocations": len(NEGATIVES),
                }
                save_receipt(out, report)
            report["parameter_changes"] = parameter_changes(report["effective_parameters"])
            report["comparisons"] = comparisons(report["cases"])
            report["status"] = "PASS_BOUNDED_COMMON_A1_CPU_RETIREMENT"
    except BaseException as error:
        report.update(status="FAIL", failure=f"{type(error).__name__}: {error}")
        raise
    finally:
        try:
            after = source_inputs()
            report["inputs_after"] = after
            report["inputs_after_sha256"] = digest_json(after)
            report["inputs_unchanged"] = after == before
            report["input_changes"] = {key: [before.get(key), after.get(key)]
                                       for key in sorted(before.keys() | after.keys()) if before.get(key) != after.get(key)}
        except Exception as error:
            report.update(inputs_unchanged=False, input_verification_error=str(error))
        if tools_before is not None:
            try:
                report["tools_after"] = tool_binding(args.build_run)
                report["tools_unchanged"] = report["tools_after"] == tools_before
            except Exception as error:
                report.update(tools_unchanged=False, tool_verification_error=str(error))
        if not report["inputs_unchanged"] or (tools_before is not None and not report.get("tools_unchanged")):
            report["status"] = "FAIL_INPUT_DRIFT"
        report["artifacts_sha256"] = {}
        try:
            for path in sorted(out.rglob("*")):
                if path.is_file() and path.name not in ("receipt.json", "receipt.json.tmp"):
                    report["artifacts_sha256"][str(path.relative_to(out))] = sha(path)
        except Exception as error:
            report["artifact_verification_error"] = str(error)
            if report["status"].startswith("PASS_"):
                report["status"] = "FAIL_ARTIFACT_VERIFICATION"
        save_receipt(out, report)
    if not report["status"].startswith("PASS_"):
        raise RuntimeError(report["status"] + "; see " + str(out / "receipt.json"))
    print(json.dumps({"status": report["status"], "evidence": str(out),
                      "comparisons": report.get("comparisons", []), "scope": SCOPE}, indent=2))


if __name__ == "__main__":
    main()
