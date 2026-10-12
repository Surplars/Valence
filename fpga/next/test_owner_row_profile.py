#!/usr/bin/env python3
"""Narrow owner/row option and rollback checks; never emit or run hardware."""
import contextlib
import copy
import importlib.util
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
GSIM = ROOT / "simulator/gsim"
sys.path.insert(0, str(GSIM))


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


exporter = module("owner_row_exporter", HERE / "export.py")
board = module("owner_row_gsim_board", GSIM / "fpga_next_board.py")
FLAGS = ("--shared-canonical-store-owner-match", "--local-payload-write-row")
FIELDS = ("shared_canonical_store_owner_match", "local_payload_write_row")


class OwnerRowProfileTests(unittest.TestCase):
    def native(self, path, options):
        args = ["--output", str(path), *(x for x in options if x != "--selected")]
        with mock.patch.object(exporter.subprocess, "check_output", return_value="0" * 40 + "\n"), \
                mock.patch.object(exporter.subprocess, "run", side_effect=AssertionError("unexpected emitter")), \
                contextlib.redirect_stdout(io.StringIO()) as stream:
            exporter.main(args)
        self.assertFalse(path.exists())
        return json.loads(stream.getvalue())

    def gsim(self, options):
        args = ["owner-row-preflight", "--tag", "owner-row-source-only", "--preflight-only",
                "--variant", "selected", *options]
        with mock.patch.object(sys, "argv", args), \
                mock.patch.object(board.subprocess, "run", side_effect=AssertionError("unexpected hardware")), \
                contextlib.redirect_stdout(io.StringIO()) as stream:
            board.main()
        return json.loads(stream.getvalue())["plan"]

    def test_explicit_52_is_exact_50_plus_two_and_omission_preserves_profile(self):
        old = json.loads((HERE / "timing-batch-zero-cycle-cleanup-profile.json").read_text())
        new = json.loads((HERE / "timing-batch-owner-row-profile.json").read_text())
        self.assertEqual(len(old["native_options"]), 50)
        self.assertEqual(new["native_options"], old["native_options"] + list(FLAGS))
        self.assertEqual(new["native_option_count"], 52)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "absent"
            off = self.native(path, old["native_options"])
            on = self.native(path, new["native_options"])
            self.assertEqual(set(off["command"][5:]), set(old["native_options"]))
            self.assertEqual(set(on["command"][5:]), set(new["native_options"]))
            restored = copy.deepcopy(on["configuration"])
            for flag, field in zip(FLAGS, FIELDS):
                self.assertNotIn(field, off["configuration"])
                self.assertIs(on["configuration"][field], True)
                del restored[field]
                restored["name"] = restored["name"].replace(flag[1:], "")
            self.assertEqual(restored, off["configuration"])
            final = json.loads((GSIM / "zero_cycle_cleanup/evidence/public-receipt.json").read_text())["configuration"]
            digest = hashlib.sha256(json.dumps(off["configuration"], sort_keys=True,
                separators=(",", ":")).encode()).hexdigest()
            self.assertEqual(digest, final["export_profile_sha256"])

    def test_independent_flags_and_gsim_forwarding(self):
        prerequisites = ["--virtual-ram-load-precheck", "--canonical-virtual-store-overlap",
                         "--line-read-channel", "--local-payload-write-enable"]
        for flags in ([], [FLAGS[0]], [FLAGS[1]], list(FLAGS)):
            with self.subTest(flags=flags), tempfile.TemporaryDirectory() as tmp:
                native = self.native(Path(tmp) / "absent", prerequisites + flags)
                plan = self.gsim(prerequisites + flags)
                for flag, field in zip(FLAGS, FIELDS):
                    self.assertEqual(native[field], flag in flags)
                    self.assertEqual(plan[field], flag in flags)
                    self.assertEqual(flag in native["command"], flag in flags)
                    self.assertEqual(flag in plan["parameters"], flag in flags)

    def test_both_parsers_reject_duplicates_values_abbreviations_and_missing_dependencies(self):
        prerequisites = ["--virtual-ram-load-precheck", "--canonical-virtual-store-overlap",
                         "--line-read-channel", "--local-payload-write-enable"]
        bad = [[FLAGS[0]], [FLAGS[1]], ["--line-read-channel", FLAGS[1]],
               ["--local-payload-write-enable", FLAGS[1]]]
        for flag in FLAGS:
            bad += [prerequisites + [flag, flag], prerequisites + [flag[:-1]]]
            bad += [prerequisites + [flag + "=" + value] for value in ("true", "false", "0", "1")]
        with tempfile.TemporaryDirectory() as tmp:
            for options in bad:
                with self.subTest(options=options), contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        self.native(Path(tmp) / "absent", options)
                    with self.assertRaises(SystemExit):
                        self.gsim(options)


if __name__ == "__main__":
    unittest.main()
