#!/usr/bin/env python3
"""Source-only qualification/argument tests; no compiler, simulator or archives."""
import contextlib
import copy
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

import build_cpu_hot_bandwidth as guests
import cpu_bandwidth_flow_board as flow


class GuestQualificationTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='cpu-hot-fresh-test-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / 'repo'
        self.bundle = Path(temporary.name) / 'bundle'
        self.bundle.mkdir()
        self.manifest = self.bundle / 'manifest.json'
        self.state = {'schema': guests.SCHEMA, 'status': guests.STATUS, 'profile': copy.deepcopy(guests.PROFILE),
                      'builder_sha256': guests.sha(guests.__file__), 'sources': {}, 'cases': {},
                      'toolchain': {name: {'name': name, 'sha256': 'a' * 64, 'version': 'fixture'}
                                    for name in ('cc', 'objcopy', 'nm', 'as', 'ld', 'cc1')}}
        for name in guests.PAYLOADS:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('fixture ' + name)
            target = self.bundle / 'sources' / Path(name).name
            target.parent.mkdir(exist_ok=True)
            shutil.copyfile(path, target)
            self.state['sources'][name] = {'path': target.relative_to(self.bundle).as_posix(), 'sha256': guests.sha(path)}
        for case in guests.CASES:
            directory = self.bundle / case
            directory.mkdir()
            symbols = {name: 0x80200000 + i * 4 for i, name in enumerate(sorted(guests.SYMBOLS))}
            symbols['hot_image_end'] = 0x80200080
            (directory / 'guest.bin').write_bytes(b'\0' * 128)
            (directory / 'guest.elf').write_bytes(b'fixture ELF')
            (directory / 'guest.o').write_bytes(b'fixture object')
            (directory / 'cpu_hot_bandwidth_symbols.h').write_text(guests.header(symbols))
            op, size = case.split('-')
            self.state['cases'][case] = {'directory': case, 'configuration': {'op': op, 'bytes': int(size), 'repetitions': 4},
                                         'symbols': symbols, 'artifacts': {name: guests.sha(directory / name) for name in guests.ARTIFACTS}}

    def write(self):
        self.manifest.write_text(json.dumps(self.state))

    def reject(self, phrase):
        self.write()
        with self.assertRaisesRegex(RuntimeError, phrase):
            guests.load_manifest(self.manifest, self.root)

    def test_complete_portable_bundle(self):
        self.write()
        _, result = guests.load_manifest(self.manifest, self.root)
        self.assertEqual(set(result), set(guests.CASES))
        moved = self.bundle.with_name('moved')
        shutil.copytree(self.bundle, moved)
        _, result = guests.load_manifest(moved / 'manifest.json', self.root)
        self.assertEqual(result['read-4096']['directory'], moved / 'read-4096')

    def test_missing_case(self):
        del self.state['cases']['copy-8192']
        self.reject('case set')

    def test_wrong_repetitions(self):
        self.state['profile']['repetitions'] = 8
        self.reject('profile drift')

    def test_wrong_case_config(self):
        self.state['cases']['copy-8192']['configuration']['bytes'] = 4096
        self.reject('case config drift')

    def test_missing_guest(self):
        (self.bundle / 'read-4096/guest.bin').unlink()
        self.reject('missing read-4096/guest.bin')

    def test_guest_drift(self):
        (self.bundle / 'read-4096/guest.bin').write_bytes(b'bad')
        self.reject('hash mismatch')

    def test_current_source_drift(self):
        (self.root / guests.PAYLOADS[0]).write_text('changed')
        self.reject('current guest source')

    def test_bundled_source_drift(self):
        (self.bundle / self.state['sources'][guests.PAYLOADS[0]]['path']).write_text('changed')
        self.reject('bundled guest source')

    def test_builder_drift(self):
        self.state['builder_sha256'] = '0' * 64
        self.reject('guest builder source')

    def test_missing_toolchain_component(self):
        del self.state['toolchain']['as']
        self.reject('incomplete guest toolchain')

    def test_absolute_directory_rejected(self):
        self.state['cases']['read-4096']['directory'] = str(self.bundle / 'read-4096')
        self.reject('nonportable manifest path')

    def test_escape_directory_rejected(self):
        self.state['cases']['read-4096']['directory'] = '../bundle/read-4096'
        self.reject('nonportable manifest path')

    def test_symbol_drift(self):
        self.state['cases']['read-4096']['symbols']['hot_begin'] += 4
        self.reject('symbol/header mismatch')

    def test_missing_artifact_hash(self):
        del self.state['cases']['read-4096']['artifacts']['guest.elf']
        self.reject('artifact inventory drift')

    def historical(self, recovered):
        self.state = {'schema': 'valence-cpu-hot-bandwidth-' + ('recovery' if recovered else 'reuse') + '-v1',
                      'status': 'PASS_CPU_HOT_BANDWIDTH_' + ('RECOVERY' if recovered else 'REUSE'),
                      'geometry': {'store_buffer_entries': 2, 'lsu_slots': 2},
                      'inputs': {name: record['sha256'] for name, record in self.state['sources'].items()},
                      'cases': {case: {'result': {'op': case.split('-')[0], 'buffer_bytes': int(case.split('-')[1]), 'reps': 4},
                                       'artifacts': record['artifacts'], 'symbols': record['symbols']}
                                for case, record in self.state['cases'].items()}}
        if recovered:
            self.state['case_provenance'] = {case: {'directory': str(self.bundle / case)} for case in guests.CASES}
        self.write()

    def test_original_receipt_compatibility(self):
        self.historical(False)
        _, result = flow.normalize_guests(self.manifest, self.root)
        self.assertEqual(set(result), set(guests.CASES))

    def test_recovery_receipt_compatibility(self):
        self.historical(True)
        _, result = flow.normalize_guests(self.manifest, self.root)
        self.assertEqual(set(result), set(guests.CASES))

    def test_historical_missing_source_hash(self):
        self.historical(True)
        self.state['inputs'] = {}
        self.write()
        with self.assertRaisesRegex(RuntimeError, 'historical guest source hash'):
            flow.normalize_guests(self.manifest, self.root)

    def test_historical_wrong_case_repetitions(self):
        self.historical(True)
        self.state['cases']['read-4096']['result']['reps'] = 8
        self.write()
        with self.assertRaisesRegex(RuntimeError, 'case config drift'):
            flow.normalize_guests(self.manifest, self.root)


class ModelQualificationTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='cpu-model-test-')
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.receipt = self.directory / 'receipt.json'
        self.inputs = {'src/fixture.scala': 'a' * 64}
        self.state = {'schema': 'valence-fpga-next-board-evidence-v1', 'status': 'PASS_FPGA_NEXT_BOARD_SMOKE',
                      'inputs': self.inputs.copy(), 'plan': flow.expected_model_plan(0),
                      'toolchain': {**flow.common.LOCK, 'compiler': 'fixture compiler'}, 'artifacts': {}}
        (self.directory / 'model').mkdir()
        for name in ('BoardSocGsim.h', 'BoardSocGsim.fir', 'BoardSocGsim0.cpp', 'BoardSocGsim0.o'):
            path = self.directory / 'model' / name
            path.write_text('fixture ' + name)
            self.state['artifacts']['model/' + name] = guests.sha(path)

    def validate(self):
        self.receipt.write_text(json.dumps(self.state))
        return flow.validate_model(self.receipt, 0, self.inputs, 'fixture compiler')

    def test_exact_checkpoint(self):
        _, _, objects = self.validate()
        self.assertEqual(len(objects), 1)

    def test_missing_model_receipt(self):
        with self.assertRaisesRegex(RuntimeError, 'missing explicitly reusable model'):
            flow.validate_model(self.receipt, 0, self.inputs, 'fixture compiler')

    def test_source_drift(self):
        self.state['inputs']['src/fixture.scala'] = 'b' * 64
        with self.assertRaisesRegex(RuntimeError, 'source inventory drift'):
            self.validate()

    def test_extra_profile_flag(self):
        self.state['plan']['parameters'].append('--prechecked-data-flow')
        with self.assertRaisesRegex(RuntimeError, 'profile drift'):
            self.validate()

    def test_wrong_flow_flag(self):
        self.state['plan'] = flow.expected_model_plan(1)
        with self.assertRaisesRegex(RuntimeError, 'profile drift'):
            self.validate()

    def test_toolchain_drift(self):
        self.state['toolchain']['revision'] = '0' * 40
        with self.assertRaisesRegex(RuntimeError, 'toolchain/profile drift'):
            self.validate()

    def test_missing_object(self):
        (self.directory / 'model/BoardSocGsim0.o').unlink()
        with self.assertRaisesRegex(RuntimeError, 'object set'):
            self.validate()

    def test_unhashed_object(self):
        del self.state['artifacts']['model/BoardSocGsim0.o']
        with self.assertRaisesRegex(RuntimeError, 'unhashed model artifact'):
            self.validate()

    def test_object_drift(self):
        (self.directory / 'model/BoardSocGsim0.o').write_text('changed')
        with self.assertRaisesRegex(RuntimeError, 'hash mismatch'):
            self.validate()

    def test_unfinished_model(self):
        self.state['status'] = 'RUNNING'
        with self.assertRaisesRegex(RuntimeError, 'completed board smoke'):
            self.validate()

    def test_explicit_combined_checkpoint(self):
        options = dict(dma_line_transfers=True, dma_line_entries=4, dma_line_yield_cycles=0)
        self.state['plan'] = flow.expected_model_plan(0, **options)
        self.receipt.write_text(json.dumps(self.state))
        flow.validate_model(self.receipt, 0, self.inputs, 'fixture compiler', **options)
        with self.assertRaisesRegex(RuntimeError, 'profile drift'):
            flow.validate_model(self.receipt, 0, self.inputs, 'fixture compiler')
        with self.assertRaisesRegex(RuntimeError, 'profile drift'):
            flow.validate_model(self.receipt, 0, self.inputs, 'fixture compiler',
                                dma_line_transfers=True, dma_line_entries=2)

    def test_invalid_shared_dma_profile(self):
        for options in (dict(dma_line_entries=4), dict(dma_line_yield_cycles=4),
                        dict(dma_line_transfers=True, dma_line_entries=3)):
            with self.assertRaises(RuntimeError):
                flow.expected_model_plan(0, **options)


class ArgumentTest(unittest.TestCase):
    def test_fresh_is_default(self):
        args = flow.arguments(['--tag', 'fresh'])
        self.assertIsNone(args.hot_receipt)
        self.assertIsNone(args.guest_manifest)
        self.assertIsNone(args.model_tag)
        self.assertFalse(args.resume)

    def test_explicit_fresh(self):
        self.assertTrue(flow.arguments(['--tag', 'fresh', '--fresh-guests']).fresh_guests)

    def test_explicit_reuse(self):
        args = flow.arguments(['--tag', 'run', '--guest-manifest', 'guests/manifest.json', '--model-tag', 'model'])
        self.assertEqual(args.model_tag, 'model')

    def test_conflicting_guest_options(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            flow.arguments(['--tag', 'run', '--fresh-guests', '--hot-receipt', 'old.json'])

    def test_unsafe_tag(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            flow.arguments(['--tag', '../old'])

    def test_missing_guest_manifest(self):
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(RuntimeError, 'missing guest'):
            flow.normalize_guests(Path(directory) / 'missing.json')

    def test_builder_will_not_overwrite(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(guests, 'toolchain') as toolchain:
            with self.assertRaisesRegex(RuntimeError, 'fresh guest output'):
                guests.build(Path(directory))
            toolchain.assert_not_called()


if __name__ == '__main__':
    unittest.main()
