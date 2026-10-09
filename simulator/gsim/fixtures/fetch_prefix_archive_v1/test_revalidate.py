#!/usr/bin/env python3
"""Independent host-metadata and fail-closed negative tests; no hardware."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import revalidate as r


class HistoricalMetadata(unittest.TestCase):
    def setUp(self):
        self.old = {'production_commit': '1' * 40, 'production_tree': '2' * 40,
                    'qualified_host_commit': '3' * 40, 'host_head': '4' * 40}
        self.current = {**self.old, 'host_head': '5' * 40}
        self.commands = []

    def git(self, *args):
        self.commands.append(args)
        return self.current['production_tree'] if args[0] == 'rev-parse' else ''

    def test_head_only_positive_and_explicit_ancestry(self):
        self.assertEqual(r.normalize_host(self.current, self.old, self.git), self.old)
        self.assertEqual(self.commands, [('rev-parse', self.old['host_head'] + ':src/main'),
            ('merge-base', '--is-ancestor', self.old['qualified_host_commit'], self.old['host_head']),
            ('merge-base', '--is-ancestor', self.old['host_head'], self.current['host_head'])])
        self.assertEqual(r.differences(self.old, self.current), ['.host_head'])

    def test_non_head_difference_rejected(self):
        for field in ('production_commit', 'production_tree', 'qualified_host_commit'):
            wrong = {**self.current, field: '9' * 40}
            with self.subTest(field=field), self.assertRaisesRegex(RuntimeError, 'non-head'):
                r.normalize_host(wrong, self.old, self.git)

    def test_field_inventory_and_type_drift(self):
        for bad in ({**self.current, 'extra': 1}, {k: v for k, v in self.current.items() if k != 'production_tree'},
                    {**self.current, 'production_tree': 2}):
            with self.subTest(bad=bad), self.assertRaises(RuntimeError):
                r.normalize_host(bad, self.old, self.git)

    def test_old_head_production_differs(self):
        with self.assertRaisesRegex(RuntimeError, 'historical host production tree differs'):
            r.normalize_host(self.current, self.old, lambda *args: '9' * 40)

    def test_old_head_not_ancestor(self):
        for failing in (('3' * 40, '4' * 40), ('4' * 40, '5' * 40)):
            def git(*args):
                if tuple(args[-2:]) == failing:
                    raise RuntimeError('nonancestor rejected')
                return self.git(*args)
            with self.subTest(edge=failing), self.assertRaisesRegex(RuntimeError, 'nonancestor'):
                r.normalize_host(self.current, self.old, git)

    def test_original_source_validator_always_called(self):
        original = mock.Mock(side_effect=RuntimeError('source mutation rejected'))
        adapter = r.HistoricalAnchor(original, self.old, self.current['host_head'])
        with self.assertRaisesRegex(RuntimeError, 'source mutation'):
            adapter(Path('/repo'), self.old['production_commit'], self.old['qualified_host_commit'], self.old['production_tree'])
        original.assert_called_once()
        self.assertFalse(adapter.calls)

    def test_current_head_changes_during_audit(self):
        original = mock.Mock(return_value={**self.current, 'host_head': '6' * 40})
        adapter = r.HistoricalAnchor(original, self.old, self.current['host_head'])
        with self.assertRaisesRegex(RuntimeError, 'current audit HEAD changed'):
            adapter(Path('/repo'), self.old['production_commit'])

    def test_non_head_nested_identity_detected(self):
        old = {'source_binding': self.old, 'compiler': '/exact/clang++-19', 'files': {'source': 'hash'},
               'environment': {'CPATH': None}, 'scope': ['original']}
        for key, value in [('compiler', '/other/clang++-19'), ('files', {'source': 'changed'}),
                           ('environment', {'CPATH': '/different'}), ('scope', ['weakened'])]:
            new = copy.deepcopy(old);new['source_binding'] = self.current;new[key] = value
            with self.subTest(key=key):
                self.assertFalse(set(r.differences(old, new)) <= {'.source_binding.host_head'})


class FrozenContent(unittest.TestCase):
    def test_source_tool_artifact_mutations_rejected(self):
        with tempfile.TemporaryDirectory(dir=r.HERE, prefix='.test-hashes-') as temp:
            root = Path(temp)
            for category in ('source', 'compiler', 'artifact'):
                path = root / category;path.write_bytes(b'qualified original content')
                mapping = {str(path): r.sha(path)}
                r.verify_hashes(mapping)
                path.write_bytes(b'changed')
                with self.subTest(category=category), self.assertRaisesRegex(RuntimeError, 'bound file content drift'):
                    r.verify_hashes(mapping)
                path.unlink()
                with self.assertRaises(RuntimeError):
                    r.verify_hashes(mapping)

    def test_exact_recorded_environment_reproduction(self):
        with mock.patch.dict(r.os.environ, {'PATH': 'ambient', 'CPATH': 'ambient', 'ASAN_OPTIONS': 'different'}, clear=True):
            env = r.environment_for({'environment': {'PATH': 'recorded', 'CPATH': 'recorded/include', 'ASAN_OPTIONS': None}})
            self.assertEqual(env['PATH'], 'recorded')
            self.assertEqual(env['CPATH'], 'recorded/include')
            self.assertNotIn('ASAN_OPTIONS', env)
            self.assertEqual(r.os.environ['PATH'], 'ambient')

    def test_normalization_does_not_modify_arguments(self):
        old = {'production_commit': '1' * 40, 'production_tree': '2' * 40,
               'qualified_host_commit': '3' * 40, 'host_head': '4' * 40}
        current = {**old, 'host_head': '5' * 40}
        before = copy.deepcopy((old, current))
        normalized = r.normalize_host(current, old, lambda *args: '2' * 40 if args[0] == 'rev-parse' else '')
        normalized['host_head'] = 'changed'
        self.assertEqual((old, current), before)


if __name__ == '__main__':
    unittest.main(verbosity=2)
