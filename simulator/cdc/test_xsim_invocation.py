import tempfile
import unittest
from pathlib import Path
from xsim_invocation import invocation, resolve_tool

class XsimInvocationTest(unittest.TestCase):
    def test_windows_prefers_batch_over_unix_launcher(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in ('xelab', 'xelab.bat', 'xelab.exe'):
                (Path(directory) / name).touch()
            self.assertTrue(resolve_tool('xelab', directory, windows=True).endswith('xelab.bat'))
            self.assertTrue(resolve_tool('xelab', directory, windows=False).endswith('/xelab'))
    def test_windows_never_falls_back_to_unix_launcher(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / 'xsim').touch()
            with self.assertRaises(RuntimeError):
                resolve_tool('xsim', directory, windows=True)
    def test_batch_generic_is_one_quoted_token(self):
        actual = invocation([r'C:\Program Files\Vivado\xelab.bat', 'fixed_timebase_tb',
                             '-generic_top', 'FABRIC_HALF=5', '-timescale', '1ns/1ps'],
                            windows=True, comspec='cmd.exe')
        self.assertEqual(actual, '"cmd.exe" /d /s /c ""C:\\Program Files\\Vivado\\xelab.bat" '
                         '"fixed_timebase_tb" "-generic_top" "FABRIC_HALF=5" "-timescale" "1ns/1ps""')
    def test_native_executable_preserves_argument_vector(self):
        args = ['xelab.exe', '-generic_top', 'FABRIC_HALF=5']
        self.assertEqual(invocation(args, windows=True), args)
        self.assertEqual(invocation(['xelab', '-generic_top', 'FABRIC_HALF=5'], windows=False),
                         ['xelab', '-generic_top', 'FABRIC_HALF=5'])
    def test_unsupported_batch_quote_rejected(self):
        with self.assertRaises(ValueError):
            invocation(['xelab.bat', 'bad"argument'], windows=True)

if __name__ == '__main__':
    unittest.main()
