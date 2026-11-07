"""Mock-only host checks. Synthetic observations are never hardware evidence."""
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


class FaultRecoveryEntryTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='mock-fp-fault-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.common = types.ModuleType('run')
        self.common.ROOT = self.root
        self.common.BUILD = self.root / 'build'
        self.common.setup = Mock(return_value=('pinned-gsim', 'clang++-19'))
        self.common.test = Mock(side_effect=self.generate)
        spec = importlib.util.spec_from_file_location('fault_entry', Path(__file__).with_name('guarded_fp_fault_recovery.py'))
        self.e = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'run': self.common}): spec.loader.exec_module(self.e)

    def generate(self, gsim, cxx, output, *args, **kwargs):
        Path(output).mkdir(parents=True)
        return Path(output)

    def state(self):
        s = dict.fromkeys(self.e.STATE_WIDTHS, 0)
        s.update(hostFs=2, guestFs=2, virtualized=1, fcsr=0x75)
        s['fpr_0'], s['fpr_1'] = self.e.SEED, self.e.LOADED
        return s

    def decode(self, n, state=None, tables=None):
        e = self.e; i = e.recipe()[n]
        return e.decode({k: i['start_bits_' + k] for k in e.START_WIDTHS},
            self.state() if state is None else state, e.initial_bytes(),
            e.initial_ptes() if tables is None else tables,
            {k: i['context_' + k] for k in e.CONTEXT_WIDTHS})

    def test_independent_fld_walk_and_byte_result(self):
        r = self.decode(1)
        self.assertEqual((r['data'], r['physical'], r['exception']), (0x400921fb54442d18, 0xc0000000, 0))
        self.assertEqual(r['ptes'], [0x200000, 0x40100000, 0x200000, 0x40101488,
                                    0x200000, 0x40102a28, 0x200010, 0x406000, 0x407000])

    def test_independent_store_address_and_source(self):
        r = self.decode(2)
        self.assertEqual((r['physical'], r['storeData'], r['data'], r['writes']), (0xc0000080, self.e.SEED, 0, False))
        self.assertEqual(len(r['ptes']), 9)

    def test_independent_joint_fs_denials(self):
        for host, guest in ((0, 2), (2, 0)):
            s = self.state(); s.update(hostFs=host, guestFs=guest)
            r = self.decode(3, s)
            self.assertEqual((r['exception'], r['cause'], r['tval'], r['ptes']), (1, 2, 0xb087, []))
            self.assertFalse(r['writes']); self.assertIsNone(r['physical'])
        s = self.state(); s.update(virtualized=0, guestFs=0)
        self.assertEqual(self.decode(0, s)['data'], self.e.SEED)

    def test_independent_misalignment_precedes_translation(self):
        r = self.decode(7, tables={})
        self.assertEqual((r['exception'], r['cause'], r['tval'], r['guestAddress'], r['ptes']), (1, 4, 0x12345001, 1, []))

    def test_independent_explicit_g_fault_and_unshifted_gpa(self):
        r = self.decode(9)
        self.assertEqual((r['cause'], r['guestPageFault'], r['guestAddress'], r['guestPhysicalAddress'], r['implicitPte']),
                         (21, 1, 1, 0x112345028, 0))
        self.assertEqual(r['ptes'], [0x200020, 0x40c488, 0x40da28])
        self.assertIsNone(r['physical'])

    def test_page_permissions_are_not_scenario_labels(self):
        ptes = self.e.initial_ptes(); ptes[0x40da28] |= 16
        r = self.decode(9, tables=ptes)
        self.assertEqual((r['exception'], r['physical']), (0, 0x60005028))
        ptes = self.e.initial_ptes(); ptes[0x407000] &= ~64
        self.assertEqual(self.decode(1, tables=ptes)['cause'], 21)
        ptes = self.e.initial_ptes(); ptes[0x200000] &= ~16
        r = self.decode(1, tables=ptes)
        self.assertEqual((r['cause'], r['guestPhysicalAddress'], r['implicitPte']), (21, 0x100000, 1))

    def test_nonidentity_mapping_change_changes_expected_result(self):
        ptes = self.e.initial_ptes(); ptes[0x407000] = (0xd0000000 >> 12 << 10) | 0xd7
        r = self.decode(1, tables=ptes)
        self.assertEqual((r['physical'], r['data']), (0xd0000000, 0))

    def test_moves_use_input_and_preserved_fpr(self):
        self.assertEqual(self.decode(0)['data'], self.e.SEED)
        for n in (4, 6, 8, 10):
            r = self.decode(n); self.assertEqual(r['data'], self.e.LOADED); self.assertFalse(r['writes'])

    def test_reserved_and_out_of_scope_instructions_rejected(self):
        e = self.e; c = {k: e.recipe()[0]['start_bits_' + k] for k in e.START_WIDTHS}
        context = {k: 0 for k in e.CONTEXT_WIDTHS}
        for inst in (0, 0x02000053, 0xf2108053, 0xf2009053, 0x2087):
            with self.subTest(inst=inst), self.assertRaises(RuntimeError):
                e.decode({**c, 'instruction': inst}, self.state(), {}, {}, context)

    def test_fixed_offer_stalls_and_response_delay_laws(self):
        for schedule in self.e.SCHEDULES:
            service = self.e.Service(schedule)
            first = service.inputs(0)
            self.assertEqual(first['pte_request_ready'], 0)
            o = dict.fromkeys(self.e.OUTPUT_WIDTHS, 0)
            o.update(pte_request_valid=1, pte_request_bits=0x200000)
            for cycle in range(3 if schedule == 'staggered' else 1):
                i = {**self.e.defaults(), **service.inputs(cycle)}
                self.assertEqual(i['pte_request_ready'], 0)
                service.step(i, o)
            i = {**self.e.defaults(), **service.inputs(4)}
            self.assertEqual(i['pte_request_ready'], 1)
            service.step(i, o)
            delay = 4 if schedule == 'staggered' else 2
            for cycle in range(1, delay + 1):
                self.assertEqual(service.inputs(cycle)['pte_response_valid'], 0)
                service.step(self.e.defaults(), dict.fromkeys(self.e.OUTPUT_WIDTHS, 0))
            self.assertEqual(service.inputs(delay + 1)['pte_response_valid'], 1)
            self.assertEqual(service.inputs(delay + 1)['pte_response_bits_data'], self.e.initial_ptes()[0x200000])

    def test_store_byte_neighbors_and_read_before_write_response(self):
        e = self.e; service = e.Service('baseline'); before = service.memory.copy()
        o = dict.fromkeys(e.OUTPUT_WIDTHS, 0)
        o.update(physical_request_valid=1, physical_request_bits_address=0xc0000080,
                 physical_request_bits_write=1, physical_request_bits_mask=255, physical_request_bits_data=e.SEED)
        i = e.defaults(); i['physical_request_ready'] = 1
        service.step(i, o)
        self.assertEqual(service.data['physical'], sum(before[0xc0000080+n] << (8*n) for n in range(8)))
        for at in before:
            expected = (e.SEED >> (8*(at-0xc0000080))) & 255 if 0xc0000080 <= at < 0xc0000088 else before[at]
            self.assertEqual(service.memory[at], expected)

    def test_frozen_plan_has_no_fault_commit_before_flush(self):
        for schedule in self.e.SCHEDULES:
            rows = self.e.planned_inputs(schedule, [4]*11)
            self.assertEqual(sum(i['trap_valid'] for _, i in rows), 4)
            self.assertEqual(sum(label.endswith('_retire') for label, _ in rows), 7)
            for n in self.e.FAULT_COMMANDS:
                pending = [(label, i) for label, i in rows if label.startswith(f'op{n}_fault_pending_')]
                self.assertEqual(len(pending), 3 if schedule == 'baseline' else 6)
                for _, i in pending:
                    self.assertTrue(i['start_valid']); self.assertFalse(i['commit0_valid'] or i['commit1_valid'])

    def test_strict_scalar_schema_types_and_all32_registers(self):
        e = self.e; row = dict.fromkeys(e.OUTPUT_WIDTHS, 0)
        e.scalar_map(row, e.OUTPUT_WIDTHS, 'pre')
        self.assertEqual(len([k for k in row if k.startswith('fpr_')]), 32)
        for key, width in e.OUTPUT_WIDTHS.items():
            for value in (-1, 1 << width, True, 0.0):
                with self.subTest(key=key, value=value), self.assertRaises(RuntimeError):
                    e.scalar_map({**row, key: value}, e.OUTPUT_WIDTHS, 'pre')
        with self.assertRaises(RuntimeError): e.scalar_map({**row, 'extra': 0}, e.OUTPUT_WIDTHS, 'pre')

    def test_strict_json_duplicates_types_and_truncation(self):
        e = self.e
        with self.assertRaises(RuntimeError): e.object_row('{"a":0,"a":1}')
        for value in (True, 0.0):
            with self.assertRaises(RuntimeError): e.exact(value, 0, 'type')
        path = self.root / 'text'
        for text in ('', '{}', 'Sanitizer\n', 'runtime error:\n', '\x00\n'):
            path.write_text(text)
            with self.assertRaises(RuntimeError): e.clean_text(path)
        path.write_bytes(b'\xff\n')
        with self.assertRaises(RuntimeError): e.clean_text(path)

    def test_missing_or_excessive_trace_rejected(self):
        path = self.root / 'trace'
        with self.assertRaises(RuntimeError): self.e.check_trace(path, 'baseline')
        path.write_bytes(b'\n' * (self.e.TRACE_LIMIT + 1))
        with self.assertRaises(RuntimeError): self.e.check_trace(path, 'baseline')

    def mock_denied_rows(self):
        e = self.e
        ledger = e.Replay(e.initial_ptes(), e.initial_bytes())
        ledger.state.update(self.state()); ledger.state['hostFs'] = 0
        ledger.state['hstatus'] = 2 << 32
        initial = ledger.state.copy()
        rows = []
        command = e.recipe()[3]
        for phase in ('issue', 'hold', 'accept', 'pending', 'trap', 'flushed'):
            i = {**e.defaults(), **{k: v for k, v in command.items() if k.startswith('context_')}}
            if phase == 'issue': i.update(command)
            if phase == 'accept': i['complete_ready'] = 1
            if phase == 'pending': i.update(start_valid=1, start_bits_instruction=0xe2008153)
            if phase == 'trap':
                i.update(trap_valid=1, trap_bits_pc=command['start_bits_pc'], trap_bits_cause=2, trap_bits_tval=0xb087)
            old = ledger.state.copy(); idle = old['statePhase'] == 0
            o = {**dict.fromkeys(e.OUTPUT_WIDTHS, 0), **old}
            offered = int(old['statePhase'] == 3 and not old['completionSeen'] and phase != 'trap')
            o.update(start_ready=int(idle and phase != 'trap'), issueAccepted=int(phase == 'issue'),
                complete_valid=offered, completionAccepted=int(phase == 'accept'),
                stateCompleteValid=int(old['statePhase'] == 3 and phase != 'trap'),
                csr_ready=int(idle and phase != 'trap'), csrIllegal=1, csrRead=0x75,
                status_ready=int(idle), memoryDrained=1, contextReplaceAllowed=int(idle),
                adapterIdle=1, translatorIdle=1, responseBufferIdle=1,
                fpMemoryEpoch=old['ownerActive'], contextMemoryEpoch=old['ownerActive'],
                selectorDomain=2*old['ownerActive'], translationActive=1)
            if ledger.command is not None and phase != 'trap': o.update(e.prefixed('complete_bits_', ledger.envelope()))
            post = old.copy()
            if phase == 'issue':
                post.update(ownerActive=1, ownerToken_index=5, ownerToken_tag=command['start_bits_token_tag'],
                            statePhase=3, busy=1, completionSeen=0)
            if phase == 'accept': post.update(ownerActive=0, completionSeen=1)
            if phase == 'trap': post.update(statePhase=0, busy=0, completionSeen=0, virtualized=0, hstatus=(2 << 32) | 384)
            rows.append((i, o, post, phase))
            ledger.step(i, o, post, phase)
        return initial, rows

    def test_mock_denied_lifecycle_release_is_not_context_credit(self):
        _, rows = self.mock_denied_rows()
        pending = next(o for _, o, _, phase in rows if phase == 'pending')
        self.assertEqual((pending['ownerActive'], pending['busy'], pending['start_ready'],
                          pending['contextReplaceAllowed'], pending['complete_valid']), (0, 1, 0, 0, 0))
        self.assertEqual(rows[-1][2]['fpr_1'], self.e.LOADED)

    def test_mock_replay_fault_credit_drain_and_mutation_corruptions(self):
        e = self.e; initial, original = self.mock_denied_rows()
        for phase, section, field, value in (
            ('hold', 1, 'executeValid', 1), ('hold', 1, 'complete_bits_cause', 4),
            ('hold', 1, 'ownerActive', 0), ('pending', 1, 'start_ready', 1),
            ('pending', 1, 'complete_valid', 1), ('accept', 1, 'memoryDrained', 0),
            ('trap', 1, 'adapterIdle', 0), ('trap', 2, 'fpr_31', 1)):
            ledger = e.Replay(e.initial_ptes(), e.initial_bytes()); ledger.state.update(initial)
            rows = copy.deepcopy(original)
            next(row for row in rows if row[3] == phase)[section][field] = value
            with self.subTest(phase=phase, field=field), self.assertRaises(RuntimeError):
                for i, o, post, label in rows: ledger.step(i, o, post, label)

    def invoke(self, *args):
        with patch.object(sys, 'argv', ['entry', *args]), patch.dict(self.e.os.environ), \
             patch.object(self.e, 'check_positive', return_value={'mock_only': True}), \
             patch.object(self.e, 'check_negative'), \
             patch.object(self.e, 'native_run', side_effect=lambda output, args, name, env: (output/name, 1 if '--negative' in args else 0)) as run, \
             patch('sys.stdout', new_callable=io.StringIO):
            self.e.main()
            return run

    def test_one_new_sanitized_model_exact_negatives(self):
        run = self.invoke()
        self.common.setup.assert_called_once_with(False)
        self.assertEqual(self.common.test.call_count, 1)
        kwargs = self.common.test.call_args.kwargs
        self.assertTrue(kwargs['sanitizer']); self.assertEqual(kwargs['timeout'], 120)
        self.assertEqual(kwargs['mill_module'], 'IonSoC.guardedFpFaultRecovery')
        self.assertEqual(run.call_count, 1 + len(self.e.NEGATIVES))
        for call in run.call_args_list:
            self.assertEqual(call.args[3]['UBSAN_OPTIONS'], 'halt_on_error=1')
            self.assertEqual(call.args[3]['ASAN_OPTIONS'], 'detect_leaks=0')

    def test_existing_outputs_and_symlink_preserved(self):
        for kind in ('file', 'directory', 'link'):
            path = self.root/kind
            if kind == 'file': path.write_text('keep')
            elif kind == 'directory': path.mkdir()
            else: path.symlink_to(self.root/'absent')
            with self.assertRaises(RuntimeError): self.invoke('--output', str(path))
        self.common.setup.assert_not_called()

    def test_setup_build_and_destination_errors(self):
        self.common.setup.side_effect = RuntimeError('pin mismatch')
        with self.assertRaisesRegex(RuntimeError, 'pin mismatch'): self.invoke()
        self.common.test.assert_not_called(); self.common.setup.side_effect = None
        self.common.test.side_effect = RuntimeError('build failed')
        with self.assertRaisesRegex(RuntimeError, 'build failed'): self.invoke()
        self.common.test.side_effect = lambda *a, **k: self.root
        with self.assertRaisesRegex(RuntimeError, 'destination changed'): self.invoke()

    def test_timeout_and_crash_never_count_as_negative(self):
        with patch.object(self.e.subprocess, 'run', side_effect=subprocess.TimeoutExpired('run', 120)):
            with self.assertRaises(subprocess.TimeoutExpired): self.e.native_run(self.root, (), 'timeout.log', {})
        for code in (0, 2, -11, True):
            with self.assertRaises(RuntimeError):
                self.e.check_negative(self.root/'absent', self.e.NEGATIVES[0], code, self.root/'trace')


if __name__ == '__main__': unittest.main()
