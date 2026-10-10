"""Host-only preset contract tests. Native byte equivalence is qualified separately."""
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import export as exporter
import performance

ROOT = Path(__file__).resolve().parents[2]
EXPECTED = json.loads((ROOT / "simulator/gsim/posted_board_lineage/expected-profile.json").read_text())


class PerformancePresetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / "native"

    def preflight(self, *options, entry=performance.main):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            entry(["--output", str(self.output), *options])
        self.assertFalse(self.output.exists())
        return json.loads(stream.getvalue())

    def test_exact_complete_profiles_and_native_commands(self):
        # All exported fields are checked by the wrapper's frozen digest. This
        # separate oracle checks the command consumed by the real Scala parser,
        # including every absent experimental flag and numeric selection.
        native = EXPECTED["native_reference"]["command"][5:]
        for disabled in (False, True):
            result = self.preflight(*(["--disable-posted"] if disabled else []))
            self.assertEqual(result["status"], "PREFLIGHT_ONLY")
            self.assertEqual(result["command"][:4],
                ["mill", "-i", "IonSoC.test.runMain", "ooo.FpgaNextMain"])
            self.assertEqual(result["command"][4], str(self.output / "rtl"))
            self.assertEqual(result["command"][5:],
                native + ([] if disabled else ["--posted-store-merge"]))
            profile = result["configuration"]
            self.assertEqual(len(profile), 63)
            self.assertEqual(hashlib.sha256(json.dumps(profile, sort_keys=True,
                separators=(",", ":")).encode()).hexdigest(), performance.PROFILE_SHA256[not disabled])
            self.assertFalse(profile["translated_response_empty_flow"])
            self.assertFalse(profile["prechecked_data_flow"])

    def test_disable_changes_only_posted_selection(self):
        on, off = self.preflight(), self.preflight("--disable-posted")
        on["configuration"]["posted_store_merge"] = False
        on["configuration"]["name"] = on["configuration"]["name"].replace("-posted-store-merge", "")
        self.assertEqual(on["configuration"], off["configuration"])
        self.assertEqual(on["command"][:-1], off["command"])

    def test_all_hardware_overrides_and_abbreviations_are_rejected(self):
        overrides = ["--reference", "--storage-candidate", "--posted-store-merge",
            "--prechecked-data-flow", "--translated-response-empty-flow",
            "--lsu-entries=2", "--data-translation-entries=8", "--dma-line-entries=2",
            "--dma-line-yield-cycles=4", "--prefetch-candidate-cycles=3",
            "--prefetch-break-on-store", "--experimental-trispeed-ethernet",
            "--experimental-jtag-bscan=1", "--disable", "--out", "--"]
        for override in overrides:
            with self.subTest(override=override), contextlib.redirect_stderr(io.StringIO()), \
                    mock.patch.object(exporter, "main") as export_call:
                with self.assertRaises(SystemExit) as error:
                    performance.main(["--output", str(self.output), override])
                self.assertEqual(error.exception.code, 2)
                export_call.assert_not_called()

    def test_legal_but_unqualified_expansion_fails_before_output_or_mill(self):
        variants = [tuple("2" if item == "4" else item for item in performance.OPTIONS)]
        variants += [tuple(item for item in performance.OPTIONS if item != flag)
            for flag in ("--prepared-store-lookahead", "--physical-load-ingress-flow",
                "--virtual-ram-load-precheck", "--fetch-previous-packet", "--load-order-older-retire")]
        variants += [(*performance.OPTIONS, "--translated-response-empty-flow")]
        for variant in variants:
            with self.subTest(variant=variant), mock.patch.object(performance, "OPTIONS", variant), \
                    mock.patch.object(exporter, "sources") as source_call, \
                    mock.patch.object(exporter.subprocess, "run") as emit_call, \
                    contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    performance.main(["--output", str(self.output), "--emit"])
                self.assertEqual(error.exception.code, 2)
                source_call.assert_not_called()
                emit_call.assert_not_called()
                self.assertFalse(self.output.exists())

    def test_full_geometry_drift_is_rejected(self):
        baseline = json.loads((ROOT / "fpga/next/baseline.json").read_text())
        for field in ("issue_width", "cache_read_mshrs", "cache_writeback_entries", "cache_ways"):
            changed = copy.deepcopy(baseline)
            changed["profile"][field] += 1
            with self.subTest(field=field), mock.patch.object(exporter.json, "loads", return_value=changed), \
                    contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    performance.main(["--output", str(self.output)])
                self.assertFalse(self.output.exists())

    def test_generic_export_defaults_stay_backward_compatible(self):
        result = self.preflight(entry=exporter.main)
        self.assertFalse(result["posted_store_merge"])
        self.assertEqual(result["configuration"]["lsu_entries"], 2)
        self.assertEqual(result["configuration"]["data_translation_entries"], 8)
        self.assertEqual(result["command"][5:], ["--selected", "--data-translation-entries=8"])

    def test_preset_is_bound_into_export_source_receipt(self):
        self.assertIn("fpga/next/performance.py", exporter.sources())


if __name__ == "__main__":
    unittest.main()
