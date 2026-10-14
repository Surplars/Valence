#!/usr/bin/env python3
"""Host-only real-evidence and isolated semantic negative tests, no hardware tools."""
import argparse
import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import check_timing_r6 as entry

class Tests(unittest.TestCase):
    def check(self, pins=None):
        return entry.check(ROOT / 'source', ROOT / 'native-r1', ROOT, pins or PINS)

    def test_actual_bound_evidence(self):
        self.assertEqual(self.check()['status'], 'PASS_R6_BOUND_INPUT_REVIEW_ONLY')

    def test_wrong_receipt_hash(self):
        for name in PINS['evidence']:
            pins = copy.deepcopy(PINS)
            pins['evidence'][name] = '0' * 64
            with self.subTest(name=name), self.assertRaises(RuntimeError):
                self.check(pins)

    def test_qualification_semantics(self):
        original = entry.read
        # Keep exact bytes/hash path active; independently exercise schema checks
        # by changing the parsed object after its hash has been checked.
        for key, value in [('status','PENDING'), ('status','FAIL'), ('candidate','timing-r5-structural-ready73-r1'), ('schema','old'), ('negative_controls',7), ('historical_qualification_inherited',True), ('new_model_objects',{})]:
            def altered(path):
                obj = original(path)
                if Path(path) == ROOT / 'qualification.json':
                    obj[key] = value
                return obj
            with self.subTest(key=key,value=value), patch.object(entry,'read',side_effect=altered), self.assertRaises(RuntimeError):
                self.check()

    def test_supplement_semantics(self):
        original = entry.read
        for key, value in [('status','PENDING'), ('candidate','r5'), ('base_qualification_sha256','wrong'), ('native_receipt_sha256','wrong'), ('source_freeze_sha256','wrong')]:
            def altered(path):
                obj = original(path)
                if Path(path) == ROOT / 'qualification-supplement-r1.json':
                    obj[key] = value
                return obj
            with self.subTest(key=key), patch.object(entry,'read',side_effect=altered), self.assertRaises(RuntimeError):
                self.check()

    def test_native_and_source_changed(self):
        original = entry.sha
        for target in [ROOT/'native-r1/FpgaNextSocTop.sv', ROOT/'source/src/main/scala/core/ooo/LoadStoreUnit.scala']:
            with self.subTest(target=target), patch.object(entry,'sha',side_effect=lambda p: '0'*64 if Path(p)==target else original(p)), self.assertRaises(RuntimeError):
                self.check()

    def test_unsafe_member(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ('../escape','/absolute',''):
                with self.assertRaises(RuntimeError):
                    entry.files(Path(d),{name:'0'*64})

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--candidate-root', type=Path, required=True)
    args, rest = p.parse_known_args()
    ROOT = args.candidate_root.resolve()
    PINS = entry.read(entry.HERE/'timing-r6-input-pins.json')
    unittest.main(argv=[sys.argv[0],*rest])
