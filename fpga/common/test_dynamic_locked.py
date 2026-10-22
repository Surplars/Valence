"""Narrow asynchronous LOCKED contract and external-overlay binding controls."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import resume_diagnostic as resume

HERE = Path(__file__).resolve().parent
DYNAMIC = 'dynamic/dynamic_clock_constraints.tcl'


class DynamicLockedTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('tclsh'), 'Tcl unavailable')
    def test_mapped_contract_and_ordinary_mutations(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(['tclsh', str(HERE / 'test_dynamic_locked.tcl')],
                                    cwd=directory, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('DYNAMIC_LOCKED_CONTRACT_PASS', result.stdout)
        self.assertIn('OLD_LOCKED_3.333_NOT_A_VALID_BOUND', result.stdout)
        self.assertIn('slack=-0.1', result.stdout)

    def test_external_synthesis_and_post_opt_use_same_overlay(self):
        expected = 'source [file join [file dirname [file normalize [info script]]] dynamic dynamic_clock_constraints.tcl]'
        forbidden = 'source [file join $valence(root) fpga common dynamic dynamic_clock_constraints.tcl]'
        for name in ('synthesize.tcl', 'post_opt.tcl'):
            script = (HERE / name).read_text()
            self.assertIn(expected, script)
            self.assertNotIn(forbidden, script)
            self.assertIn('native_dynamic_clock_constraints', script)
        self.assertIn(DYNAMIC, resume.CACHE_TOOLS)
        self.assertIn(DYNAMIC, resume.POST_PROOFS)
        self.assertEqual(resume.continuation_tools()[DYNAMIC], resume.sha(HERE / DYNAMIC))

    def test_recovery_receipt_binds_external_dynamic_checker(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            out = root / 'diagnostic-run/synthesis'
            (out / 'project').mkdir(parents=True)
            (out / 'project/common_board.xpr').write_text('preserved project')
            (out / 'diagnostic-failure.txt').write_text('original failure')
            (out / 'ip-synthesis.json').write_text('preserved IP evidence')
            (root / 'diagnostic.json').write_text('original manifest')
            diagnostic = mock.Mock(STATUS='DIAGNOSTIC_UNQUALIFIED_NO_BITSTREAM')
            manifest = {'configuration': {'clock_profile': 'performance300-static'}}
            with mock.patch.object(resume, 'frozen', return_value=(diagnostic, manifest, 'profile')), \
                 mock.patch.object(resume, 'verify_dcps', return_value={'original.dcp': 'hash'}):
                record = resume.check(root)
            self.assertEqual(record['recovery_tool_sha256'][DYNAMIC], resume.sha(HERE / DYNAMIC))
            self.assertEqual((root / 'diagnostic.json').read_text(), 'original manifest')
            self.assertFalse((out / 'raw-synthesized-unqualified.dcp').exists())


if __name__ == '__main__':
    unittest.main()
