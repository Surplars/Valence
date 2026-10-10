#!/usr/bin/env python3
"""Read-only CLI checks: local response flow is the sole explicit profile delta."""
import json
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
FLAGS = ['--lsu-entries', '4', '--virtual-ram-load-precheck', '--physical-load-ingress-flow',
         '--load-order-older-retire', '--fetch-previous-packet', '--dma-line-transfers',
         '--dma-line-entries', '4', '--data-translation-entries', '16', '--prepared-store-lookahead',
         '--store-next-line-prefetch', '--store-prefetch-mru-insertion']


class TranslatedResponseFlowCli(unittest.TestCase):
    def read(self, script, args):
        p = subprocess.run([sys.executable, '-B', str(ROOT / script), *args], cwd=ROOT,
                           check=True, capture_output=True, text=True, timeout=30)
        return json.loads(p.stdout)

    def test_board_has_one_explicit_delta(self):
        base = ['--tag', 'response-flow-cli-only', '--variant', 'selected', '--preflight-only', *FLAGS]
        off = self.read('simulator/gsim/fpga_next_board.py', base)['plan']
        on = self.read('simulator/gsim/fpga_next_board.py', base + ['--translated-response-empty-flow'])['plan']
        self.assertFalse(off['translated_response_empty_flow'])
        self.assertTrue(on['translated_response_empty_flow'])
        self.assertNotIn('--prechecked-data-flow', on['parameters'])
        self.assertEqual([p for p in on['parameters'] if p != '--translated-response-empty-flow'], off['parameters'])
        on['parameters'] = off['parameters']
        on['translated_response_empty_flow'] = False
        self.assertEqual(on, off)

    def test_native_has_one_explicit_delta(self):
        base = ['--output', str(ROOT / 'build/response-flow-native-cli-only'), *FLAGS]
        off = self.read('fpga/next/export.py', base)
        on = self.read('fpga/next/export.py', base + ['--translated-response-empty-flow'])
        self.assertFalse(off['translated_response_empty_flow'])
        self.assertTrue(on['translated_response_empty_flow'])
        self.assertEqual(on['profile'].count('-translated-response-empty-flow'), 1)
        self.assertEqual(on['profile'].replace('-translated-response-empty-flow', ''), off['profile'])
        self.assertFalse(off['configuration']['translated_response_empty_flow'])
        self.assertTrue(on['configuration']['translated_response_empty_flow'])
        self.assertEqual(on['configuration']['name'].count('-translated-response-empty-flow'), 1)
        self.assertEqual(on['configuration']['name'].replace('-translated-response-empty-flow', ''),
                         off['configuration']['name'])
        self.assertEqual(on['command'].count('--translated-response-empty-flow'), 1)
        expected_command = list(off['command'])
        expected_command.insert(expected_command.index('--physical-load-ingress-flow') + 1,
                                '--translated-response-empty-flow')
        self.assertEqual(on['command'], expected_command)
        self.assertEqual([option for option in on['command'] if option != '--translated-response-empty-flow'],
                         off['command'])
        on['configuration']['translated_response_empty_flow'] = False
        on['configuration']['name'] = off['configuration']['name']
        on['command'] = off['command']
        on['profile'] = off['profile']
        on['translated_response_empty_flow'] = False
        self.assertEqual(on, off)

    def test_both_preflights_reject_missing_profile_prerequisites(self):
        entries = [
            ('simulator/gsim/fpga_next_board.py',
             ['--tag', 'response-flow-invalid-cli-only', '--variant', 'selected', '--preflight-only']),
            ('fpga/next/export.py', ['--output', str(ROOT / 'build/response-flow-invalid-cli-only')]),
        ]
        invalid = [
            (['--prechecked-data-flow'], 'prechecked data flow requires --virtual-ram-load-precheck'),
            (['--store-prefetch-mru-insertion'], '--store-prefetch-mru-insertion requires --store-next-line-prefetch'),
            (['--dma-line-entries', '4'], 'multiple DMA line owners require --dma-line-transfers'),
            (['--dma-line-yield-cycles', '4'], 'line yield requires --dma-line-transfers'),
        ]
        for script, base in entries:
            for flags, reason in invalid:
                for flow in ([], ['--translated-response-empty-flow']):
                    with self.subTest(script=script, flags=flags, flow=bool(flow)):
                        p = subprocess.run([sys.executable, '-B', str(ROOT / script), *base, *flags, *flow],
                                           cwd=ROOT, capture_output=True, text=True, timeout=30)
                        self.assertEqual(p.returncode, 2)
                        self.assertIn(reason, p.stderr)

    def test_every_cli_topology_defaults_to_response_flow_off(self):
        for variant in (None, 'reference', 'candidate', 'selected'):
            with self.subTest(board=variant):
                args = ['--tag', 'response-flow-defaults-cli-only', '--preflight-only']
                if variant:
                    args += ['--variant', variant]
                plan = self.read('simulator/gsim/fpga_next_board.py', args)['plan']
                self.assertFalse(plan['translated_response_empty_flow'])
                self.assertNotIn('--translated-response-empty-flow', plan['parameters'])
        for variant in ([], ['--reference'], ['--storage-candidate']):
            with self.subTest(native=variant):
                result = self.read('fpga/next/export.py',
                                   ['--output', str(ROOT / 'build/response-flow-defaults-cli-only'), *variant])
                self.assertFalse(result['translated_response_empty_flow'])
                self.assertNotIn('translated-response-empty-flow', result['profile'])

    def test_native_emit_forwards_only_the_requested_response_option(self):
        # Intercept the actual elaborator boundary; no Scala or RTL tool runs.
        spec = importlib.util.spec_from_file_location('response_flow_export_test', ROOT / 'fpga/next/export.py')
        export = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(export)

        class CommandObserved(Exception):
            pass

        with tempfile.TemporaryDirectory(prefix='valence-response-cli-') as directory:
            commands = []
            head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True)
            for mode in (0, 1):
                output = Path(directory) / str(mode)
                argv = ['export.py', '--emit', '--output', str(output), *FLAGS]
                if mode:
                    argv.append('--translated-response-empty-flow')
                with patch.object(sys, 'argv', argv), patch.object(export.subprocess, 'check_output', return_value=head), patch.object(export.subprocess, 'run',
                        side_effect=CommandObserved) as intercepted:
                    with self.assertRaises(CommandObserved):
                        export.main()
                intercepted.assert_called_once()
                command = intercepted.call_args.args[0]
                self.assertEqual(command[:4], ['mill', '-i', 'IonSoC.test.runMain', 'ooo.FpgaNextMain'])
                self.assertEqual(command[4], str(output / 'rtl'))
                commands.append(command[5:])
            self.assertEqual(commands[1].count('--translated-response-empty-flow'), 1)
            self.assertNotIn('--prechecked-data-flow', commands[1])
            self.assertEqual([arg for arg in commands[1] if arg != '--translated-response-empty-flow'], commands[0])


if __name__ == '__main__':
    unittest.main()
