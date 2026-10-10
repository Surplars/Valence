#!/usr/bin/env python3
"""Bind, then run the serial actual-CPU lineage gate with existing pinned tools.

`bind` only reads source/tools and writes a new binding. `run` requires an explicit
slot grant and a binding digest. Neither action calls setup, make, or downloads.
The downstream device is a synthetic 512-cycle retention contract, not a cache.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
RELATIVE = Path("simulator/gsim/posted_cpu/run_lineage.py")
TOP = "PostedStoreCpuLineageGsim"
CASES = (
    "physical-lineage-reuse-load-aplic-fence-context-recovery",
    "precise-misaligned-store", "precise-locked-pmp-store",
    "precise-virtual-store-page-fault", "successful-virtual-store-no-proof",
)
CONTROLS = ("token", "byte")
PASS = "GSIM CPU posted-store lineage: PASS;"
REJECT = "immutable full-token/epoch/payload lineage mismatch"
EPOCH_CONTROLS = ("CPU_POSTED_EPOCH_ORACLE delayed_old_rejected=1 external_old_rejected=1"
                  " same_tick_old_reply_rejected=1 empty_old_new_start_allowed=1")
CANCEL_CONTROLS = ("CPU_POSTED_CANCEL_ORACLE store_rejected=1 older_load_rejected=1 wrong_tag_rejected=1"
                   " wrong_epoch_rejected=1 late_response_rejected=1 fake_completion_rejected=1 fake_retirement_rejected=1")
ENV_KEYS = ("PATH", "JAVA_HOME", "JAVA_TOOL_OPTIONS", "COURSIER_CACHE", "COURSIER_REPOSITORIES",
            "CHISEL_FIRTOOL_PATH", "FIRTOOL", "LD_LIBRARY_PATH", "GSIM_CXX", "VALENCE_CLOUD_ENV",
            "VALENCE_GSIM_SOURCE", "XDG_CACHE_HOME", "CPATH", "LIBRARY_PATH")
PROFILE = dict(issueWidth=2, robEntries=16, memoryEntries=4, dataTranslationEntries=16,
               virtualRamLoadPrecheck=True, preparedStoreLookahead=True, storeNextLinePrefetch=True,
               storePrefetchMruInsertion=True, physicalLoadIngressFlow=True,
               loadOrderOlderRetire=True, fetchPreviousPacket=True,
               precheckedDataRequestFlow=False, translatedResponseEmptyFlow=False,
               fastBufferedStoreRetire=False, externalRetentionCycles=512, caseCycleLimit=12000)
MIB = 1024 ** 2
NATIVE_FLAGS = ["-std=c++20", "-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
HOST_ONLY_PATHS = {str(RELATIVE), "simulator/gsim/posted_cpu/test_launcher.py",
                   "simulator/gsim/harness/posted_store_cpu_lineage.cpp",
                   "docs/posted-store-cpu-lineage-fixture.md"}


class GateError(Exception):
    """Deliberately not RuntimeError: run.test must not invoke a fallback tool."""


def require(ok, message):
    if not ok:
        raise GateError(message)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(MIB), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path, value, fresh=False):
    with Path(path).open("x" if fresh else "w") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def source(repo):
    require(not git(repo, "status", "--porcelain"), "source must be frozen and clean")
    names = subprocess.check_output(["git", "-C", str(repo), "ls-files", "-z"]).decode().split("\0")
    files = {name: sha(repo / name) for name in names if name and (repo / name).is_file()}
    return {"head": git(repo, "rev-parse", "HEAD"), "tree": git(repo, "rev-parse", "HEAD^{tree}"),
            "files": files}


def environment():
    # Bind relevant inherited settings without copying possible proxy credentials.
    return {key: hashlib.sha256(os.environ.get(key, "").encode()).hexdigest() for key in ENV_KEYS}


def check_tools(receipt):
    for name in ("mill_wrapper", "mill_dist", "gsim", "clang", "firtool"):
        require(name in receipt["files"], "missing pinned tool: " + name)
    for name, item in receipt["files"].items():
        require(Path(item["path"]).is_file() and sha(item["path"]) == item["sha256"],
                "pinned tool drift: " + name)
    tools = receipt["files"]
    require(shutil.which("mill") == tools["mill_wrapper"]["path"], "activated Mill path differs")
    require(os.environ.get("GSIM_CXX") == tools["clang"]["path"], "activated clang path differs")
    require(Path(os.environ.get("CHISEL_FIRTOOL_PATH", "/missing")) / "firtool" ==
            Path(tools["firtool"]["path"]), "activated firtool path differs")
    require(os.environ.get("COURSIER_CACHE") and os.environ.get("JAVA_TOOL_OPTIONS"),
            "activate the recovered environment before bind and run")


def bind(args):
    repo = args.repo.resolve()
    require((repo / RELATIVE).resolve() == Path(__file__).resolve(), "invoke the launcher from the bound repo")
    snapshot = source(repo)
    require(snapshot["head"] == args.expect_head and snapshot["tree"] == args.expect_tree,
            "explicit approved source head/tree differs")
    require(sha(args.tool_files) == args.tool_files_sha256, "tool receipt digest differs")
    tools = json.loads(args.tool_files.read_text())
    check_tools(tools)
    binding = {"schema": "posted-cpu-lineage-binding-v1", "repo": str(repo), "source": snapshot,
               "tool_receipt": tools, "tool_receipt_path": str(args.tool_files.resolve()),
               "tool_receipt_sha256": args.tool_files_sha256, "environment": environment(),
               "python": {"path": str(Path(sys.executable).resolve()), "sha256": sha(sys.executable),
                          "version": sys.version}, "profile": PROFILE, "cases": CASES,
               "negative_controls": CONTROLS, "scope": "actual CPU with synthetic downstream retention only"}
    write_json(args.output, binding, fresh=True)
    print("BOUND_SOURCE_AND_TOOLS_NO_HARDWARE_RUN", args.output, sha(args.output))


def module(fir, name):
    match = re.search(r"^  (?:public )?module " + re.escape(name) +
                      r"\s*:.*?(?=^  (?:public )?(?:module|extmodule) |\Z)", fir, re.M | re.S)
    require(match is not None, "missing emitted module: " + name)
    return match[0]


def census(fir, enabled):
    backend, stores, adapter, lsu = (module(fir, name) for name in
        ("IntegerBackend", "StoreBuffer", "DataTranslationAdapter", "ParallelLoadStoreUnit"))
    for body, field in ((backend, "posted :"), (stores, "upstreamProof :"), (adapter, "posted :")):
        port = next((line for line in body.splitlines() if line.startswith("    output io :")), "")
        require(port and (field in port) == enabled, "emitted optional CPU proof port disagrees with mode: " + field)
    require(len(re.findall(r"^    inst slots_\d+ of LoadStoreUnit(?:_\d+)?\b", lsu, re.M)) == 4,
            "emitted actual CPU does not have four LSU slots")
    require("index : UInt<4>, tag : UInt<64>" in lsu, "emitted actual full-token geometry differs")
    require(("proofs :" in stores) == enabled, "emitted StoreBuffer proof storage disagrees with mode")
    require(not re.search(r"^  (?:public )?module PostedStoreMerge\s*:", fir, re.M),
            "fixture unexpectedly contains real cache owner; scope must be reviewed")
    if enabled:
        require("epoch : UInt<32>" in backend and "finalChecked" in adapter,
                "emitted full CPU proof lineage/epoch absent")
    return {"status": "PASS_EMITTED_CPU_CENSUS", "enabled": enabled, "memoryEntries": 4,
            "tokenTagBits": 64, "tokenIndexBits": 4, "realCacheOwner": False}


def outcome(log, code, mode, case, control=None):
    require(not re.search(r"AddressSanitizer|UndefinedBehaviorSanitizer|runtime error:|LeakSanitizer", log),
            "sanitizer diagnostic")
    require(log.count(EPOCH_CONTROLS) == 1, "host epoch sensitivity controls absent")
    require(log.count(CANCEL_CONTROLS) == 1, "host cancellation sensitivity controls absent")
    if control:
        require(code == 1 and REJECT in log and "case=" + case in log and PASS not in log,
                "negative control must reject the original lineage witness, not crash or time out")
        return {"status": "EXPECTED_ORACLE_REJECTION", "diagnostic": REJECT,
                "epoch_controls": EPOCH_CONTROLS, "cancel_controls": CANCEL_CONTROLS}
    require(code == 0 and PASS in log, "normal CPU case failed")
    rows = re.findall(r"^CPU_POSTED_LINEAGE (.*)$", log, re.M)
    require(len(rows) == 1, "missing/duplicate per-case coverage row")
    fields = dict(item.split("=", 1) for item in rows[0].split())
    require(fields.pop("case") == case and fields.pop("mode") == mode, "case/mode coverage mismatch")
    coverage = {name: int(value) for name, value in fields.items()}
    mandatory = ("commits", "stores", "proofs", "requestHolds", "realResponseHolds", "robReuseWhileBusy",
                 "loadWait", "ackedStoreIndexReuse", "retiredWhileBusy", "aplicWait", "systemWait",
                 "fenceWait", "fenceIWait", "contextWait", "recoveryBusy", "traps", "pteReads",
                 "contextChanges", "virtualPhysicalRequests", "virtualPhysicalResponses", "virtualCompletions")
    require(set(coverage) == set(mandatory), "coverage schema missing or changed")
    require(all(value >= 0 for value in coverage.values()), "negative coverage counter")
    if mode == "off":
        require(coverage["proofs"] == 0, "OFF emitted authority")
    if mode == "on" and case == CASES[0]:
        for field in ("proofs", "requestHolds", "realResponseHolds", "robReuseWhileBusy", "loadWait",
                      "ackedStoreIndexReuse", "aplicWait", "fenceWait", "fenceIWait", "contextWait", "recoveryBusy"):
            require(coverage[field] > 0, "mandatory coverage absent: " + field)
        require(coverage["retiredWhileBusy"] > 16, "ROB reuse coverage incomplete")
    if case in CASES[1:4]:
        require(coverage["traps"] == 1, "precise fault coverage incomplete")
    if case == CASES[3]:
        require(coverage["pteReads"] == 1 and coverage["virtualPhysicalRequests"] == 0 and
                coverage["virtualCompletions"] == 1, "virtual fault coverage incomplete")
    if case == CASES[4]:
        require(coverage["pteReads"] == 2 and coverage["traps"] == 0 and
                coverage["virtualPhysicalRequests"] == coverage["virtualPhysicalResponses"] ==
                coverage["virtualCompletions"] == 1, "virtual success coverage incomplete")
    return {"status": "PASS", "coverage": coverage, "epoch_controls": EPOCH_CONTROLS,
            "cancel_controls": CANCEL_CONTROLS}


def trace_summary(path, case, control=False):
    kinds, expected_count = {}, None
    with path.open() as stream:
        for line in stream:
            event = json.loads(line)
            require(event["case"] == case, "trace contains a different case")
            kind = event["kind"]
            kinds[kind] = kinds.get(kind, 0) + 1
            if kind == "case_begin":
                expected_count = event["expected_instructions"]
    require(kinds.get("case_begin") == 1 and kinds.get("expected", 0) == expected_count,
            "trace omitted expected architectural instructions")
    require(kinds.get("rename", 0) > 0, "trace has no actual instruction execution")
    require(kinds.get("failure", 0) == (1 if control else 0) and
            kinds.get("case_pass", 0) == (0 if control else 1), "trace terminal disagrees with result")
    return kinds


def reusable_source(previous, current):
    old, new = previous["source"]["files"], current["source"]["files"]
    changed = sorted(name for name in old.keys() | new.keys() if old.get(name) != new.get(name))
    require(set(changed) <= HOST_ONLY_PATHS, "reuse would cross an RTL/build/tool source change: " + str(changed))
    require(previous["tool_receipt"] == current["tool_receipt"], "reused model tool identity differs")
    return changed


class Gate:
    def __init__(self, args, binding):
        self.args, self.binding, self.out = args, binding, args.output.resolve()
        self.repo = Path(binding["repo"])
        self.tools = binding["tool_receipt"]["files"]
        self.receipt = {"schema": "posted-cpu-lineage-gate-v1", "status": "RUNNING",
                        "binding_sha256": args.binding_sha256, "binding": binding,
                        "historical_pass_inherited": False, "steps": [], "models": {}, "cases": {},
                        "scope": "actual CPU authorization and ordered boundaries; synthetic 512-cycle cache retention; no throughput result"}
        for mode in ("off", "on"):
            for case in CASES:
                self.receipt["cases"][mode + "/" + case] = {"status": "NOT_RUN"}
        for control in CONTROLS:
            self.receipt["cases"]["on/negative-" + control] = {"status": "NOT_RUN"}

    def save(self):
        write_json(self.out / "receipt.json", self.receipt)

    def verify(self):
        require(source(self.repo) == self.binding["source"], "bound source drift")
        require(environment() == self.binding["environment"], "bound execution environment drift")
        require(sha(self.args.binding) == self.args.binding_sha256, "binding changed")
        require(sha(self.binding["tool_receipt_path"]) == self.binding["tool_receipt_sha256"], "tool receipt drift")
        require(sha(sys.executable) == self.binding["python"]["sha256"] and sys.version == self.binding["python"]["version"],
                "Python driver drift")
        check_tools(self.binding["tool_receipt"])

    def process(self, command, log, timeout):
        self.verify()
        command = list(map(str, command))
        if command[0] == "mill":
            command = [self.tools["mill_wrapper"]["path"], "-j", "1", *command[1:]]
        allowed = {self.tools[name]["path"] for name in ("mill_wrapper", "gsim", "clang")}
        allowed.update(str(self.out / "models" / mode / "run") for mode in ("off", "on"))
        require(command[0] in allowed, "unbound executable: " + command[0])
        log.parent.mkdir(parents=True, exist_ok=True)
        started, guard, code = time.monotonic(), None, None
        entry = {"command": command, "log": str(log.relative_to(self.out)), "status": "RUNNING"}
        self.receipt["steps"].append(entry)
        self.save()
        try:
            with log.open("x") as stream:
                child = subprocess.Popen(command, cwd=self.repo, stdout=stream, stderr=subprocess.STDOUT,
                                         start_new_session=True, env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0",
                                                                      "PYTHONDONTWRITEBYTECODE": "1",
                                                                      "POSTED_CPU_CENSUS_DIR": str(self.out / "board-census")})
                try:
                    while child.poll() is None:
                        if time.monotonic() - started > timeout:
                            guard = "bounded-timeout"
                        if shutil.disk_usage(self.out).free < self.args.free_floor_mib * MIB:
                            guard = "disk-floor"
                        if sum(p.stat().st_size for p in self.out.rglob("*") if p.is_file()) > self.args.output_budget_mib * MIB:
                            guard = "output-budget"
                        if guard:
                            break
                        time.sleep(0.25)
                finally:
                    if child.poll() is None:
                        os.killpg(child.pid, signal.SIGTERM)
                        try:
                            child.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            os.killpg(child.pid, signal.SIGKILL)
                            child.wait()
                    code = child.returncode
        finally:
            entry.update(status="FINISHED", exit=code, guard=guard, seconds=time.monotonic() - started,
                         log_sha256=sha(log) if log.exists() else None)
            self.save()
        self.verify()
        require(guard is None, "process guard: " + str(guard))
        return code, log.read_text()

    def case(self, mode, case, control=None):
        name = "negative-" + control if control else case
        key = mode + "/" + name
        output = self.out / "cases" / mode / name
        output.mkdir(parents=True)
        trace = output / "trace.jsonl"
        command = [self.out / "models" / mode / "run", "--" + mode, "--case", case, "--trace", trace]
        if control:
            command.append("--inject-oracle-" + control + "-mismatch")
        try:
            code, log = self.process(command, output / "runtime.log", 180)
            result = outcome(log, code, mode, case, control)
            require(trace.is_file() and trace.stat().st_size > 0, "missing complete trace or failure prefix")
            result["trace_sha256"] = sha(trace)
            result["trace_events"] = trace_summary(trace, case, control is not None)
        except Exception as error:
            result = {"status": "FAIL", "error": str(error)}
        result["artifacts"] = {str(p.relative_to(output)): sha(p) for p in output.rglob("*") if p.is_file()}
        self.receipt["cases"][key] = result
        write_json(output / "result.json", result)
        self.save()

    def common_run(self, command, *, cwd=None, log=None, timeout=600, env=None):
        # run.test's runtime is dispatched separately so each failure is recorded
        # and subsequent independent cases still run. Build failures stop that model.
        if Path(str(command[0])).name == "run":
            self.case(self.mode, CASES[0])
            log.write_text((self.out / "cases" / self.mode / CASES[0] / "runtime.log").read_text())
            return
        if log.name == "compile.log":
            self.syntax(self.mode)
            self.native(self.mode)
            return
        code, text = self.process(command, log, timeout)
        require(code == 0, "build/config step failed: " + str(log))
        require(not re.search(r"AddressSanitizer|UndefinedBehaviorSanitizer|runtime error:", text), "build sanitizer diagnostic")
        if log.name == "elaborate.log":
            fir = log.parent / (TOP + ".fir")
            result = census(fir.read_text(), self.mode == "on")
            result["fir_sha256"] = sha(fir)
            write_json(log.parent / "census.json", result, fresh=True)

    def syntax(self, mode):
        model = self.out / "models" / mode
        command = [self.tools["clang"]["path"], *NATIVE_FLAGS, "-I" + str(model), "-fsyntax-only",
                   self.repo / "simulator/gsim/harness/posted_store_cpu_lineage.cpp"]
        code, log = self.process(command, model / "host-syntax.log", 120)
        require(code == 0, "host syntax failed against actual " + mode + " header")

    def native(self, mode):
        model = self.out / "models" / mode
        cxx = self.tools["clang"]["path"]
        flags = [*NATIVE_FLAGS, "-I" + str(model)]
        objects = []
        for generated in sorted(model.glob(TOP + "[0-9]*.cpp")):
            obj = generated.with_suffix(".o")
            if not obj.exists():
                code, log = self.process([cxx, *flags, "-c", generated, "-o", obj],
                                         model / ("compile-" + generated.stem + ".log"), 900)
                require(code == 0, "native model compile failed: " + generated.name)
            objects.append(obj)
        require(objects, "no generated native model objects")
        self.receipt["models"].setdefault(mode, {})["native"] = {"flags": NATIVE_FLAGS,
            "objects": {p.name: sha(p) for p in objects}}
        code, log = self.process([cxx, *flags, self.repo / "simulator/gsim/harness/posted_store_cpu_lineage.cpp",
                                 *objects, "-ldl", "-o", model / "run"], model / "compile.log", 300)
        require(code == 0, "native host link failed: " + mode)

    def reuse(self):
        origin = self.args.reuse_attempt.resolve()
        receipt_file = origin / "receipt.json"
        require(sha(receipt_file) == self.args.reuse_receipt_sha256, "explicit prior receipt digest differs")
        previous = json.loads(receipt_file.read_text())
        require(previous["schema"] == "posted-cpu-lineage-gate-v1" and previous["status"] != "RUNNING",
                "only a terminal bound CPU attempt can supply generated models")
        changed = reusable_source(previous["binding"], self.binding)
        require(len(previous.get("board_census", {})) == 2, "prior actual board ON/OFF census absent")
        for relative, digest in previous["board_census"].items():
            require(sha(origin / relative) == digest, "prior board census drift")
            target = self.out / relative
            require(target.resolve().is_relative_to(self.out), "prior census path escapes output")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(origin / relative, target)
        for mode in ("off", "on"):
            old_model, model = origin / "models" / mode, self.out / "models" / mode
            model.mkdir(parents=True)
            artifacts = previous["models"][mode]["artifacts"]
            required = [TOP + ".fir", TOP + ".h"]
            required += sorted(name for name in artifacts if re.fullmatch(TOP + r"[0-9]+\.cpp", name))
            require(len(required) > 2, "prior generated C++ model missing")
            for name in required:
                require(name in artifacts and sha(old_model / name) == artifacts[name], "prior model artifact drift: " + name)
                shutil.copyfile(old_model / name, model / name)
            write_json(model / "census.json", census((model / (TOP + ".fir")).read_text(), mode == "on"), fresh=True)
            native = previous["models"][mode].get("native", {})
            reused_objects = False
            if native.get("flags") == NATIVE_FLAGS:
                for name, digest in native["objects"].items():
                    require(re.fullmatch(TOP + r"[0-9]+\.o", name) and sha(old_model / name) == digest and
                            artifacts.get(name) == digest, "prior native object drift")
                    shutil.copyfile(old_model / name, model / name)
                    reused_objects = True
            self.receipt["models"][mode] = {"origin": str(old_model), "origin_artifacts": artifacts,
                                             "object_reuse": reused_objects}
        self.receipt["reuse"] = {"origin": str(origin), "receipt_sha256": self.args.reuse_receipt_sha256,
                                 "original_binding": previous["binding"], "changed_host_files": changed,
                                 "same_full_source_inventory": False,
                                 "scope": "same RTL/build sources and tools; explicitly new host/launcher identity"}
        self.receipt["board_census"] = previous["board_census"]
        self.save()
        # Both real headers must accept the new host before any model recompiles.
        for mode in ("off", "on"):
            self.syntax(mode)

    def run(self):
        spec = importlib.util.spec_from_file_location("posted_lineage_common", self.repo / "simulator/gsim/run.py")
        common = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(common)
        common.BUILD = self.out / "models"
        common.run = self.common_run
        self.save()
        try:
            self.verify()
            if self.args.reuse_attempt:
                self.reuse()
            else:
                code, log = self.process([self.tools["mill_wrapper"]["path"], "-i", "-j", "1",
                                         "IonSoC.test.testOnly", "ooo.PostedStoreCpuConfigSpec"],
                                        self.out / "scala-config-census.log", 1200)
                require(code == 0 and "All tests passed" in log, "actual board ON/OFF configuration census failed")
                self.receipt["board_census"] = {str(p.relative_to(self.out)): sha(p)
                                                for p in (self.out / "board-census").rglob("*") if p.is_file()}
                require(len(self.receipt["board_census"]) == 2, "actual board ON/OFF emitted files missing")
            for mode in ("off", "on"):
                self.mode = mode
                model = self.out / "models" / mode
                try:
                    if self.args.reuse_attempt:
                        self.native(mode)
                        self.case(mode, CASES[0])
                    else:
                        require(not model.exists(), "fresh model namespace required")
                        common.test(Path(self.tools["gsim"]["path"]), self.tools["clang"]["path"], mode,
                                    "ooo.PostedStoreCpuLineageGsimMain", TOP, "posted_store_cpu_lineage.cpp",
                                    parameters=(mode,), runtime_args=("--" + mode,), defines={}, sanitizer=True,
                                    timeout=180)
                    for case in CASES[1:]:
                        self.case(mode, case)
                    if mode == "on":
                        for control in CONTROLS:
                            self.case(mode, CASES[0], control)
                except Exception as error:
                    self.receipt["models"].setdefault(mode, {}).update(status="FAIL", error=str(error))
                else:
                    self.receipt["models"].setdefault(mode, {}).update(status="BUILT")
                finally:
                    self.receipt["models"][mode]["artifacts"] = {
                        str(p.relative_to(model)): sha(p) for p in model.rglob("*") if p.is_file()}
                    self.save()
            self.verify()
            require(all(item["status"] in ("PASS", "EXPECTED_ORACLE_REJECTION")
                        for item in self.receipt["cases"].values()), "one or more CPU cases failed or did not run")
            self.receipt["status"] = "PASS_CPU_LINEAGE_SYNTHETIC_RETENTION_ONLY"
        except BaseException as error:
            self.receipt["status"] = "FAIL"
            self.receipt["error"] = str(error)
        finally:
            for item in self.receipt["cases"].values():
                if item["status"] == "NOT_RUN":
                    item.update(status="BLOCKED", reason="earlier bound build/config failure; inspect steps/models")
            self.save()
        print(self.receipt["status"], self.out / "receipt.json")
        return 0 if self.receipt["status"].startswith("PASS_") else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    prepare = sub.add_parser("bind", help="lightweight source/tool binding; no Scala or compiler")
    prepare.add_argument("--repo", type=Path, required=True)
    prepare.add_argument("--expect-head", required=True)
    prepare.add_argument("--expect-tree", required=True)
    prepare.add_argument("--tool-files", type=Path, required=True)
    prepare.add_argument("--tool-files-sha256", required=True)
    prepare.add_argument("--output", type=Path, required=True)
    execute = sub.add_parser("run", help="requires parent's assigned heavy slot")
    execute.add_argument("--binding", type=Path, required=True)
    execute.add_argument("--binding-sha256", required=True)
    execute.add_argument("--slot-granted", action="store_true")
    execute.add_argument("--reuse-attempt", type=Path,
                         help="reuse exact prior FIR/generated sources after a host-only change")
    execute.add_argument("--reuse-receipt-sha256")
    execute.add_argument("--output", type=Path, required=True)
    execute.add_argument("--free-floor-mib", type=int, default=1024)
    execute.add_argument("--output-budget-mib", type=int, default=1024)
    args = parser.parse_args()
    if args.action == "bind":
        bind(args)
        return 0
    require(args.slot_granted, "parent-granted serial heavy slot required")
    require(bool(args.reuse_attempt) == bool(args.reuse_receipt_sha256), "reuse requires both origin and receipt digest")
    require(sha(args.binding) == args.binding_sha256, "explicit binding digest differs")
    binding = json.loads(args.binding.read_text())
    require(binding["schema"] == "posted-cpu-lineage-binding-v1", "unknown binding schema")
    require(Path(binding["repo"]) / RELATIVE == Path(__file__).resolve(), "run the bound repo's launcher")
    require(args.free_floor_mib >= 700 and args.output_budget_mib > 0, "invalid disk limits")
    require(not args.output.exists(), "fresh output required; never overwrite a failed attempt")
    require(shutil.disk_usage(args.output.parent).free >= (args.free_floor_mib + args.output_budget_mib) * MIB,
            "insufficient disk for output budget plus free floor")
    args.output.mkdir()
    return Gate(args, binding).run()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except GateError as error:
        print("CPU_LINEAGE_PREFLIGHT_FAIL", error, file=sys.stderr)
        sys.exit(2)
