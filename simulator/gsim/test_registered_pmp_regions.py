"""Host-only optional GSIM argument compatibility checks; no hardware build."""
import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent))
import run as common


class GsimOptionsContractTests(unittest.TestCase):
    def commands(self, *options):
        calls = []
        def record(argv, **kwargs):
            calls.append(list(map(str, argv)))
            if kwargs.get("log"):
                kwargs["log"].write_text("mock host command only\n")
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(common, "BUILD", Path(directory)), mock.patch.object(common, "run", side_effect=record):
                with contextlib.redirect_stdout(io.StringIO()):
                    common.test("gsim", "clang++-19", "contract", "Emitter", "Top", "driver.cpp",
                                **({"gsim_options": options} if options else {}))
            return [[arg.replace(directory, "BUILD") for arg in argv] for argv in calls]

    def test_omitted_option_preserves_original_command(self):
        commands = self.commands()
        self.assertEqual(commands[1], ["gsim", "--threads=1", "--dir=BUILD/contract", "BUILD/contract/Top.fir"])
        self.assertEqual(commands[2][0], "clang++-19")
        self.assertNotIn("-j", commands[2])

    def test_official_split_changes_only_generation_argv(self):
        default = self.commands()
        split = self.commands("--cpp-max-size-KB=1024")
        self.assertEqual(split[1], ["gsim", "--threads=1", "--cpp-max-size-KB=1024",
                                    "--dir=BUILD/contract", "BUILD/contract/Top.fir"])
        split[1].remove("--cpp-max-size-KB=1024")
        self.assertEqual(split, default)


if __name__ == "__main__":
    unittest.main()
