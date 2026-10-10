#!/usr/bin/env python3
"""Read final instantiated parameters and prove unchanged frozen FIR graphs."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
import run_board as board
core = board.core


def normalized_fir(text):
    # CIRCT CHIRRTL source locators are metadata. Every remaining character,
    # including module/port/register/node/connection/assert content, must match.
    return re.sub(r" @\[[^\n]*?\]", "", text)


class Audit(board.Gate):
    def run(self):
        self.receipt.update(schema="posted-board-actual-parameter-audit-v1", phase="actual-parameter-audit",
                            scope="read actual instantiated constructors; exact normalized FIR graph equality; no hardware mutation",
                            sides={})
        self.save()
        try:
            self.verify()
            for mode in ("off", "on"):
                origin = getattr(self.args, "model_" + mode).resolve()
                digest = getattr(self.args, "model_" + mode + "_sha256")
                core.require(core.sha(origin / "receipt.json") == digest, "model receipt changed")
                model = json.loads((origin / "receipt.json").read_text())
                core.require(model["status"] == "PASS_MODEL_SIDE" and mode in model["models"], "wrong model side")
                core.require(model["binding"]["tool_receipt"] == self.binding["tool_receipt"], "audit tools differ")
                old, new = model["binding"]["source"]["files"], self.binding["source"]["files"]
                changed = sorted(name for name in old.keys() | new.keys() if old.get(name) != new.get(name))
                core.require(set(changed) == {"src/test/scala/ooo/PostedBoardActualParamsAuditMain.scala",
                    "simulator/gsim/posted_board_lineage/run_actual_audit.py"}, "audit changed model source: " + str(changed))
                donor = origin / "models" / mode
                for name, value in model["models"][mode]["artifacts"].items():
                    core.require(core.sha(donor / name) == value, "frozen donor artifact changed: " + name)
                output = self.out / mode
                output.mkdir()
                self.checked([self.tools["mill_wrapper"]["path"], "-i", "-j", "1", "IonSoC.test.runMain",
                    "ooo.PostedBoardActualParamsAuditMain", output, mode], output / "elaborate.log", 1200)
                source_fir = donor / "BoardSocGsim.fir"
                audit_fir = output / "BoardSocGsim.fir"
                reference = normalized_fir(source_fir.read_text())
                actual = normalized_fir(audit_fir.read_text())
                core.require(reference == actual, "actual-parameter audit changed frozen FIR graph")
                profile = json.loads((donor / "profile.json").read_text())
                report = json.loads((output / "actual-parameters.json").read_text())
                core.require(report["schema"] == "posted-board-actual-parameters-v1" and report["mode"] == mode and
                    report["hardwareMutation"] is False and report["allActualParametersEqualExpected"] is True,
                    "actual parameter report incomplete")
                core.require(report["entryProfile"] == profile["profile"] and report["expectedCore"] == profile["core"],
                    "audit reference differs from frozen model profile")
                core.require(len(report["coreParameters"]) == 6 and len(report["ddrParameters"]) == 2 and
                    len(report["cacheConcurrency"]) == 3 and len(report["cacheTileLinkParameters"]) >= 1,
                    "actual constructor instances omitted")
                for row in report["coreParameters"]:
                    core.require(len(row["values"]) == 134 and row["values"] == profile["core"],
                        "actual final core differs: " + row["instancePath"])
                for row in report["ddrParameters"]:
                    core.require(row["values"] == profile["ddr"], "actual final DDR differs")
                for row in report["cacheConcurrency"]:
                    core.require(row["values"] == profile["cache"], "actual final cache concurrency differs")
                self.receipt["sides"][mode] = {"status": "PASS_ACTUAL_PARAMETERS_SAME_GRAPH",
                    "model_receipt": str(origin / "receipt.json"), "model_receipt_sha256": digest,
                    "model_binding": model["binding"], "audit_only_source_changes": changed,
                    "model_fir_sha256": core.sha(source_fir), "audit_fir_sha256": core.sha(audit_fir),
                    "normalized_fir_sha256": hashlib.sha256(actual.encode()).hexdigest(),
                    "actual_parameters": report, "actual_parameters_sha256": core.sha(output / "actual-parameters.json"),
                    "structural_profile": board.verify_fir(actual)}
                self.save()
            self.verify()
            self.receipt["status"] = "PASS_ACTUAL_FINAL_PARAMETERS_SAME_GRAPH"
        except BaseException as error:
            self.receipt.update(status="FAIL", error=str(error))
        finally:
            self.save()
        print(self.receipt["status"], self.out / "receipt.json")
        return 0 if self.receipt["status"].startswith("PASS_") else 1


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--binding", type=Path, required=True)
    p.add_argument("--binding-sha256", required=True)
    p.add_argument("--slot-granted", action="store_true")
    p.add_argument("--output", type=Path, required=True)
    for mode in ("off", "on"):
        p.add_argument("--model-" + mode, type=Path, required=True)
        p.add_argument("--model-" + mode + "-sha256", required=True)
    args = p.parse_args()
    args.action = "audit"
    args.free_floor_mib = 1024
    args.output_budget_mib = 1024
    core.require(args.slot_granted and core.sha(args.binding) == args.binding_sha256, "missing slot or wrong binding")
    binding = json.loads(args.binding.read_text())
    core.require(Path(binding["repo"]) / "simulator/gsim/posted_board_lineage/run_actual_audit.py" ==
                 Path(__file__).resolve(), "audit launcher differs")
    core.require(not args.output.exists(), "fresh audit namespace required")
    args.output.mkdir()
    return Audit(args, binding).run()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        print("FAIL_PREFLIGHT", error, file=sys.stderr)
        sys.exit(1)
