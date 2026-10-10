#!/usr/bin/env python3
"""Strict, separately bound real Board model build and host execution.

Every command uses installed tools from the explicit receipt. No setup, make,
downloads or implicit tool fallback. Models can be frozen before host-only work;
the host phase proves exact RTL/build equality and verifies every reused artifact.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from profile_check import verify_profile, verify_profile_pair, verify_fir
ROOT = HERE.parents[2]
RELATIVE = Path("simulator/gsim/posted_board_lineage/run_board.py")
spec = importlib.util.spec_from_file_location("cpu_strict", HERE.parent / "posted_cpu/run_lineage.py")
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)
spec = importlib.util.spec_from_file_location("board_census", HERE.parent / "posted_cpu/verify_model.py")
census = importlib.util.module_from_spec(spec)
spec.loader.exec_module(census)
TOP = "BoardSocGsim"
FLAGS = ["-std=c++20", "-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
HOST = "simulator/gsim/harness/posted_store_board_lineage.cpp"


def verify_metrics(value):
    core.require(set(value) == {"kernel", "flush"}, "complete kernel/flush AXI windows required")
    for name, item in value.items():
        cycles = item["cycles"]
        core.require(isinstance(cycles, int) and cycles > 0, "empty AXI window: " + name)
        core.require(item["outstanding_sample"] == "pre_edge_accepted_owners", "ambiguous AXI occupancy convention")
        for channel in ("ar", "aw", "r", "w"):
            row = item[channel]
            core.require(set(row) == {"fire", "valid_not_ready", "no_offer"} and
                         all(isinstance(n, int) and n >= 0 for n in row.values()) and
                         sum(row.values()) == cycles, "AXI channel cycle conservation: " + name + "/" + channel)
        core.require(item["accepted_r_wire_bytes"] == 8 * item["r"]["fire"] and
                     item["accepted_w_wire_bytes"] == 8 * item["w"]["fire"], "accepted wire byte count differs")
        core.require(0 <= item["accepted_r_requested_payload_bytes"] <= item["accepted_r_wire_bytes"] and
                     0 <= item["accepted_w_strobe_bytes"] <= item["accepted_w_wire_bytes"], "payload bytes exceed wire bytes")
        for direction in ("read", "write"):
            hist = item[direction + "_outstanding_histogram"]
            core.require(sum(hist.values()) == cycles and
                         sum(int(depth) * count for depth, count in hist.items()) ==
                         item[direction + "_outstanding_cycle_sum"], "AXI occupancy histogram conservation")
            core.require(max(map(int, hist)) == item[direction + "_outstanding_peak"], "AXI occupancy peak differs")
        core.require(item["r_backpressure_cycles"] == item["r"]["valid_not_ready"], "R backpressure classification differs")


def verify_same_guest_and_memory(out):
    snapshots = ("guest.bin", "initial-memory.bin", "final-memory.bin",
                 "initial-memory-sparse.json", "final-memory-sparse.json")
    result = {}
    for name in snapshots:
        digests = {}
        for variant in ("old-only", "off", "on"):
            path = out / "cases" / variant / name
            core.require(path.is_file() and path.stat().st_size > 0, "missing guest/full-memory witness: " + str(path))
            digests[variant] = core.sha(path)
        core.require(len(set(digests.values())) == 1, "A/B guest or full-memory image differs: " + name)
        result[name] = digests
    return result


def verify_trace(path, variant, control=None):
    counts, terminal, expected = {}, None, []
    with path.open() as stream:
        for line in stream:
            row = json.loads(line)
            event = row["event"]
            counts[event] = counts.get(event, 0) + 1
            if event == "expected_instruction":
                expected.append(row)
            if event in ("pass", "expected_oracle_rejection"):
                terminal = row
    core.require(counts.get("case_begin") == 1 and expected and counts.get("allocation", 0) > 0 and
                 not counts.get("terminal_failure"), "trace lacks actual guest provenance or records a failure")
    if control:
        mutation = "negative_token_mutation" if control == "token" else "negative_final_byte_mutation"
        core.require(counts.get(mutation) == 1 and counts.get("expected_oracle_rejection") == 1 and
                     not counts.get("pass") and terminal["control"] == control,
                     "trace did not preserve exact intended oracle mutation/rejection")
    else:
        core.require(counts.get("pass") == 1 and not counts.get("expected_oracle_rejection") and
                     terminal["enabled"] == (variant == "on"), "trace terminal differs from normal case")
        stores = sum(row["memory"] and row["store"] for row in expected)
        loads = sum(row["memory"] and not row["store"] for row in expected)
        core.require(terminal["commits"] == len(expected) and terminal["stores"] == stores and
                     terminal["loads"] == loads and terminal["proofs"] == (stores if variant == "on" else 0),
                     "actual retired/store/load/proof totals differ from original raw guest")
        core.require(terminal["held_b_cycles"] >= 256 and terminal["delayed_writes"] >= 3 and
                     counts.get("victim_release_beat") == 8 and counts.get("victim_release_ack") == 1,
                     "actual delayed-B/victim-final-Ack coverage absent")
        if variant == "on":
            for event in ("owner_accept", "owner_acquired", "owner_grant_ack", "owner_refilled", "owner_installed",
                          "owner_member_ack", "owner_member_drained", "owner_released",
                          "owner_attached", "owner_sent", "owner_completed"):
                core.require(counts.get(event, 0) > 0, "actual owner lineage event missing: " + event)
            core.require(all(terminal[field] > 0 for field in
                             ("blocked_load_cycles", "reuse_during_write", "retire_during_write")),
                         "actual ordinary-load/token-reuse/retirement boundary coverage absent")
    return counts


def bind(args):
    repo = args.repo.resolve()
    core.require((repo / RELATIVE).resolve() == Path(__file__).resolve(), "invoke the bound repo launcher")
    snapshot = core.source(repo)
    core.require(snapshot["head"] == args.expect_head and snapshot["tree"] == args.expect_tree,
                 "approved source head/tree differs")
    core.require(core.sha(args.tool_files) == args.tool_files_sha256, "tool receipt digest differs")
    tools = json.loads(args.tool_files.read_text())
    core.check_tools(tools)
    binding = {"schema": "posted-board-binding-v1", "repo": str(repo), "source": snapshot,
               "tool_receipt": tools, "tool_receipt_path": str(args.tool_files.resolve()),
               "tool_receipt_sha256": args.tool_files_sha256, "environment": core.environment(),
               "python": {"path": str(Path(sys.executable).resolve()), "sha256": core.sha(sys.executable),
                          "version": sys.version}}
    core.write_json(args.output, binding, fresh=True)
    print(core.sha(args.output), args.output)


class Gate(core.Gate):
    def __init__(self, args, binding):
        self.args, self.binding, self.out = args, binding, args.output.resolve()
        self.repo = Path(binding["repo"])
        self.tools = binding["tool_receipt"]["files"]
        self.receipt = {"schema": "posted-board-gate-v1", "status": "RUNNING", "phase": args.action,
                        "binding_sha256": args.binding_sha256, "binding": binding,
                        "historical_pass_inherited": False, "steps": [], "models": {}, "cases": {},
                        "scope": "real CPU/proof/private-cache/Mixed-home/AXI composition; raw functional guest; no throughput claim"}
        if args.action == "run":
            self.receipt["cases"] = {name: {"status": "NOT_RUN"} for name in
                                     ("old-only", "off", "on", "on-negative-token", "on-negative-byte")}

    def artifacts(self, mode):
        model = self.out / "models" / mode
        self.receipt["models"].setdefault(mode, {})["artifacts"] = {
            str(p.relative_to(model)): core.sha(p) for p in model.rglob("*") if p.is_file()}
        self.save()

    def checked(self, command, log, timeout):
        code, text = self.process(command, log, timeout)
        core.require(code == 0, "step failed: " + str(log))
        core.require(not re.search(r"AddressSanitizer|UndefinedBehaviorSanitizer|runtime error:", text),
                     "sanitizer diagnostic: " + str(log))
        return text

    def model(self, mode):
        model = self.out / "models" / mode
        model.mkdir(parents=True)
        self.checked([self.tools["mill_wrapper"]["path"], "-i", "-j", "1", "IonSoC.test.runMain",
                      "ooo.PostedStoreBoardLineageGsimMain", model, mode], model / "elaborate.log", 1200)
        fir = model / (TOP + ".fir")
        text = fir.read_text()
        profile = json.loads((model / "profile.json").read_text())
        verify_profile(profile, mode)
        structural_profile = verify_fir(text)
        result = census.verify_posted_model(text, mode == "on")
        top = census._module(text, TOP)
        core.require("output lineage :" in top and "headInstruction : UInt<32>" in top and
                     "tag : UInt<64>" in top and "word7 : UInt<64>" in top, "actual passive Board scalar view missing")
        parallel = census._module(text, "ParallelLoadStoreUnit")
        core.require(len(re.findall(r"inst slots_\d+ of LoadStoreUnit", parallel)) == 4,
                     "actual four-owner LSU instance count differs")
        result.update(fir_sha256=core.sha(fir), memory_entries=4, passive_probes=True,
                      normalized_profile=profile, structural_profile=structural_profile)
        core.write_json(model / "census.json", result, fresh=True)
        self.checked([self.tools["gsim"]["path"], "--threads=1", "--dir=" + str(model), fir],
                     model / "generate.log", 1200)
        generated = sorted(model.glob(TOP + "[0-9]*.cpp"))
        core.require(generated and (model / (TOP + ".h")).is_file(), "actual GSIM model missing")
        header = (model / (TOP + ".h")).read_text()
        for signal in ("get_lineage$$alloc0$$valid", "get_lineage$$cache$$proof$$valid",
                       "get_lineage$$owner$$accepted$$valid", "get_lineage$$tlC$$bits$$source"):
            core.require(signal in header, "actual generated scalar getter missing: " + signal)
        for item in generated:
            self.checked([self.tools["clang"]["path"], *FLAGS, "-I" + str(model), "-c", item,
                          "-o", item.with_suffix(".o")], model / ("compile-" + item.stem + ".log"), 1800)
        self.receipt["models"][mode] = {"status": "BUILT_MODEL_ONLY", "flags": FLAGS, "census": result}

    def reuse(self):
        self.receipt["reuse"] = {"sides": {}, "same_full_source_inventory": False}
        summaries = {}
        for mode in ("off", "on"):
            separate = mode == "on" and self.args.models_on is not None
            origin = (self.args.models_on if separate else self.args.models).resolve()
            digest = self.args.models_on_receipt_sha256 if separate else self.args.models_receipt_sha256
            core.require(core.sha(origin / "receipt.json") == digest, "model receipt digest differs")
            previous = json.loads((origin / "receipt.json").read_text())
            core.require(previous["schema"] == "posted-board-gate-v1" and previous["status"] in
                         ("PASS_MODELS_ONLY", "PASS_MODEL_SIDE") and mode in previous["models"],
                         "complete frozen side required: " + mode)
            core.require(previous["binding"]["tool_receipt"] == self.binding["tool_receipt"], "model tools differ")
            old, new = previous["binding"]["source"]["files"], self.binding["source"]["files"]
            changed = sorted(name for name in old.keys() | new.keys() if old.get(name) != new.get(name))
            core.require(all(name == HOST or name.startswith("simulator/gsim/posted_board_lineage/") or
                             name.startswith("docs/") for name in changed), "reuse crosses RTL/build change: " + str(changed))
            model = self.out / "models" / mode
            model.mkdir(parents=True)
            item = previous["models"][mode]
            core.require(item["status"] == "BUILT_MODEL_ONLY" and item["flags"] == FLAGS, "model flags differ")
            for name, artifact_digest in item["artifacts"].items():
                source = origin / "models" / mode / name
                target = model / name
                core.require(source.resolve().is_relative_to(origin) and target.resolve().is_relative_to(model),
                             "artifact path escapes namespace")
                core.require(core.sha(source) == artifact_digest, "frozen model artifact changed: " + name)
                if source.suffix in (".fir", ".h", ".cpp", ".o") or name in ("profile.json", "census.json"):
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
            summaries[mode] = json.loads((model / "profile.json").read_text())
            verify_profile(summaries[mode], mode)
            self.receipt["models"][mode] = {"status": "REUSED", "flags": FLAGS, "census": item["census"]}
            self.receipt["reuse"]["sides"][mode] = {"origin": str(origin), "receipt_sha256": digest,
                "original_binding": previous["binding"], "changed_host_files": changed}
        verify_profile_pair(summaries["off"], summaries["on"])
        self.receipt["reuse"]["same_full_source_inventory"] = all(
            not side["changed_host_files"] for side in self.receipt["reuse"]["sides"].values())
        self.receipt["full_profile_pair"] = summaries
        self.save()

    def host(self, mode):
        model = self.out / "models" / mode
        cxx = self.tools["clang"]["path"]
        flags = [*FLAGS, "-I" + str(model)]
        self.checked([cxx, *flags, "-fsyntax-only", self.repo / HOST], model / "host-syntax.log", 180)
        objects = sorted(model.glob(TOP + "[0-9]*.o"))
        core.require(objects, "no exact frozen model objects")
        self.checked([cxx, *flags, self.repo / HOST, *objects, "-ldl", "-o", model / "run"],
                     model / "host-link.log", 600)
        self.receipt["models"][mode]["status"] = "LINKED_EXACT_REUSED_MODEL"
        self.save()

    def case(self, mode, variant, control=None):
        name = variant + ("-negative-" + control if control else "")
        out = self.out / "cases" / name
        out.mkdir(parents=True)
        command = [self.out / "models" / mode / "run", "--variant=" + variant,
                   "--trace=" + str(out / "trace.jsonl")]
        if control:
            command.append("--inject-proof-token" if control == "token" else "--inject-final-byte")
        code, log = self.process(command, out / "runtime.log", 300)
        result = {"exit": code, "status": "FAIL"}
        try:
            core.require(not re.search(r"AddressSanitizer|UndefinedBehaviorSanitizer|runtime error:", log),
                         "runtime sanitizer diagnostic")
            # Exact host markers are part of the frozen host ABI, not inferred
            # from an exit status or a missing crash.
            if control:
                marker = "BOARD_ORACLE_REJECT " + control
                core.require(code == 1 and marker in log, "negative did not reach exact independent oracle rejection")
                result.update(status="EXPECTED_ORACLE_REJECTION", diagnostic=marker)
            else:
                core.require(code == 0 and "POSTED_BOARD_LINEAGE_PASS" in log, "real Board case failed")
                core.require((out / "trace.jsonl").stat().st_size > 0, "full raw trace missing")
                metrics = json.loads((out / "axi-metrics.json").read_text())
                verify_metrics(metrics)
                result["axi_metrics"] = metrics
                result["status"] = "PASS"
            result["trace_events"] = verify_trace(out / "trace.jsonl", variant, control)
        except Exception as error:
            result["error"] = str(error)
        result["artifacts"] = {str(p.relative_to(out)): core.sha(p) for p in out.rglob("*") if p.is_file()}
        self.receipt["cases"][name] = result
        core.write_json(out / "result.json", result, fresh=True)
        self.save()

    def run(self):
        self.save()
        try:
            self.verify()
            if self.args.action == "models":
                for mode in (("off", "on") if self.args.side == "both" else (self.args.side,)):
                    try:
                        self.model(mode)
                    finally:
                        self.artifacts(mode)
                self.receipt["status"] = "PASS_MODELS_ONLY" if self.args.side == "both" else "PASS_MODEL_SIDE"
            else:
                self.reuse()
                for mode in ("off", "on"):
                    try:
                        self.host(mode)
                        for variant in (("old-only", "off") if mode == "off" else ("on",)):
                            self.case(mode, variant)
                        if mode == "on":
                            for control in ("token", "byte"):
                                self.case(mode, "on", control)
                    finally:
                        self.artifacts(mode)
                core.require(len(self.receipt["cases"]) == 5 and all(
                    item["status"] in ("PASS", "EXPECTED_ORACLE_REJECTION") for item in self.receipt["cases"].values()),
                    "real Board cases incomplete or failed")
                self.receipt["same_guest_and_full_memory"] = verify_same_guest_and_memory(self.out)
                self.receipt["status"] = "PASS_REAL_BOARD_FUNCTIONAL_ONLY"
            self.verify()
        except BaseException as error:
            self.receipt.update(status="FAIL", error=str(error))
        finally:
            for item in self.receipt["cases"].values():
                if item["status"] == "NOT_RUN":
                    item.update(status="BLOCKED", reason="earlier bound build/reuse failure; inspect steps/models")
            self.save()
        print(self.receipt["status"], self.out / "receipt.json")
        return 0 if self.receipt["status"].startswith("PASS_") else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    prepare = sub.add_parser("bind")
    prepare.add_argument("--repo", type=Path, required=True)
    prepare.add_argument("--expect-head", required=True)
    prepare.add_argument("--expect-tree", required=True)
    prepare.add_argument("--tool-files", type=Path, required=True)
    prepare.add_argument("--tool-files-sha256", required=True)
    prepare.add_argument("--output", type=Path, required=True)
    for name in ("models", "run"):
        action = sub.add_parser(name)
        action.add_argument("--binding", type=Path, required=True)
        action.add_argument("--binding-sha256", required=True)
        action.add_argument("--slot-granted", action="store_true")
        action.add_argument("--output", type=Path, required=True)
        action.add_argument("--free-floor-mib", type=int, default=1024)
        action.add_argument("--output-budget-mib", type=int, default=2048)
        if name == "models":
            action.add_argument("--side", choices=("off", "on", "both"), default="both")
        if name == "run":
            action.add_argument("--models-on", type=Path)
            action.add_argument("--models-on-receipt-sha256")
            action.add_argument("--models", type=Path, required=True)
            action.add_argument("--models-receipt-sha256", required=True)
    args = parser.parse_args()
    if args.action == "bind":
        bind(args)
        return 0
    core.require(args.slot_granted, "parent-granted heavy slot required")
    core.require(core.sha(args.binding) == args.binding_sha256, "binding digest differs")
    binding = json.loads(args.binding.read_text())
    if args.action == "run":
        core.require(bool(args.models_on) == bool(args.models_on_receipt_sha256),
                     "separate ON side requires both origin and receipt digest")
    core.require(binding["schema"] == "posted-board-binding-v1" and
                 Path(binding["repo"]) / RELATIVE == Path(__file__).resolve(), "bound launcher differs")
    core.require(not args.output.exists(), "fresh output required; never overwrite failed attempts")
    core.require(args.free_floor_mib >= 700 and args.output_budget_mib > 0, "invalid disk limits")
    core.require(shutil.disk_usage(args.output.parent).free >=
                 (args.free_floor_mib + args.output_budget_mib) * core.MIB, "insufficient disk budget")
    args.output.mkdir()
    return Gate(args, binding).run()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        print("FAIL_PREFLIGHT:", error, file=sys.stderr)
        sys.exit(1)
