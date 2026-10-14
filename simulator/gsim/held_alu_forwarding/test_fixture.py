#!/usr/bin/env python3
"""In-memory rejection checks for the portable evidence checker."""
import copy
import sys
import unittest
sys.dont_write_bytecode = True
from check_fixture import HERE, check, read, verify_records

class FixtureChecks(unittest.TestCase):
    def setUp(self): self.rows = read(HERE/'evidence/results.json')['records']
    def test_complete_read_only_fixture(self): self.assertEqual(check()['functional_passes'], 24)
    def test_missing_control_rejected(self):
        with self.assertRaises(AssertionError): verify_records([r for r in self.rows if r.get('control') != 'owner'])
    def test_invalid_log_digest_rejected(self):
        rows = copy.deepcopy(self.rows)
        rows[0]['raw_log_sha256'] = 'invalid'
        with self.assertRaises(AssertionError): verify_records(rows)
    def test_unreached_is_not_rejection(self):
        rows = copy.deepcopy(self.rows)
        next(r for r in rows if r.get('control') == 'value')['status'] = 'NOT_REACHED'
        with self.assertRaises(AssertionError): verify_records(rows)
    def test_off_capture_claim_rejected(self):
        rows = copy.deepcopy(self.rows)
        next(r for r in rows if r['kind'] == 'corrected' and r['mode'] == 'off')['case']['observations']['held_captures'] = 1
        with self.assertRaises(AssertionError): verify_records(rows)

if __name__ == '__main__': unittest.main()
