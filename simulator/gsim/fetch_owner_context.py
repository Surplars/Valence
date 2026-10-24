#!/usr/bin/env python3
"""P1 immutable physical fetch privilege: explicit owner contract and exact A2 supply comparison."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

import a1_fetch_supply as supply
import a1_common_cpu_retirement as cpu
import a2_fetch
import run as common

HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def negative(executable, output, flag, diagnostic, marker):
    result = subprocess.run([str(executable), flag], capture_output=True, text=True, timeout=60,
                            env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
    log = result.stdout + result.stderr
    (output / (flag[2:] + ".log")).write_text(log)
    assert result.returncode == 1 and diagnostic in log and marker in log, (flag, result.returncode, log)
    assert "ERROR: AddressSanitizer" not in log and "runtime error:" not in log, log
    return {"flag": flag, "exit": result.returncode, "diagnostic": diagnostic, "marker": marker}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gsim", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--baseline", type=Path, required=True, help="retained full A2 frontend receipt")
    parser.add_argument("--cpu-baseline", type=Path, help="also rebuild only dual-slot actual CPU and compare A2")
    args = parser.parse_args()
    assert re.fullmatch(r"[A-Za-z0-9_-]+", args.tag)
    output = common.BUILD / args.tag
    assert not output.exists(), "fresh evidence directory required"
    gsim = args.gsim.resolve(strict=True)
    cxx, compiler = common.compiler()
    baseline = json.loads(args.baseline.read_text())
    assert baseline["status"] == "PASS_A2_TWO_OWNER_FETCH_WITH_MATCHED_WARM_SUPPLY"
    sources = sorted((common.ROOT / "src/main/scala").rglob("*.scala")) + [
        common.ROOT / "src/test/scala/ooo/A1FetchSupplyGsim.scala",
        common.ROOT / "src/test/scala/ooo/FetchOwnerContextSpec.scala",
        common.ROOT / "src/test/scala/ooo/FetchRequestContextGsim.scala",
        common.ROOT / "src/test/scala/ooo/FetchOwnerPermissionGsim.scala",
        HERE / "fetch_owner_context.py", HERE / "a1_fetch_supply.py", HERE / "a2_fetch.py", HERE / "run.py",
        HERE / "a1_fetch_supply/driver.cpp", HERE / "a1_fetch_supply/oracle.h",
        HERE / "a1_fetch_supply/oracle_test.cpp", HERE / "a2_fetch/warm.cpp",
    ] + sorted((HERE / "fetch_owner_context").glob("*.cpp"))
    inputs = {str(path.relative_to(common.ROOT)): sha(path) for path in sources}
    cpu_inputs = cpu.source_inputs() if args.cpu_baseline else None
    cpu_tools = cpu.tool_binding(True) if args.cpu_baseline else None
    tool_hash = sha(gsim)
    host_oracle = supply.oracle_only(cxx)
    units, negatives, models = [], [], {}
    for mode in ("registered", "flow", "independent"):
        model = common.test(gsim, cxx, f"{args.tag}/buffer-{mode}", "ooo.FetchRequestContextGsimMain",
                            "FetchRequestContextGsim", "../fetch_owner_context/buffer.cpp", parameters=(mode,),
                            defines={}, timeout=60)
        log = (model / "test.log").read_text()
        assert log.count("PASS FETCH_REQUEST_CONTEXT_BUFFER ") == 1
        units.append({"model": "buffer-" + mode, "log": log.strip()})
        negatives.append({"model": "buffer-" + mode, **negative(model / "run", model, "--inject-context",
            "independent accepted request-context oracle mismatch: injected context observation", "INJECT context")})
    for slots in (1, 2):
        model = common.test(gsim, cxx, f"{args.tag}/permission-{slots}", "ooo.FetchOwnerPermissionGsimMain",
                            "FetchOwnerPermissionGsim", "../fetch_owner_context/permission.cpp",
                            parameters=(str(slots),), defines={}, timeout=60)
        log = (model / "test.log").read_text()
        assert log.count("PASS PMP_FETCH_LINE_IMPLICATION ") == 1
        assert log.count("PASS FETCH_OWNER_PERMISSION ") == 1
        units.append({"model": f"permission-{slots}", "log": log.strip()})
        negatives.append({"model": f"permission-{slots}", **negative(model / "run", model,
            "--inject-cache-context", "owner context not used for legal M line authorization", "INJECT cache context")})
    fields = 0
    for label, slots, aligned in (("original", 1, False), ("aligned-control", 1, True), ("two-owner", 2, True)):
        model = common.test(gsim, cxx, f"{args.tag}/{label}", "ooo.A2FetchSupplyGsimMain", "A1FetchSupplyGsim",
                            "../a1_fetch_supply/driver.cpp", parameters=(str(slots), str(aligned).lower()),
                            defines={}, timeout=120)
        rows = supply.parse((model / "test.log").read_text())
        assert rows == baseline["models"][label]["scenarios"], (label, "P1 changed an A2 cold supply field")
        fields += sum(len(row) for row in rows.values())
        warm = model / "run-warm"
        common.run([cxx, "-std=c++20", "-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                    "-I" + str(model), *sorted(model.glob("A1FetchSupplyGsim[0-9]*.cpp")),
                    HERE / "a2_fetch/warm.cpp", "-ldl", "-o", warm], log=model / "warm-compile.log")
        common.run([warm], log=model / "warm.log", timeout=120,
                   env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
        warm_rows = a2_fetch.parse_warm((model / "warm.log").read_text())
        assert warm_rows == baseline["models"][label]["warm"], (label, "P1 changed an A2 warm supply field")
        fields += sum(len(row) for row in warm_rows.values())
        models[label] = {"scenarios": rows, "warm": warm_rows}
        if label == "two-owner":
            for flag, diagnostic in (
                ("--inject-pc", "consumed PC duplicated, skipped, or from old path"),
                ("--inject-data", "instruction differs from independent memory bytes"),
                ("--inject-tval", "fault tval is not first failing required parcel"),
                ("--inject-source", "D without source owner"),
            ):
                # Preserve existing observation negatives with their exact old diagnostics.
                negatives.append({"model": label, **a2_fetch.negative(model / "run", model, flag, diagnostic)})
    cpu_result = None
    if args.cpu_baseline:
        reference = cpu.read_json(args.cpu_baseline.read_text())
        assert reference["status"] == "PASS_BOUNDED_COMMON_A1_CPU_RETIREMENT"
        assert cpu.source_inputs() == cpu_inputs and cpu.tool_binding(True) == cpu_tools, "pre-CPU input drift"
        model = common.test(gsim, cxx, f"{args.tag}/cpu-dual-slot", cpu.MAIN, cpu.TOP, cpu.HOST.name,
                            parameters=("dual-slot", cpu.BASE), defines={}, timeout=300)
        rows = cpu.metrics(model / "test.log")
        parameters = cpu.load_parameters(model)
        assert rows == reference["cases"]["dual-slot"], "P1 changed an A2 dual-slot CPU metric"
        assert parameters == reference["effective_parameters"]["dual-slot"], "P1 changed the actual CPU configuration"
        controls = [cpu.negative(model / "run", flag, marker, model / (flag[2:] + ".log"), 60)
                    for flag, marker in cpu.NEGATIVES.items()]
        cpu_result = {"status": "PASS_EXACT_A2_DUAL_SLOT_CPU", "cases": rows, "negativeControls": controls,
                      "effectiveParameters": parameters, "baselineSha256": sha(args.cpu_baseline),
                      "firSha256": sha(model / (cpu.TOP + ".fir")), "executableSha256": sha(model / "run"),
                      "scope": cpu.SCOPE, "notRebuilt": ["legacy", "single-page"]}
        assert cpu.source_inputs() == cpu_inputs and cpu.tool_binding(True) == cpu_tools, "post-CPU input drift"
    assert inputs == {str(path.relative_to(common.ROOT)): sha(path) for path in sources}, "P1 source drift"
    assert tool_hash == sha(gsim), "P1 tool drift"
    receipt = {"status": "PASS_P1_OWNER_CONTRACT_AND_EXACT_A2_SUPPLY", "sourceSha256": inputs,
               "gsimSha256": tool_hash, "compiler": compiler, "baselineSha256": sha(args.baseline),
               "hostOracle": host_oracle.strip(), "unitChecks": units, "negativeControls": negatives,
               "models": models, "exactComparedFields": fields, "serviceLaw": supply.SERVICE_LAW,
               "cpu": cpu_result, "cpuSourceSha256": cpu_inputs, "cpuTools": cpu_tools,
               "limits": ["Only dual-slot CPU is rebuilt when --cpu-baseline is supplied; single-owner CPU is not rerun",
                          "MSU trap issuer is a legal host stimulus, not a full ROB exception-selection proof",
                          "P1 is explicit owner-contract hardening, not a reproduced privilege-expansion vulnerability fix",
                          "Only explicitly context-enabled demand paths are qualified; prefetch is rejected",
                          "No Fmax, PPA, CDC, board, Linux or full regression qualification"]}
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(f"PASS P1 explicit owner contract; all {fields} cold/warm A2 supply fields identical")


if __name__ == "__main__":
    main()
