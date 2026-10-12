"""Host-only optional flags and strict historical constructor bridges."""
import contextlib
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import export as exporter
import board_profile as profile
import board_release as release
import board_timing_cdc as timing
import board_pmp_publication as pmp
import board_bound_store_prefetch as bound
import board_durable_read_prefetch as durable
import board_dual_proof_credit as dual
from test_board_tagged_schema import original_expected

FIELDS = ("internalLineGrant", "concurrentReadStorePrefetch", "memoryScheduleOverlap")


class LineGrantPrefetchTests(unittest.TestCase):
    def preflight(self, options):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "absent"
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                exporter.main(["--output", str(output), *(o for o in options if o != "--selected")])
            self.assertFalse(output.exists())
            result = json.loads(stream.getvalue())
        self.assertEqual(result["status"], "PREFLIGHT_ONLY")
        self.assertFalse(result["physical_qualification"])
        result["command"][4] = "OUTPUT"
        return result

    def test_independent_flags_change_only_requested_configuration(self):
        base = durable.native_options()
        old = self.preflight(base)
        for options in (("--internal-line-grant",), ("--concurrent-read-store-prefetch",),
                        ("--memory-schedule-overlap",),
                        ("--internal-line-grant", "--concurrent-read-store-prefetch", "--memory-schedule-overlap"),
                        ("--internal-line-grant", "--concurrent-read-store-prefetch")):
            new = self.preflight([*base, *options])
            name = new["configuration"].pop("name")
            for option in options:
                selector = "-" + option[2:]
                self.assertEqual(name.count(selector), 1)
                name = name.replace(selector, "", 1)
                self.assertIs(new["configuration"].pop(option[2:].replace("-", "_")), True)
                self.assertEqual(new["command"].count(option), 1)
                new["command"].remove(option)
            self.assertEqual(name, old["configuration"]["name"])
            self.assertEqual(new["configuration"], {k: v for k, v in old["configuration"].items() if k != "name"})
            self.assertEqual(new["command"], old["command"])

    def test_invalid_and_unqualified_flags_fail_before_output(self):
        for options in (("--internal-line-grant=1",), ("--internal-line",),
                        ("--memory-schedule-overlap",), ("--memory-schedule-overlap=1",),
                        (*durable.native_options(), "--memory-schedule-overlap", "--memory-schedule-overlap"),
                        ("--internal-line-grant", "--internal-line-grant"),
                        ("--concurrent-read-store-prefetch",),
                        ("--concurrent-read-store-prefetch=false",),
                        (*durable.native_options(), "--concurrent-read-store-prefetch", "--concurrent-read-store-prefetch")):
            with self.subTest(options=options), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    self.preflight(options)
                self.assertEqual(error.exception.code, 2)

    def test_all_historical_entries_require_explicit_strict_false(self):
        cases = [(original_expected(m), lambda x, m=m: profile.compare_constructor(m, x)) for m in ("A", "B")]
        old_release = original_expected("B")
        old_release["profile"]["experimentalTriSpeedEthernet"] = True
        cases.append((old_release, release.compare_constructor))
        cases += [(module.expected_constructor(), module.compare_constructor)
                  for module in (timing, pmp, bound, durable, dual)]
        cases.append((dual.expected_fabric(), dual.compare_fabric))
        for expected, compare in cases:
            compare(expected)
            sections = ("cache",) if "cpu" in expected else ("profile", "cache")
            for section in sections:
                for field in FIELDS:
                    self.assertIs(expected[section][field], False)
                    for value in (None, True, 0, 1):
                        actual = copy.deepcopy(expected)
                        if value is None:
                            del actual[section][field]
                        else:
                            actual[section][field] = value
                        with self.subTest(section=section, field=field, value=value), self.assertRaises(RuntimeError):
                            compare(actual)


if __name__ == "__main__":
    unittest.main()
