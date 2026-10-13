#!/usr/bin/env python3
"""Executable-entry and source-identity negatives; no compiler or hardware."""
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "simulator/gsim"))


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


final = module("entry_contract_final", HERE / "board_final.py")
exporter = final.exporter_module()
board = module("entry_contract_gsim", ROOT / "simulator/gsim/fpga_next_board.py")
HELPERS = ("src/test/scala/ooo/PostedStoreBoardLineageGsim.scala",
           "src/test/scala/ooo/TimingBatchActualAudit.scala")


class BoardEntryContractTests(unittest.TestCase):
    def test_executed_helpers_are_bound_and_mutations_fail(self):
        sources = exporter.sources()
        profile = final.load_profile()
        future_module, future_bridge = final.future_source_bridge(profile)
        historical = future_module.project(sources, future_bridge)
        for name in HELPERS:
            self.assertEqual(historical[name], profile["source_only_entry_contract_bridge"]["newly_export_bound_helpers"][name])
            self.assertEqual(sources[name], final.sha(ROOT / name))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in sources:
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / name, target)
            with mock.patch.object(exporter, "ROOT", root), mock.patch.object(final, "exporter_module", return_value=exporter):
                for name in HELPERS:
                    with self.subTest(name=name):
                        target = root / name
                        original = target.read_bytes()
                        target.write_bytes(original + b"\n// altered executed helper\n")
                        with self.assertRaisesRegex(RuntimeError, "source closure changed"):
                            final.load_profile()
                        target.write_bytes(original)

    def test_bridge_rejects_widening_and_identity_or_scope_changes(self):
        profile = final.load_profile()
        mutations = [
            lambda b: b["changed_python_sources"].update({"src/main/scala/unknown.scala": {}}),
            lambda b: b["changed_python_sources"]["fpga/next/export.py"].update(qualified_sha256="0" * 64),
            lambda b: b["changed_python_sources"]["simulator/gsim/fpga_next_board.py"].update(current_sha256="0" * 64),
            lambda b: b["newly_export_bound_helpers"].pop(HELPERS[0]),
            lambda b: b["newly_export_bound_helpers"].update({HELPERS[1]: "0" * 64}),
            lambda b: b["qualified_scala_source_closure"].update(canonical_sha256="0" * 64),
            lambda b: b["export_profile_sha256"].update(default52="0" * 64),
            lambda b: b.update(default52_cpu_rerun=True),
            lambda b: b.update(optional53_cpu_rerun=True),
            lambda b: b.update(native_export_rerun=True),
        ]
        for index, mutate in enumerate(mutations):
            bad = copy.deepcopy(profile)
            mutate(bad["source_only_entry_contract_bridge"])
            with self.subTest(index=index), self.assertRaisesRegex(RuntimeError, "entry source bridge"):
                final.check_source_bridge(bad, exporter)

    def call_generic(self, root, extra):
        with mock.patch.object(board.common, "BUILD", root), \
                mock.patch.object(sys, "argv", ["fpga_next_board.py", "--tag", "contract-check", *extra]), \
                mock.patch.object(Path, "mkdir", side_effect=AssertionError("unexpected output creation")), \
                mock.patch.object(board, "source_inventory", side_effect=AssertionError("unexpected model freeze")), \
                mock.patch.object(board.subprocess, "run", side_effect=AssertionError("unexpected subprocess")), \
                mock.patch.object(board.subprocess, "check_output", side_effect=AssertionError("unexpected subprocess")):
            board.main()

    def test_generic_execution_and_resume_fail_without_side_effects(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "absent"
            for extra in ([], ["--variant", "selected"], ["--resume"], ["--smoke-only"]):
                with self.subTest(extra=extra), contextlib.redirect_stderr(io.StringIO()) as stream:
                    with self.assertRaises(SystemExit) as error:
                        self.call_generic(root, extra)
                self.assertEqual(error.exception.code, 2)
                self.assertIn("ooo.CpuMatchingBoardProfileGsimMain", stream.getvalue())
                self.assertIn("tri-speed/USER2", stream.getvalue())
                self.assertFalse(root.exists())
            previous = root / "fpga-next-board-contract-check"
            previous.mkdir(parents=True)
            receipt = previous / "receipt.json"
            receipt.write_text('{"status":"RETAINED_PRIOR_RESULT"}\n')
            original = receipt.read_bytes()
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                self.call_generic(root, ["--resume"])
            self.assertEqual(error.exception.code, 2)
            self.assertEqual(receipt.read_bytes(), original)
            self.assertEqual(list(previous.iterdir()), [receipt])

    def test_generic_preflight_is_explicitly_non_executable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "absent"
            with contextlib.redirect_stdout(io.StringIO()) as stream:
                self.call_generic(root, ["--preflight-only", "--variant", "selected"])
            result = json.loads(stream.getvalue())
            self.assertEqual(result["status"], "PREFLIGHT_ONLY")
            self.assertIs(result["execution_supported"], False)
            self.assertIn("ooo.CpuMatchingBoardProfileGsimMain", result["execution_blocker"])
            self.assertIn("--selected", result["plan"]["parameters"])
            self.assertFalse(root.exists())


if __name__ == "__main__":
    unittest.main()
