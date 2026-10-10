#!/usr/bin/env python3
"""Host-only CLI selection checks. These do not establish a hardware PASS."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
FLAG = '--posted-prefetch-head-offer'
DEPENDENCIES = ['--posted-store-merge', '--posted-prefetch-coexistence']


class Selection(unittest.TestCase):
    def call(self, script, args, ok=True):
        result = subprocess.run([sys.executable, '-B', str(ROOT / script), *args],
                                cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(result.returncode == 0, ok, result.stderr)
        return json.loads(result.stdout) if ok else result.stderr

    def test_default_and_selected_profiles(self):
        with tempfile.TemporaryDirectory(prefix='posted-pf-head-offer-') as directory:
            out = Path(directory) / 'uncreated'
            for script, args, profiles in [
                ('simulator/gsim/fpga_next_board.py', ['--tag=head-offer-selection', '--preflight-only'],
                 [[], ['--variant=reference'], ['--variant=candidate'], ['--variant=selected']]),
                ('fpga/next/export.py', ['--output=' + str(out)],
                 [[], ['--reference'], ['--storage-candidate']]),
            ]:
                default = self.call(script, args)
                self.assertFalse(default.get('plan', default)['posted_prefetch_head_offer'])
                for profile in profiles:
                    for store_pf in ([], ['--store-next-line-prefetch'],
                                     ['--store-next-line-prefetch', '--dma-line-transfers', '--dma-line-entries=4']):
                        flags = args + profile + DEPENDENCIES + store_pf
                        before = self.call(script, flags)
                        after = self.call(script, flags + [FLAG])
                        off, on = before.get('plan', before), after.get('plan', after)
                        self.assertFalse(off['posted_prefetch_head_offer'])
                        self.assertTrue(on['posted_prefetch_head_offer'])
                        for key in off:
                            if key not in ('posted_prefetch_head_offer', 'parameters', 'profile', 'configuration', 'command'):
                                self.assertEqual(on[key], off[key], key)
                        if 'parameters' in on:
                            self.assertEqual(on['parameters'], off['parameters'] + [FLAG])
                        else:
                            self.assertEqual(on['command'], off['command'] + [FLAG])
                            configuration = dict(on['configuration'])
                            configuration['posted_prefetch_head_offer'] = False
                            configuration['name'] = configuration['name'].replace('-posted-prefetch-head-offer', '')
                            self.assertEqual(configuration, off['configuration'])
                            suffix = '-posted-prefetch-head-offer'
                            self.assertEqual(on['profile'].count(suffix), 1)
                            self.assertEqual(on['profile'].replace(suffix, ''), off['profile'])
                self.assertFalse(out.exists())

    def test_illegal_combinations_fail_before_output(self):
        with tempfile.TemporaryDirectory(prefix='posted-pf-head-offer-illegal-') as directory:
            out = Path(directory) / 'uncreated'
            for script, args in [
                ('simulator/gsim/fpga_next_board.py', ['--tag=head-offer-selection', '--preflight-only']),
                ('fpga/next/export.py', ['--output=' + str(out)]),
            ]:
                for missing in ([], DEPENDENCIES[:1], DEPENDENCIES[1:]):
                    error = self.call(script, args + missing + [FLAG], False)
                    self.assertIn(FLAG + ' requires --posted-store-merge and --posted-prefetch-coexistence', error)
                error = self.call(script, args + DEPENDENCIES + [FLAG, '--prechecked-data-flow'], False)
                self.assertIn('--posted-store-merge excludes --prechecked-data-flow', error)
                self.assertFalse(out.exists())


if __name__ == '__main__':
    unittest.main()
