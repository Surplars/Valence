#!/usr/bin/env python3
"""Synthetic receipt/counter tests only. No compiler, model or simulator execution."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import types
import unittest
from unittest import mock

import cpu_flow_board_nemu as replay
import verify_cpu_flow_board_nemu as verifier

REAL_ROOT = Path(os.environ.get('VALENCE_TEST_ROOT', str(replay.HERE.parents[1]))).resolve()
sys.path.insert(0, str(REAL_ROOT / 'simulator/gsim'))
import cpu_bandwidth_flow_board as flow


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n' if isinstance(value, dict) else value)
    return path


def positive(hot):
    return hot + '\nHOT_PASS total_cycles=10\n' + (
        'NEMU_PASS guest_pc_checks=12 boot_pc_checks=5 guest_retire_edges=8 dual_retire_edges=4 '
        'guest_gpr_edges=8 boot_gpr_edges=4 gpr_value_checks=384 final_memory_bytes=4194368 '
        'guest_pc_trace=123 reference_resynchronizations=0 gpr_boundary=post_entire_retire_edge '
        'independent_lane_intermediate_gpr=0 speculative_requests_stepped=0\n')


class ReceiptFixture(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='nemu-portability-test-')
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.root = self.base / 'repo'
        self.bundle = self.base / 'checker'
        self.cache = self.base / 'reference'
        self.out = self.root / 'build/gsim/fresh-hot'
        self.receipt = self.out / 'receipt.json'
        self.sources = {name: replay.sha(write(self.root / name, 'fixture source ' + name))
                        for name in (*flow.guests.PAYLOADS, 'simulator/gsim/harness/cpu_flow_bandwidth.cpp')}
        self.fake_flow = types.SimpleNamespace(
            common=types.SimpleNamespace(ROOT=self.root), guests=flow.guests,
            board=types.SimpleNamespace(source_inventory=lambda: dict(self.sources)),
            inventory=lambda: dict(self.sources), validate_model=flow.validate_model, parse=flow.parse)
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(replay, 'BUNDLE', self.bundle).start()
        mock.patch.object(replay.importlib, 'import_module', return_value=self.fake_flow).start()
        self.make_guest()
        target = write(self.base / 'bin/clang-19', 'fixture compiler bytes')
        self.cxx = self.base / 'bin/clang++-19'
        self.cxx.symlink_to(target)
        self.cxx.chmod(0o755)
        self.state = {'schema': 'valence-cpu-physical-flow-board-v2', 'status': 'PASS_SOURCE_MATCHED_CPU_FLOW_BOARD',
                      'inputs': dict(self.sources), 'guest_input': {'kind': 'fresh_source_build', 'path': str(self.manifest), 'sha256': replay.sha(self.manifest)},
                      'model_request': {'reuse_tag': 'fixture', 'shared_options': dict(replay.SHARED)},
                      'host_compiler': {'path': str(target), 'sha256': replay.sha(target)}, 'compiler': 'fixture compiler',
                      'models': {}, 'cases': {}, 'steps': {}}
        self.make_models()
        self.make_reference()
        self.save()

    def make_guest(self):
        directory = self.out / 'guests'
        self.manifest = directory / 'manifest.json'
        self.guest = {'schema': flow.guests.SCHEMA, 'status': flow.guests.STATUS,
                      'profile': copy.deepcopy(flow.guests.PROFILE), 'builder_sha256': replay.sha(flow.guests.__file__),
                      'sources': {}, 'cases': {}, 'commands': [],
                      'toolchain': {name: {'name': name, 'sha256': 'a' * 64, 'version': 'fixture'}
                                    for name in ('cc', 'objcopy', 'nm', 'as', 'ld', 'cc1')}}
        for name in flow.guests.PAYLOADS:
            relative = 'sources/' + Path(name).name
            write(directory / relative, (self.root / name).read_text())
            self.guest['sources'][name] = {'path': relative, 'sha256': self.sources[name]}
        for case in replay.CASES:
            symbols = {name: 0x80200000 + i * 4 for i, name in enumerate(sorted(flow.guests.SYMBOLS))}
            symbols['hot_image_end'] = 0x80200080
            write(directory / case / 'guest.bin', '0' * 128)
            write(directory / case / 'guest.elf', 'fixture ELF')
            write(directory / case / 'guest.o', 'fixture object')
            write(directory / case / 'cpu_hot_bandwidth_symbols.h', flow.guests.header(symbols))
            op, size = case.split('-')
            self.guest['cases'][case] = {'directory': case, 'configuration': {'op': op, 'bytes': int(size), 'repetitions': 4},
                'symbols': symbols, 'artifacts': {name: replay.sha(directory / case / name) for name in flow.guests.ARTIFACTS}}
            for step in ('assemble', 'link', 'binary', 'symbols'):
                log = write(directory / case / (step + '.log'), 'fixture log')
                self.guest['commands'].append({'exit': 0, 'log': str(log.relative_to(directory)), 'log_sha256': replay.sha(log)})
        write(self.manifest, self.guest)

    def record(self, name, command, text='', exit=0, artifacts=None):
        log = write(self.out / (name + '.log'), text)
        return {'command': list(map(str, command)), 'exit': exit, 'log': log.name, 'log_sha256': replay.sha(log),
                'artifacts': artifacts or {}}

    def make_models(self):
        for label in replay.LABELS:
            folder = self.root / 'build/gsim' / ('model-' + label)
            model = folder / 'model'
            paths = [write(model / name, 'fixture ' + label + ' ' + name)
                     for name in ('BoardSocGsim.h', 'BoardSocGsim.fir', 'BoardSocGsim0.cpp', 'BoardSocGsim0.o')]
            mr = folder / 'receipt.json'
            model_state = {'schema': 'valence-fpga-next-board-evidence-v1', 'status': 'PASS_FPGA_NEXT_BOARD_SMOKE',
                           'inputs': dict(self.sources), 'plan': flow.expected_model_plan(int(label == 'on'), **replay.SHARED),
                           'toolchain': {**flow.common.LOCK, 'compiler': 'fixture compiler'}, 'steps': {},
                           'artifacts': {str(p.relative_to(folder)): replay.sha(p) for p in paths}}
            write(mr, model_state)
            self.state['models'][label] = {'receipt': str(mr), 'receipt_sha256': replay.sha(mr), 'inputs': dict(self.sources),
                                          'plan': model_state['plan'], 'origin': 'explicit_reuse'}
            self.state['cases'][label] = {}
            for case in replay.CASES:
                directory = self.manifest.parent / case
                binary = write(self.out / label / case / 'run', 'fixture hot executable')
                key = label + '-' + case
                command = [self.cxx, *replay.flags(label, case, model, directory),
                           self.root / 'simulator/gsim/harness/cpu_flow_bandwidth.cpp', model / 'BoardSocGsim0.o', '-ldl', '-o', binary]
                self.state['steps'][key + '-link'] = self.record(key + '-link', command, artifacts={str(binary): replay.sha(binary)})
                op, size = case.split('-')
                text = f'HOT_RESULT op={op} buffer_bytes={size} reps=4 kernel_cycles=10\nHOT_PASS total_cycles=10\n'
                self.state['steps'][key + '-run'] = self.record(key + '-run', [binary, directory / 'guest.bin'], text)
                self.state['cases'][label][case] = {**flow.parse(text), 'binary_sha256': replay.sha(binary), 'guest_sha256': replay.sha(directory / 'guest.bin')}
            for mode, anchor in replay.FLOW_NEGATIVES.items():
                name = label + '-negative-' + mode
                self.state['steps'][name] = self.record(name, [self.out / label / 'read-4096/run', self.manifest.parent / 'read-4096/guest.bin', '--inject-' + mode], anchor, exit=1)

    def make_reference(self):
        lock = {'repository': 'fixture', 'revision': 'a' * 40, 'resources': {'fixture.h': replay.sha(write(self.cache / 'nemu-src/resource/fixture.h', 'resource'))}}
        write(self.root / 'simulator/gsim/config/reference-lock.json', lock)
        config = write(self.root / 'simulator/gsim/config/rv64-integer-ref_defconfig', 'config')
        resolved = write(self.cache / 'nemu-src/.config', 'resolved config')
        library = write(self.cache / 'nemu-src/build/riscv64-nemu-interpreter-so', 'library')
        write(self.cache / 'nemu-src/src/example.c', 'source')
        used = {**lock, 'config_sha256': replay.sha(config), 'resolved_config_sha256': replay.sha(resolved), 'library_sha256': replay.sha(library)}
        write(self.cache / 'reference-used.json', used)
        files = {str(p.relative_to(self.cache)): replay.sha(p) for p in self.cache.rglob('*') if p.is_file()}
        write(self.bundle / 'reference_cache_manifest.json', {'schema': 'valence-board-hot-nemu-reference-cache-v1', 'files': files})
        checker_files = {name: replay.sha(write(self.bundle / name, 'fixture checker ' + name))
                         for name in ('reference.h', 'board_nemu_observer.h', 'cpu_flow_bandwidth.cpp')}
        write(self.bundle / 'checker_provenance.json', {'schema': 'valence-board-hot-nemu-checker-provenance-v1',
              'checker_files': checker_files, 'historical_checker_files': checker_files,
              'production_origins': {'cpu_flow_bandwidth.cpp': self.sources['simulator/gsim/harness/cpu_flow_bandwidth.cpp']}})

    def save(self):
        write(self.receipt, self.state)

    def inputs(self, **kwargs):
        self.save()
        return replay.Inputs(self.root, self.receipt, self.cache, **kwargs)

    def reject(self, regex):
        with self.assertRaisesRegex(RuntimeError, regex):
            self.inputs()

    def model_change(self, label, fn):
        path = Path(self.state['models'][label]['receipt'])
        state = replay.load(path)
        fn(state)
        write(path, state)
        self.state['models'][label]['receipt_sha256'] = replay.sha(path)

    def test_complete_preflight_no_subprocess(self):
        with mock.patch.object(replay.subprocess, 'run', side_effect=AssertionError('execution forbidden')):
            inputs = self.inputs()
            inputs.guard()
        self.assertEqual(inputs.cxx, self.cxx)
        self.assertNotEqual(inputs.cxx, inputs.cxx.resolve())
        self.assertEqual(inputs.command('off', 'read-4096', self.base / 'out')[0], str(self.cxx))

    def test_no_historical_schema(self):
        self.state['schema'] = 'valence-cpu-physical-flow-board-v1'
        self.reject('fresh completed')

    def test_no_partial_flow(self):
        self.state['status'] = 'RUNNING'
        self.reject('fresh completed')

    def test_source_drift(self):
        self.state['inputs'] = {}
        self.reject('source inventory')

    def test_no_historical_guests(self):
        self.state['guest_input']['kind'] = 'historical_guest_receipt'
        self.reject('fresh guest')

    def test_guest_manifest_hash(self):
        self.state['guest_input']['sha256'] = '0' * 64
        self.reject('input hash')

    def test_guest_binary_hash(self):
        write(self.manifest.parent / 'read-4096/guest.bin', 'corrupt')
        self.reject('hash mismatch')

    def test_wrong_dma_depth(self):
        self.state['model_request']['shared_options']['dma_line_entries'] = 2
        self.reject('depth4/yield0')

    def test_wrong_dma_yield(self):
        self.state['model_request']['shared_options']['dma_line_yield_cycles'] = 4
        self.reject('depth4/yield0')

    def test_model_reuse_required(self):
        self.state['models']['off']['origin'] = 'built_for_this_run'
        self.reject('explicitly reused')

    def test_model_hash(self):
        self.state['models']['off']['receipt_sha256'] = '0' * 64
        self.reject('input hash')

    def test_model_partial(self):
        self.model_change('off', lambda s: s.update(status='RUNNING'))
        self.reject('completed board smoke')

    def test_model_config(self):
        self.model_change('off', lambda s: s['plan']['parameters'].append('--physical-load-ingress-flow'))
        self.reject('profile drift')

    def test_model_object_hash(self):
        write(self.root / 'build/gsim/model-off/model/BoardSocGsim0.o', 'corrupt')
        self.reject('hash mismatch')

    def test_model_object_inventory(self):
        write(self.root / 'build/gsim/model-off/model/BoardSocGsim1.o', 'extra')
        self.reject('object set')

    def test_hot_flags(self):
        self.state['steps']['off-read-4096-link']['command'][2] = '-O3'
        self.reject('configuration drift')

    def test_hot_original_log_hash(self):
        write(self.out / 'off-read-4096-run.log', 'corrupt')
        self.reject('input hash')

    def test_hot_guest_binding(self):
        self.state['cases']['off']['read-4096']['guest_sha256'] = '0' * 64
        self.reject('guest binding')

    def test_hot_result_binding(self):
        self.state['cases']['off']['read-4096']['result']['kernel_cycles'] = 11
        self.reject('receipt/log drift')

    def test_missing_hot_negative(self):
        del self.state['steps']['on-negative-route']
        with self.assertRaises((RuntimeError, KeyError)):
            self.inputs()

    def test_reference_library_hash(self):
        write(self.cache / 'nemu-src/build/riscv64-nemu-interpreter-so', 'corrupt')
        self.reject('input hash')

    def test_reference_config_hash(self):
        write(self.cache / 'nemu-src/.config', 'corrupt')
        self.reject('input hash')

    def test_reference_source_hash(self):
        write(self.cache / 'nemu-src/src/example.c', 'corrupt')
        self.reject('input hash')

    def test_reference_extra_source(self):
        write(self.cache / 'nemu-src/src/extra.c', 'extra')
        self.reject('inventory drift')

    def test_checker_hash(self):
        write(self.bundle / 'board_nemu_observer.h', 'corrupt')
        self.reject('input hash')

    def test_guard_extra_reference(self):
        inputs = self.inputs()
        write(self.cache / 'nemu-src/src/extra.c', 'extra')
        with self.assertRaisesRegex(RuntimeError, 'inventory changed'):
            inputs.guard()

    def test_compiler_hash(self):
        write(self.cxx.resolve(), 'corrupt')
        self.reject('input hash')

    def test_compiler_override_retains_driver(self):
        driver = self.base / 'elsewhere/clang++'
        driver.parent.mkdir()
        driver.symlink_to(self.cxx.resolve())
        inputs = self.inputs(compiler=driver)
        self.assertEqual(inputs.command('on', 'read-4096', self.base / 'out')[0], str(driver))

    def test_driver_symlink_retarget_rejected(self):
        inputs = self.inputs()
        other = write(self.base / 'bin/clang-other', 'other compiler')
        self.cxx.unlink()
        self.cxx.symlink_to(other)
        with self.assertRaisesRegex(RuntimeError, 'driver target changed'):
            inputs.guard()

    def test_hot_negative_command_binding(self):
        self.state['steps']['off-negative-route']['command'][-1] = '--inject-wrong'
        self.reject('negative input binding')

    def test_recorded_source_root_relocation(self):
        old_root = '/different/workspace/Valence'
        # Rebase only recorded receipt strings. Keep all actual input files here.
        self.state = json.loads(json.dumps(self.state).replace(str(self.root), old_root))
        for label in replay.LABELS:
            path = self.root / 'build/gsim' / ('model-' + label) / 'receipt.json'
            self.state['models'][label]['receipt_sha256'] = replay.sha(path)
        inputs = self.inputs(recorded_root=old_root)
        self.assertEqual(inputs.cases['read-4096']['directory'], self.manifest.parent / 'read-4096')
        self.assertEqual(inputs.models['off']['model'], self.root / 'build/gsim/model-off/model')

    def simulated_run(self, variant=None, case=None):
        inputs = self.inputs()
        out = self.base / 'replay'
        def fake_run(command, *, stdout, **kwargs):
            if '-o' in command:
                write(Path(command[command.index('-o') + 1]), 'synthetic replay executable')
                return types.SimpleNamespace(returncode=0)
            injection = next((x for x in command if x.startswith('--inject-nemu-')), None)
            if injection:
                stdout.write(replay.NEGATIVES[injection.removeprefix('--inject-nemu-')])
                return types.SimpleNamespace(returncode=1)
            binary = Path(command[0])
            key = binary.parent.parent.name + '-' + binary.parent.name
            stdout.write(positive(inputs.original_results[key]))
            return types.SimpleNamespace(returncode=0)
        with mock.patch.object(replay.subprocess, 'run', side_effect=fake_run), contextlib.redirect_stdout(io.StringIO()):
            replay.run(inputs, out, variant=variant, case=case)
        return inputs, out

    def test_serial_replay_receipt_and_full_audit_synthetic(self):
        inputs, out = self.simulated_run()
        summary = verifier.audit(out / 'receipt.json', inputs)
        self.assertEqual(len(summary['cases']), 12)
        self.assertEqual(len(summary['negatives']), 6)
        self.assertEqual(summary['scope']['dma'], 'CONFIGURED BUT IDLE')
        self.assertFalse(summary['scope']['concurrent_dma_nemu_claim'])
        with mock.patch.object(replay.subprocess, 'run', side_effect=AssertionError('resume executed')), contextlib.redirect_stdout(io.StringIO()):
            replay.run(inputs, out, resume=True)
        verifier.audit(out / 'receipt.json', inputs)

    def test_partial_not_full_audit(self):
        inputs, out = self.simulated_run(variant='off', case='read-4096')
        self.assertEqual(replay.load(out / 'receipt.json')['status'], 'PARTIAL_PASS')
        with self.assertRaisesRegex(RuntimeError, 'completed integrated'):
            verifier.audit(out / 'receipt.json', inputs)

    def test_audit_missing_negative(self):
        inputs, out = self.simulated_run()
        state = replay.load(out / 'receipt.json')
        del state['negatives']['on-negative-nemu-pc']
        write(out / 'receipt.json', state)
        with self.assertRaisesRegex(RuntimeError, 'negative set'):
            verifier.audit(out / 'receipt.json', inputs)

    def test_audit_counter_binding(self):
        inputs, out = self.simulated_run()
        state = replay.load(out / 'receipt.json')
        state['cases']['off-read-4096']['nemu']['gpr_value_checks'] = '385'
        write(out / 'receipt.json', state)
        with self.assertRaisesRegex(RuntimeError, 'counter mismatch'):
            verifier.audit(out / 'receipt.json', inputs)

    def test_audit_command_binding(self):
        inputs, out = self.simulated_run()
        state = replay.load(out / 'receipt.json')
        state['steps']['off-read-4096-run']['command'][-1] = '/wrong/library'
        write(out / 'receipt.json', state)
        with self.assertRaisesRegex(RuntimeError, 'command binding'):
            verifier.audit(out / 'receipt.json', inputs)

    def test_audit_binary_hash(self):
        inputs, out = self.simulated_run()
        write(out / 'off/read-4096/run', 'corrupt')
        with self.assertRaisesRegex(RuntimeError, 'binary hash'):
            verifier.audit(out / 'receipt.json', inputs)

    def test_audit_negative_rejection(self):
        inputs, out = self.simulated_run()
        state = replay.load(out / 'receipt.json')
        record = state['steps']['off-negative-nemu-pc']
        log = write(out / record['log'], 'NEMU PC mismatch\nNEMU_PASS bogus=1\n')
        record['log_sha256'] = replay.sha(log)
        write(out / 'receipt.json', state)
        with self.assertRaisesRegex(RuntimeError, 'did not reject'):
            verifier.audit(out / 'receipt.json', inputs)


class Counters(unittest.TestCase):
    def test_valid(self):
        replay.nemu_counters(positive('HOT_RESULT test=1'))

    def test_fail_closed_mutations(self):
        mutations = [
            ('reference_resynchronizations=0', 'reference_resynchronizations=1'),
            ('speculative_requests_stepped=0', 'speculative_requests_stepped=1'),
            ('gpr_boundary=post_entire_retire_edge', 'gpr_boundary=per_lane'),
            ('gpr_value_checks=384', 'gpr_value_checks=383'),
            ('guest_gpr_edges=8', 'guest_gpr_edges=7'),
            ('guest_pc_checks=12', 'guest_pc_checks=11'),
            ('boot_pc_checks=5', 'boot_pc_checks=4'),
            ('final_memory_bytes=4194368', 'final_memory_bytes=4096'),
            ('independent_lane_intermediate_gpr=0', 'independent_lane_intermediate_gpr=1'),
            ('dual_retire_edges=4', 'dual_retire_edges=-1'),
        ]
        for old, new in mutations:
            with self.subTest(mutation=new), self.assertRaises(RuntimeError):
                replay.nemu_counters(positive('HOT_RESULT test=1').replace(old, new))

    def test_duplicate_pass(self):
        with self.assertRaisesRegex(RuntimeError, 'duplicate'):
            replay.nemu_counters(positive('HOT_RESULT test=1') + 'NEMU_PASS fake=1\n')

    def test_default_is_read_only(self):
        args = replay.arguments(['--flow-receipt', 'x', '--reference-cache', 'y'])
        self.assertFalse(args.run)


if __name__ == '__main__':
    unittest.main()
