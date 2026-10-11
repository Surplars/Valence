#!/usr/bin/env python3
"""Preparation-only rejection controls; no compiler, model or DUT."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from materialize_sources import materialize

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
MANIFEST = json.loads((HERE / "source-inputs.json").read_text())


class SourceMaterialization(unittest.TestCase):
    def reject(self, changed, expected):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "fresh"
            with self.assertRaisesRegex(ValueError, expected):
                materialize(ROOT, output, changed)
            self.assertFalse(output.exists(), "rejected input wrote output")

    def test_source_hash_mismatch(self):
        changed = copy.deepcopy(MANIFEST)
        changed["files"][0]["sha256"] = "0" * 64
        self.reject(changed, "source hash mismatch")

    def test_source_and_destination_path_escape(self):
        for field in ("source", "path"):
            changed = copy.deepcopy(MANIFEST)
            changed["files"][0][field] = "../escape"
            self.reject(changed, "unsafe relative path")

    def test_occupied_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            sentinel = output / "keep.txt"
            sentinel.write_bytes(b"preserve existing output")
            with self.assertRaisesRegex(ValueError, "destination must be"):
                materialize(ROOT, output, MANIFEST)
            self.assertEqual(sentinel.read_bytes(), b"preserve existing output")
            self.assertEqual(list(output.iterdir()), [sentinel])


if __name__ == "__main__":
    unittest.main(verbosity=2)
