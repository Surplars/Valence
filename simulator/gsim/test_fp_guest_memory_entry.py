"""Host orchestration checks only. Every hardware build/execution is mocked."""
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


class FpGuestMemoryEntryTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.common = types.ModuleType('run')
        self.common.ROOT = self.root
        self.common.BUILD = self.root / 'build/gsim'
        self.common.setup = Mock(return_value=('gsim', 'clang++-19'))
        self.common.test = Mock(side_effect=self.generate)
        spec = importlib.util.spec_from_file_location('fp_guest_entry', Path(__file__).with_name('fp_guest_memory.py'))
        self.entry = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'run': self.common}):
            spec.loader.exec_module(self.entry)
        self.memory = {'schema': 1, 'component_only': True, 'guest_fd_execution': False, 'schedules': []}
        for i in range(2):
            self.memory['schedules'].append({**self.entry.MEMORY_EXACT, **copy.deepcopy(self.entry.MEMORY_ARRAYS),
                'schedule': i, 'cycles': 78, 'drained': True, 'pte_requests': 100, 'pte_responses': 100,
                'held_physical': 1, 'held_pte': 1, 'held_completions': 450})
        records = []
        lengths = {'command': 6, 'context': 11, 'handshake': 5, 'retire': 5, 'pte': 6,
                   'physical': 7, 'virtual_request': 2, 'pma': 6, 'adapter_response': 4,
                   'buffer_response': 3, 'pipeline': 2, 'converted': 12, 'complete': 2,
                   'state': 4, 'fpr': 32, 'idle': 4}
        for schedule in range(2):
            for cycle in range(1, 4):
                records.append({'schedule': schedule, 'cycle': cycle, 'event': 'idle_init',
                                'set_fs': [0, 2], 'csr': [0, 3, 0, 1, 117], 'fs': 0, 'fcsr': 0})
            for cycle, case in enumerate(self.entry.memory_case_names(), 4):
                records.append({'schedule': schedule, 'cycle': cycle - 1, 'case': case,
                                'event': 'memory_init', 'bytes': [], 'ptes': []})
                records.append({'schedule': schedule, 'cycle': cycle, 'case': case,
                                **{key: [0] * length for key, length in lengths.items()}})
                records.append({'schedule': schedule, 'cycle': cycle, 'case': case,
                                'event': 'memory_final', 'bytes': []})
        self.memory_trace = ''.join(json.dumps(record) + '\n' for record in records)
        self.buffer_trace = 'cycle,lane,reset,input_valid,input_ready,output_valid,output_ready\n' + ''.join(
            f'{c},{lane},0,0,1,0,1\n' for c in range(732) for lane in range(16))
        self.buffer = {'component_only': True, 'guest_fd_execution': False, 'configs': 16, 'capacity': 2,
            'cycles': 732, 'cycle_limit': 1024, 'idle_resets': 2, 'reset_cycles': 4, 'trace_rows': 11712,
            'trace_bytes': len(self.buffer_trace.encode()), 'lanes': []}
        for i in range(16):
            metadata, tagged, flow = bool(i // 2 % 2), bool(i % 2), i // 4 in (0, 3)
            self.buffer['lanes'].append({'lane': i, 'mode': self.entry.BUFFER_MODES[i // 4],
                'metadata': metadata, 'tagged': tagged, 'accepted': 400, 'consumed': 400, 'max_occupancy': 2,
                **dict.fromkeys(self.entry.BUFFER_POSITIVE, 1), 'continuous_accepted': 128,
                'continuous_consumed': 128 if flow else 127, 'empty_bypass': 1 if flow else 0,
                'status_mask': 15, 'metadata_changes': int(metadata), 'metadata_clears': int(metadata),
                'high_gpa': int(metadata), 'metadata_mask': 255 if metadata else 1,
                'high_handle': int(tagged), 'handle_mask': (1 << 64) - 1 if tagged else 1})
        self.negative_code = 1
        self.negative_override = None

    def generate(self, gsim, cxx, name, *args, **kwargs):
        profile = name.rsplit('/', 1)[1]
        output = self.common.BUILD / name
        output.mkdir(parents=True, exist_ok=True)
        row = self.memory if profile == 'memory' else self.buffer
        (output / 'test.log').write_text(self.entry.MARKERS[profile] + ' ' + json.dumps(row) + '\n')
        Path(kwargs['runtime_args'][1]).write_text(self.memory_trace if profile == 'memory' else self.buffer_trace)
        return output

    def negative_text(self, profile, name):
        if profile == 'memory':
            return f'FP_GUEST_MEMORY_CHECK[{name}]: {self.entry.MEMORY_NEGATIVES[name]}\n'
        label, lane = self.entry.BUFFER_NEGATIVES[name]
        return f'FP_GUEST_RESPONSE_BUFFER_NEGATIVE {name} lane={lane} cycle=9\nFP_GUEST_RESPONSE_BUFFER_FAIL {label} lane={lane} cycle=9\n'

    def negative(self, args, **kwargs):
        profile, name = Path(args[0]).parent.name, args[2]
        kwargs['stdout'].write(self.negative_override if self.negative_override is not None else self.negative_text(profile, name))
        return subprocess.CompletedProcess(args, self.negative_code)

    def invoke(self):
        with patch.object(sys, 'argv', ['fp_guest_memory.py']), patch.object(self.entry.subprocess, 'run', side_effect=self.negative) as run:
            self.entry.main()
            return run

    def check(self, profile='memory', row=None, trace=None, log=None):
        selected = self.memory if profile == 'memory' else self.buffer
        path = self.root / 'positive.log'
        path.write_text(log if log is not None else self.entry.MARKERS[profile] + ' ' + json.dumps(selected if row is None else row) + '\n')
        raw = self.root / 'trace'
        raw.write_text(trace if trace is not None else self.memory_trace if profile == 'memory' else self.buffer_trace)
        return self.entry.check_positive(path, profile, raw)

    def test_two_fresh_models_and_twelve_named_negatives(self):
        run = self.invoke()
        self.common.setup.assert_called_once_with(False)
        self.assertEqual(self.common.test.call_count, 2)
        for call, (profile, main, model, driver, trace) in zip(self.common.test.call_args_list, self.entry.PROFILES):
            self.assertEqual(call.args, ('gsim', 'clang++-19', 'fp-guest-memory/' + profile, main, model, driver))
            self.assertEqual(call.kwargs, {'runtime_args': ('--trace', str(self.common.BUILD / 'fp-guest-memory' / profile / trace)),
                'cxx_flags': ('-fbracket-depth=4096',), 'timeout': 120, 'mill_module': 'IonSoC.fpGuestMemoryPreparation'})
        self.assertEqual(run.call_count, 12)
        for call in run.call_args_list:
            self.assertEqual(call.args[0][1], '--negative')
            self.assertEqual(call.kwargs['cwd'], self.root)
            self.assertEqual(call.kwargs['timeout'], 120)
            self.assertEqual(call.kwargs['env']['UBSAN_OPTIONS'], 'halt_on_error=1')

    def test_unverified_reuse_option_is_rejected(self):
        with patch.object(sys, 'argv', ['entry', '--reuse-unverified']), self.assertRaises(SystemExit) as error:
            self.entry.main()
        self.assertEqual(error.exception.code, 2)
        self.common.setup.assert_not_called()

    def test_failed_tool_binding_never_runs_a_model(self):
        self.common.setup.side_effect = RuntimeError('binding changed')
        with self.assertRaisesRegex(RuntimeError, 'binding changed'): self.invoke()
        self.common.test.assert_not_called()

    def test_all_exact_memory_counts_are_required(self):
        for key in self.entry.MEMORY_EXACT:
            row = copy.deepcopy(self.memory); row['schedules'][0][key] -= 1
            with self.subTest(key=key), self.assertRaises(RuntimeError): self.check(row=row)

    def test_integer_boolean_confusion_is_rejected(self):
        row = copy.deepcopy(self.memory); row['schedules'][0]['commands'] = True
        with self.assertRaises(RuntimeError): self.check(row=row)

    def test_scope_and_schedule_identity_are_required(self):
        for key, value in [('component_only', False), ('guest_fd_execution', True)]:
            row = copy.deepcopy(self.memory); row[key] = value
            with self.assertRaises(RuntimeError): self.check(row=row)
        row = copy.deepcopy(self.memory); row['schedules'].reverse()
        with self.assertRaises(RuntimeError): self.check(row=row)

    def test_matrix_and_credit_checks_are_required(self):
        for key in self.entry.MEMORY_ARRAYS:
            row = copy.deepcopy(self.memory); row['schedules'][1][key][0] += 1
            with self.assertRaises(RuntimeError): self.check(row=row)
        row = copy.deepcopy(self.memory); row['schedules'][0]['pte_responses'] -= 1
        with self.assertRaises(RuntimeError): self.check(row=row)

    def test_memory_trace_gap_truncation_and_duplicate_keys_fail(self):
        for trace in [self.memory_trace.rsplit('\n', 2)[0] + '\n', self.memory_trace.replace('"cycle": 2', '"cycle": 1', 1),
                      self.memory_trace.replace('"cycle": 1', '"cycle": 1, "cycle": 1', 1)]:
            with self.assertRaises(RuntimeError): self.check(trace=trace)

    def test_summary_duplicate_key_and_nonfinal_footer_fail(self):
        normal = self.entry.MARKERS['memory'] + ' ' + json.dumps(self.memory) + '\n'
        for log in [normal + 'more\n', normal + normal, normal.replace('"schema": 1', '"schema": 1, "schema": 1')]:
            with self.assertRaises(RuntimeError): self.check(log=log)

    def test_buffer_mode_identity_and_capacity_are_required(self):
        for key, value in [('lane', 1), ('mode', 'registered_head'), ('max_occupancy', 3), ('continuous_consumed', 127)]:
            row = copy.deepcopy(self.buffer); row['lanes'][0][key] = value
            with self.assertRaises(RuntimeError): self.check('buffer', row=row)

    def test_buffer_optional_metadata_and_handles_must_be_exact(self):
        for index, key in [(2, 'metadata_mask'), (1, 'handle_mask'), (0, 'metadata_clears'), (0, 'high_handle')]:
            row = copy.deepcopy(self.buffer); row['lanes'][index][key] ^= 1
            with self.assertRaises(RuntimeError): self.check('buffer', row=row)

    def test_buffer_trace_order_and_byte_count_are_required(self):
        row = copy.deepcopy(self.buffer); row['trace_bytes'] += 1
        with self.assertRaises(RuntimeError): self.check('buffer', row=row)
        trace = self.buffer_trace.replace('0,1,0,0,1,0,1', '0,0,0,0,1,0,1', 1)
        with self.assertRaises(RuntimeError): self.check('buffer', trace=trace)

    def test_sanitizer_and_control_bytes_are_not_success(self):
        normal = self.entry.MARKERS['memory'] + ' ' + json.dumps(self.memory) + '\n'
        for prefix in ['runtime error: bad\n', 'AddressSanitizer: bad\n', '\x00']:
            with self.assertRaises(RuntimeError): self.check(log=prefix + normal)

    def test_negative_must_exit_exactly_one(self):
        for code in [0, -11, 2]:
            self.negative_code = code
            with self.assertRaises(RuntimeError): self.invoke()

    def test_negative_must_reach_its_exact_named_checker(self):
        self.negative_override = 'FP_GUEST_MEMORY_CHECK[timeout]: timed out\n'
        with self.assertRaises(RuntimeError): self.invoke()

    def test_buffer_negative_injection_and_failure_must_match(self):
        path = self.root / 'negative.log'
        text = self.negative_text('buffer', 'metadata-mismatch')
        for altered in [text.replace('cycle=9', 'cycle=10', 1), text.splitlines()[-1] + '\n', text + 'FP_GUEST_RESPONSE_BUFFER_PASS {}\n']:
            path.write_text(altered)
            with self.assertRaises(RuntimeError): self.entry.check_negative(path, 'buffer', 'metadata-mismatch', 1)


if __name__ == '__main__':
    unittest.main()
