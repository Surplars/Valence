#!/usr/bin/env python3
"""No-build command/config isolation and source-bound authorization invariants."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
FLAG = '--posted-preparation-priority'
PARENTS = ['--prepared-store-lookahead', '--posted-store-merge']
# Raw tree of published e2f506c9a67a742d3bcd63751625e82840fb53e3.
# A normal checkout need not contain the private tree-equivalent recovery commit.
BASE = '20831b2ee236504cbcfb3536af70d4f9d62f84f5'


class PostedPreparationPriorityCliTests(unittest.TestCase):
    def call(self, script, args, accepted=True):
        result = subprocess.run([sys.executable, '-B', str(ROOT / script), *args], cwd=ROOT,
                                text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0 if accepted else 2, result.stdout + result.stderr)
        if not accepted:
            self.assertIn(FLAG + ' requires --prepared-store-lookahead and --posted-store-merge', result.stderr)
            return None
        return json.loads(result.stdout)

    def test_exact_option_forwarding_and_configuration_isolation(self):
        with tempfile.TemporaryDirectory(prefix='posted-preparation-cli-') as tmp:
            output = Path(tmp) / 'must-remain-absent'
            for native_selector, variant in (([], 'selected'), (['--reference'], 'reference'),
                                             (['--storage-candidate'], 'candidate')):
                for parents in ([], PARENTS):
                    off = self.call('fpga/next/export.py', ['--output', str(output), *native_selector, *parents])
                    board_off = self.call('simulator/gsim/fpga_next_board.py',
                        ['--tag', 'posted-preparation-cli', '--preflight-only', '--variant', variant, *parents])
                    self.assertNotIn(FLAG, off['command'])
                    self.assertNotIn('posted_preparation_priority', off['configuration'])
                    self.assertFalse(board_off['plan']['posted_preparation_priority'])
                    if not parents:
                        continue
                    on = self.call('fpga/next/export.py', ['--output', str(output), *native_selector, *parents, FLAG])
                    board_on = self.call('simulator/gsim/fpga_next_board.py',
                        ['--tag', 'posted-preparation-cli', '--preflight-only', '--variant', variant, *parents, FLAG])
                    self.assertEqual(on['command'][5:], board_on['plan']['parameters'])
                    self.assertEqual(on['command'].count(FLAG), 1)
                    self.assertEqual([x for x in on['command'] if x != FLAG], off['command'])
                    configuration = on['configuration']
                    self.assertIs(configuration.pop('posted_preparation_priority'), True)
                    configuration['name'] = configuration['name'].replace('-posted-preparation-priority', '')
                    self.assertEqual(configuration, off['configuration'])
                    plan = board_on['plan']
                    self.assertIs(plan.pop('posted_preparation_priority'), True)
                    plan['parameters'].remove(FLAG)
                    board_off['plan'].pop('posted_preparation_priority')
                    self.assertEqual(plan, board_off['plan'])
                    self.assertFalse(Path(board_on['output']).exists())
            self.assertFalse(output.exists())

    def test_each_missing_parent_rejected_before_build_or_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'must-remain-absent'
            for parents in ([], PARENTS[:1], PARENTS[1:]):
                self.call('fpga/next/export.py', ['--output', str(output), *parents, FLAG], False)
                self.call('simulator/gsim/fpga_next_board.py',
                    ['--tag', 'posted-preparation-rejected', '--preflight-only', *parents, FLAG], False)
            self.assertFalse(output.exists())

    def test_launch_seal_payload_and_prepared_store_qualification_are_unchanged(self):
        name = 'src/main/scala/core/ooo/integration/IntegerBackend.scala'
        old = subprocess.check_output(['git', 'show', BASE + ':src/main/scala/core/ooo/IntegerBackend.scala'], cwd=ROOT, text=True)
        current = (ROOT / name).read_text()
        before = '                }).asUInt\n                Mux(originalMemoryMask.orR, originalMemoryMask, preparedStoreMask)'
        self.assertEqual(old.split(before)[0], current.split('                }).asUInt\n                if (p.postedPreparationPriority)')[0])
        boundary = '            planner.io.eligible := preparationMask'
        self.assertEqual(old.split(boundary)[1], current.split(boundary)[1])
        # These modules own accepted transactions, PMP checks, ACK/fault handling and selector ranks.
        for name in ('PostedStoreMerge', 'PostedStoreCpu', 'ParallelLoadStoreUnit', 'MemoryPreparationSelector'):
            path = 'src/main/scala/core/ooo/lsu/' + name + '.scala'
            historical_path = 'src/main/scala/core/ooo/' + name + '.scala'
            reference = subprocess.check_output(['git', 'show', BASE + ':' + historical_path], cwd=ROOT)
            self.assertEqual(hashlib.sha256(reference).digest(), hashlib.sha256((ROOT / path).read_bytes()).digest())


if __name__ == '__main__':
    unittest.main(verbosity=2)
