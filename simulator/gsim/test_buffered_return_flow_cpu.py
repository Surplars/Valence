#!/usr/bin/env python3
"""Source-only contract calibrations; no DUT generation, compilation or runtime."""
import copy
import tempfile
from pathlib import Path
import unittest
import buffered_return_flow_cpu as flow


class ReturnFlowRunnerContract(unittest.TestCase):
    def parameters(self):
        old = {'bufferedThirdRankLoadProof': 'true', 'robEntries': '16', 'tagBits': '64',
               'translatedResponseEmptyFlow': 'false', 'reconstructIssueTokenIndex': 'false'}
        control = dict(old, bufferedReturnFlow='false')
        candidate = dict(control, bufferedReturnFlow='true', translatedResponseEmptyFlow='true',
                         reconstructIssueTokenIndex='true')
        return ({k: copy.deepcopy(control) for k in ('config', 'core')},
                {k: copy.deepcopy(candidate) for k in ('config', 'core')},
                {k: copy.deepcopy(old) for k in ('config', 'core')})

    def test_exact_three_flag_delta(self):
        self.assertTrue(flow.parameter_gate(*self.parameters())['all_execution_capacities_unchanged'])

    def test_each_missing_behavior_rejected(self):
        for name in ('bufferedReturnFlow', 'translatedResponseEmptyFlow', 'reconstructIssueTokenIndex'):
            a, b, old = self.parameters()
            b['core'][name] = 'false'
            with self.assertRaises(Exception):
                flow.parameter_gate(a, b, old)

    def test_capacity_and_tag_drift_rejected(self):
        for name, value in (('robEntries', '64'), ('tagBits', '32')):
            a, b, old = self.parameters()
            b['core'][name] = value
            with self.assertRaises(Exception):
                flow.parameter_gate(a, b, old)

    def test_disabled_new_flag_or_old_field_drift_rejected(self):
        for name, value in (('bufferedReturnFlow', 'true'), ('robEntries', '64')):
            a, b, old = self.parameters()
            a['core'][name] = value
            with self.assertRaises(Exception):
                flow.parameter_gate(a, b, old)

    def test_source_locations_only_normalization(self):
        normalize = flow.row.normalize_fir
        a = b'node a = UInt<1>(0) @[old.scala 1:2]\n'
        b = b'node a = UInt<1>(0) @[new.scala 9:8]\n'
        self.assertEqual(normalize(a), normalize(b))
        self.assertNotEqual(normalize(a), normalize(b.replace(b'(0)', b'(1)')))
        self.assertNotEqual(normalize(b'printf("@[a.scala 1]")'),
                            normalize(b'printf("@[b.scala 2]")'))

    def test_return_metric_conservation_and_duplicate_rejected(self):
        line = ('BUFFERED_RETURN_FLOW name=hot_loads cycles=8 allocations=2 live_checks=6 '
                'accepted=2 consumed=2 bypass=1 captures=1 queued_pops=1 full_pop=0 faults=0 fp=0 slot_starts=1 slot_reply_accepts=1 slot_completions=1 slot_released_without_completion=0\n'
                'BUFFERED_LSU_SLOT_REPLY name=hot_loads cycle=3 slot=0 token_index=0 token_tag=9223372036854775809 start_cycle=1 outer_reply_same_cycle=1 any_complete_same_cycle=0\n')
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / 'test.log'
            log.write_text(line)
            self.assertEqual(flow.return_observer_metrics(log, ['hot_loads'])[0]['accepted'], 2)
            for bad in (line + line, line.replace('consumed=2', 'consumed=1'),
                        line.replace('live_checks=6', 'live_checks=0')):
                log.write_text(bad)
                with self.assertRaises(Exception):
                    flow.return_observer_metrics(log, ['hot_loads'])

    def test_only_new_profile_and_current_reference(self):
        self.assertEqual(flow.CANDIDATE, flow.CONTROL + '-return-flow-index')
        self.assertEqual(flow.COMMIT, '7daf1190db48b37214f73a2fdd68a9fd0dbff3aa')
        self.assertEqual(flow.ALLOW_ADDED, set())
        self.assertEqual(flow.ALLOW_REMOVED, set())
        self.assertNotIn('OwnerBankedPhysicalRegisterFile', flow.ALLOW_CHANGED)
        self.assertNotIn('BankedIssuePayload', flow.ALLOW_CHANGED)


if __name__ == '__main__':
    unittest.main()
