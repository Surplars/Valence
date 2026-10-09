#!/usr/bin/env python3
"""Read-only qualification rejection checks; never changes original evidence."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest

import cpu_hot_bandwidth_recover as recovery


class RecoveryQualificationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = recovery.hot.ROOT / "build/gsim/cpu-hot-bandwidth-r2"
        if not cls.original.is_dir():
            raise unittest.SkipTest("saved r2 evidence is needed for these qualification tests")
        cls.reference = json.loads((cls.original / "receipt.json").read_text())
        cls.before = recovery.tree_hashes(cls.original)

    @classmethod
    def tearDownClass(cls):
        assert recovery.tree_hashes(cls.original) == cls.before, "test modified original evidence"

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="hot-recovery-test-", dir=self.original.parent)
        self.addCleanup(self.temporary.cleanup)
        self.prior = Path(self.temporary.name)
        for source in self.original.rglob("*"):
            destination = self.prior / source.relative_to(self.original)
            if source.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
            elif source.name != "receipt.json":
                # Only read these hard links; every mutation is to a receipt copy.
                os.link(source, destination)
        self.receipt = copy.deepcopy(self.reference)

    def write(self):
        (self.prior / "receipt.json").write_text(json.dumps(self.receipt))

    def rejected(self, phrase):
        self.write()
        with self.assertRaisesRegex(RuntimeError, phrase):
            recovery.validate_prior(self.prior)

    def test_original_qualification_passes(self):
        self.write()
        state, _ = recovery.validate_prior(self.prior)
        self.assertEqual(state["cases"], self.reference["cases"])

    def test_reject_changed_source_digest(self):
        name = "simulator/gsim/harness/cpu_hot_bandwidth.h"
        self.receipt["inputs"][name] = "0" * 64
        self.rejected("frozen observer/guest source")

    def test_reject_changed_model_receipt_digest(self):
        self.receipt["selected_model"]["receipt_sha256"] = "0" * 64
        self.rejected("selected model receipt")

    def test_reject_unanchored_model_artifact(self):
        self.receipt["model_artifacts"]["model/BoardSocGsim0.o"] = "0" * 64
        self.rejected("not anchored in model receipt")

    def test_reject_changed_log_digest(self):
        self.receipt["commands"][3]["log_sha256"] = "0" * 64
        self.rejected("prior command log")

    def test_reject_changed_case_artifact_digest(self):
        self.receipt["cases"]["read-4096"]["artifacts"]["run"] = "0" * 64
        self.rejected("prior case artifact")

    def test_reject_changed_parsed_result(self):
        self.receipt["cases"]["read-4096"]["result"]["kernel_cycles"] += 1
        self.rejected("does not match preserved log")

    def test_reject_unsuccessful_run(self):
        self.receipt["commands"][3]["exit"] = 1
        self.rejected("successful historical run")

    def test_reject_wrong_store_buffer_depth(self):
        self.receipt["geometry"]["store_buffer_entries"] = 3
        self.rejected("unexpected geometry")

    def test_reject_repetition_mismatch(self):
        self.receipt["cases"]["read-4096"]["result"]["reps"] = 8
        self.rejected("four timed repetitions")

    def test_reject_unqualified_current_model(self):
        self.receipt["current_source_model_qualified"] = True
        self.rejected("invalid model qualification")

    def test_reject_prebuilt_flag_mismatch(self):
        _, logs = recovery.validate_prior(self.original)
        logs = copy.deepcopy(logs)
        command = logs["read-8192-observer.log"]["command"]
        command[command.index("-DHOT_SB_ENTRIES=2")] = "-DHOT_SB_ENTRIES=3"
        with self.assertRaisesRegex(RuntimeError, "build flags differ"):
            recovery.prepared_case(self.original, "read-8192", logs)


if __name__ == "__main__":
    unittest.main(verbosity=2)
