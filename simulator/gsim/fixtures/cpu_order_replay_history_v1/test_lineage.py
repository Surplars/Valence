#!/usr/bin/env python3
"""Retained R7 source and runner-contract checks; no compiler or simulation."""
import json
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_fixture as runner
import strict_validation as validation


class R7Lineage(unittest.TestCase):
    def setUp(self):
        self.pins = json.loads((HERE / 'r7_lineage.json').read_text())

    def test_exact_r7_sources(self):
        expected = {'build_guest.py', 'cpu_order_replay.S', 'cpu_order_replay.ld',
                    'cpu_order_replay.cpp', 'order_oracle.h', 'test_oracle.cpp'}
        self.assertEqual(set(self.pins['retained_fixture_sha256']), expected)
        for name, digest in self.pins['retained_fixture_sha256'].items():
            with self.subTest(name=name):
                self.assertEqual(validation.sha(HERE / name), digest)
        self.assertEqual(self.pins['retained_fixture_sha256']['cpu_order_replay.cpp'],
                         'a3fbec18be74d24c61766e59ba4c3d453c330784bfb7cb510de9b44a1d061919')

    def test_receipt_and_anchors(self):
        self.assertEqual(self.pins['qualified_r7_receipt_sha256'],
                         'ebc318ee5e79f00c886d53d0f08b5e3668a8c40a88c7d3e4052855b1060efb63')
        self.assertEqual(self.pins['production_commit'], runner.PRODUCTION)
        self.assertEqual(self.pins['host_commit'], runner.HOST)
        self.assertEqual(self.pins['qualified_r7_status'], 'PASS_EXECUTED_CPU_ORDER_REPLAY_OFF_ON')

    def test_unchanged_twelve_observation_negatives(self):
        self.assertEqual(runner.NEGATIVES, {
            'selector': 'missing selector to pending boundary',
            'pending': 'missing pending witness',
            'generation': 'selector full-token mismatch',
            'recovery': 'missing accepted replay recovery',
            'cancellation': 'accepted recovery omitted LSU cancellation',
            'canceled-retirement': 'canceled full generation retired',
            'read-data': 'independent known-memory response mismatch',
            'data': 'committed register data mismatch',
            'final-data': 'committed register data mismatch',
            'terminal-axi': 'terminal pre-callback AXI state not empty',
            'pc': 'committed PC sequence mismatch',
            'drain': 'terminal pending owner/reply drain failure',
        })

    def test_current_receipt_profiles(self):
        self.assertEqual(set(self.pins['qualified_model_receipts']), {'off', 'on'})
        for label, state in self.pins['qualified_model_receipts'].items():
            with self.subTest(label=label):
                self.assertTrue(validation.exact(state['profile'], validation.expected_plan(label == 'on')))


if __name__ == '__main__':
    unittest.main(verbosity=2)
