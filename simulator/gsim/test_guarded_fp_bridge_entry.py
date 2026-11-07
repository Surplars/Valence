"""Mock-only orchestration/replay sensitivity. These packets are not hardware evidence."""
import copy
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch


class GuardedFpBridgeEntryTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='mock-only-fp-bridge-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.common = types.ModuleType('run')
        self.common.ROOT = self.root
        self.common.BUILD = self.root / 'build'
        self.common.setup = Mock(return_value=('pinned-gsim', 'clang++-19'))
        self.common.test = Mock(side_effect=self.generate)
        spec = importlib.util.spec_from_file_location('fp_bridge_entry', Path(__file__).with_name('guarded_fp_bridge.py'))
        self.e = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'run': self.common}): spec.loader.exec_module(self.e)
        self.records = {name: self.mock_records(name) for name in self.e.SCHEDULES}

    def mock_records(self, schedule):
        e = self.e
        ledger = e.Replay()
        rows = [e.header(schedule)]
        for number, (phase, stimulus) in enumerate(e.plan(schedule)):
            output = {**dict.fromkeys(e.OUTPUT_WIDTHS, 0), **ledger.step(stimulus)}
            rows.append({'type': 'cycle', 'cycle': number, 'phase': phase, 'in': stimulus,
                'pre': output, 'post': {key: ledger.state[key] for key in e.POST_WIDTHS}})
        return rows + [{'type': 'footer', 'cycles': len(rows) - 1, 'complete': True}]

    def trace(self, schedule='baseline', records=None):
        return ''.join(json.dumps(row) + '\n' for row in (self.records[schedule] if records is None else records))

    def check(self, schedule='baseline', records=None, text=None, summary=None):
        log, trace = self.root / 'positive.log', self.root / 'raw.jsonl'
        log.write_text(self.e.MARKER + ' ' + json.dumps(self.e.expected_summary(schedule) if summary is None else summary) + '\n')
        trace.write_text(self.trace(schedule, records) if text is None else text)
        return self.e.check_positive(log, schedule, trace)

    def generate(self, gsim, cxx, output, *args, **kwargs):
        output = Path(output)
        output.mkdir(parents=True)
        (output / 'test.log').write_text(self.e.MARKER + ' ' + json.dumps(self.e.expected_summary('baseline')) + '\n')
        (output / 'raw-baseline.jsonl').write_text(self.trace())
        return output

    def negative_text(self, name):
        phase = self.e.NEGATIVE_PHASES[name]
        cycle = next(n for n, (label, _) in enumerate(self.e.plan('baseline')) if label == phase)
        return f'GUARDED_FP_CHECK[{name}] cycle={cycle} phase={phase}\n'

    def native(self, args, **kwargs):
        schedule = args[args.index('--schedule') + 1]
        Path(args[args.index('--trace') + 1]).write_text(self.trace(schedule))
        if '--negative' in args:
            name = args[args.index('--negative') + 1]
            kwargs['stdout'].write(self.negative_text(name))
            return types.SimpleNamespace(returncode=1)
        kwargs['stdout'].write(self.e.MARKER + ' ' + json.dumps(self.e.expected_summary(schedule)) + '\n')
        return types.SimpleNamespace(returncode=0)

    def invoke(self, *args):
        with patch.object(sys, 'argv', ['entry', *args]), patch.dict(self.e.os.environ), \
             patch.object(self.e.subprocess, 'run', side_effect=self.native) as run, \
             patch('sys.stdout', new_callable=io.StringIO):
            self.e.main()
            return run

    def changed(self, phase, section, field, value):
        rows = copy.deepcopy(self.records['baseline'])
        row = next(row for row in rows[1:-1] if row['phase'] == phase)
        row[section][field] = value
        return rows

    def test_mock_schedules_pass(self):
        for name in self.e.SCHEDULES: self.assertEqual(self.check(name), self.e.expected_summary(name))
        self.assertEqual([len(self.e.plan(n)) for n in self.e.SCHEDULES], [264, 360])

    def test_exact_rational_add_oracle(self):
        e = self.e
        self.assertEqual(e.add_ieee(0x3ff8000000000000, 0x4002000000000000, True, 0), (0x400e000000000000, 0))
        self.assertEqual(e.add_ieee(0x3f800000, 0x33800000, False, 0), (0xffffffff3f800000, 1))
        self.assertEqual(e.add_ieee(0x3f800000, 0x33800000, False, 3), (0xffffffff3f800001, 1))
        self.assertEqual(e.add_ieee(0x3ff0000000000000, 0x3ca0000000000000, True, 3), (0x3ff0000000000001, 1))
        # Exercise the round-to-even tie with an odd lower significand too.
        self.assertEqual(e.add_ieee(0x3f800001, 0x33800000, False, 0), (0xffffffff3f800002, 1))
        for left, right, double, rm in [(0, 1, False, 0), (0x7f800000, 0x3f800000, False, 0),
                                      (0x3f800000, 0x33800000, False, 2)]:
            with self.assertRaises(RuntimeError): e.add_ieee(left, right, double, rm)

    def test_one_fresh_model_and_eight_exact_negatives(self):
        run = self.invoke()
        output = self.common.BUILD / 'guarded-fp-bridge'
        self.common.setup.assert_called_once_with(False)
        self.common.test.assert_called_once_with('pinned-gsim', 'clang++-19', str(output),
            'ooo.GuardedFpBridgeGsimMain', 'GuardedFpBridgeGsim', 'guarded_fp_bridge.cpp',
            runtime_args=('--schedule', 'baseline', '--trace', str(output / 'raw-baseline.jsonl')),
            sanitizer=True, cxx_flags=('-fbracket-depth=4096',), timeout=120,
            mill_module='IonSoC.guardedFpBridge')
        self.assertEqual(run.call_count, 9)
        for call in run.call_args_list:
            self.assertEqual(call.args[0][0], str(output / 'run'))
            self.assertEqual(call.kwargs['timeout'], 120)
            self.assertEqual(call.kwargs['env']['UBSAN_OPTIONS'], 'halt_on_error=1')
            self.assertEqual(call.kwargs['env']['ASAN_OPTIONS'], 'detect_leaks=0')
        receipt = json.loads((output / 'entry-summary.json').read_text())
        self.assertEqual(receipt['negatives'], list(self.e.NEGATIVES))
        self.assertFalse(receipt['guest_fd_cpu_execution'])
        self.assertTrue(receipt['real_fp_arithmetic'])

    def test_custom_output(self):
        output = self.root / 'custom'
        self.invoke('--output', str(output))
        self.assertEqual(self.common.test.call_args.args[2], str(output))

    def test_existing_file_directory_and_dangling_link_rejected(self):
        paths = [self.root / 'file', self.root / 'directory', self.root / 'link']
        paths[0].write_text('preserve'); paths[1].mkdir(); paths[2].symlink_to(self.root / 'absent')
        for path in paths:
            with self.subTest(path=path), self.assertRaises(RuntimeError): self.invoke('--output', str(path))
        self.common.setup.assert_not_called()
        self.assertEqual(paths[0].read_text(), 'preserve')

    def test_reuse_switch_rejected(self):
        with self.assertRaises(SystemExit): self.invoke('--reuse-unverified')
        self.common.setup.assert_not_called()

    def test_setup_and_build_failure_no_fallback(self):
        self.common.setup.side_effect = RuntimeError('pin')
        with self.assertRaisesRegex(RuntimeError, 'pin'): self.invoke()
        self.common.test.assert_not_called()
        self.common.setup.side_effect = None
        self.common.test.side_effect = RuntimeError('build')
        with self.assertRaisesRegex(RuntimeError, 'build'): self.invoke()
        self.common.test.assert_called_once()

    def test_destination_changed(self):
        self.common.test.side_effect = lambda *a, **k: self.root
        with self.assertRaisesRegex(RuntimeError, 'destination changed'): self.invoke()

    def test_summary_schema_types_and_counts(self):
        normal = self.e.expected_summary('baseline')
        for key in normal:
            for value in (normal[key] + 1, True, float(normal[key])):
                with self.subTest(key=key, value=value), self.assertRaises(RuntimeError):
                    self.e.check_summary({**normal, key: value}, 'baseline')
        for key in normal:
            row = normal.copy(); del row[key]
            with self.assertRaises(RuntimeError): self.e.check_summary(row, 'baseline')
        with self.assertRaises(RuntimeError): self.e.check_summary({**normal, 'extra': 0}, 'baseline')

    def test_headers_scope_recipe_types(self):
        for key, value in [('schema', True), ('schedule', 'staggered'), ('ready_hold', 2),
                ('real_fp_arithmetic', False), ('guest_fd_cpu_execution', True), ('extra', 0)]:
            rows = copy.deepcopy(self.records['baseline']); rows[0][key] = value
            with self.subTest(key=key), self.assertRaises(RuntimeError): self.check(records=rows)
        rows = copy.deepcopy(self.records['baseline']); rows[0]['recipe'][0]['start_bits_instruction'] ^= 1 << 15
        with self.assertRaises(RuntimeError): self.check(records=rows)

    def test_truncation_duplicates_reordering_coverage(self):
        rows = self.records['baseline']
        for bad in (rows[1:], rows[:-1], rows[:10] + rows[11:], rows[:10] + rows[9:], rows[:10] + rows[11:13] + rows[10:11] + rows[13:]):
            with self.assertRaises(RuntimeError): self.check(records=bad)
        with self.assertRaises(RuntimeError): self.check(text=self.trace()[:-1])
        with self.assertRaises(RuntimeError): self.check(text=self.trace().replace('"schema": 1', '"schema": 1, "schema": 1', 1))
        with self.assertRaises(RuntimeError): self.check(text='Sanitizer\n')
        with self.assertRaises(RuntimeError): self.check(text='runtime error:\n')

    def test_all_named_negative_corruptions_rejected_by_replay(self):
        targets = [('op7_complete_hold_0', 'pre', 'complete_bits_data', 0x400e000000000001),
            ('op9_retire', 'post', 'fpr_8', 0x3f800001),
            ('op10_complete_hold_0', 'pre', 'complete_bits_data', 0xffffffff3f800001),
            ('op7_wait_0', 'pre', 'mutation_valid', 1),
            ('op12_retire', 'post', 'fcsr', 96), ('op9_retire', 'post', 'guestFs', 2),
            ('op0_retire_hold_0', 'pre', 'complete_valid', 1), ('op7_retire', 'pre', 'start_ready', 1)]
        for target in targets:
            with self.subTest(target=target), self.assertRaises(RuntimeError): self.check(records=self.changed(*target))

    def test_raw_state_tokens_and_flags_not_learned_from_observations(self):
        for phase, field, value in [('op0_wait_0', 'statePhase', 3), ('op0_wait_0', 'complete_valid', 1),
            ('op15_complete_hold_0', 'complete_bits_token_tag', 0x145600000000000f),
            ('op9_wait_0', 'virtualized', 0), ('op12_retire', 'retireAccepted', 0),
            ('cold_lane0', 'retireAccepted', 1), ('op8_issue', 'issueAccepted', 0)]:
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                self.check(records=self.changed(phase, 'pre', field, value))

    def test_every_architectural_register_checked(self):
        for n in range(32):
            original = next(r for r in self.records['baseline'][1:-1] if r['phase'] == 'final_idle_0')['pre'][f'fpr_{n}']
            with self.subTest(register=n), self.assertRaises(RuntimeError):
                self.check(records=self.changed('final_idle_0', 'pre', f'fpr_{n}', original ^ 1))

    def test_inputs_width_schema_frozen_plan(self):
        cases = [('start_bits_token_tag', -1), ('start_bits_token_tag', 1 << 64),
            ('translationActive', True), ('translationActive', 0), ('extra', 1)]
        for field, value in cases:
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                self.check(records=self.changed('op0_issue', 'in', field, value))
        rows = copy.deepcopy(self.records['baseline']); del rows[1]['pre']['busy']
        with self.assertRaises(RuntimeError): self.check(records=rows)
        rows = copy.deepcopy(self.records['baseline']); rows[1]['pre']['busy'] = 0.0
        with self.assertRaises(RuntimeError): self.check(records=rows)

    def test_exact_negative_diagnostics_require_good_raw_trace(self):
        log, trace = self.root / 'negative.log', self.root / 'negative.jsonl'
        trace.write_text(self.trace())
        for name in self.e.NEGATIVES:
            log.write_text(self.negative_text(name))
            self.e.check_negative(log, name, 1, trace)
            for code in (0, 2, -11, True):
                with self.assertRaises(RuntimeError): self.e.check_negative(log, name, code, trace)
            for text in ('wrong\n', self.negative_text(name) + 'extra\n', 'Sanitizer\n', self.negative_text(name).replace('cycle=', 'cycle=1')):
                log.write_text(text)
                with self.assertRaises(RuntimeError): self.e.check_negative(log, name, 1, trace)
        log.write_text(self.negative_text('boxed_single'))
        trace.write_text(self.trace(records=self.changed('op9_retire', 'post', 'fpr_8', 0x3f800001)))
        with self.assertRaises(RuntimeError): self.e.check_negative(log, 'boxed_single', 1, trace)

    def test_native_failure_or_timeout_is_not_negative_success(self):
        with patch.object(self.e.subprocess, 'run', side_effect=subprocess.TimeoutExpired('run', 120)):
            with self.assertRaises(subprocess.TimeoutExpired): self.e.native_run(self.root, (), 'timeout.log', {})
        with patch.object(self.e, 'native_run', return_value=(self.root / 'absent', -11)):
            with self.assertRaisesRegex(RuntimeError, 'staggered execution failed'): self.invoke()


if __name__ == '__main__': unittest.main()
