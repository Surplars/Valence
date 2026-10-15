"""Lightweight boundary tests; no hardware simulator or Vivado invocation."""
import importlib.util
if not __debug__:
    raise SystemExit('Safety checks require Python without -O')

from pathlib import Path
import subprocess
import sys
import tempfile
import tkinter
import unittest
from input_contract import relative_input, tcl_value, positive_threads

HERE = Path(__file__).resolve().parent


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tcl = tkinter.Tcl()
        self.tcl.eval((HERE / 'runtime.tcl').read_text(encoding='utf-8'))

    def test_all_tcl_is_complete_and_has_no_route_or_bit_command(self):
        import re
        for path in HERE.glob('*.tcl'):
            text = path.read_text(encoding='utf-8')
            self.assertEqual(int(self.tcl.call('info', 'complete', text)), 1, path)
            self.assertIsNone(re.search(r'^\s*(route_design|write_bitstream)\b', text, re.M))

    def test_thread_syntax_rejects_invalid_inputs_and_accepts_explicit_16(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'physical-config.tcl'
            for threads in (0, -1, '3.5', 'bad'):
                path.write_text('set ::r3_config [dict create threads {' + str(threads) +
                                '} part part python_mode native python_command python3 '
                                'wsl_command wsl.exe wsl_distribution {} rom_sha256 h padded_sha256 h]')
                with self.assertRaises(tkinter.TclError):
                    self.tcl.call('r3_load_config', directory)
            template = path.read_text(encoding='utf-8')
            for threads in (1, 4, 16, 32):
                path.write_text(template.replace('threads {bad}', 'threads {'+str(threads)+'}'))
                self.tcl.call('r3_load_config', directory)
                self.assertEqual(self.tcl.eval('dict get $::r3_config threads'), str(threads))

    def test_unique_query_preserves_collection_and_fails_on_multiple(self):
        self.tcl.eval((HERE / 'r3_common.tcl').read_text(encoding='utf-8'))
        self.tcl.eval('proc fixture {args} {return [list {pin with spaces}]}')
        self.assertEqual(self.tcl.eval('r3_one fixture pattern'), '{pin with spaces}')
        self.tcl.eval('proc fixture {args} {return [list a b]}')
        with self.assertRaises(tkinter.TclError):
            self.tcl.eval('r3_one fixture pattern')

    def test_prepare_rejects_invalid_threads_and_missing_wsl_selection(self):
        args = [sys.executable, '-B', str(HERE / 'prepare.py')]
        for key in ('source-root', 'run-root', 'native-root', 'ip-root', 'ip-manifest', 'rom-root'):
            args += ['--' + key, 'unused']
        args += ['--commit', 'a' * 40, '--rom-sha256', 'b' * 64,
                 '--padded-sha256', 'c' * 64, '--python-mode', 'wsl', '--python-command', 'python3']
        for extra in ([], ['--threads', '0'], ['--threads', '-1'], ['--threads', '3.5']):
            result = subprocess.run(args + extra, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertNotIn('Traceback', result.stderr)

    def test_python_thread_syntax_has_no_artificial_policy_ceiling(self):
        for value in ('1', '4', '16', '32', '64'):
            self.assertEqual(positive_threads(value), int(value))
        for value in ('0', '-1', '3.5', 'bad', '', True):
            with self.assertRaises(ValueError):
                positive_threads(value)

    def thread_fixture(self):
        self.tcl.eval('set ::r3_config [dict create threads 16]')
        self.tcl.eval('proc version {args} {return mock-tool}')
        self.tcl.eval('proc set_param {name value} {set ::observed $value}')
        self.tcl.eval('proc get_param {name} {return $::observed}')

    def test_applied_threads_are_read_back_and_recorded(self):
        self.thread_fixture()
        with tempfile.TemporaryDirectory() as directory:
            previous = self.tcl.eval('pwd')
            try:
                self.tcl.call('cd', directory)
                self.tcl.eval('r3_apply_threads before_opt')
                text = (Path(directory) / 'threads.tsv').read_text(encoding='utf-8')
                self.assertIn('before_opt\t16\t16\tAPPLIED\tmock-tool', text)
            finally:
                self.tcl.call('cd', previous)

    def test_tool_rejection_and_silent_clamping_abort_with_evidence(self):
        self.thread_fixture()
        with tempfile.TemporaryDirectory() as directory:
            previous = self.tcl.eval('pwd')
            try:
                self.tcl.call('cd', directory)
                self.tcl.eval('proc set_param {name value} {error {unsupported by fixture tool}}')
                with self.assertRaises(tkinter.TclError):
                    self.tcl.eval('r3_apply_threads rejected')
                self.tcl.eval('proc set_param {name value} {set ::observed 8}')
                with self.assertRaises(tkinter.TclError):
                    self.tcl.eval('r3_apply_threads clamped')
                text = (Path(directory) / 'threads.tsv').read_text(encoding='utf-8')
                self.assertIn('\tREJECTED\t', text)
                self.assertIn('clamped\t16\t8\tMISMATCH\t', text)
            finally:
                self.tcl.call('cd', previous)

    def test_summary_rejects_path_traversal(self):
        spec = importlib.util.spec_from_file_location('summary', HERE / 'summarize.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with self.assertRaises(ValueError):
            module.summarize(HERE, '../other')

    def test_config_values_are_literal_including_empty_and_tcl_metacharacters(self):
        for value in ('', 'space path', '$env(HOME);[error injected]\\{}', '中文'):
            self.tcl.eval('set fixture ' + tcl_value(value))
            self.assertEqual(self.tcl.eval('set fixture'), value)
        command = ['python command', '-B', '[error injected]']
        self.tcl.eval('set fixture ' + tcl_value(command))
        self.assertEqual(tuple(self.tcl.splitlist(self.tcl.eval('set fixture'))), tuple(command))

    def test_manifest_rejects_parent_absolute_and_foreign_paths(self):
        for name in ('../secret', '/secret', 'ip-build/../../secret', 'C:/secret', 'ip-build/..\\secret'):
            with self.assertRaises(ValueError):
                relative_input(HERE, name)
        self.assertEqual(relative_input(HERE, 'board/pins.xdc'), HERE / 'board/pins.xdc')


if __name__ == '__main__':
    unittest.main()
