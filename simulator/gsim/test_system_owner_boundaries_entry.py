"""Mock-only host orchestration/schema tests, never native hardware evidence.

Every tool build and native execution is mocked. Synthetic trace packets are
created only in test temporary directories and are not retained proof traces.
"""
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


class SystemOwnerBoundariesEntryTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='mock-only-owner-boundaries-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.common = types.ModuleType('run')
        self.common.ROOT = self.root
        self.common.BUILD = self.root / 'mock-only/build/gsim'
        self.common.setup = Mock(return_value=('gsim', 'clang++-19'))
        self.common.test = Mock(side_effect=self.generate)
        spec = importlib.util.spec_from_file_location('owner_entry', Path(__file__).with_name('system_owner_boundaries.py'))
        self.entry = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'run': self.common}):
            spec.loader.exec_module(self.entry)
        self.summaries = {name: self.entry.expected_summary(name) for name in self.entry.SCHEDULES}
        self.records = {name: self.mock_records(name) for name in self.entry.SCHEDULES}
        self.negative_code = 1
        self.negative_override = None
        self.staggered_code = 0

    def blank_input(self):
        return {'start': [0, 0, 0, 0x13], 'complete': [0, 0, 0, 1],
                'commits': [[0, 0, 0], [0, 0, 0]], 'request_valid': [0, 0, 0],
                'request': [[0] * 12 for _ in range(3)], 'response_ready': [1, 1, 1],
                'native_request_ready': 1, 'native_response_valid': 0,
                'native_response': [0, 0, 0], 'busy': [0] * 5}

    def mock_records(self, schedule):
        e = self.entry
        rows = [copy.deepcopy(e.header(schedule))]
        owner, domain = [0, 0, 0, 0, 0, 0], 0
        for number, phase in enumerate(e.plan(schedule), 1):
            i = self.blank_input()
            capture = None
            if phase.startswith('probe_'):
                token = (0, 0) if phase.startswith('probe_reset_') else e.TOKENS[4]
                probe = int(phase[-1])
                if probe in (0, 1):
                    i['commits'][probe] = [1, *token]
                elif probe == 2:
                    i['commits'] = [[0, *token], [0, *token]]
                elif probe == 3:
                    i['commits'][0] = [1, token[0], token[1] ^ (1 << 63)]
                elif probe == 4:
                    i['commits'][1] = [1, token[0] ^ 1, token[1]]
            elif phase not in ('reset', 'final'):
                n = ord(phase[-1]) - ord('A')
                token = e.TOKENS[n]
                if phase.startswith('start_'):
                    capture = n
                if phase.startswith(('retire_capture_', 'exception_capture_')):
                    capture = n + 1
                if capture is not None:
                    word = e.H_WORD if e.DOMAINS[capture] == 1 else e.FP_WORD
                    i['start'] = [1, *e.TOKENS[capture], word]
                if phase.startswith('complete_'):
                    i['complete'] = [1, *token, 0]
                if phase.startswith(('release_', 'exception_capture_')):
                    i['complete'] = [1, *token, 1]
                if phase.startswith('retire_'):
                    i['commits'][int(n in (3, 7))] = [1, *token]
                if phase.startswith('hold_'):
                    i['complete'] = [0, *token, 1]
                    i['commits'] = [[1, token[0], token[1] ^ (1 << 63)], [1, token[0] ^ 1, token[1]]]
                if phase.startswith(('request_', 'request_stall_')):
                    i['request_valid'][domain] = 1
                    i['request'][domain] = [0x80000000 + n * 8, (1 << 63) | n, n, 3, 255, 0, 0, 0, 0, 0, 0, 0]
                    i['native_request_ready'] = int(not phase.startswith('request_stall_'))
                if phase.startswith(('response_', 'response_stall_')):
                    i['native_response_valid'] = 1
                    i['native_response'] = [(1 << 63) | n, int(n in e.EXCEPTIONAL), 0]
                    i['response_ready'][domain] = int(not phase.startswith('response_stall_'))
            if phase.startswith(('delay_', 'response_', 'response_stall_')):
                i['busy'][domain] = 1
            mask = sum(int(valid and [index, tag] == owner[1:3]) << lane
                       for lane, (valid, index, tag) in enumerate(i['commits']))
            o = {'owner': owner.copy(), 'domain': domain, 'retired': int(bool(mask)), 'retire_matches': mask,
                 'busy': int(any(i['busy'])), 'cpu_busy': int(any(i['busy'][:4])), 'request_ready': [int(port == domain) * i['native_request_ready'] for port in range(3)],
                 'response_valid': [int(port == domain) * i['native_response_valid'] for port in range(3)],
                 'response': [i['native_response'].copy() for _ in range(3)],
                 'native_request_valid': i['request_valid'][domain], 'native_response_ready': i['response_ready'][domain],
                 'native_request': i['request'][domain].copy()}
            if mask or (i['complete'][0] and i['complete'][3]):
                owner, domain = [0, *owner[1:3], 0, 0, 0], 0
            if capture is not None:
                domain = e.DOMAINS[capture]
                owner = [1, *e.TOKENS[capture], 1, int(domain == 1), int(domain == 2)]
            rows.append({'event': 'cycle', 'cycle': number, 'reset': int(number <= 2), 'phase': phase,
                         'input': i, 'output': o, 'post': {'owner': owner.copy(), 'domain': domain}})
        rows[-1]['post'] = None
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
            text = self.negative_override if self.negative_override is not None else (
                f'SYSTEM_OWNER_BOUNDARIES_CHECK[{name}]: cycle={self.entry.NEGATIVE_LOCATIONS[name]}\n')
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
             patch.object(self.entry.subprocess, 'run', side_effect=self.native) as run, \
             patch('sys.stdout', new_callable=io.StringIO):
            self.entry.main()
            return run

    def check(self, schedule='baseline', summary=None, trace=None, log=None):
        path, raw = self.root / 'mock-only-positive.log', self.root / 'mock-only-trace.jsonl'
        row = self.summaries[schedule] if summary is None else summary
        path.write_text(log if log is not None else self.entry.MARKER + ' ' + json.dumps(row) + '\n')
        raw.write_text(self.trace_text(schedule) if trace is None else trace)
        return self.entry.check_positive(path, schedule, raw)

    def mutate(self, phase, operation):
        rows = copy.deepcopy(self.records['baseline'])
        edge = next(row for row in rows[1:-1] if row['phase'] == phase)
        operation(edge)
        return self.trace_text(records=rows)

    def test_one_fresh_model_two_schedules_and_nine_named_negatives(self):
        run = self.invoke()
        self.common.setup.assert_called_once_with(False)
        output = self.common.BUILD / 'system-owner-boundaries'
        self.common.test.assert_called_once_with('gsim', 'clang++-19', str(output),
            'ooo.SystemOwnerBoundariesGsimMain', 'SystemOwnerBoundariesGsim', 'system_owner_boundaries.cpp',
            runtime_args=('--schedule', 'baseline', '--trace', str(output / 'raw-baseline.jsonl')),
            sanitizer=True, cxx_flags=('-fbracket-depth=4096',), timeout=120,
            mill_module='IonSoC.systemOwnerBoundaries')
        self.assertEqual(run.call_count, 10)
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

    def test_custom_fresh_output_does_not_change_build_root(self):
        output = self.root / 'mock-only-custom-model'
        build = self.common.BUILD
        self.invoke('--output', str(output))
        self.assertEqual(self.common.test.call_args.args[2], str(output))
        self.assertEqual(self.common.BUILD, build)

    def test_existing_empty_output_is_rejected_untouched(self):
        output = self.common.BUILD / 'system-owner-boundaries'
        output.mkdir(parents=True)
        with self.assertRaisesRegex(RuntimeError, 'fresh output'): self.invoke()
        self.common.setup.assert_not_called()
        self.assertEqual(list(output.iterdir()), [])

    def test_existing_file_and_dangling_symlink_are_rejected(self):
        file = self.root / 'retained-file'; file.write_text('retained')
        link = self.root / 'dangling-link'; link.symlink_to(self.root / 'absent')
        for path in (file, link):
            with self.subTest(path=path), self.assertRaises(RuntimeError): self.invoke('--output', str(path))
        self.assertEqual(file.read_text(), 'retained')
        self.common.setup.assert_not_called()

    def test_unverified_reuse_is_rejected(self):
        with self.assertRaises(SystemExit) as error: self.invoke('--reuse-unverified')
        self.assertEqual(error.exception.code, 2)
        self.common.setup.assert_not_called()

    def test_failed_tool_binding_never_builds(self):
        self.common.setup.side_effect = RuntimeError('binding changed')
        with self.assertRaisesRegex(RuntimeError, 'binding changed'): self.invoke()
        self.common.test.assert_not_called()

    def test_build_failure_has_no_fallback(self):
        self.common.test.side_effect = RuntimeError('compile failed')
        with self.assertRaisesRegex(RuntimeError, 'compile failed'): self.invoke()
        self.assertEqual(self.common.test.call_count, 1)

    def test_changed_model_destination_is_rejected(self):
        self.common.test.side_effect = lambda *args, **kwargs: self.root / 'wrong'
        with self.assertRaisesRegex(RuntimeError, 'destination changed'): self.invoke()

    def test_all_summary_fields_are_exact(self):
        for key in self.summaries['baseline']:
            row = copy.deepcopy(self.summaries['baseline']); del row[key]
            with self.subTest(key=key), self.assertRaises(RuntimeError): self.check(summary=row)
        row = copy.deepcopy(self.summaries['baseline']); row['unexpected'] = 1
        with self.assertRaises(RuntimeError): self.check(summary=row)

    def test_every_numeric_summary_count_is_frozen(self):
        for key, value in self.summaries['baseline'].items():
            if type(value) is int:
                row = copy.deepcopy(self.summaries['baseline']); row[key] += 1
                with self.subTest(key=key), self.assertRaises(RuntimeError): self.check(summary=row)
        for key in ('requests', 'responses'):
            row = copy.deepcopy(self.summaries['baseline']); row[key][1] -= 1
            with self.assertRaises(RuntimeError): self.check(summary=row)

    def test_boolean_integer_confusion_is_rejected(self):
        for key, value in self.summaries['baseline'].items():
            if type(value) is int:
                row = copy.deepcopy(self.summaries['baseline']); row[key] = True
                with self.subTest(key=key), self.assertRaises(RuntimeError): self.check(summary=row)

    def test_scope_schedule_and_drained_state_are_exact(self):
        for key, value in (('component_only', 1), ('guest_fd_execution', 0), ('drained', 1), ('schedule', 'staggered')):
            row = copy.deepcopy(self.summaries['baseline']); row[key] = value
            with self.subTest(key=key), self.assertRaises(RuntimeError): self.check(summary=row)

    def test_extra_pass_duplicate_missing_and_nonfinal_summary_fail(self):
        normal = self.entry.MARKER + ' ' + json.dumps(self.summaries['baseline']) + '\n'
        for log in ('PASS\n' + normal, normal + 'PASS\n', normal + normal, '{}\n', ''):
            with self.subTest(log=log[:40]), self.assertRaises(RuntimeError): self.check(log=log)

    def test_duplicate_json_keys_fail(self):
        normal = self.entry.MARKER + ' ' + json.dumps(self.summaries['baseline']) + '\n'
        with self.assertRaises(RuntimeError): self.check(log=normal.replace('"schema": 1', '"schema": 1, "schema": 1'))
        with self.assertRaises(RuntimeError): self.check(trace=self.trace_text().replace('"cycle": 1', '"cycle": 1, "cycle": 1', 1))

    def test_unknown_header_schema_fields_and_scope_fail(self):
        for key, value in (('schema', 2), ('schema', True), ('owners', 9), ('cycle_limit', 257), ('component_only', 1)):
            rows = copy.deepcopy(self.records['baseline']); rows[0][key] = value
            with self.subTest(key=key), self.assertRaises(RuntimeError): self.check(trace=self.trace_text(records=rows))
        rows = copy.deepcopy(self.records['baseline']); rows[0]['extra'] = 0
        with self.assertRaises(RuntimeError): self.check(trace=self.trace_text(records=rows))

    def test_missing_duplicate_reordered_and_truncated_rows_fail(self):
        normal = self.records['baseline']
        for rows in (normal[1:], normal[:-1], normal[:12] + normal[13:], normal[:12] + normal[11:],
                     normal[:10] + [normal[11], normal[10]] + normal[12:]):
            with self.assertRaises(RuntimeError): self.check(trace=self.trace_text(records=rows))
        with self.assertRaises(RuntimeError): self.check(trace=self.trace_text()[:-1])
        with self.assertRaises(RuntimeError): self.check(trace=self.trace_text()[:-20] + '\n')

    def test_raw_event_schema_and_phase_are_exact(self):
        for key, value in (('event', 'other'), ('cycle', True), ('phase', 'release_B'), ('extra', 0)):
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                self.check(trace=self.mutate('release_A', lambda row: row.__setitem__(key, value)))

    def test_input_output_and_post_fields_are_exact(self):
        for section in ('input', 'output', 'post'):
            for action in ('missing', 'extra'):
                def change(row):
                    target = row[section]
                    if action == 'extra': target['unexpected'] = 0
                    else: del target[next(iter(target))]
                with self.subTest(section=section, action=action), self.assertRaises(RuntimeError):
                    self.check(trace=self.mutate('release_A', change))

    def test_raw_integer_widths_exclude_booleans_overflow_and_floats(self):
        for value in (True, -1, 1 << 64, 0.5):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                self.check(trace=self.mutate('hold_A', lambda row: row['output']['owner'].__setitem__(2, value)))
        with self.assertRaises(RuntimeError):
            self.check(trace=self.mutate('hold_A', lambda row: row['input']['request'][0].pop()))

    def test_inactive_match_must_not_be_active_gated(self):
        def change(row): row['output'].update(retired=0, retire_matches=0)
        with self.assertRaisesRegex(RuntimeError, 'retirement match'): self.check(trace=self.mutate('probe_reset_0', change))
        with self.assertRaisesRegex(RuntimeError, 'retirement match'): self.check(trace=self.mutate('probe_retained_1', change))

    def test_high_tag_index_and_valid_matching_are_checked(self):
        for phase in ('probe_reset_2', 'probe_reset_3', 'probe_reset_4', 'hold_C'):
            with self.subTest(phase=phase), self.assertRaisesRegex(RuntimeError, 'retirement match'):
                self.check(trace=self.mutate(phase, lambda row: row['output'].update(retired=1, retire_matches=1)))

    def test_start_tokens_keep_upper_tag_bits(self):
        with self.assertRaisesRegex(RuntimeError, 'start token'):
            self.check(trace=self.mutate('start_A', lambda row: row['input']['start'].__setitem__(2, 0x55)))

    def test_completion_requires_accepted_valid_and_matching_token(self):
        for position, value in ((0, 0), (1, 2), (2, 0x55), (3, 0)):
            with self.subTest(position=position), self.assertRaises(RuntimeError):
                self.check(trace=self.mutate('release_A', lambda row: row['input']['complete'].__setitem__(position, value)))

    def test_invalid_exception_completion_remains_a_non_event(self):
        with self.assertRaisesRegex(RuntimeError, 'invalid exceptional completion'):
            self.check(trace=self.mutate('hold_A', lambda row: row['input']['complete'].__setitem__(3, 0)))
        with self.assertRaises(RuntimeError):
            self.check(trace=self.mutate('hold_A', lambda row: row['post']['owner'].__setitem__(0, 0)))

    def test_success_completion_cannot_release_owner(self):
        with self.assertRaisesRegex(RuntimeError, 'post-edge'):
            self.check(trace=self.mutate('complete_C', lambda row: row['post']['owner'].__setitem__(0, 0)))

    def test_exception_release_clears_active_epochs_but_retains_token(self):
        for position, value in ((0, 1), (1, 0), (2, 0), (3, 1), (4, 1), (5, 1)):
            with self.subTest(position=position), self.assertRaisesRegex(RuntimeError, 'post-edge'):
                self.check(trace=self.mutate('release_A', lambda row: row['post']['owner'].__setitem__(position, value)))

    def test_capture_wins_both_release_priorities(self):
        for phase in ('retire_capture_C', 'retire_capture_D', 'exception_capture_F', 'exception_capture_G'):
            with self.subTest(phase=phase), self.assertRaisesRegex(RuntimeError, 'post-edge'):
                self.check(trace=self.mutate(phase, lambda row: row['post'].update(owner=row['output']['owner'].copy())))

    def test_post_state_must_equal_next_observation(self):
        with self.assertRaises(RuntimeError):
            self.check(trace=self.mutate('request_stall_D', lambda row: row['output']['owner'].__setitem__(2, 0x55)))

    def test_only_final_row_may_lack_post_observation(self):
        with self.assertRaises(RuntimeError): self.check(trace=self.mutate('release_A', lambda row: row.__setitem__('post', None)))
        rows = copy.deepcopy(self.records['baseline']); rows[-2]['post'] = copy.deepcopy(rows[-3]['post'])
        with self.assertRaisesRegex(RuntimeError, 'unobserved post'): self.check(trace=self.trace_text(records=rows))

    def test_exception_tokens_are_never_validly_committed(self):
        with self.assertRaises(RuntimeError):
            self.check(trace=self.mutate('release_A', lambda row: row['input']['commits'].__setitem__(0, [1, *self.entry.TOKENS[0]])))

    def test_completion_boundary_requires_quiet_native_drain(self):
        for key in ('busy', 'request_valid'):
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                self.check(trace=self.mutate('release_A', lambda row: row['input'][key].__setitem__(1, 1)))
        with self.assertRaises(RuntimeError):
            self.check(trace=self.mutate('release_A', lambda row: row['input'].__setitem__('native_response_valid', 1)))

    def test_changed_response_or_drain_order_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'phase changed'):
            self.check(trace=self.mutate('drain_A', lambda row: row.__setitem__('phase', 'release_A')))
        with self.assertRaises(RuntimeError):
            self.check(trace=self.mutate('response_A', lambda row: row['input'].__setitem__('native_response_valid', 0)))

    def test_exact_native_transfer_schedule_and_exclusion(self):
        with self.assertRaises(RuntimeError):
            self.check(trace=self.mutate('request_A', lambda row: row['output']['request_ready'].__setitem__(2, 1)))
        with self.assertRaises(RuntimeError):
            self.check(trace=self.mutate('response_A', lambda row: row['output']['response_valid'].__setitem__(2, 1)))
        with self.assertRaises(RuntimeError):
            self.check(trace=self.mutate('request_stall_A', lambda row: row['input'].__setitem__('native_request_ready', 1)))

    def test_complete_payload_routing_is_checked(self):
        with self.assertRaisesRegex(RuntimeError, 'payload routing'):
            self.check(trace=self.mutate('request_A', lambda row: row['output']['native_request'].__setitem__(0, 0)))
        with self.assertRaisesRegex(RuntimeError, 'payload routing'):
            self.check(trace=self.mutate('response_A', lambda row: row['output']['response'][1].__setitem__(0, 0)))

    def test_stalled_request_payload_is_stable(self):
        def change(row):
            row['input']['request'][1][0] += 8
            row['output']['native_request'][0] += 8
        with self.assertRaisesRegex(RuntimeError, 'held request'): self.check(trace=self.mutate('request_A', change))

    def test_stalled_response_payload_is_stable(self):
        def change(row):
            row['input']['native_response'][0] += 8
            for reply in row['output']['response']: reply[0] += 8
        with self.assertRaisesRegex(RuntimeError, 'held response'): self.check(trace=self.mutate('response_A', change))

    def test_memory_busy_aggregation_is_checked(self):
        with self.assertRaisesRegex(RuntimeError, 'busy aggregation'):
            self.check(trace=self.mutate('hold_A', lambda row: row['output'].__setitem__('busy', 1)))

    def test_footer_must_be_exact_and_well_typed(self):
        for key, value in (('event', 'unfinished'), ('extra', 0)):
            rows = copy.deepcopy(self.records['baseline']); rows[-1][key] = value
            with self.assertRaises(RuntimeError): self.check(trace=self.trace_text(records=rows))
        rows = copy.deepcopy(self.records['baseline']); rows[-1]['summary']['starts'] = True
        with self.assertRaises(RuntimeError): self.check(trace=self.trace_text(records=rows))

    def test_noninitial_reset_and_nonquiet_final_fail(self):
        with self.assertRaisesRegex(RuntimeError, 'initial inactive reset'):
            self.check(trace=self.mutate('hold_A', lambda row: row.__setitem__('reset', 1)))
        rows = copy.deepcopy(self.records['baseline']); rows[-2]['input']['busy'][4] = 1
        rows[-2]['output']['busy'] = 1
        with self.assertRaises(RuntimeError): self.check(trace=self.trace_text(records=rows))

    def test_sanitizer_control_bytes_and_invalid_utf8_are_not_evidence(self):
        normal = self.entry.MARKER + ' ' + json.dumps(self.summaries['baseline']) + '\n'
        for prefix in ('runtime error: bad\n', 'AddressSanitizer: bad\n', 'UndefinedBehaviorSanitizer: bad\n', '\x00'):
            with self.assertRaises(RuntimeError): self.check(log=prefix + normal)
        path = self.root / 'invalid-utf8'; path.write_bytes(b'\xff\n')
        with self.assertRaises(RuntimeError): self.entry.clean_text(path)

    def test_missing_empty_and_excessive_evidence_fail(self):
        with self.assertRaises(RuntimeError): self.entry.clean_text(self.root / 'missing')
        path = self.root / 'empty'; path.write_text('')
        with self.assertRaises(RuntimeError): self.entry.clean_text(path)
        path.write_text('abcdef\n')
        with self.assertRaises(RuntimeError): self.entry.clean_text(path, limit=4)

    def test_negative_requires_exact_exit_one(self):
        path = self.root / 'negative.log'; path.write_text('SYSTEM_OWNER_BOUNDARIES_CHECK[exception_release]: cycle=18\n')
        for code in (0, 2, -11, 124, True):
            with self.subTest(code=code), self.assertRaises(RuntimeError): self.entry.check_negative(path, 'exception_release', code)

    def test_negative_requires_exact_name_cycle_and_no_other_output(self):
        normal = 'SYSTEM_OWNER_BOUNDARIES_CHECK[exception_release]: cycle=18\n'
        path = self.root / 'negative.log'
        for text in (normal.replace('exception_release', 'epoch_clear'), normal.replace('cycle=18', 'cycle=19'),
                     normal + 'PASS\n', normal + self.entry.MARKER + ' {}\n', 'AddressSanitizer: bad\n' + normal, ''):
            path.write_text(text)
            with self.subTest(text=text), self.assertRaises(RuntimeError): self.entry.check_negative(path, 'exception_release', 1)

    def test_missing_negative_never_produces_receipt(self):
        self.negative_override = ''
        with self.assertRaises(RuntimeError): self.invoke()
        self.assertFalse((self.common.BUILD / 'system-owner-boundaries/entry-summary.json').exists())

    def test_staggered_failure_stops_before_negatives(self):
        self.staggered_code = 1
        with self.assertRaisesRegex(RuntimeError, 'staggered execution failed'): self.invoke()
        self.assertFalse((self.common.BUILD / 'system-owner-boundaries/entry-summary.json').exists())

    def test_native_timeout_is_fatal_and_not_retried(self):
        with patch.object(sys, 'argv', ['entry']), patch.dict(self.entry.os.environ), \
             patch.object(self.entry.subprocess, 'run', side_effect=subprocess.TimeoutExpired('run', 120)) as run:
            with self.assertRaises(subprocess.TimeoutExpired): self.entry.main()
        run.assert_called_once()
        self.assertFalse((self.common.BUILD / 'system-owner-boundaries/entry-summary.json').exists())

    def test_both_mock_schedules_pass_replay_and_counts(self):
        for name in self.entry.SCHEDULES:
            self.assertEqual(self.check(name), self.summaries[name])


if __name__ == '__main__':
    unittest.main()
