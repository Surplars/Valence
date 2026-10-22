"""Pure Tcl mapping-contract regression; not native CDC/STA evidence."""
from pathlib import Path
import shutil
import subprocess
import unittest


@unittest.skipUnless(shutil.which('tclsh'), 'Tcl unavailable')
class ScalarMailboxTests(unittest.TestCase):
    def test_actual_capture_mux_and_oracle_negatives(self):
        result = subprocess.run(['tclsh', str(Path(__file__).with_suffix('.tcl'))],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('SCALAR_MAILBOX_DIRECT_AND_FOLDED_MUX_PASS_NOT_NATIVE_QUALIFIED', result.stdout)
