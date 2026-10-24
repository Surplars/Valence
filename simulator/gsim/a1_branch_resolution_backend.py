#!/usr/bin/env python3
"""B2: matched decoded real-A1 backend branch-resolution transport qualification.

The two models differ only in branchResolutionTopology. CPU/NEMU throughput is a
separate matched fixture; these decoded-input cycles are never reported as CPU IPC.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import subprocess

import run as common


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inputs():
    files = sorted((common.ROOT / "src/main/scala").rglob("*.scala"))
    files += [common.ROOT / name for name in (
        "src/test/scala/ooo/A1DualBackendGsim.scala",
        "src/test/scala/ooo/BranchResolutionMailboxSpec.scala",
        "simulator/gsim/harness/a1_dual_backend.cpp",
        "simulator/gsim/a1_branch_resolution_backend.py", "simulator/gsim/run.py")]
    return {str(path.relative_to(common.ROOT)): sha(path) for path in files}


def metrics(log, require_final_pass=True):
    text = Path(log).read_text()
    if require_final_pass and "A1_DUAL_BACKEND_PASS" not in text:
        raise RuntimeError("independent backend acceptance marker absent")
    rows = [json.loads(line[len("A1_BACKEND_METRIC "):]) for line in text.splitlines()
        if line.startswith("A1_BACKEND_METRIC ")]
    if not rows or len({row["name"] for row in rows}) != len(rows):
        raise RuntimeError("missing or duplicate case measurements")
    return rows


def negative(binary, flag, marker, rejection, path):
    result = subprocess.run([str(binary), flag], capture_output=True, text=True, timeout=120,
        env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
    log = result.stdout + result.stderr
    path.write_text(log)
    if result.returncode == 0 or marker not in log or rejection not in log or \
            "AddressSanitizer" in log or "runtime error:" in log:
        raise RuntimeError("negative control failed to reach its precise oracle: " + flag)
    return {"status": "REJECTED", "returncode": result.returncode,
        "marker": marker, "rejection": rejection, "log_sha256": sha(path)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--build-run", action="store_true")
    parser.add_argument("--reuse-writeback-model", type=Path,
        help="reuse the immutable r1 baseline model and its four successful directed cases")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.tag):
        parser.error("tag must be a fresh filesystem-safe label")
    before = inputs()
    if not args.build_run:
        print(json.dumps({"status": "PREFLIGHT_ONLY", "source_count": len(before),
            "completionTopology": "dual-owner", "branchResolutionTopology":
            ["writeback-coupled", "execution-mailbox"], "backend_connected": True}))
        return
    out = common.BUILD / args.tag
    out.mkdir(parents=True, exist_ok=False)
    report = {"status": "RUNNING", "inputs": before, "backend_connected": True,
        "scope": "decoded real A1 backend, original 13 plus four matched branch programs; two stronger fault inputs are candidate-only defensive positives",
        "legacy_fault_scope": "controlFlow retained with fetch fault exceeds the real IntegerCore faultRequest contract; not a production frontend bug",
        "new_data_stages": 0, "redirect_minimum_latency": 1, "dispatch_writeback_commit_widths": [2, 2, 2],
        "timing_and_board": "UNVERIFIED", "cases": {}, "negative": {}}
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    try:
        gsim = common.SOURCE / "build/gsim/gsim"
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=common.SOURCE, text=True).strip()
        if revision != common.LOCK["revision"] or not gsim.is_file():
            raise RuntimeError("prebuilt pinned GSIM required; this runner never installs tools")
        cxx, compiler = common.compiler()
        report.update(compiler=compiler, gsim_revision=revision, gsim_sha256=sha(gsim))
        for topology in ("writeback-coupled", "execution-mailbox"):
            reuse = topology == "writeback-coupled" and args.reuse_writeback_model is not None
            if reuse:
                model = args.reuse_writeback_model.resolve()
                old_receipt = json.loads((model.parent / "receipt.json").read_text())
                if old_receipt["status"] != "FAIL" or "command failed (1)" not in old_receipt["failure"] or \
                        not old_receipt["inputs_unchanged"]:
                    raise RuntimeError("reuse requires the preserved baseline fault-input failure receipt")
                for key, value in before.items():
                    if key != "simulator/gsim/a1_branch_resolution_backend.py" and old_receipt["inputs"].get(key) != value:
                        raise RuntimeError("reused baseline source differs: " + key)
                report["reused_baseline"] = {"path": str(model), "receipt_sha256": sha(model.parent / "receipt.json"),
                    "artifacts": {str(path.relative_to(model)): sha(path) for path in sorted(model.rglob("*")) if path.is_file()}}
            else:
                model = common.test(gsim, cxx, args.tag + "/" + topology,
                    "soc.core.ooo.A1DualBackendGsimMain", "A1DualBackendGsim", "a1_dual_backend.cpp",
                    parameters=("dual-owner", topology), defines={"A1_DUAL_OWNER": 1,
                        "A1_BRANCH_FIXTURE": 1, "A1_BRANCH_MAILBOX": int(topology == "execution-mailbox")},
                    timeout=180)
            fir = (model / "A1DualBackendGsim.fir").read_text()
            structure = {"mailbox_instances": len(re.findall(r"\binst branchMailbox of BranchResolutionMailbox\b", fir)),
                "legacy_redirect_valid_registers": len(re.findall(r"\breg(?:reset)? branchRedirectValid\b", fir)),
                "legacy_redirect_payload_registers": len(re.findall(r"\breg(?:reset)? branchRedirect\b", fir)),
                "gsim_combinational_graph_lowered": True}
            expected = int(topology == "execution-mailbox")
            if structure["mailbox_instances"] != expected or \
                    structure["legacy_redirect_valid_registers"] != 1 - expected or \
                    structure["legacy_redirect_payload_registers"] != 1 - expected:
                raise RuntimeError("branch transport did not replace exactly one old register boundary")
            report.setdefault("structure", {})[topology] = structure
            report["cases"][topology] = {"existing13": metrics(model / "test.log")}
            if len(report["cases"][topology]["existing13"]) != 13:
                raise RuntimeError("B2 must preserve the original thirteen programs")
            run_dir = out / topology
            run_dir.mkdir(exist_ok=True)
            matched_names = ["mailbox_writeback_pressure", "mailbox_protected_store",
                "mailbox_protected_system", "mailbox_physical_branch_ages"]
            fault_names = ["mailbox_faulted_branch", "mailbox_page_faulted_branch"]
            branch_text = ""
            if topology == "execution-mailbox":
                common.run([model / "run", "--branch-mailbox-only"], log=run_dir / "branch-cases.log", timeout=180,
                    env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
                branch_text = (run_dir / "branch-cases.log").read_text()
                all_rows = metrics(run_dir / "branch-cases.log")
                if {row["name"] for row in all_rows} != set(matched_names + fault_names):
                    raise RuntimeError("candidate must pass all four matched plus two defensive fault cases")
                report["cases"][topology]["branch_directed"] = [r for r in all_rows if r["name"] in matched_names]
                report["cases"][topology]["defensive_faults"] = [r for r in all_rows if r["name"] in fault_names]
            else:
                rows = []
                if reuse:
                    old_log = model / "branch-cases.log"
                    branch_text = old_log.read_text()
                    rows = metrics(old_log, require_final_pass=False)
                    if {r["name"] for r in rows} != set(matched_names):
                        raise RuntimeError("preserved failed log lacks exactly the four completed matched cases")
                    for name in matched_names:
                        if "program=" + name + " " not in branch_text:
                            raise RuntimeError("preserved per-program pass witness missing")
                else:
                    for name in matched_names:
                        path = run_dir / (name + ".log")
                        common.run([model / "run", "--branch-mailbox-only", "--program", name], log=path, timeout=120,
                            env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
                        rows += metrics(path)
                        branch_text += path.read_text()
                report["cases"][topology]["branch_directed"] = rows
                report["legacy_fault_contract_rejections"] = {}
                for name in fault_names:
                    if reuse and name == fault_names[0]:
                        log = (model / "branch-cases.log").read_text()
                        returncode = 1
                        path = model / "branch-cases.log"
                    else:
                        result = subprocess.run([str(model / "run"), "--branch-mailbox-only", "--program", name],
                            capture_output=True, text=True, timeout=120,
                            env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
                        returncode = result.returncode
                        log = result.stdout + result.stderr
                        path = run_dir / (name + "-unsupported.log")
                        path.write_text(log)
                    rejection = "A1_DUAL_BACKEND_FAIL " + name + " cycle=6 redirect not justified by independent control flow"
                    if returncode != 1 or rejection not in log or "AddressSanitizer" in log or "runtime error:" in log:
                        raise RuntimeError("legacy fault-input case did not reach the exact unsupported-contract rejection")
                    report["legacy_fault_contract_rejections"][name] = {"status": "EXPECTED_UNSUPPORTED_INPUT_CONTRACT",
                        "returncode": returncode, "rejection": rejection, "log": str(path), "log_sha256": sha(path)}
            branch_rows = [json.loads(line[len("A1_BRANCH_METRIC "):]) for line in branch_text.splitlines()
                if line.startswith("A1_BRANCH_METRIC ")]
            if len(branch_rows) != (6 if topology == "execution-mailbox" else 4):
                raise RuntimeError("directed branch coverage records missing")
            report.setdefault("branch_coverage", {})[topology] = branch_rows
            report.setdefault("effective_parameters", {})[topology] = json.loads(
                (model / "effective-parameters.json").read_text())
            report["negative"][topology] = negative(model / "run", "--inject-mismatch",
                "A1_NEGATIVE_REACHED", "retirement data", out / (topology + "-negative.log"))
            if topology == "execution-mailbox":
                report["negative"]["branch-observer"] = negative(model / "run", "--inject-branch-mismatch",
                    "A1_BRANCH_NEGATIVE_REACHED", "independent mailbox capture oracle mismatch",
                    out / "branch-observer-negative.log")
        old_params = report["effective_parameters"]["writeback-coupled"]
        new_params = report["effective_parameters"]["execution-mailbox"]
        parameter_changes = {key: [old_params.get(key), new_params.get(key)]
            for key in old_params.keys() | new_params.keys() if old_params.get(key) != new_params.get(key)}
        if parameter_changes != {"branchResolutionTopology": ["writeback-coupled", "execution-mailbox"]}:
            raise RuntimeError("matched backend parameters changed beyond branch resolution topology")
        report["parameter_changes"] = parameter_changes
        report["comparison"] = {}
        for group in ("existing13", "branch_directed"):
            baseline = {r["name"]: r for r in report["cases"]["writeback-coupled"][group]}
            candidate = {r["name"]: r for r in report["cases"]["execution-mailbox"][group]}
            if baseline.keys() != candidate.keys():
                raise RuntimeError("mismatched architectural programs")
            comparison = []
            for name, old in baseline.items():
                new = candidate[name]
                if old["retired"] != new["retired"]:
                    raise RuntimeError("mismatched retired instruction stream")
                comparison.append({"name": name, "baseline_cycles": old["cycles"],
                    "candidate_cycles": new["cycles"], "retired": old["retired"],
                    "same_clock_speedup": old["cycles"] / new["cycles"]})
            report["comparison"][group] = comparison
        report["status"] = "PASS_B2_DECODED_BACKEND"
    except Exception as error:
        report.update(status="FAIL", failure=str(error))
        raise
    finally:
        report["inputs_unchanged"] = inputs() == before
        if not report["inputs_unchanged"]:
            report["status"] = "FAIL_INPUT_DRIFT"
        report["artifacts"] = {str(path.relative_to(out)): sha(path) for path in sorted(out.rglob("*"))
            if path.is_file() and path.name != "receipt.json"}
        (out / "receipt.json").write_text(json.dumps(report, indent=2) + "\n")
    if report["status"] != "PASS_B2_DECODED_BACKEND":
        raise RuntimeError(report["status"])
    print(json.dumps({"status": report["status"], "evidence": str(out), "comparison": report["comparison"]}))


if __name__ == "__main__":
    main()
