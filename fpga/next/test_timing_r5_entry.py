#!/usr/bin/env python3
"""Host-only fail-closed tests; never starts Vivado or a hardware compiler."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.dont_write_bytecode = True
import board_timing_r5 as entry
import run_timing_r5 as run

class EntryTests(unittest.TestCase):
    def test_qualification_controls(self):
        pins = entry.read(entry.HERE / 'timing-r5-input-pins.json')
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'component').write_text('actual component test receipt')
            (root / 'integration').write_text('actual integrated run receipt')
            (root / 'plan').write_text('the exact executed plan')
            (root / 'model.o').write_text('test fixture, not actual model evidence')
            files = {x: entry.sha(root / x) for x in ('component', 'integration', 'plan')}
            q = {'schema': 'valence-r5-structural-ready73-qualification-v1',
                'physical_qualification': False, 'historical_cpu_qualification_inherited': False,
                'candidate': entry.CANDIDATE, 'status': 'PASS_COMPONENT_AND_SEVEN_POSITIVE_EIGHT_NEGATIVE',
                'source_freeze_sha256': pins['source_freeze_sha256'],
                'compile_receipt_sha256': pins['compile_receipt_sha256'],
                'native_emission_receipt_sha256': pins['native_receipt_sha256'],
                'short_tests_receipt_sha256': files['component'], 'integration_receipt_sha256': files['integration'],
                'integration_plan_sha256': files['plan'], 'evidence_files': files,
                'new_model_objects': {'model.o': entry.sha(root / 'model.o')}}
            path = root / 'qualification.json'
            path.write_text(json.dumps(q))
            with patch.object(run, 'sha', return_value=pins['qualification_sha256']):
                run.qualification(path)
            for key in ('schema', 'candidate', 'status', 'source_freeze_sha256', 'compile_receipt_sha256',
                        'native_emission_receipt_sha256', 'short_tests_receipt_sha256',
                        'integration_receipt_sha256', 'integration_plan_sha256'):
                altered = copy.deepcopy(q)
                altered[key] = 'WRONG_OR_PENDING'
                path.write_text(json.dumps(altered))
                with patch.object(run, 'sha', return_value=pins['qualification_sha256']), self.assertRaises(RuntimeError, msg=key):
                    run.qualification(path)
            path.write_text(json.dumps(q))
            # Even an internally valid substitute receipt is refused by its bytes.
            with self.assertRaises(RuntimeError):
                run.qualification(path)
            (root / 'integration').write_text('mutated')
            with patch.object(run, 'sha', return_value=pins['qualification_sha256']), self.assertRaises(RuntimeError):
                run.qualification(path)

    def test_unsafe_or_changed_file(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for name in ('../escape', '/absolute', 'missing'):
                with self.assertRaises(RuntimeError):
                    entry.check_files(root, {name: 'bad'})

    def test_launcher_refuses_missing_gate_before_process(self):
        with patch.object(run, 'verify'), patch.object(run.subprocess, 'run') as process:
            with self.assertRaises(FileNotFoundError):
                run.launch('vivado', Path('src'), Path('export'), Path('binding'), Path('out'), Path('/nonexistent-r5-qualification'))
            process.assert_not_called()

    def test_original_failure_propagation(self):
        with tempfile.TemporaryDirectory() as d, patch.object(run, 'verify'), patch.object(run, 'qualification'), patch.object(run, 'sha', return_value='fixture'):
            for code in (1, 7, -9, 0):
                with patch.object(run.subprocess, 'run', return_value=subprocess.CompletedProcess([], code)):
                    self.assertEqual(run.launch('vivado', Path('source'), Path('export'), Path('binding'), Path(d) / 'out', Path('q')), {1: 1, 7: 7, -9: 137, 0: 1}[code])

    def test_native_actual_mutations(self):
        # Small constructor-shaped fixtures use the existing actual comparator.
        source = Path(__file__).resolve().parents[4] / 'source'
        if not source.is_dir():
            self.skipTest('run in the prepared handoff tree for real profile mutations')
        profile = entry.read(source / 'fpga/next/timing-ready73-profile.json')
        old = entry.module(source, 'board_timing_ready73.py')
        fixtures = {'profile.json': profile['on_profile'],
            'actual-product-field-order.json': {k: profile[k + '_fields'] for k in ('core', 'profile')},
            'actual-timing-closure.json': old.expected(profile, 'on', 'timing_audit'),
            'timing-ready73-entry.json': old.completion(profile)}
        for name, key in [('actual-held-alu-forwarding.json', 'held'), ('actual-resident-memory.json', 'resident'), ('actual-mac-raw-handoff.json', 'mac')]:
            fixtures[name] = old.expected(profile, 'on', 'existing_audits')[key]
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for name, data in fixtures.items():
                (root / name).write_text(json.dumps(data))
            (root / 'options.txt').write_text(''.join(x + '\n' for x in profile['on_options']))
            entry.actual(source, root, profile)
            for name, data in fixtures.items():
                (root / name).write_text('{}')
                with self.assertRaises(RuntimeError, msg=name):
                    entry.actual(source, root, profile)
                (root / name).write_text(json.dumps(data))
            (root / 'options.txt').write_text('wrong option order')
            with self.assertRaises(RuntimeError):
                entry.actual(source, root, profile)

if __name__ == '__main__':
    unittest.main()
