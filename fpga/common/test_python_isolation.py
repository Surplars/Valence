"""External Python must ignore Vivado's incompatible Python environment."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).parent
EXPECTED = {'diagnostic.tcl': 2, 'producer_common.tcl': 2,
            'resume_diagnostic.tcl': 1, 'board_audit.tcl': 1, 'simulate.tcl': 1, 'signoff.tcl': 1}


class PythonIsolationTests(unittest.TestCase):
    def prefixes(self):
        result = {}
        for path in HERE.glob('*.tcl'):
            calls = re.findall(r'exec\s+(\$(?:::)?valence\(python\)|\$python)\s+([^\s]+)', path.read_text())
            if calls:
                result[path.name] = calls
        return result

    def test_all_external_python_argv_ignore_environment(self):
        calls = self.prefixes()
        self.assertEqual({p: len(v) for p, v in calls.items()}, EXPECTED)
        for path, entries in calls.items():
            for variable, flag in entries:
                self.assertEqual(flag, '-E', path)

    @unittest.skipUnless(shutil.which('tclsh'), 'Tcl interpreter unavailable')
    def test_poisoned_python_environment_and_negative_control(self):
        with tempfile.TemporaryDirectory(prefix='python isolation ') as tmp:
            root = Path(tmp)
            (root/'re.py').write_text("raise AssertionError('SRE module mismatch negative control')\n")
            # Probe stays elsewhere so its own script directory is not the poison.
            probe = root/'probe'; probe.mkdir()
            script = probe/'check.py'
            script.write_text("import re, sys\nassert sys.flags.ignore_environment == 1\nprint('ISOLATED')\n")
            env = dict(os.environ, PYTHONPATH=str(root))
            negative = subprocess.run([sys.executable, str(script)], env=env, capture_output=True, text=True)
            self.assertNotEqual(negative.returncode, 0)
            self.assertIn('SRE module mismatch negative control', negative.stderr)
            env['PYTHONHOME'] = str(root/'nonexistent-vivado-home')
            for entries in self.prefixes().values():
                for variable, flag in entries:
                    # Exercise the actual Tcl command prefix and argv, not a shell.
                    command = ('set python {'+sys.executable+'}\nset valence(python) $python\n'
                               'if {[catch {exec '+variable+' '+flag+' {'+str(script)+'}} result]} {puts stderr $result; exit 1}\nputs $result\n')
                    run = subprocess.run(['tclsh'], input=command, env=env, capture_output=True, text=True)
                    self.assertEqual(run.returncode, 0, run.stderr)
                    self.assertEqual(run.stdout.strip(), 'ISOLATED')


if __name__ == '__main__':
    unittest.main()
