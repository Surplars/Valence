#!/usr/bin/env python3
"""Source-only CLI/model/guest/result tests. No compiler or simulator is executed."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest import mock

import cpu_flow_data_pmp as pmp


class ArgumentsTest(unittest.TestCase):
    base = ['--out', 'result', '--off-model-tag', 'cpu-flow-off-new', '--on-model-tag', 'cpu-flow-on-new']

    def reject(self, argv):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            pmp.arguments(argv)

    def test_explicit_tags(self):
        args = pmp.arguments(self.base)
        paths = pmp.model_paths(args, Path('/tmp/model-root'))
        self.assertEqual(paths['off'], Path('/tmp/model-root/fpga-next-board-cpu-flow-off-new/receipt.json'))
        self.assertEqual(paths['on'], Path('/tmp/model-root/fpga-next-board-cpu-flow-on-new/receipt.json'))
        self.assertFalse(args.dma_line_transfers)
        self.assertEqual((args.dma_line_entries, args.dma_line_yield_cycles), (1, 0))

    def test_explicit_receipts(self):
        args = pmp.arguments(['--out', 'new', '--off-model-receipt', 'a/receipt.json', '--on-model-receipt', 'b/receipt.json'])
        self.assertEqual(pmp.model_paths(args), {side: Path(value).resolve()
                         for side, value in [('off', 'a/receipt.json'), ('on', 'b/receipt.json')]})

    def test_mixed_explicit_paths_and_tags(self):
        args = pmp.arguments(['--out', 'new', '--off-model-receipt', 'a/receipt.json', '--on-model-tag', 'b'])
        self.assertEqual(pmp.model_paths(args)['off'], Path('a/receipt.json').resolve())

    def test_no_model_autodiscovery(self):
        self.reject(['--out', 'new'])

    def test_both_sides_required(self):
        self.reject(self.base[:-2])

    def test_output_required(self):
        self.reject(self.base[2:])

    def test_unsafe_tag(self):
        self.reject(self.base[:-1] + ['../old'])

    def test_receipt_and_tag_exclusive(self):
        self.reject(self.base + ['--off-model-receipt', 'a'])

    def test_no_resume(self):
        self.reject(self.base + ['--resume'])

    def test_explicit_shared_dma(self):
        args = pmp.arguments(self.base + ['--dma-line-transfers', '--dma-line-entries', '4', '--dma-line-yield-cycles', '8'])
        self.assertEqual((args.dma_line_transfers, args.dma_line_entries, args.dma_line_yield_cycles), (True, 4, 8))

    def test_dma_settings_need_enable(self):
        self.reject(self.base + ['--dma-line-entries', '4'])
        self.reject(self.base + ['--dma-line-yield-cycles', '8'])

    def test_invalid_dma_settings(self):
        self.reject(self.base + ['--dma-line-transfers', '--dma-line-entries', '3'])
        self.reject(self.base + ['--dma-line-transfers', '--dma-line-yield-cycles', '1'])
        self.reject(self.base + ['--dma-line-transfer'])

    def test_fresh_output_checked_before_tools(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(pmp.common, 'compiler') as compiler:
            args = pmp.arguments(['--out', directory, *self.base[2:]])
            with self.assertRaisesRegex(RuntimeError, 'fresh data-PMP output'):
                pmp.run(args)
            compiler.assert_not_called()


class ModelPairTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='cpu-pmp-model-test-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.inputs = {'src/fixture.scala': 'a' * 64}
        self.paths, self.states = {}, {}
        for side in ('off', 'on'):
            directory = self.root / side
            (directory / 'model').mkdir(parents=True)
            state = {'schema': 'valence-fpga-next-board-evidence-v1', 'status': 'PASS_FPGA_NEXT_BOARD_SMOKE',
                     'inputs': self.inputs.copy(), 'plan': pmp.flow.expected_model_plan(side == 'on'),
                     'toolchain': {**pmp.common.LOCK, 'compiler': 'test compiler'}, 'artifacts': {}}
            for name in ('BoardSocGsim.h', 'BoardSocGsim.fir', 'BoardSocGsim0.cpp', 'BoardSocGsim0.o'):
                path = directory / 'model' / name
                path.write_text(side + ' test ' + name)
                state['artifacts']['model/' + name] = pmp.sha(path)
            self.paths[side] = directory / 'receipt.json'
            self.states[side] = state
        self.write()

    def write(self):
        for side in ('off', 'on'):
            self.paths[side].write_text(json.dumps(self.states[side]))

    def validate(self, **options):
        self.write()
        return pmp.validate_models(self.paths, self.inputs, 'test compiler', **options)

    def test_standalone_pair(self):
        result = self.validate()
        self.assertEqual(set(result), {'off', 'on'})
        self.assertEqual(result['on']['receipt_sha256'], pmp.sha(self.paths['on']))
        self.assertEqual(len(result['off']['objects']), 1)

    def test_multiple_objects(self):
        for side in ('off', 'on'):
            for extension in ('cpp', 'o'):
                path = self.paths[side].parent / 'model' / ('BoardSocGsim1.' + extension)
                path.write_text('second unit')
                self.states[side]['artifacts']['model/' + path.name] = pmp.sha(path)
        self.assertEqual(len(self.validate()['on']['objects']), 2)

    def test_explicit_dma_pair(self):
        options = {'dma_line_transfers': True, 'dma_line_entries': 4, 'dma_line_yield_cycles': 0}
        for side in ('off', 'on'):
            self.states[side]['plan'] = pmp.flow.expected_model_plan(side == 'on', **options)
        self.assertEqual(set(self.validate(**options)), {'off', 'on'})
        with self.assertRaisesRegex(RuntimeError, 'profile drift'):
            self.validate()
        with self.assertRaisesRegex(RuntimeError, 'profile drift'):
            self.validate(**{**options, 'dma_line_entries': 2})

    def test_different_shared_profiles_rejected(self):
        self.states['on']['plan'] = pmp.flow.expected_model_plan(True, dma_line_transfers=True, dma_line_entries=4)
        with self.assertRaisesRegex(RuntimeError, 'profile drift'):
            self.validate()

    def test_unexpected_shared_option(self):
        with self.assertRaises(TypeError):
            self.validate(typo=True)

    def test_incomplete_pair(self):
        with self.assertRaisesRegex(RuntimeError, 'explicit OFF/ON'):
            pmp.validate_models({'off': self.paths['off']}, self.inputs, 'test compiler')

    def test_same_receipt_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'must be distinct'):
            pmp.validate_models({'off': self.paths['off'], 'on': self.paths['off']}, self.inputs, 'test compiler')

    def test_wrong_flow_side(self):
        self.states['on']['plan'] = pmp.flow.expected_model_plan(False)
        with self.assertRaisesRegex(RuntimeError, 'profile drift'):
            self.validate()

    def test_unrelated_profile_flag(self):
        self.states['off']['plan']['parameters'].append('--prechecked-data-flow')
        with self.assertRaisesRegex(RuntimeError, 'profile drift'):
            self.validate()

    def test_source_drift(self):
        self.states['on']['inputs']['src/fixture.scala'] = 'b' * 64
        with self.assertRaisesRegex(RuntimeError, 'source inventory drift'):
            self.validate()

    def test_toolchain_drift(self):
        self.states['on']['toolchain']['compiler'] = 'another compiler'
        with self.assertRaisesRegex(RuntimeError, 'toolchain/profile drift'):
            self.validate()

    def test_incomplete_status(self):
        self.states['on']['status'] = 'RUNNING'
        with self.assertRaisesRegex(RuntimeError, 'completed board smoke'):
            self.validate()

    def test_object_hash_drift(self):
        (self.paths['off'].parent / 'model/BoardSocGsim0.o').write_text('changed')
        with self.assertRaisesRegex(RuntimeError, 'hash mismatch'):
            self.validate()

    def test_missing_object_hash(self):
        del self.states['off']['artifacts']['model/BoardSocGsim0.o']
        with self.assertRaisesRegex(RuntimeError, 'unhashed model artifact'):
            self.validate()

    def test_missing_object(self):
        (self.paths['off'].parent / 'model/BoardSocGsim0.o').unlink()
        with self.assertRaisesRegex(RuntimeError, 'object set'):
            self.validate()

    def test_manifest_escape(self):
        self.states['off']['artifacts']['../outside'] = '0' * 64
        with self.assertRaisesRegex(RuntimeError, 'nonportable manifest path'):
            self.validate()

    def test_receipt_changes_during_validation(self):
        original = pmp.flow.validate_model
        def change(*args, **kwargs):
            result = original(*args, **kwargs)
            Path(args[0]).write_text(Path(args[0]).read_text() + '\n')
            return result
        with mock.patch.object(pmp.flow, 'validate_model', side_effect=change):
            with self.assertRaisesRegex(RuntimeError, 'model receipt during validation'):
                self.validate()

    def test_invalid_pair_prevents_guest_toolchain_and_output(self):
        self.states['on']['plan'] = pmp.flow.expected_model_plan(False)
        self.write()
        out = self.root / 'new-output'
        args = pmp.arguments(['--out', str(out), '--off-model-receipt', str(self.paths['off']),
                              '--on-model-receipt', str(self.paths['on'])])
        with mock.patch.object(pmp, 'inventory', return_value=self.inputs), \
             mock.patch.object(pmp.board, 'source_inventory', return_value=self.inputs), \
             mock.patch.object(pmp.common, 'compiler', return_value=('test-cxx', 'test compiler')), \
             mock.patch.object(pmp.guests, 'toolchain') as toolchain:
            with self.assertRaisesRegex(RuntimeError, 'profile drift'):
                pmp.run(args)
            toolchain.assert_not_called()
            self.assertFalse(out.exists())


class OrchestrationTest(unittest.TestCase):
    setUp = ModelPairTest.setUp
    write = ModelPairTest.write
    def exercise(self, failure=None, symlink=False):
        out = self.root / 'output'
        args = pmp.arguments(['--out', str(out), '--off-model-receipt', str(self.paths['off']),
                              '--on-model-receipt', str(self.paths['on'])])
        executable = self.root / 'host'
        executable.write_text('mock host executable, never run')
        executable.chmod(0o755)
        if symlink:
            driver = self.root / 'clang++-fixture'
            driver.symlink_to(executable)
            executable = driver
        tools, records = {}, {}
        for name in ('cc', 'nm', 'objcopy', 'as', 'ld', 'cc1'):
            path = self.root / name
            path.write_text('mock tool, never run: ' + name)
            tools[name] = path
            records[name] = {'name': name, 'sha256': pmp.sha(path), 'version': 'mock'}
        calls = []
        def command(argv, **kwargs):
            calls.append(argv)
            self.assertEqual(kwargs['cwd'], out)
            stream = kwargs['stdout']
            if failure == 'timeout' and Path(argv[0]).name == 'cc':
                raise subprocess.TimeoutExpired(argv, 180)
            if '-o' in argv:
                target = Path(argv[argv.index('-o') + 1])
                if not target.is_absolute():
                    target = out / target
                target.write_bytes(b'mock artifact')
            if Path(argv[0]).name == 'objcopy':
                (out / 'guest.bin').write_bytes(b'\0' * 384)
            if Path(argv[0]).name == 'nm':
                stream.write('\n'.join(f'{value:x} T {name}' for name, value in GuestAndResultTest.symbols.items()))
            if Path(argv[0]).name in ('off-run', 'on-run'):
                if len(argv) == 3:
                    mutation = argv[-1].removeprefix('--inject-')
                    stream.write(pmp.NEGATIVES[mutation] + '\n')
                    return subprocess.CompletedProcess(argv, 0 if failure == 'negative-accepted' else 1)
                stream.write(GuestAndResultTest.line + '\n')
            if failure == 'artifact-drift' and Path(argv[0]).name == 'host':
                (self.paths['off'].parent / 'model/BoardSocGsim0.o').write_text('changed after link')
            return subprocess.CompletedProcess(argv, 0)
        with mock.patch.object(pmp, 'inventory', return_value=self.inputs), \
             mock.patch.object(pmp.board, 'source_inventory', return_value=self.inputs), \
             mock.patch.object(pmp.common, 'compiler', return_value=(str(executable), 'test compiler')), \
             mock.patch.object(pmp.guests, 'toolchain', return_value=(tools, records)), \
             mock.patch.object(pmp.subprocess, 'run', side_effect=command), \
             contextlib.redirect_stdout(io.StringIO()):
            if failure:
                with self.assertRaises((RuntimeError, subprocess.TimeoutExpired)):
                    pmp.run(args)
            else:
                pmp.run(args)
        return json.loads((out / 'receipt.json').read_text()), calls

    def test_full_mock_run(self):
        state, calls = self.exercise()
        self.assertEqual(state['status'], pmp.STATUS)
        self.assertEqual(len(state['steps']), 14)
        self.assertEqual(len(state['negatives']), 6)
        self.assertEqual(set(state['artifacts']), {'guest.o', 'guest.elf', 'guest.bin', 'guest_symbols.h', 'off-run', 'on-run'})
        self.assertEqual(state['comparison'], {'retired': 108, 'pc_trace': 12345})
        self.assertEqual(len(calls), 14)
        self.assertEqual(state['model_request']['shared_options'],
                         {'dma_line_transfers': False, 'dma_line_entries': 1, 'dma_line_yield_cycles': 0})

    def test_cpp_driver_symlink_preserves_argv0(self):
        state, calls = self.exercise(symlink=True)
        driver = self.root / 'clang++-fixture'
        self.assertEqual(state['host_compiler']['path'], str(driver))
        self.assertEqual(state['host_compiler']['resolved_path'], str(self.root / 'host'))
        for side in ('off', 'on'):
            self.assertEqual(state['steps'][side + '-link']['command'][0], str(driver))

    def test_mock_timeout_records_failure(self):
        state, calls = self.exercise('timeout')
        self.assertEqual(state['status'], 'FAIL')
        self.assertIn('error', state['steps']['guest-compile'])
        self.assertIn('log_sha256', state['steps']['guest-compile'])
        self.assertEqual(len(calls), 1)

    def test_mock_corruption_negative_must_fail(self):
        state, _ = self.exercise('negative-accepted')
        self.assertEqual(state['status'], 'FAIL')
        self.assertEqual(state['steps']['off-negative-trap']['exit'], 0)
        self.assertEqual(state['negatives'], {})

    def test_mock_model_drift_during_run(self):
        state, _ = self.exercise('artifact-drift')
        self.assertEqual(state['status'], 'FAIL')
        self.assertIn('hash mismatch', state['error'])
        self.assertNotIn('off-test', state['steps'])


class GuestAndResultTest(unittest.TestCase):
    symbols = {'denied_s': 0x80200084, 'denied_mprv': 0x802000d0, 'supervisor_ecall': 0x802000b0,
               'done': 0x80200128, 'fail': 0x8020017c}
    line = ('DATA_PMP_BOARD_PASS cycles=1992 traps=3 denied_s=1 denied_mprv=1 '
            'allowed_reads=3 forbidden_physical=0 retired=108 pc_trace=12345')

    def test_symbol_header_matches_historical_shape(self):
        nm = '\n'.join(f'{value:x} T {name}' for name, value in self.symbols.items())
        self.assertEqual(pmp.parse_symbols('80200000 T _start\n' + nm), self.symbols)
        expected = ''.join(f'#define GUEST_{name.upper()} 0x{self.symbols[name]:x}ULL\n' for name in pmp.SYMBOLS)
        self.assertEqual(pmp.symbol_header(self.symbols), expected)

    def test_missing_symbol(self):
        with self.assertRaisesRegex(RuntimeError, 'missing or unexpected'):
            pmp.parse_symbols('80200084 T denied_s')

    def test_duplicate_symbol(self):
        with self.assertRaisesRegex(RuntimeError, 'duplicate'):
            pmp.parse_symbols('80200084 T denied_s\n80200084 T denied_s')

    def test_bad_symbol_address(self):
        for value in (0, 0x80204000, 0x80200085, True):
            with self.subTest(value=value), self.assertRaisesRegex(RuntimeError, 'outside aligned'):
                pmp.symbol_header({**self.symbols, 'denied_s': value})

    def test_aliased_symbols(self):
        with self.assertRaisesRegex(RuntimeError, 'aliased'):
            pmp.symbol_header({**self.symbols, 'denied_s': self.symbols['done']})

    def test_result_parse(self):
        self.assertEqual(pmp.parse_result('log\n' + self.line + '\n'), {'cycles': 1992, 'retired': 108, 'pc_trace': 12345})

    def test_result_fixed_witnesses(self):
        for before, after in [('traps=3', 'traps=2'), ('denied_s=1', 'denied_s=0'),
                              ('denied_mprv=1', 'denied_mprv=0'), ('forbidden_physical=0', 'forbidden_physical=1')]:
            with self.subTest(before=before), self.assertRaisesRegex(RuntimeError, 'malformed'):
                pmp.parse_result(self.line.replace(before, after))

    def test_result_duplicates_or_missing(self):
        for text in ('nothing', self.line + '\n' + self.line):
            with self.subTest(text=text), self.assertRaisesRegex(RuntimeError, 'missing or ambiguous'):
                pmp.parse_result(text)

    def test_result_bad_counters(self):
        for before, after in [('cycles=1992', 'cycles=0'), ('retired=108', 'retired=0'),
                              ('pc_trace=12345', 'pc_trace=' + str(2**64))]:
            with self.subTest(before=before), self.assertRaisesRegex(RuntimeError, 'invalid data-PMP counters'):
                pmp.parse_result(self.line.replace(before, after))

    def test_exact_retirement_comparison_allows_cycle_difference(self):
        off = pmp.parse_result(self.line)
        self.assertEqual(pmp.compare_results({'off': off, 'on': {**off, 'cycles': 1989}}),
                         {'retired': 108, 'pc_trace': 12345})
        for field in ('retired', 'pc_trace'):
            with self.subTest(field=field), self.assertRaisesRegex(RuntimeError, 'count/trace mismatch'):
                pmp.compare_results({'off': off, 'on': {**off, field: off[field] + 1}})


if __name__ == '__main__':
    unittest.main()
