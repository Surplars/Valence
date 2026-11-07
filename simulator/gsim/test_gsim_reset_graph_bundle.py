"""Read-only real-profile and copied-input failure tests; never execute tools.

Set VALENCE_RESET_GRAPH_TEST_BUNDLE and VALENCE_RESET_GRAPH_TEST_REPO to run
integration cases, after activating the pinned bundle's environment.
"""
import json
import os
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import gsim_initialization_setup as setup
import gsim_reset_graph_bundle as bundle


class SelectionTest(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.common = SimpleNamespace(ROOT=Path('/repository'),
                                      compiler=lambda: ('/qualified/clang', '19'))

    def test_explicit_bundle(self):
        binding = {'gsim': {'path': '/qualified/gsim'}, 'compiler': {'command': '/qualified/clang'}}
        with patch.dict(os.environ, {'VALENCE_GSIM_RESET_GRAPH_BUNDLE': '/bundle'}), \
             patch.object(bundle, 'tool_binding', return_value=binding) as verify, \
             patch.object(setup, 'build_fresh') as build, \
             patch.object(setup.epoch, 'tool_binding') as epoch:
            self.assertEqual(setup.setup(False, self.common), (Path('/qualified/gsim'), '/qualified/clang'))
            verify.assert_called_once_with('/bundle', self.common.ROOT)
            build.assert_not_called()
            epoch.assert_not_called()

    def test_compiler_contract_failure_is_preserved(self):
        binding = {'gsim': {'path': '/qualified/gsim'}, 'compiler': {'command': '/qualified/clang'}}
        with patch.dict(os.environ, {'VALENCE_GSIM_RESET_GRAPH_BUNDLE': '/bundle'}), \
             patch.object(bundle, 'tool_binding', return_value=binding), \
             patch.object(self.common, 'compiler', side_effect=RuntimeError('minimum compiler version')):
            with self.assertRaisesRegex(RuntimeError, 'minimum compiler version'):
                setup.setup(False, self.common)

    def test_compiler_selection_drift_is_rejected(self):
        binding = {'gsim': {'path': '/qualified/gsim'}, 'compiler': {'command': '/qualified/clang'}}
        with patch.dict(os.environ, {'VALENCE_GSIM_RESET_GRAPH_BUNDLE': '/bundle'}), \
             patch.object(bundle, 'tool_binding', return_value=binding), \
             patch.object(self.common, 'compiler', return_value=('/different/clang', '19')):
            with self.assertRaisesRegex(RuntimeError, 'compiler selection changed'):
                setup.setup(False, self.common)

    def test_ambiguous_including_empty_receipt(self):
        for receipt in ('/receipt', ''):
            with self.subTest(receipt=receipt), \
                 patch.dict(os.environ, {'VALENCE_GSIM_RESET_GRAPH_BUNDLE': '/bundle',
                                         'VALENCE_GSIM_INIT_RECEIPT': receipt}), \
                 patch.object(bundle, 'tool_binding') as verify, \
                 patch.object(setup, 'build_fresh') as build, \
                 patch.object(setup.epoch, 'tool_binding') as epoch:
                with self.assertRaisesRegex(RuntimeError, 'only one'):
                    setup.setup(True, self.common)
                verify.assert_not_called()
                build.assert_not_called()
                epoch.assert_not_called()

    def test_empty_selector(self):
        with patch.dict(os.environ, {'VALENCE_GSIM_RESET_GRAPH_BUNDLE': ''}), \
             patch.object(setup, 'build_fresh') as build:
            with self.assertRaisesRegex(RuntimeError, 'must not be empty'):
                setup.setup(True, self.common)
            build.assert_not_called()

    def test_invalid_explicit_never_falls_back(self):
        with patch.dict(os.environ, {'VALENCE_GSIM_RESET_GRAPH_BUNDLE': '/missing'}), \
             patch.object(bundle, 'tool_binding', side_effect=RuntimeError('invalid bundle')), \
             patch.object(setup, 'build_fresh') as build, \
             patch.object(setup.epoch, 'tool_binding') as epoch:
            with self.assertRaisesRegex(RuntimeError, 'invalid bundle'):
                setup.setup(True, self.common)
            build.assert_not_called()
            epoch.assert_not_called()


@unittest.skipUnless(os.environ.get('VALENCE_RESET_GRAPH_TEST_BUNDLE') and
                     os.environ.get('VALENCE_RESET_GRAPH_TEST_REPO'),
                     'set real pinned bundle and repository paths for integration checks')
class RealProfileTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = Path(os.environ['VALENCE_RESET_GRAPH_TEST_BUNDLE']).resolve()
        cls.repository = Path(os.environ['VALENCE_RESET_GRAPH_TEST_REPO']).resolve()
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name) / 'bundle'
        cls.repo = Path(cls.temp.name) / 'repo'
        cls.root.mkdir()
        manifest = json.loads((cls.repository / 'simulator/gsim/tool_fixes/reset-graph-inputs.json').read_text())
        paths = list(manifest['executed_fixture_sha256']) + [
            'simulator/gsim/tool_fixes/reset-graph-inputs.json',
            *['simulator/gsim/tool_fixes/' + name for name in bundle.PATCHES],
        ]
        for name in paths:
            dest = cls.repo / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(cls.repository / name, dest)
        for name in ['TOOLCHAIN-RECEIPT.json', 'gsim/qualification/PASS.json']:
            dest = cls.root / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(cls.original / name, dest)
        shutil.copytree(cls.original / 'gsim/source', cls.root / 'gsim/source',
                        ignore=shutil.ignore_patterns('build', '.git'))
        receipt = json.loads((cls.original / 'TOOLCHAIN-RECEIPT.json').read_text())
        names = [Path(receipt['tools'][key]['path']).relative_to(bundle.HISTORICAL_ROOT)
                 for key in ('gsim', 'clang', 'mill', 'firtool', 'env')]
        names.append(Path('generation/bin/mill'))
        for name in names:
            dest = cls.root / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.symlink_to(cls.original / name)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def verify(self):
        # The copied source is deliberately distinct; active executable symlinks
        # still resolve to the authentic bundle. Do not mock the verifier/hash.
        env = {key: value for key, value in os.environ.items()
               if key not in ('GSIM', 'VALENCE_GSIM_SOURCE', 'FIRTOOL')}
        env['CHISEL_FIRTOOL_PATH'] = str(self.root /
            'generation/firtool/org.chipsalliance/llvm-firtool/linux-x64/bin')
        with patch.dict(os.environ, env, clear=True):
            return bundle.tool_binding(self.root, self.repo)

    def altered(self, path, data=None):
        original = path.read_bytes()
        target = path.readlink() if path.is_symlink() else None
        path.unlink()
        if data is not None:
            path.write_bytes(data)
        try:
            with self.assertRaises((RuntimeError, FileNotFoundError)):
                self.verify()
        finally:
            if path.exists():
                path.unlink()
            if target is not None:
                path.symlink_to(target)
            else:
                path.write_bytes(original)

    def test_real_positive(self):
        result = bundle.tool_binding(self.original, self.repository)
        self.assertEqual(result['profile'], bundle.PROFILE)
        self.assertEqual(len(result['gsim']['source_sha256']), 101)
        self.assertEqual(self.verify()['gsim']['sha256'], result['gsim']['sha256'])

    def test_real_setup_path(self):
        with patch.dict(os.environ, {'VALENCE_GSIM_RESET_GRAPH_BUNDLE': str(self.original)}), \
             patch.object(setup, 'build_fresh') as build, \
             patch.object(setup.epoch, 'tool_binding') as epoch:
            result = setup.setup(True, SimpleNamespace(
                ROOT=self.repository, compiler=lambda: (os.environ['GSIM_CXX'], '19')))
            self.assertEqual(result[0], self.original / 'gsim/source/build/gsim/gsim')
            build.assert_not_called()
            epoch.assert_not_called()

    def test_changed_or_missing_receipts(self):
        for name in ('TOOLCHAIN-RECEIPT.json', 'gsim/qualification/PASS.json'):
            for data in (b'{"status":"PASS"}', None):
                with self.subTest(name=name, data=data):
                    self.altered(self.root / name, data)

    def test_manifest_changes(self):
        path = self.repo / 'simulator/gsim/tool_fixes/reset-graph-inputs.json'
        for key in ('upstream_commit', 'patch_order', 'final_source_sha256', 'executed_fixture_sha256'):
            with self.subTest(key=key):
                obj = json.loads(path.read_text())
                obj[key] = {} if isinstance(obj[key], dict) else []
                self.altered(path, json.dumps(obj).encode())

    def test_changed_and_missing_patch_bytes(self):
        for name in bundle.PATCHES:
            for data in (b'tampered', None):
                with self.subTest(name=name, data=data):
                    self.altered(self.repo / 'simulator/gsim/tool_fixes' / name, data)

    def test_changed_and_missing_source(self):
        for data in (b'tampered', None):
            with self.subTest(data=data):
                self.altered(self.root / 'gsim/source/src/cppEmitter.cpp', data)

    def test_extra_source(self):
        path = self.root / 'gsim/source/src/unqualified.cpp'
        path.write_text('extra source')
        try:
            with self.assertRaisesRegex(RuntimeError, 'source inventory'):
                self.verify()
        finally:
            path.unlink()

    def test_changed_and_missing_fixture(self):
        for data in (b'tampered', None):
            with self.subTest(data=data):
                self.altered(self.repo / 'simulator/gsim/harness/gsim_model_storage.h', data)

    def test_changed_and_missing_executables(self):
        for name in ('gsim/source/build/gsim/gsim', 'native/root/usr/bin/clang++-19',
                     'generation/downloads/mill-1.1.7', 'generation/bin/mill',
                     'generation/firtool/org.chipsalliance/llvm-firtool/linux-x64/bin/firtool'):
            for data in (b'tampered', None):
                with self.subTest(name=name, data=data):
                    self.altered(self.root / name, data)

    def test_active_tool_conflicts(self):
        for key in ('GSIM_CXX', 'GSIM', 'VALENCE_GSIM_SOURCE', 'FIRTOOL',
                    'CHISEL_FIRTOOL_PATH', 'JAVA_HOME'):
            with self.subTest(key=key), patch.dict(os.environ, {key: '/wrong/tool'}):
                with self.assertRaises(RuntimeError):
                    bundle.tool_binding(self.original, self.repository)
        with patch.dict(os.environ, {'CHISEL_FIRTOOL_PATH': ''}):
            with self.assertRaisesRegex(RuntimeError, 'must select'):
                bundle.tool_binding(self.original, self.repository)
        with patch.dict(os.environ, {'PATH': ''}):
            with self.assertRaises(RuntimeError):
                bundle.tool_binding(self.original, self.repository)


if __name__ == '__main__':
    unittest.main()
