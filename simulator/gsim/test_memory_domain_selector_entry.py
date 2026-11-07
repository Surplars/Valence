"""Host orchestration/schema checks only. Builds and all native runs are mocked.

The synthetic packets below are not a hardware result or retained proof trace.
They only exercise the entry's acceptance/rejection and raw-counter checks.
"""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch


class MemoryDomainSelectorEntryTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.common = types.ModuleType('run')
        self.common.ROOT = self.root
        self.common.BUILD = self.root / 'build/gsim'
        self.common.setup = Mock(return_value=('gsim', 'clang++-19'))
        self.common.test = Mock(side_effect=self.generate)
        spec = importlib.util.spec_from_file_location('selector_entry', Path(__file__).with_name('memory_domain_selector.py'))
        self.entry = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'run': self.common}):
            spec.loader.exec_module(self.entry)
        self.summaries = {schedule: {'schema': 1, 'component_only': True, 'guest_fd_execution': False,
            'schedule': schedule, 'cycles': self.entry.SCHEDULE_CYCLES[schedule], 'idle_resets': 1,
            'lanes': [self.entry.expected_lane(schedule, lane) for lane in range(2)]}
            for schedule in self.entry.SCHEDULES}
        self.records = {schedule: self.mock_records(schedule) for schedule in self.entry.SCHEDULES}
        self.negative_code = 1
        self.negative_override = None
        self.staggered_code = 0

    def blank_lane(self):
        e = self.entry
        i = {**{key: [0] * len(widths) for key, widths in e.INPUT_ARRAYS.items()},
             **dict.fromkeys(e.INPUT_SCALARS, 0), 'commits': [[0, 0, 0], [0, 0, 0]],
             'request': [[0] * 13 for _ in range(3)]}
        o = {**{key: [0] * len(widths) for key, widths in e.OUTPUT_ARRAYS.items()},
             **dict.fromkeys(e.OUTPUT_SCALARS, 0), 'response': [[0] * 8 for _ in range(3)]}
        i['native_request_ready'] = 1
        i['response_ready'] = [1, 1, 1]
        o['native_response_ready'] = 1
        o['request_ready'][0] = 1
        return {'input': i, 'output': o}

    def mock_records(self, schedule):
        rows = [copy.deepcopy(self.entry.header(schedule))]

        def add(lanes=None, reset=0):
            rows.append({'event': 'cycle', 'cycle': len(rows), 'reset': reset,
                         'lanes': lanes if lanes is not None else [self.blank_lane(), self.blank_lane()]})

        add(reset=1)
        add(reset=1)
        for mask in range(32):
            lanes = [self.blank_lane(), self.blank_lane()]
            for lane in lanes:
                lane['input']['busy'] = [(mask >> n) & 1 for n in range(5)]
                lane['input']['architectural_fp_busy'] = 1
                lane['output']['busy'] = int(mask != 0)
                lane['output']['cpu_busy'] = int((mask & 15) != 0)
                lane['output']['architecture_only'] = int(mask == 0)
            add(lanes)
        for beat in range(9):
            lanes = [self.blank_lane(), self.blank_lane()]
            for index, lane in enumerate(lanes):
                i, o = lane['input'], lane['output']
                i['request_valid'][0] = o['native_request_valid'] = int(beat < 8)
                i['native_response_valid'] = o['response_valid'][0] = int(beat > 0)
                i['request'][0][3] = o['native_request'][3] = beat % 8 if index else 0
            add(lanes)
        stalled = schedule == 'staggered'
        r, d, s, h = (3, 3, 3, 4) if stalled else (2, 1, 2, 2)
        phases = (['start'] + ['request_stall'] * r + ['request'] + ['delay'] * d +
                  ['response_stall'] * s + ['response', 'complete'] + ['hold'] * h + ['retire', 'idle'])
        for case in range(64):
            for phase_index, phase in enumerate(phases):
                lanes = [self.blank_lane(), self.blank_lane()]
                for index, lane in enumerate(lanes):
                    i, o = lane['input'], lane['output']
                    domain = case % 2 * 2 if index else (0, 1, 2, 0, 2, 1, 0, 0)[case % 8]
                    protected = domain != 0 or (index == 0 and case % 8 == 7)
                    token = [case % 16, (1 << 63) | case]
                    active = int(protected and phase not in ('start', 'idle'))
                    o['owner'] = [active, *token, int(active and domain != 0),
                                  int(active and domain == 1), int(active and domain == 2)]
                    o['domain'] = domain if phase not in ('start', 'idle') else 0
                    o['request_ready'] = [int(port == o['domain']) for port in range(3)]
                    if phase == 'start' and protected:
                        word = (self.entry.H_FORMS[((case // 8) * 2 + int(case % 8 == 5)) % 13]
                                if domain == 1 else 0x0004b387 if domain == 2 else 0x02b483d3)
                        i['start'] = [1, *token, word]
                    if phase in ('request', 'request_stall'):
                        ready = int(phase == 'request')
                        i['request_valid'][domain] = o['native_request_valid'] = 1
                        i['native_request_ready'] = o['request_ready'][domain] = ready
                        handle = ((case // 2) % 16 if domain == 0 else 16) if index else 0
                        i['request'][domain][3] = o['native_request'][3] = handle
                    if phase in ('response', 'response_stall'):
                        ready = int(phase == 'response')
                        i['native_response_valid'] = o['response_valid'][domain] = 1
                        i['response_ready'][domain] = o['native_response_ready'] = ready
                        reply = [case, 0, 0, case & 1, (case >> 1) & 1,
                                 0 if index else case & 1, 0 if index else (case >> 1) & 1,
                                 0 if index else (case >> 2) & 1]
                        i['native_response'] = reply.copy()
                        o['response'][domain] = reply
                    if phase == 'complete' and protected:
                        i['complete'] = [1, *token]
                    if phase == 'hold' and protected and phase_index - phases.index('hold') < 2:
                        i['commits'] = [[1, token[0], token[1] ^ (1 << 63)],
                                        [1, token[0] ^ 1, token[1]]]
                    if phase == 'retire' and protected:
                        i['commits'][0] = [1, *token]
                        o['retired'] = 1
                        o['retire_matches'] = 1
                add(lanes)
        add()
        add()
        rows.append({'event': 'summary', 'summary': copy.deepcopy(self.summaries[schedule])})
        return rows

    def write_evidence(self, output, schedule, log_name):
        output.mkdir(parents=True, exist_ok=True)
        (output / log_name).write_text(self.entry.MARKER + ' ' + json.dumps(self.summaries[schedule]) + '\n')
        (output / ('raw-' + schedule + '.jsonl')).write_text(self.trace_text(schedule))

    def generate(self, gsim, cxx, output, *args, **kwargs):
        path = Path(output)
        self.write_evidence(path, 'baseline', 'test.log')
        return path

    def native(self, args, **kwargs):
        if '--negative' in args:
            name = args[args.index('--negative') + 1]
            lane, cycle = self.entry.NEGATIVE_LOCATIONS[name]
            text = self.negative_override if self.negative_override is not None else (
                f'MEMORY_DOMAIN_SELECTOR_CHECK[{name}]: lane={lane} cycle={cycle}\n')
            kwargs['stdout'].write(text)
            return subprocess.CompletedProcess(args, self.negative_code)
        self.assertEqual(args[1:3], ['--schedule', 'staggered'])
        kwargs['stdout'].write(self.entry.MARKER + ' ' + json.dumps(self.summaries['staggered']) + '\n')
        Path(args[4]).write_text(self.trace_text('staggered'))
        return subprocess.CompletedProcess(args, self.staggered_code)

    def trace_text(self, schedule='baseline', records=None):
        return ''.join(json.dumps(row) + '\n' for row in (self.records[schedule] if records is None else records))

    def invoke(self, *args):
        with patch.object(sys, 'argv', ['entry', *args]), patch.dict(self.entry.os.environ), \
             patch.object(self.entry.subprocess, 'run', side_effect=self.native) as run:
            self.entry.main()
            return run

    def check(self, schedule='baseline', summary=None, trace=None, log=None):
        path, raw = self.root / 'positive.log', self.root / 'trace.jsonl'
        row = self.summaries[schedule] if summary is None else summary
        path.write_text(log if log is not None else self.entry.MARKER + ' ' + json.dumps(row) + '\n')
        raw.write_text(self.trace_text(schedule) if trace is None else trace)
        return self.entry.check_positive(path, schedule, raw)

    def test_one_fresh_model_two_schedules_and_all_named_negatives(self):
        run = self.invoke()
        self.common.setup.assert_called_once_with(False)
        output = self.common.BUILD / 'memory-domain-selector'
        self.common.test.assert_called_once_with('gsim', 'clang++-19', str(output),
            'ooo.MemoryDomainSelectorGsimMain', 'MemoryDomainSelectorGsim', 'memory_domain_selector.cpp',
            runtime_args=('--schedule', 'baseline', '--trace', str(output / 'raw-baseline.jsonl')),
            sanitizer=True, cxx_flags=('-fbracket-depth=4096',), timeout=120,
            mill_module='IonSoC.memoryDomainSelector')
        self.assertEqual(run.call_count, 12)
        for call in run.call_args_list:
            self.assertEqual(call.args[0][0], str(output / 'run'))
            self.assertEqual(call.kwargs['cwd'], self.root)
            self.assertEqual(call.kwargs['timeout'], 120)
            self.assertEqual(call.kwargs['env']['UBSAN_OPTIONS'], 'halt_on_error=1')
            self.assertEqual(call.kwargs['env']['ASAN_OPTIONS'], 'detect_leaks=0')
        self.assertEqual([call.args[0][-1] for call in run.call_args_list[1:]], list(self.entry.NEGATIVES))
        receipt = json.loads((output / 'entry-summary.json').read_text())
        self.assertEqual(receipt['negatives'], list(self.entry.NEGATIVES))
        self.assertEqual([row['schedule'] for row in receipt['schedules']], ['baseline', 'staggered'])

    def test_custom_fresh_output_is_used_without_changing_build_root(self):
        output = self.root / 'custom-model'
        build = self.common.BUILD
        self.invoke('--output', str(output))
        self.assertEqual(self.common.test.call_args.args[2], str(output))
        self.assertEqual(self.common.BUILD, build)
        self.assertTrue((output / 'entry-summary.json').is_file())

    def test_existing_empty_output_is_rejected_without_touching_it(self):
        output = self.common.BUILD / 'memory-domain-selector'
        output.mkdir(parents=True)
        with self.assertRaisesRegex(RuntimeError, 'fresh output'): self.invoke()
        self.common.setup.assert_not_called()
        self.assertEqual(list(output.iterdir()), [])

    def test_existing_file_or_dangling_symlink_output_is_rejected(self):
        file = self.root / 'retained-file'
        file.write_text('retained')
        link = self.root / 'dangling-link'
        link.symlink_to(self.root / 'absent')
        for path in (file, link):
            with self.subTest(path=path), self.assertRaises(RuntimeError):
                self.invoke('--output', str(path))
        self.assertEqual(file.read_text(), 'retained')
        self.common.setup.assert_not_called()

    def test_unverified_reuse_option_is_rejected(self):
        with self.assertRaises(SystemExit) as error: self.invoke('--reuse-unverified')
        self.assertEqual(error.exception.code, 2)
        self.common.setup.assert_not_called()

    def test_failed_tool_binding_never_builds_or_runs(self):
        self.common.setup.side_effect = RuntimeError('binding changed')
        with self.assertRaisesRegex(RuntimeError, 'binding changed'): self.invoke()
        self.common.test.assert_not_called()

    def test_build_failure_has_no_fallback(self):
        self.common.test.side_effect = RuntimeError('compile failed')
        with patch.object(self.entry.subprocess, 'run') as run, self.assertRaises(RuntimeError): self.invoke()
        self.assertEqual(self.common.test.call_count, 1)
        run.assert_not_called()

    def test_missing_or_unexpected_summary_fields_fail(self):
        for key in self.summaries['baseline']:
            row = copy.deepcopy(self.summaries['baseline'])
            del row[key]
            with self.subTest(key=key), self.assertRaises(RuntimeError): self.check(summary=row)
        row = copy.deepcopy(self.summaries['baseline']); row['unexpected'] = 1
        with self.assertRaises(RuntimeError): self.check(summary=row)

    def test_all_exact_lane_counts_and_arrays_are_required(self):
        for index in range(2):
            for key in self.entry.LANE_COUNTERS:
                row = copy.deepcopy(self.summaries['baseline']); row['lanes'][index][key] += 1
                with self.subTest(index=index, key=key), self.assertRaises(RuntimeError): self.check(summary=row)
            for key in ('requests', 'responses'):
                row = copy.deepcopy(self.summaries['baseline']); row['lanes'][index][key][0] -= 1
                with self.subTest(index=index, key=key), self.assertRaises(RuntimeError): self.check(summary=row)

    def test_boolean_integer_confusion_is_rejected(self):
        for key in ('schema', 'idle_resets', 'cycles'):
            row = copy.deepcopy(self.summaries['baseline']); row[key] = True
            with self.subTest(key=key), self.assertRaises(RuntimeError): self.check(summary=row)
        row = copy.deepcopy(self.summaries['baseline']); row['lanes'][0]['handles'] = True
        with self.assertRaises(RuntimeError): self.check(summary=row)

    def test_scope_lane_identity_and_drained_state_are_required(self):
        for key, value in (('component_only', 1), ('guest_fd_execution', 0), ('schedule', 'staggered')):
            row = copy.deepcopy(self.summaries['baseline']); row[key] = value
            with self.subTest(key=key), self.assertRaises(RuntimeError): self.check(summary=row)
        for key, value in (('name', 'host'), ('drained', 1)):
            row = copy.deepcopy(self.summaries['baseline']); row['lanes'][0][key] = value
            with self.subTest(key=key), self.assertRaises(RuntimeError): self.check(summary=row)

    def test_schedule_cycle_total_cannot_be_relaxed(self):
        for schedule in self.entry.SCHEDULES:
            row = copy.deepcopy(self.summaries[schedule]); row['cycles'] -= 1
            with self.assertRaises(RuntimeError): self.check(schedule, summary=row)

    def test_extra_pass_nonfinal_duplicate_or_missing_summary_fails(self):
        normal = self.entry.MARKER + ' ' + json.dumps(self.summaries['baseline']) + '\n'
        for log in ('PASS\n' + normal, normal + 'PASS\n', normal + normal, '{}\n', ''):
            with self.subTest(log=log[:40]), self.assertRaises(RuntimeError): self.check(log=log)

    def test_duplicate_json_keys_are_rejected(self):
        normal = self.entry.MARKER + ' ' + json.dumps(self.summaries['baseline']) + '\n'
        with self.assertRaises(RuntimeError): self.check(log=normal.replace('"schema": 1', '"schema": 1, "schema": 1'))
        with self.assertRaises(RuntimeError): self.check(trace=self.trace_text().replace('"cycle": 1', '"cycle": 1, "cycle": 1', 1))

    def test_missing_or_wrong_trace_header_fails(self):
        for key in self.records['baseline'][0]:
            rows = copy.deepcopy(self.records['baseline']); del rows[0][key]
            with self.subTest(key=key), self.assertRaises(RuntimeError): self.check(trace=self.trace_text(records=rows))
        rows = copy.deepcopy(self.records['baseline']); rows[0]['schema'] = True
        with self.assertRaises(RuntimeError): self.check(trace=self.trace_text(records=rows))

    def test_truncated_missing_extra_or_reordered_trace_rows_fail(self):
        rows = self.records['baseline']
        for changed in (rows[:-1], rows[:-2] + rows[-1:], rows[:3] + rows[2:], rows[:3] + [rows[4], rows[3]] + rows[5:]):
            with self.assertRaises(RuntimeError): self.check(trace=self.trace_text(records=changed))
        with self.assertRaises(RuntimeError): self.check(trace=self.trace_text().rstrip('\n'))

    def test_trace_scalar_types_ranges_and_lane_count_are_checked(self):
        for key, value in (('cycle', True), ('reset', False), ('reset', 2), ('lanes', [])):
            rows = copy.deepcopy(self.records['baseline']); rows[40][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(RuntimeError): self.check(trace=self.trace_text(records=rows))
        rows = copy.deepcopy(self.records['baseline']); rows[40]['lanes'][0]['output']['domain'] = 3
        with self.assertRaises(RuntimeError): self.check(trace=self.trace_text(records=rows))

    def test_missing_raw_inputs_or_outputs_are_rejected(self):
        for side in ('input', 'output'):
            for key in self.records['baseline'][40]['lanes'][0][side]:
                rows = copy.deepcopy(self.records['baseline']); del rows[40]['lanes'][0][side][key]
                with self.subTest(side=side, key=key), self.assertRaises(RuntimeError): self.check(trace=self.trace_text(records=rows))

    def test_wrong_raw_array_types_lengths_or_widths_are_rejected(self):
        for side, key in (('input', 'start'), ('input', 'request_valid'), ('output', 'owner'), ('output', 'native_request')):
            for value in (None, [], [0], 'invalid'):
                rows = copy.deepcopy(self.records['baseline']); rows[40]['lanes'][0][side][key] = value
                with self.subTest(side=side, key=key, value=value), self.assertRaises(RuntimeError): self.check(trace=self.trace_text(records=rows))
        for value in (True, -1, 1 << 64, 0.5):
            rows = copy.deepcopy(self.records['baseline']); rows[40]['lanes'][0]['input']['request'][0][0] = value
            with self.assertRaises(RuntimeError): self.check(trace=self.trace_text(records=rows))

    def test_raw_transfer_counts_cannot_be_replaced_by_summary(self):
        rows = copy.deepcopy(self.records['baseline'])
        lane = rows[47]['lanes'][0]
        lane['input']['request_valid'] = [0, 0, 0]
        lane['output']['native_request_valid'] = 0
        with self.assertRaises(RuntimeError): self.check(trace=self.trace_text(records=rows))

    def test_raw_selected_transfer_exclusion_is_checked(self):
        rows = copy.deepcopy(self.records['baseline'])
        rows[35]['lanes'][0]['input']['request_valid'][1] = 1
        rows[35]['lanes'][0]['output']['request_ready'][1] = 1
        with self.assertRaises(RuntimeError): self.check(trace=self.trace_text(records=rows))

    def test_continuous_stream_bubble_is_rejected(self):
        rows = copy.deepcopy(self.records['baseline'])
        lane = rows[40]['lanes'][0]
        lane['input']['request_valid'][0] = lane['output']['native_request_valid'] = 0
        with self.assertRaisesRegex(RuntimeError, 'transfer bubble'): self.check(trace=self.trace_text(records=rows))

    def test_raw_footer_must_match_stdout_and_be_well_typed(self):
        rows = copy.deepcopy(self.records['baseline']); rows[-1]['summary']['lanes'][0]['handles'] = True
        with self.assertRaises(RuntimeError): self.check(trace=self.trace_text(records=rows))
        rows = copy.deepcopy(self.records['baseline']); rows[-1]['event'] = 'unfinished'
        with self.assertRaises(RuntimeError): self.check(trace=self.trace_text(records=rows))

    def test_final_raw_state_must_be_drained(self):
        rows = copy.deepcopy(self.records['baseline']); rows[-2]['lanes'][0]['output']['owner'][0] = 1
        with self.assertRaisesRegex(RuntimeError, 'not drained'): self.check(trace=self.trace_text(records=rows))

    def test_noninitial_reset_is_rejected(self):
        rows = copy.deepcopy(self.records['baseline']); rows[100]['reset'] = 1
        with self.assertRaises(RuntimeError): self.check(trace=self.trace_text(records=rows))

    def test_sanitizer_control_bytes_and_invalid_utf8_are_not_evidence(self):
        normal = self.entry.MARKER + ' ' + json.dumps(self.summaries['baseline']) + '\n'
        for prefix in ('runtime error: bad\n', 'AddressSanitizer: bad\n', 'UndefinedBehaviorSanitizer: bad\n', '\x00'):
            with self.assertRaises(RuntimeError): self.check(log=prefix + normal)
        path = self.root / 'invalid-utf8'; path.write_bytes(b'\xff\n')
        with self.assertRaises(RuntimeError): self.entry.clean_text(path)

    def test_missing_empty_or_excessive_evidence_is_rejected(self):
        with self.assertRaises(RuntimeError): self.entry.clean_text(self.root / 'missing')
        path = self.root / 'empty'; path.write_text('')
        with self.assertRaises(RuntimeError): self.entry.clean_text(path)
        path.write_text('abcdef\n')
        with self.assertRaises(RuntimeError): self.entry.clean_text(path, limit=4)

    def test_negative_requires_exact_exit_one(self):
        path = self.root / 'negative.log'
        path.write_text('MEMORY_DOMAIN_SELECTOR_CHECK[owner]: lane=0 cycle=58\n')
        for code in (0, 2, -11, 124, True):
            with self.subTest(code=code), self.assertRaises(RuntimeError): self.entry.check_negative(path, 'owner', code)

    def test_negative_requires_exact_name_lane_cycle_and_no_extra_output(self):
        normal = 'MEMORY_DOMAIN_SELECTOR_CHECK[owner]: lane=0 cycle=58\n'
        path = self.root / 'negative.log'
        for text in (normal.replace('owner', 'busy'), normal.replace('lane=0', 'lane=1'),
                     normal.replace('cycle=58', 'cycle=59'), normal + 'PASS\n',
                     normal + self.entry.MARKER + ' {}\n', 'AddressSanitizer: bad\n' + normal, ''):
            path.write_text(text)
            with self.subTest(text=text), self.assertRaises(RuntimeError): self.entry.check_negative(path, 'owner', 1)

    def test_missing_negative_never_produces_entry_receipt(self):
        self.negative_override = ''
        with self.assertRaises(RuntimeError): self.invoke()
        self.assertFalse((self.common.BUILD / 'memory-domain-selector/entry-summary.json').exists())

    def test_staggered_failure_stops_before_negatives(self):
        self.staggered_code = 1
        with self.assertRaisesRegex(RuntimeError, 'staggered execution failed'): self.invoke()
        self.assertFalse((self.common.BUILD / 'memory-domain-selector/entry-summary.json').exists())

    def test_native_timeout_is_fatal_and_not_retried(self):
        with patch.object(sys, 'argv', ['entry']), patch.dict(self.entry.os.environ), \
             patch.object(self.entry.subprocess, 'run', side_effect=subprocess.TimeoutExpired('run', 120)) as run:
            with self.assertRaises(subprocess.TimeoutExpired): self.entry.main()
        run.assert_called_once()
        self.assertFalse((self.common.BUILD / 'memory-domain-selector/entry-summary.json').exists())

    def test_both_mock_positive_schedules_pass_structural_and_counter_checks(self):
        for schedule in self.entry.SCHEDULES:
            self.assertEqual(self.check(schedule), self.summaries[schedule])


if __name__ == '__main__':
    unittest.main()
