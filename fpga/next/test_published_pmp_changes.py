"""Host CLI contracts only; no Scala, GSIM or physical qualification."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parent))
import export as exporter


class PublishedPmpChangesTests(unittest.TestCase):
    def preflight(self, *options):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "native"
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                exporter.main(["--output", str(output), *options])
            self.assertFalse(output.exists())
            value = json.loads(stream.getvalue())
            self.assertEqual(value["status"], "PREFLIGHT_ONLY")
            self.assertFalse(value["physical_qualification"])
            value["command"][4] = "OUTPUT"
            return value

    def test_explicit_option_preserves_each_frozen_preset(self):
        for preset in ((), ("--reference",), ("--storage-candidate",)):
            with self.subTest(preset=preset):
                old = self.preflight(*preset)
                new = self.preflight(*preset, "--published-pmp-changes")
                self.assertNotIn("published_pmp_changes", old["configuration"])
                self.assertTrue(new["configuration"].pop("published_pmp_changes"))
                self.assertEqual(new["configuration"].pop("name"), old["configuration"].pop("name") + "-published-pmp-changes")
                self.assertEqual(new["configuration"], old["configuration"])
                self.assertEqual(new["command"].count("--published-pmp-changes"), 1)
                new["command"].remove("--published-pmp-changes")
                self.assertEqual(new["command"], old["command"])

    def test_duplicate_value_and_abbreviated_options_rejected(self):
        for options in (("--published-pmp-changes", "--published-pmp-changes"),
                        ("--published-pmp-changes=false",), ("--published-pmp",)):
            with self.subTest(options=options), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    self.preflight(*options)
                self.assertEqual(error.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
