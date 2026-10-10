#!/usr/bin/env python3
"""Host-only production CLI selection and rejected combinations; no RTL PASS claim."""
import ast
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
FLAG = '--posted-prefetch-coexistence'


class Selection(unittest.TestCase):
    def call(self, path, arguments, ok=True):
        run = subprocess.run([sys.executable, '-B', str(ROOT / path), *arguments],
                             cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(run.returncode == 0, ok, run.stderr)
        return json.loads(run.stdout) if ok else run.stderr

    def test_default_and_selected_paths(self):
        with tempfile.TemporaryDirectory(prefix='posted-pf-selection-') as directory:
            out = Path(directory) / 'uncreated'
            for script, args in [
                ('simulator/gsim/fpga_next_board.py', ['--tag=posted-pf-selection-only', '--preflight-only']),
                ('fpga/next/export.py', ['--output=' + str(out)]),
            ]:
                ast.parse((ROOT / script).read_text())
                for stores in (False, True):
                    flags = ['--posted-store-merge'] + (['--store-next-line-prefetch'] if stores else [])
                    before = self.call(script, args + flags)
                    after = self.call(script, args + flags + [FLAG])
                    baseline, candidate = before.get('plan', before), after.get('plan', after)
                    self.assertFalse(baseline['posted_prefetch_coexistence'])
                    self.assertTrue(candidate['posted_prefetch_coexistence'])
                    for key in baseline:
                        if key not in ('posted_prefetch_coexistence', 'parameters', 'profile', 'configuration', 'command'):
                            self.assertEqual(candidate[key], baseline[key], key)
                    if 'parameters' in candidate:
                        self.assertEqual(candidate['parameters'], baseline['parameters'] + [FLAG])
                    else:
                        self.assertEqual(candidate['profile'], baseline['profile'] + '-posted-prefetch-coexistence')
                self.assertFalse(out.exists())

    def test_illegal_paths_rejected_before_output(self):
        with tempfile.TemporaryDirectory(prefix='posted-pf-illegal-') as directory:
            out = Path(directory) / 'uncreated'
            for script, args in [
                ('simulator/gsim/fpga_next_board.py', ['--tag=posted-pf-selection-only', '--preflight-only']),
                ('fpga/next/export.py', ['--output=' + str(out)]),
            ]:
                for flags in ([FLAG], [FLAG, '--store-next-line-prefetch']):
                    self.assertIn(FLAG + ' requires --posted-store-merge', self.call(script, args + flags, False))
                self.assertIn('--posted-store-merge excludes --prechecked-data-flow', self.call(
                    script, args + [FLAG, '--posted-store-merge', '--prechecked-data-flow'], False))
                self.assertFalse(out.exists())

    def test_both_scala_entrypoints_accept_same_explicit_option(self):
        for name in ('FpgaNextMain.scala', 'FpgaNextBoardGsimMain.scala'):
            source = (ROOT / 'src/test/scala/ooo' / name).read_text()
            self.assertIn('Set("--posted-prefetch-coexistence", "--posted-store-merge",', source)
            self.assertIn('[--posted-prefetch-coexistence]', source)
            self.assertIn('FpgaNextConfig.fromOptions', source)


if __name__ == '__main__':
    unittest.main()
