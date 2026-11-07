"""Control-flow tests only: all compilation and simulator calls are mocked."""
import importlib.util
import collections
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch


class PlatformEntryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / "build/gsim/hypervisor-platform"
        self.output.mkdir(parents=True)
        self.common = types.ModuleType("run")
        self.common.ROOT = self.root
        self.common.HERE = self.root / "simulator/gsim"
        self.common.setup = Mock(return_value=("gsim", "clang++-19"))
        self.chain_marker = "HYPERVISOR_PLATFORM_PASS"
        self.pma_marker = "PLATFORM_VS_PMA_EXCEPTIONS_PASS"
        self.negative_marker = "independent platform store value"
        self.negative_exit = 1
        self.common.test = Mock(side_effect=self.generate)
        self.common.run = Mock(side_effect=self.mock_run)
        spec = importlib.util.spec_from_file_location(
            "platform_entry_under_test", Path(__file__).with_name("hypervisor_platform.py"))
        self.entry = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"run": self.common}):
            spec.loader.exec_module(self.entry)

    def generate(self, *args, **kwargs):
        (self.output / "test.log").write_text(self.chain_marker)
        (self.output / "HypervisorPlatformGsim0.cpp").write_text("mock model")
        return self.output

    def mock_run(self, args, **kwargs):
        if args[0] == self.output / "pma":
            kwargs["log"].write_text(self.pma_marker)

    def negative(self, args, **kwargs):
        kwargs["stdout"].write(self.negative_marker)
        return subprocess.CompletedProcess(args, self.negative_exit)

    def invoke(self):
        with patch.object(sys, "argv", ["hypervisor_platform.py"]), \
             patch.object(self.entry.subprocess, "run", side_effect=self.negative) as negative:
            self.entry.main()
            return negative

    def test_success_uses_one_generation_and_repo_relative_drivers(self):
        negative = self.invoke()
        self.common.setup.assert_called_once_with(False)
        self.common.test.assert_called_once_with(
            "gsim", "clang++-19", "hypervisor-platform", "ooo.HypervisorPlatformGsimMain",
            "HypervisorPlatformGsim", "hypervisor_platform.cpp", defines={},
            cxx_flags=("-fbracket-depth=4096",), timeout=600)
        self.assertEqual(self.common.run.call_count, 2)
        compile_args = self.common.run.call_args_list[0].args[0]
        self.assertIn(self.output / "HypervisorPlatformGsim0.cpp", compile_args)
        self.assertIn(self.common.HERE / "harness/platform_pma_exceptions.cpp", compile_args)
        self.assertIn("-fsanitize=address,undefined", compile_args)
        negative.assert_called_once()
        self.assertEqual(negative.call_args.args[0][-1], "--wrong-memory")
        self.assertEqual(negative.call_args.kwargs["cwd"], self.root)

    def test_setup_failure_stops_before_build(self):
        self.common.setup.side_effect = RuntimeError("missing toolchain")
        with self.assertRaisesRegex(RuntimeError, "missing toolchain"):
            self.invoke()
        self.common.test.assert_not_called()

    def test_chain_failure_stops_before_pma(self):
        self.common.test.side_effect = RuntimeError("chain failed")
        with self.assertRaisesRegex(RuntimeError, "chain failed"):
            self.invoke()
        self.common.run.assert_not_called()

    def test_missing_chain_marker_fails(self):
        self.chain_marker = ""
        with self.assertRaisesRegex(RuntimeError, "HYPERVISOR_PLATFORM_PASS missing"):
            self.invoke()
        self.common.run.assert_not_called()

    def test_missing_pma_marker_fails(self):
        self.pma_marker = ""
        with self.assertRaisesRegex(RuntimeError, "PLATFORM_VS_PMA_EXCEPTIONS_PASS missing"):
            self.invoke()

    def test_compile_failure_propagates(self):
        self.common.run.side_effect = RuntimeError("compile failed")
        with self.assertRaisesRegex(RuntimeError, "compile failed"):
            self.invoke()

    def test_negative_unexpected_exit_fails(self):
        for code in (0, 2, -11):
            with self.subTest(code=code):
                self.negative_exit = code
                with self.assertRaisesRegex(RuntimeError, "expected 1"):
                    self.invoke()

    def test_negative_wrong_failure_fails(self):
        self.negative_marker = "unrelated error"
        with self.assertRaisesRegex(RuntimeError, "independent platform store value missing"):
            self.invoke()

    def test_help_does_not_setup(self):
        with patch.object(sys, "argv", ["hypervisor_platform.py", "--help"]):
            with self.assertRaises(SystemExit) as raised:
                self.entry.main()
        self.assertEqual(raised.exception.code, 0)
        self.common.setup.assert_not_called()


class FixtureRegistrationTest(unittest.TestCase):
    def test_exact_fixture_inputs_preserve_normal_sources(self):
        root = Path(__file__).resolve().parents[2]
        build = (root / "build.mill").read_text()
        declaration = re.search(r'def gsimFixtureSources = Task\.Sources\((.*?)\n        \)', build, re.S)
        self.assertIsNotNone(declaration)
        names = re.findall(r'"(simulator/gsim/fixtures/[^"\n]+\.scala)"', declaration.group(1))
        self.assertEqual(names, [
            "simulator/gsim/fixtures/AiaRetiringCoreGsim.scala",
            "simulator/gsim/fixtures/AiaTranslatedCoreGsim.scala",
            "simulator/gsim/fixtures/HypervisorPlatformGsim.scala",
            "simulator/gsim/fixtures/HypervisorPlatformShapes.scala",
        ])
        self.assertIn("super.sources() ++ gsimFixtureSources()", build)
        self.assertNotIn('PathRef(pwd / "simulator/gsim/fixtures")', build)

    def test_no_duplicate_declarations_in_effective_sources(self):
        root = Path(__file__).resolve().parents[2]
        names = ["AiaRetiringCoreGsim.scala", "AiaTranslatedCoreGsim.scala",
                 "HypervisorPlatformGsim.scala", "HypervisorPlatformShapes.scala"]
        paths = sorted((root / "src/test/scala").rglob("*.scala"))
        self.assertTrue(paths, "Run against the complete assembled repository")
        paths += [root / "simulator/gsim/fixtures" / name for name in names]
        declarations = collections.defaultdict(list)
        for path in paths:
            source = path.read_text()
            package = re.search(r'^package ([\w.]+)', source, re.M)
            package = package.group(1) if package else ""
            for kind, name in re.findall(r'^(?:(?:final|sealed|abstract|case|private)\s+)*(class|object|trait)\s+(\w+)', source, re.M):
                declarations[(package, kind, name)].append(str(path.relative_to(root)))
        duplicates = {".".join(key): paths for key, paths in declarations.items() if len(paths) > 1}
        self.assertEqual(duplicates, {})


if __name__ == "__main__":
    unittest.main()
