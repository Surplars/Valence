"""Pure mock syntax/subprocess tests: no WSL, Vivado, native RTL, or hardware run."""
import copy
from pathlib import Path, PureWindowsPath, PurePosixPath
import sys
import tempfile
import tkinter
import unittest
from combined_contract import checked_files, info, validate_constraint_text, validate_validator_revision
from input_contract import relative_input

HERE = Path(__file__).resolve().parent


class ManifestPathTests(unittest.TestCase):
    def test_posix_manifest_names_are_independent_of_windows_spelling(self):
        name = 'firmware/bootrom.bin'
        self.assertNotEqual(str(PureWindowsPath(name)), name)
        self.assertEqual(PurePosixPath(name).as_posix(), name)
        with tempfile.TemporaryDirectory(prefix='mock-manifest-') as directory:
            root = Path(directory)
            path = root/'firmware'/'bootrom.bin'
            path.parent.mkdir(); path.write_bytes(b'mock')
            checked_files(root, {name: info(path)})
            self.assertEqual(relative_input(root, name), path.resolve())
        windows_root = PureWindowsPath('C:/mock/input')
        windows_file = windows_root/PurePosixPath(name)
        self.assertEqual(windows_file.relative_to(windows_root).as_posix(), name)

    def test_nonportable_manifest_paths_fail_closed(self):
        for name in ('../escape', 'firmware/../escape', '/absolute', '//server/share',
                     r'firmware\bootrom.bin', r'\\server\share', 'C:/file', 'C:file',
                     './firmware/bootrom.bin', 'firmware//bootrom.bin', 'firmware/', ''):
            with self.subTest(name=name), self.assertRaises(ValueError):
                checked_files(Path(tempfile.gettempdir()), {name: {}})

    def test_resolved_symlink_escape_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix='mock-escape-') as directory:
            root = Path(directory)/'root'; root.mkdir()
            outside = Path(directory)/'outside'; outside.mkdir()
            (outside/'file').write_bytes(b'mock')
            try:
                (root/'link').symlink_to(outside, target_is_directory=True)
            except OSError as error:
                self.skipTest('Symlink creation unavailable: '+str(error))
            with self.assertRaisesRegex(ValueError, 'escapes its root'):
                checked_files(root, {'link/file': info(outside/'file')})


class ConstraintCommentTests(unittest.TestCase):
    def test_full_line_comment_does_not_load_a_file(self):
        validate_constraint_text('# XDC uses individual set_property commands (Vivado read_xdc does not accept foreach).\nset_property PACKAGE_PIN A1 [get_ports clk]\n', 'mock.xdc')
        validate_constraint_text('  # source old.xdc; [exec bad]\nset_property IOSTANDARD LVCMOS18 [get_ports x]\n', 'mock.xdc')

    def test_real_loading_commands_remain_rejected(self):
        for text in ('source old.xdc\n', 'read_xdc old.xdc\n', 'exec program\n',
                     'set value [source old.xdc]\n', 'set value "[exec program]"\n',
                     'set value "line1\n# [source old.xdc]\n"\n',
                     'set value [format "%s"\n# [exec program]\n]\n',
                     'set value \\\n# [source old.xdc]\n'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                validate_constraint_text(text, 'mock.xdc')

    def test_script_revision_may_not_relabel_rtl_source(self):
        source = dict(commit='original', gitlinks={}, files={'src/main/rtl.scala': {'sha256':'a'},
                       'fpga/next/physical_eval/combined_runtime.tcl': {'sha256':'b'}})
        validator = copy.deepcopy(source);validator['commit'] = 'validator'
        validator['files']['fpga/next/physical_eval/combined_runtime.tcl'] = {'sha256':'c'}
        validate_validator_revision(source, validator)
        self.assertEqual(source['commit'], 'original')
        validator['files']['src/main/rtl.scala'] = {'sha256':'d'}
        with self.assertRaisesRegex(ValueError, 'non-staging source'):
            validate_validator_revision(source, validator)


class StderrCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='mock-stderr-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.tcl = tkinter.Tcl()
        self.tcl.eval((HERE/'combined_runtime.tcl').read_text())
        self.tcl.call('set', '::combined_runtime_root', str(self.root))

    def command(self, status):
        return (sys.executable, '-c', 'import sys;sys.stdout.write(\'{"ok":true}\\n\');'
                'sys.stderr.buffer.write("WSL mock warning".encode("utf-16le"));sys.exit('+str(status)+')')

    def test_zero_exit_warning_keeps_json_stdout_and_raw_utf16_stderr(self):
        result = self.tcl.call('combined_exec', self.command(0))
        self.assertEqual(result, '{"ok":true}')
        logs = list((self.root/'combined-runtime-stderr').glob('*.bin'))
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].read_bytes(), 'WSL mock warning'.encode('utf-16le'))
        self.assertIn('tcl_code 0', Path(str(logs[0])+'.status').read_text())

    def test_nonzero_exit_never_accepted_even_with_valid_stdout(self):
        with self.assertRaises(tkinter.TclError):
            self.tcl.call('combined_exec', self.command(7))
        self.assertIn('CHILDSTATUS', self.tcl.eval('set errorCode'))
        self.assertTrue(self.tcl.eval('set errorCode').endswith('7'))
        status = next((self.root/'combined-runtime-stderr').glob('*.status')).read_text()
        self.assertIn('tcl_code 1', status)
        self.assertIn('CHILDSTATUS', status)

    def test_separate_logs_preserve_every_invocation(self):
        for _ in range(2): self.tcl.call('combined_exec', self.command(0))
        self.assertEqual(len(list((self.root/'combined-runtime-stderr').glob('*.bin'))), 2)


if __name__ == '__main__':
    unittest.main()
