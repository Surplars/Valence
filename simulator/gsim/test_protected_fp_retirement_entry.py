"""Mock-only entry/parser sensitivity checks. Never native or hardware evidence."""
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


class ProtectedFpRetirementEntryTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='mock-only-fp-retirement-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.common = types.ModuleType('run')
        self.common.ROOT = self.root
        self.common.BUILD = self.root / 'build'
        self.common.setup = Mock(return_value=('pinned-gsim', 'clang++-19'))
        self.common.test = Mock(side_effect=self.generate)
        spec = importlib.util.spec_from_file_location('fp_entry', Path(__file__).with_name('protected_fp_retirement.py'))
        self.e = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'run': self.common}): spec.loader.exec_module(self.e)
        self.records = {name: self.mock_records(name) for name in self.e.SCHEDULES}

    def mock_records(self, schedule):
        # This test fixture uses the input ledger solely to produce well-shaped
        # mock packets. Its outputs are not retained or claimed as DUT evidence.
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
        return f'PROTECTED_FP_CHECK[{name}] cycle={cycle} phase={phase}\n'

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

    def test_one_fresh_model_and_seven_exact_negatives(self):
        run = self.invoke()
        output = self.common.BUILD / 'protected-fp-retirement'
        self.common.setup.assert_called_once_with(False)
        self.common.test.assert_called_once_with('pinned-gsim', 'clang++-19', str(output),
            'ooo.ProtectedFpRetirementGsimMain', 'ProtectedFpRetirementGsim', 'protected_fp_retirement.cpp',
            runtime_args=('--schedule', 'baseline', '--trace', str(output / 'raw-baseline.jsonl')),
            sanitizer=True, cxx_flags=('-fbracket-depth=4096',), timeout=120,
            mill_module='IonSoC.protectedFpRetirement')
        self.assertEqual(run.call_count, 8)
        for call in run.call_args_list:
            self.assertEqual(call.args[0][0], str(output / 'run'))
            self.assertIn('--trace', call.args[0])
            self.assertEqual(call.kwargs['timeout'], 120)
            self.assertEqual(call.kwargs['env']['UBSAN_OPTIONS'], 'halt_on_error=1')
            self.assertEqual(call.kwargs['env']['ASAN_OPTIONS'], 'detect_leaks=0')
        receipt = json.loads((output / 'entry-summary.json').read_text())
        self.assertEqual(receipt['negatives'], list(self.e.NEGATIVES))

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

    def test_summary_missing_extra_changed_or_wrong_type(self):
        normal = self.e.expected_summary('baseline')
        for key in normal:
            for mode in ('missing', 'changed', 'boolean', 'float'):
                row = normal.copy()
                if mode == 'missing': del row[key]
                else: row[key] = normal[key] + 1 if mode == 'changed' else True if mode == 'boolean' else float(normal[key])
                with self.subTest(key=key, mode=mode), self.assertRaises(RuntimeError): self.check(summary=row)
        with self.assertRaises(RuntimeError): self.check(summary={**normal, 'extra': 0})

    def test_headers_require_exact_types_scope_and_recipe(self):
        for key in self.records['baseline'][0]:
            rows = copy.deepcopy(self.records['baseline']); del rows[0][key]
            with self.subTest(key=key), self.assertRaises(RuntimeError): self.check(records=rows)
        for key, value in (('schema', True), ('schedule', 'staggered'), ('execute_hold', 2), ('extra', 0)):
            rows = copy.deepcopy(self.records['baseline']); rows[0][key] = value
            with self.subTest(key=key), self.assertRaises(RuntimeError): self.check(records=rows)
        rows = copy.deepcopy(self.records['baseline']); rows[0]['recipe'][0]['issue_bits_token_tag'] &= 0xffffffff
        with self.assertRaises(RuntimeError): self.check(records=rows)

    def test_truncation_duplicates_reordering_and_coverage(self):
        rows = self.records['baseline']
        for bad in (rows[1:], rows[:-1], rows[:10] + rows[11:], rows[:10] + rows[9:],
                    rows[:10] + [rows[11], rows[10]] + rows[12:]):
            with self.assertRaises(RuntimeError): self.check(records=bad)
        for text in (self.trace()[:-1], self.trace().replace('"cycle": 0', '"cycle": 0, "cycle": 0', 1), '{}\n'):
            with self.assertRaises(RuntimeError): self.check(text=text)

    def test_every_raw_field_schema_and_width(self):
        for section, widths in (('in', self.e.INPUT_WIDTHS), ('pre', self.e.OUTPUT_WIDTHS), ('post', self.e.POST_WIDTHS)):
            for field, width in widths.items():
                for value in (True, -1, 1 << width, 0.5):
                    with self.subTest(section=section, field=field, value=value), self.assertRaises(RuntimeError):
                        self.check(records=self.changed('op0_retire', section, field, value))
            rows = self.changed('op0_retire', section, 'extra', 0)
            with self.assertRaises(RuntimeError): self.check(records=rows)
            rows = copy.deepcopy(self.records['baseline'])
            del rows[12][section][next(iter(widths))]
            with self.assertRaises(RuntimeError): self.check(records=rows)

    def test_all_defined_observations_are_sensitive(self):
        # Multi-observable sensitivity controls, independent of summary counts.
        for phase in ('op0_hold_execute_0', 'op1_complete_hold_0', 'op2_retire', 'op3_repeat0'):
            row = next(row for row in self.records['baseline'][1:-1] if row['phase'] == phase)
            for section, widths in (('pre', self.e.OUTPUT_WIDTHS), ('post', self.e.POST_WIDTHS)):
                for key in widths:
                    with self.subTest(phase=phase, section=section, key=key), self.assertRaises(RuntimeError):
                        self.check(records=self.changed(phase, section, key, row[section][key] ^ 1))

    def test_frozen_inputs_cannot_rewrite_the_oracle_recipe(self):
        for phase, key in (('op0_issue', 'issue_bits_instruction'), ('op1_result', 'result_bits_value'),
                           ('op0_wrong_tag', 'commit0_bits_tag'), ('op3_issue', 'commit1_valid'),
                           ('op0_complete_hold_1', 'completeAccept'), ('guest_enter', 'sret')):
            row = next(row for row in self.records['baseline'][1:-1] if row['phase'] == phase)
            with self.subTest(phase=phase), self.assertRaises(RuntimeError):
                self.check(records=self.changed(phase, 'in', key, row['in'][key] ^ 1))

    def test_post_link_and_final_observation_required(self):
        rows = copy.deepcopy(self.records['baseline']); rows[-2]['post'] = None
        with self.assertRaises(RuntimeError): self.check(records=rows)
        rows = copy.deepcopy(self.records['baseline']); rows[-1]['complete'] = 1
        with self.assertRaises(RuntimeError): self.check(records=rows)

    def test_malformed_nontext_sanitizer_and_bounds(self):
        path = self.root / 'bad'
        for data in (b'', b'\xff\n', b'\x00\n', b'AddressSanitizer\n', b'runtime error: test\n', b'{}'):
            path.write_bytes(data)
            with self.subTest(data=data), self.assertRaises(RuntimeError): self.e.clean_text(path)
        path.write_text('123456\n')
        with self.assertRaises(RuntimeError): self.e.clean_text(path, 4)
        with self.assertRaises(RuntimeError): self.e.clean_text(self.root / 'absent')
        for text in ('NaN', '[]', '{', '{"x":1,"x":2}'):
            with self.assertRaises(RuntimeError): self.e.object_row(text)

    def test_negative_requires_one_named_checker_and_full_target_trace(self):
        log, trace = self.root / 'negative.log', self.root / 'negative.jsonl'
        trace.write_text(self.trace())
        for name in self.e.NEGATIVES:
            normal = self.negative_text(name)
            log.write_text(normal)
            self.e.check_negative(log, name, 1, trace)
            for code in (0, 2, -11, 124, True):
                with self.assertRaises(RuntimeError): self.e.check_negative(log, name, code, trace)
            for bad in ('', normal + 'PASS\n', normal + self.e.MARKER + ' {}\n', normal.replace(name, 'other'), 'AddressSanitizer\n' + normal):
                log.write_text(bad)
                with self.assertRaises(RuntimeError): self.e.check_negative(log, name, 1, trace)
            log.write_text(normal)
            with self.assertRaises(RuntimeError): self.e.check_negative(log, name, 1, self.root / 'absent')
        trace.write_text(self.trace(records=self.records['baseline'][:-2]))
        with self.assertRaises(RuntimeError): self.e.check_negative(log, name, 1, trace)

    def test_bad_native_exit_and_missing_negative_trace_stop_receipt(self):
        for mode in ('exit', 'negative_trace'):
            real = self.native
            def native(args, **kwargs):
                result = real(args, **kwargs)
                if mode == 'exit': result.returncode = 2
                elif '--negative' in args: Path(args[args.index('--trace') + 1]).unlink()
                return result
            output = self.root / mode
            with patch.object(sys, 'argv', ['entry', '--output', str(output)]), \
                 patch.dict(self.e.os.environ), patch.object(self.e.subprocess, 'run', side_effect=native):
                with self.assertRaises(RuntimeError): self.e.main()
            self.assertFalse((output / 'entry-summary.json').exists())

    def test_positive_log_requires_single_summary(self):
        log, trace = self.root / 'bad.log', self.root / 'raw.jsonl'
        trace.write_text(self.trace())
        normal = self.e.MARKER + ' ' + json.dumps(self.e.expected_summary('baseline')) + '\n'
        for text in ('PASS\n' + normal, normal + 'PASS\n', normal + normal, '{}\n',
                     normal.replace('"cycles": 67', '"cycles": 67, "cycles": 67')):
            log.write_text(text)
            with self.assertRaises(RuntimeError): self.e.check_positive(log, 'baseline', trace)

    def test_failure_timeout_and_no_receipt(self):
        for failure in (subprocess.TimeoutExpired('run', 120), RuntimeError('native')):
            with patch.object(sys, 'argv', ['entry', '--output', str(self.root / type(failure).__name__)]), \
                 patch.dict(self.e.os.environ), patch.object(self.e.subprocess, 'run', side_effect=failure) as run:
                with self.assertRaises(type(failure)): self.e.main()
                run.assert_called_once()
            self.assertFalse((self.root / type(failure).__name__ / 'entry-summary.json').exists())


if __name__ == '__main__':
    unittest.main()
