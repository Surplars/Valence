"""Exact passive observer materialization; no compiler or model execution."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "fpga/next"))
import board_durable_read_prefetch as entry
import durable_read_prefetch_host as host


class DurableReadPrefetchHostTests(unittest.TestCase):
    def inputs(self, root):
        spec = entry.load_manifest()
        profile = root / "profile.json"
        fabric = root / "fabric.json"
        profile.write_text(json.dumps(spec["constructor_profile"]))
        fabric.write_text(json.dumps(spec["executed_fabric"]))
        return profile, fabric

    def test_both_measured_host_identities_and_exact_flag_binding(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile, fabric = self.inputs(root)
            contract = host.load_contract()
            for law, key in (("original", "positive_host17"), ("burst-locked", "fixed_host17")):
                result = host.prepare(profile, fabric, root / law, law)
                self.assertEqual(result["host17"], contract[key])
                self.assertEqual(result["host_defines"], contract["host_defines"])
                self.assertFalse(result["new_model_qualification"])
                self.assertFalse(result["source_writes"])
                self.assertEqual(len(result["host17"]), 17)
                with self.assertRaises(FileExistsError):
                    host.prepare(profile, fabric, root / law, law)

    def test_every_actual_constructor_or_fabric_mutation_is_rejected_before_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile, fabric = self.inputs(root)
            original = json.loads(profile.read_text())
            for key in ("durableReadPrefetchCandidate", "readPrefetchBehindStore"):
                value = copy.deepcopy(original)
                value["cache"][key] = False
                profile.write_text(json.dumps(value))
                with self.assertRaises(RuntimeError):
                    host.prepare(profile, fabric, root / "absent")
                self.assertFalse((root / "absent").exists())
            profile.write_text(json.dumps(original))
            altered = json.loads(fabric.read_text())
            altered["actualLsuOwners"] = 2
            fabric.write_text(json.dumps(altered))
            with self.assertRaises(ValueError):
                host.prepare(profile, fabric, root / "absent")
            self.assertFalse((root / "absent").exists())

    def test_contract_drift_and_unknown_law_fail_closed(self):
        with mock.patch.object(host, "CONTRACT_SHA256", "0" * 64):
            with self.assertRaises(ValueError):
                host.load_contract()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile, fabric = self.inputs(root)
            with self.assertRaises(ValueError):
                host.prepare(profile, fabric, root / "absent", "unmeasured")
            self.assertFalse((root / "absent").exists())


if __name__ == "__main__":
    unittest.main()
