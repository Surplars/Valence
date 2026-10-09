"""Host-only selector checks. Never compile Scala, emit RTL or run a model."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
COMMON = ['--virtual-ram-load-precheck', '--lsu-entries', '4', '--physical-load-ingress-flow',
          '--load-order-older-retire', '--fetch-previous-packet', '--dma-line-transfers', '--dma-line-entries', '4']

class DataTranslationCapacityCliTests(unittest.TestCase):
    def command(self, script, options, ok=True):
        proc = subprocess.run([sys.executable, '-B', str(ROOT / script), *options],
                              cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0 if ok else 2, proc.stdout + proc.stderr)
        return json.loads(proc.stdout) if ok else proc.stderr

    def test_native_preflight_legal_and_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'native'
            for entries in (None, 4, 8, 16, 32):
                opts = ['--output', str(output), *COMMON]
                if entries is not None: opts += ['--data-translation-entries', str(entries)]
                result = self.command('fpga/next/export.py', opts)
                self.assertEqual(result['status'], 'PREFLIGHT_ONLY')
                self.assertEqual(result['data_translation_entries'], entries or 8)
                self.assertEqual((result['instruction_translation_entries'], result['pte_cache_entries']), (8, 4))
                self.assertFalse(output.exists())

    def test_gsim_preflight_changes_only_capacity(self):
        base = None
        for entries in (None, 4, 8, 16, 32):
            opts = ['--tag', 'dtlb-host-only-never-built', '--variant', 'selected', '--preflight-only', *COMMON]
            if entries is not None: opts += ['--data-translation-entries', str(entries)]
            result = self.command('simulator/gsim/fpga_next_board.py', opts)
            self.assertFalse(Path(result['output']).exists())
            plan = result['plan']
            self.assertEqual(plan['data_translation_entries'], entries or 8)
            self.assertEqual((plan['instruction_translation_entries'], plan['pte_cache_entries']), (8, 4))
            self.assertIn('--data-translation-entries=' + str(entries or 8), plan['parameters'])
            self.assertNotIn('--prechecked-data-flow', plan['parameters'])
            self.assertNotIn('--authorized-store-merge', plan['parameters'])
            del plan['data_translation_entries']
            plan['parameters'] = [x for x in plan['parameters'] if not x.startswith('--data-translation-entries=')]
            if base is None: base = plan
            self.assertEqual(plan, base)

    def test_both_clis_reject_illegal_capacities_before_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            for entries in ('-1', '0', '2', '6', '9', '17', '33', '64', 'nope'):
                self.command('fpga/next/export.py', ['--output', tmp + '/native',
                    '--data-translation-entries', entries], ok=False)
                self.command('simulator/gsim/fpga_next_board.py', ['--tag', 'dtlb-rejected',
                    '--data-translation-entries', entries], ok=False)
            self.assertFalse((Path(tmp) / 'native').exists())
            self.assertFalse((ROOT / 'build/gsim/fpga-next-board-dtlb-rejected').exists())

if __name__ == '__main__':
    unittest.main()
