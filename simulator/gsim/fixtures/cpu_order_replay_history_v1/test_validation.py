#!/usr/bin/env python3
"""Small independent synthetic checkpoint/source negatives; no compiler or GSIM."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import strict_validation as v


class ModelValidation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=HERE, prefix='.test-model-')
        self.root = Path(self.temp.name)
        (self.root / 'model').mkdir()
        self.inputs = {'src/main/example.scala': 'source hash'}
        self.lock = {'gsim': 'qualified-version'}
        self.receipt = self.root / 'receipt.json'
        self.state = {
            'schema': 'valence-fpga-next-board-evidence-v1',
            'status': 'PASS_FPGA_NEXT_BOARD_SMOKE', 'inputs': self.inputs.copy(),
            'plan': v.expected_plan(False), 'toolchain': {**self.lock, 'compiler': 'test-compiler'},
            'artifacts': {},
        }
        for name in ('BoardSocGsim.h', 'BoardSocGsim.fir', 'BoardSocGsim0.cpp', 'BoardSocGsim0.o'):
            self.add_file('model/' + name)
        self.add_file('gc')

    def tearDown(self):
        self.temp.cleanup()

    def add_file(self, name, declared=True):
        path = self.root / name
        path.write_text('synthetic check data for ' + name + '\n')
        if declared:
            self.state['artifacts'][name] = v.sha(path)

    def validate(self, older_prefix=False):
        self.receipt.write_text(json.dumps(self.state))
        return v.validate_model(self.receipt, self.inputs, 'test-compiler', self.lock,
                                older_prefix=older_prefix)

    def rejected(self, reason):
        with self.assertRaisesRegex(RuntimeError, reason):
            self.validate()

    def test_positive_both_profiles(self):
        self.validate()
        self.state['plan'] = v.expected_plan(True)
        self.validate(True)

    def test_strict_boolean_options(self):
        for value in (0, 1, 'true', None):
            with self.subTest(value=value), self.assertRaisesRegex(RuntimeError, 'Boolean'):
                v.expected_plan(value)

    def test_profile_negatives(self):
        plan = copy.deepcopy(self.state['plan'])
        for key, value in [('fetch_previous_packet', False), ('fetch_previous_packet', 1),
                           ('fetch_previous_packet', 'true'), ('smoke_only', False),
                           ('smoke_only', 1), ('passive_probes', False), ('passive_probes', 1),
                           ('guest_suite', ['rv64gc', 'extra'])]:
            with self.subTest(key=key, value=value):
                self.state['plan'] = {**plan, key: value}
                self.rejected('model profile drift')
        for flag in plan['parameters']:
            with self.subTest(missing_flag=flag):
                self.state['plan'] = {**plan, 'parameters': [x for x in plan['parameters'] if x != flag]}
                self.rejected('model profile drift')
        for flag in ['--load-order-older-retire', '--virtual-load-precheck', '--prechecked-load-flow',
                     '--dma-line-yield-cycles=4', '--lsu-entries=2']:
            with self.subTest(extra_flag=flag):
                self.state['plan'] = {**plan, 'parameters': [*plan['parameters'], flag]}
                self.rejected('model profile drift')
        self.state['plan'] = {**plan, 'unknown': True}
        self.rejected('model profile drift')

    def test_source_negatives(self):
        for inputs in ({}, {**self.inputs, 'unexpected': 'hash'}, {'src/main/example.scala': 'changed'}):
            with self.subTest(inputs=inputs):
                self.state['inputs'] = inputs
                self.rejected('source inventory drift')

    def test_status_and_toolchain_negatives(self):
        for status in ('RUNNING', 'FAIL', 'PASS'):
            self.state['status'] = status
            self.rejected('completed board smoke')
        self.state['status'] = 'PASS_FPGA_NEXT_BOARD_SMOKE'
        self.state['toolchain']['compiler'] = 'another-compiler'
        self.rejected('toolchain/profile drift')

    def test_missing_receipt_artifact(self):
        for name in list(self.state['artifacts']):
            if name.startswith('model/'):
                with self.subTest(name=name):
                    digest = self.state['artifacts'].pop(name)
                    self.rejected('complete model file set')
                    self.state['artifacts'][name] = digest

    def test_missing_files(self):
        for name in list(self.state['artifacts']):
            path = self.root / name
            old = path.read_bytes()
            path.unlink()
            with self.subTest(name=name), self.assertRaises(RuntimeError):
                self.validate()
            path.write_bytes(old)

    def test_content_mutations(self):
        for name in list(self.state['artifacts']):
            path = self.root / name
            old = path.read_bytes()
            path.write_bytes(old + b'changed')
            with self.subTest(name=name):
                self.rejected('artifact content drift')
            path.write_bytes(old)

    def test_extra_model_files_including_nonglob_names(self):
        for name in ('junk.o', 'junk.cpp', 'BoardSocGsim1.o', 'BoardSocGsim1.cpp',
                     'BoardSocGsim0-extra.cpp', 'extra.txt'):
            with self.subTest(name=name):
                self.add_file('model/' + name, declared=False)
                self.rejected('complete model file set')
                (self.root / 'model' / name).unlink()

    def test_declared_extra_model_file(self):
        self.add_file('model/junk.o')
        self.rejected('complete model file set')

    def test_noncanonical_or_nested_units(self):
        self.add_file('model/BoardSocGsim01.cpp')
        self.add_file('model/BoardSocGsim01.o')
        self.rejected('noncanonical model translation unit set')

    def test_nested_directory(self):
        (self.root / 'model' / 'nested').mkdir()
        self.rejected('nonregular model entry')

    def test_model_symlink(self):
        path = self.root / 'model' / 'BoardSocGsim0.o'
        path.unlink()
        path.symlink_to(self.root / 'gc')
        self.rejected('nonregular model entry')

    def test_artifact_escape(self):
        self.state['artifacts']['../outside'] = '0' * 64
        self.rejected('noncanonical artifact path')


class ProductionValidation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=HERE, prefix='.test-source-')
        self.repo = Path(self.temp.name)
        self.source = self.repo / 'src/main/example.scala'
        self.resource = self.repo / 'src/main/resources/example.bin'
        self.resource.parent.mkdir(parents=True)
        self.source.write_text('original source\n')
        self.resource.write_bytes(b'original resource\n')
        self.git('init', '-q')
        self.git('add', 'src/main')
        self.git('-c', 'user.name=Fixture Test', '-c', 'user.email=fixture@example.invalid',
                 'commit', '-qm', 'Source fixture')
        self.anchor = self.git('rev-parse', 'HEAD')

    def tearDown(self):
        self.temp.cleanup()

    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.repo, text=True,
                                       stderr=subprocess.DEVNULL).strip()

    def validate(self):
        return v.production_anchor(self.repo, self.anchor, self.anchor)

    def test_source_and_host_only_positive(self):
        self.validate()
        (self.repo / 'README.md').write_text('host-only commit\n')
        self.git('add', 'README.md')
        self.git('-c', 'user.name=Fixture Test', '-c', 'user.email=fixture@example.invalid',
                 'commit', '-qm', 'Host-only fixture')
        self.validate()

    def test_tracked_source_and_resource_mutations(self):
        for path in (self.source, self.resource):
            old = path.read_bytes()
            path.write_bytes(old + b'mutation')
            with self.subTest(path=path), self.assertRaisesRegex(RuntimeError, 'worktree content drift'):
                self.validate()
            path.write_bytes(old)

    def test_untracked_source_and_resource(self):
        for name in ('new.scala', 'resources/new.bin'):
            path = self.repo / 'src/main' / name
            path.write_text('new')
            with self.subTest(name=name), self.assertRaisesRegex(RuntimeError, 'file inventory drift'):
                self.validate()
            path.unlink()

    def test_committed_source_mutation(self):
        self.source.write_text('new source')
        self.git('add', 'src/main')
        self.git('-c', 'user.name=Fixture Test', '-c', 'user.email=fixture@example.invalid',
                 'commit', '-qm', 'Modified source')
        with self.assertRaisesRegex(RuntimeError, 'production source tree drift'):
            self.validate()

    def test_broken_symlink(self):
        (self.repo / 'src/main/broken').symlink_to('missing')
        with self.assertRaisesRegex(RuntimeError, 'symlink inventory drift'):
            self.validate()


if __name__ == '__main__':
    unittest.main(verbosity=2)
