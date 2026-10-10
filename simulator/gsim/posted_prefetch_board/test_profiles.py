"""Host-only explicit experiment, complete-profile and binding negative controls."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import profiles
import run_board


class Profiles(unittest.TestCase):
    def test_original_posted_meaning_and_complete_profiles(self):
        for mode in ('off', 'on'):
            summary = profiles.expected('posted', mode)
            run_board.DEFAULT_CONTRACT.verify_profile(summary, mode)
            self.assertEqual(summary['profile']['postedStoreMerge'], mode == 'on')
            self.assertFalse(summary['profile']['postedPrefetchCoexistence'])
            self.assertFalse(summary['profile']['postedPrefetchHeadOffer'])
        self.assertEqual(run_board.DEFAULT_CONTRACT.verify_profile_pair(
            profiles.expected('posted', 'off'), profiles.expected('posted', 'on'))['only_differences'],
            ['profile.postedStoreMerge', 'core.postedStoreMerge'])

    def test_experiment_pairs_and_exact_placement(self):
        for contract in (profiles.COEXISTENCE, profiles.HEAD_OFFER):
            self.assertEqual(contract.verify_profile_pair(profiles.expected(contract.name, 'off'),
                profiles.expected(contract.name, 'on'))['only_differences'], list(contract.differences))
            for mode in ('off', 'on'):
                self.assertTrue(contract.posted_enabled(mode))
                self.assertEqual(len(profiles.expected(contract.name, mode)['core']), 135)
                self.assertEqual(len(profiles.expected(contract.name, mode)['profile']), 26)

    def test_all_old_fields_mutations_and_unknown_keys_fail(self):
        def leaves(value, path=()):
            if isinstance(value, dict):
                for key, item in value.items():
                    yield from leaves(item, path + (key,))
            else:
                yield path, value
        for contract in (profiles.COEXISTENCE, profiles.HEAD_OFFER):
            for mode in ('off', 'on'):
                expected = profiles.expected(contract.name, mode)
                for path, value in leaves(expected):
                    bad = copy.deepcopy(expected)
                    target = bad
                    for key in path[:-1]:
                        target = target[key]
                    target[path[-1]] = not value if type(value) is bool else value + 1 if type(value) is int else 'MUTATED'
                    with self.subTest(contract=contract.name, mode=mode, path=path), self.assertRaises(ValueError):
                        contract.verify_profile(bad, mode)
                for group, value in expected.items():
                    if isinstance(value, dict):
                        bad = copy.deepcopy(expected)
                        bad[group]['unknown'] = False
                        with self.assertRaises(ValueError):
                            contract.verify_profile(bad, mode)
                        for field in value:
                            bad = copy.deepcopy(expected)
                            del bad[group][field]
                            with self.assertRaises(ValueError):
                                contract.verify_profile(bad, mode)

    def test_same_baseline_mutation_cannot_cancel_in_pair(self):
        for contract in (profiles.COEXISTENCE, profiles.HEAD_OFFER):
            off, on = [profiles.expected(contract.name, mode) for mode in ('off', 'on')]
            off['core']['fastBufferedStoreRetire'] = on['core']['fastBufferedStoreRetire'] = True
            with self.assertRaises(ValueError):
                contract.verify_profile_pair(off, on)

    def test_legacy_and_experiment_cases_stay_distinct(self):
        original = run_board.DEFAULT_CONTRACT
        self.assertEqual(tuple(original.case_name(*case) for case in original.cases),
            ('old-only', 'off', 'on', 'on-negative-token', 'on-negative-byte'))
        self.assertFalse(original.posted_enabled('off'))
        self.assertTrue(original.posted_enabled('on'))
        for contract in (profiles.COEXISTENCE, profiles.HEAD_OFFER):
            self.assertEqual(tuple(contract.case_name(*case) for case in contract.cases),
                ('off', 'off-negative-token', 'off-negative-byte', 'on', 'on-negative-token', 'on-negative-byte'))
            self.assertEqual(contract.snapshot_variants, ('off', 'on'))

    def test_cross_experiment_binding_rejected_before_execution(self):
        args = SimpleNamespace()
        for contract in (profiles.COEXISTENCE, profiles.HEAD_OFFER):
            for other in ('posted', 'coexistence', 'head-offer'):
                if other == contract.name:
                    continue
                with self.assertRaisesRegex(run_board.core.GateError, 'bound experiment differs'):
                    run_board.Gate(args, {'experiment': other}, contract)

    def test_wrong_launch_path_fails_before_output(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / 'uncreated'
            binding = Path(directory) / 'binding.json'
            binding.write_text(json.dumps({'schema': 'posted-board-binding-v1',
                'repo': str(run_board.ROOT), 'experiment': 'head-offer',
                'launcher': 'simulator/gsim/posted_board_lineage/run_board.py'}))
            argv = ['models', '--binding', str(binding), '--binding-sha256', run_board.core.sha(binding),
                '--slot-granted', '--output', str(out)]
            with self.assertRaisesRegex(run_board.core.GateError, 'bound launcher differs'), \
                    mock.patch.object(run_board, 'Gate') as gate:
                run_board.main(argv, contract=profiles.HEAD_OFFER,
                    launcher=profiles.HERE / 'head_offer.py')
            gate.assert_not_called()
            self.assertFalse(out.exists())

    def test_unknown_modes_and_experiments_rejected(self):
        for experiment, mode in [('other', 'off'), ('posted', 'other')]:
            with self.assertRaises(ValueError):
                profiles.expected(experiment, mode)


if __name__ == '__main__':
    unittest.main()
