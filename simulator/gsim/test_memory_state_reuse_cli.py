#!/usr/bin/env python3
"""Host-only selection, forwarding and default-isolation checks; never builds RTL."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
OPTIONS = {'--reconstruct-issue-token-index': 'reconstruct_issue_token_index',
           '--shared-memory-address-state': 'shared_memory_address_state'}


class MemoryStateReuseCliTests(unittest.TestCase):
    def call(self, script, args, accepted=True):
        result = subprocess.run([sys.executable, '-B', str(ROOT / script), *args], cwd=ROOT,
                                text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0 if accepted else 2, result.stdout + result.stderr)
        return json.loads(result.stdout) if accepted else result.stderr

    def test_independent_native_and_gsim_selectors_preserve_other_configuration(self):
        with tempfile.TemporaryDirectory(prefix='memory-state-cli-') as tmp:
            output = Path(tmp) / 'must-remain-absent'
            for native_selector, variant in (([], 'selected'), (['--reference'], 'reference'),
                                             (['--storage-candidate'], 'candidate')):
                for geometry in ([], ['--rob-entries=64', '--physical-regs=64', '--lsu-entries=4',
                                      '--data-translation-entries=16']):
                    native_args = ['--output', str(output), *native_selector, *geometry]
                    board_args = ['--tag', 'memory-state-cli', '--preflight-only', '--variant', variant, *geometry]
                    off = self.call('fpga/next/export.py', native_args)
                    board_off = self.call('simulator/gsim/fpga_next_board.py', board_args)
                    for flag, field in OPTIONS.items():
                        with self.subTest(variant=variant, geometry=geometry, flag=flag):
                            self.assertNotIn(flag, off['command'])
                            self.assertNotIn(field, off['configuration'])
                            self.assertIs(board_off['plan'][field], False)
                            on = self.call('fpga/next/export.py', native_args + [flag])
                            board_on = self.call('simulator/gsim/fpga_next_board.py', board_args + [flag])
                            self.assertEqual(on['command'][5:], board_on['plan']['parameters'])
                            self.assertEqual(on['command'].count(flag), 1)
                            self.assertEqual([x for x in on['command'] if x != flag], off['command'])
                            configuration = copy.deepcopy(on['configuration'])
                            self.assertIs(configuration.pop(field), True)
                            configuration['name'] = configuration['name'].replace(flag[1:], '')
                            self.assertEqual(configuration, off['configuration'])
                            plan = copy.deepcopy(board_on['plan'])
                            self.assertIs(plan[field], True)
                            plan[field] = False
                            plan['parameters'].remove(flag)
                            self.assertEqual(plan, board_off['plan'])
                            self.assertFalse(Path(board_on['output']).exists())
                    both = self.call('fpga/next/export.py', native_args + list(OPTIONS))
                    board_both = self.call('simulator/gsim/fpga_next_board.py', board_args + list(OPTIONS))
                    self.assertEqual(both['command'][5:], board_both['plan']['parameters'])
                    configuration = copy.deepcopy(both['configuration'])
                    plan = copy.deepcopy(board_both['plan'])
                    for flag, field in OPTIONS.items():
                        self.assertEqual(both['command'].count(flag), 1)
                        self.assertIs(configuration.pop(field), True)
                        configuration['name'] = configuration['name'].replace(flag[1:], '')
                        self.assertIs(plan[field], True)
                        plan[field] = False
                        plan['parameters'].remove(flag)
                    self.assertEqual(configuration, off['configuration'])
                    self.assertEqual(plan, board_off['plan'])
                    self.assertEqual([x for x in both['command'] if x not in OPTIONS], off['command'])
                    self.assertFalse(Path(board_both['output']).exists())
            self.assertFalse(output.exists())

    def test_duplicate_and_valued_boolean_forms_rejected_before_output(self):
        with tempfile.TemporaryDirectory(prefix='memory-state-reject-') as tmp:
            output = Path(tmp) / 'must-remain-absent'
            for flag in OPTIONS:
                for bad in ([flag, flag], [flag + '=true'], [flag + '=false'], [flag + '=1'],
                            [flag + '='], [flag, 'true']):
                    with self.subTest(arguments=bad):
                        for script, args in (
                                ('fpga/next/export.py', ['--output', str(output)]),
                                ('simulator/gsim/fpga_next_board.py',
                                 ['--tag', 'memory-state-rejected', '--preflight-only'])):
                            error = self.call(script, args + bad, accepted=False)
                            self.assertIn(flag, error)
            self.assertFalse(output.exists())

    def test_recommended_preset_stays_exactly_frozen(self):
        expected = json.loads((ROOT / 'fpga/next/performance-profile.json').read_text())
        with tempfile.TemporaryDirectory(prefix='memory-state-preset-') as tmp:
            output = Path(tmp) / 'must-remain-absent'
            for mode, flags in (('on', []), ('off', ['--disable-posted'])):
                preset = self.call('fpga/next/performance.py', ['--output', str(output), *flags])
                self.assertEqual(preset['configuration'], expected[mode])
                for flag, field in OPTIONS.items():
                    self.assertNotIn(flag, preset['command'])
                    self.assertNotIn(field, preset['configuration'])
            self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
