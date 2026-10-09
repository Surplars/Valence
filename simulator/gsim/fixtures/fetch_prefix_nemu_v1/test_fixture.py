#!/usr/bin/env python3
"""Source-only contract negatives. No host compiler, GSIM, or NEMU execution."""
import copy
import importlib.util
from pathlib import Path
import sys
import unittest
sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_fixture as runner
pins, common, board, guests, hot, nemu, validation = runner.dependencies(runner.ROOT)

# Reuse the validator's independent synthetic model/source tests, but place all
# temporary files inside this new fixture. No old fixture content is modified.
existing = runner.module('fetch_prefix_validation_tests', runner.ROOT /
    'simulator/gsim/fixtures/cpu_order_replay_history_v1/test_validation.py')
existing.HERE = HERE
ModelValidation = existing.ModelValidation
ProductionValidation = existing.ProductionValidation


def counters(**updates):
    values = {'guest_pc_checks': 8, 'boot_pc_checks': 5, 'guest_retire_edges': 5,
              'dual_retire_edges': 3, 'guest_gpr_edges': 5, 'boot_gpr_edges': 3,
              'gpr_value_checks': 256, 'final_memory_bytes': 0x400040,
              'guest_pc_trace': 1234, 'reference_resynchronizations': 0,
              'gpr_boundary': 'post_entire_retire_edge',
              'independent_lane_intermediate_gpr': 0, 'speculative_requests_stepped': 0}
    values.update(updates)
    return 'NEMU_PASS ' + ' '.join(f'{k}={v}' for k, v in values.items()) + '\nHOT_PASS ok=1\n'


class InstrumentationContract(unittest.TestCase):
    def test_retained_checker_and_reference_unchanged(self):
        provenance = runner.load(nemu.BUNDLE / 'checker_provenance.json')
        for name in ('board_nemu_observer.h', 'reference.h'):
            self.assertEqual(runner.sha(nemu.BUNDLE / name), provenance['historical_checker_files'][name])

    def test_exact_existing_instrumentation(self):
        original = (runner.ROOT / 'simulator/gsim/harness/cpu_retire_prefix_hot.cpp').read_text()
        result = nemu.instrument(original)
        self.assertEqual(result.count('nemu.sample(d);'), 1)
        self.assertEqual(result.count('observer.nemu.initialize(image,argv[2],injection);'), 1)
        self.assertEqual(result.count('observer.nemu.verifyMemory(test);'), 1)
        self.assertIn('test.tick();\n    observer.nemu.verifyMemory(test);', result)
        self.assertIn('observer.verify();observer.report();observer.nemu.report();return 0;', result)
        for mode in nemu.NEGATIVES:
            self.assertIn('"--inject-nemu-' + mode + '"', result)
        for label in nemu.LABELS:
            for mode in nemu.negative_modes(label):
                self.assertIn('"--inject-' + mode + '"', result)

    def test_instrumentation_fails_on_anchor_drift(self):
        original = (runner.ROOT / 'simulator/gsim/harness/cpu_retire_prefix_hot.cpp').read_text()
        for old in ('#include <limits>', '    void sample(SBoardSocGsim &d) {',
                    '    observer.verify();observer.report();return 0;'):
            for replacement in ('', old + '\n' + old):
                with self.subTest(old=old, replacement=replacement), self.assertRaisesRegex(RuntimeError, 'anchor drift'):
                    nemu.instrument(original.replace(old, replacement))

    def test_full_architectural_observation_contract(self):
        text = (nemu.BUNDLE / 'board_nemu_observer.h').read_text()
        self.assertLess(text.index('if(pending)'), text.index('for(unsigned lane=0;lane<2;++lane)'))
        self.assertIn('for(unsigned r=0;r<32;++r)', text)
        self.assertIn('before.pc==pc', text)
        self.assertIn('expected=reference->executeOne(); // Never repair or resynchronize.', text)
        self.assertIn('test.ddr.pendingWrites.empty()&&test.ddr.pendingB.empty()', text)
        self.assertIn('finalized&&!pending&&boundary', text)
        self.assertIn('constexpr size_t memoryBytes=0x400040', text)

    def test_flag_contract(self):
        f = nemu.flags('off', 'copy-8192', Path('/model'), Path('/guest'))
        for value in ('-O1', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                      '-DBACKEND_OWNER_COUNT=4', '-DPHYSICAL_INGRESS_FLOW=1', '-DHOT_BYTES=8192',
                      '-DHOT_OP=2', '-DHOT_REPS=4', '-DDDR_READ_LATENCY=32',
                      '-DDDR_READ_BEAT_GAP=1', '-DDDR_READ_CREDITS=8'):
            self.assertIn(value, f)


class ReceiptContract(unittest.TestCase):
    def test_whole_edge_counter_positive(self):
        parsed = nemu.nemu_counters(counters())
        self.assertEqual(parsed['gpr_boundary'], 'post_entire_retire_edge')
        self.assertEqual(parsed['gpr_value_checks'], '256')

    def test_counter_coverage_negatives(self):
        cases = [('guest_pc_checks', 7), ('guest_pc_checks', 0), ('guest_gpr_edges', 4),
                 ('guest_retire_edges', 0), ('dual_retire_edges', 6), ('boot_pc_checks', 4),
                 ('boot_gpr_edges', 2), ('boot_gpr_edges', 6), ('gpr_value_checks', 255),
                 ('final_memory_bytes', 0x400000), ('reference_resynchronizations', 1),
                 ('gpr_boundary', 'per_lane'), ('independent_lane_intermediate_gpr', 1),
                 ('speculative_requests_stepped', 1), ('guest_pc_trace', 'invalid'),
                 ('guest_pc_checks', -1)]
        for name, value in cases:
            with self.subTest(name=name, value=value), self.assertRaises(RuntimeError):
                nemu.nemu_counters(counters(**{name: value}))

    def test_missing_duplicate_and_extra_counters(self):
        text = counters()
        for bad in (text.replace('guest_pc_trace=1234 ', ''), text + text,
                    text.replace('NEMU_PASS ', 'NEMU_PASS unqualified=1 '),
                    text.replace('NEMU_PASS ', 'NEMU_PASS guest_pc_checks=8 '),
                    text.replace('\nHOT_PASS ok=1\n', '\n')):
            with self.subTest(text=bad), self.assertRaises(RuntimeError):
                nemu.nemu_counters(bad)

    def test_negative_exact_failure_and_no_success(self):
        anchor = 'NEMU PC mismatch'
        runner.negative_check('HOT_FAIL ' + anchor, 1, anchor)
        for text, code in [('HOT_FAIL unrelated', 1), ('HOT_FAIL ' + anchor, 0),
                           ('HOT_FAIL ' + anchor, 2), ('HOT_FAIL ' + anchor + '\nNEMU_PASS', 1),
                           ('HOT_FAIL ' + anchor + '\nHOT_PASS', 1)]:
            with self.subTest(text=text, code=code), self.assertRaises(RuntimeError):
                runner.negative_check(text, code, anchor)

    def test_negative_mode_inventory(self):
        for label in nemu.LABELS:
            modes = {**{'nemu-' + k: v for k, v in nemu.NEGATIVES.items()}, **nemu.negative_modes(label)}
            self.assertEqual(len(modes), 13)
            self.assertTrue({'nemu-pc', 'nemu-gpr', 'nemu-memory', 'upper-token', 'upper-live',
                             'return-token', 'reserve-guard', 'authorization', 'private-metadata'} <= set(modes))

    def test_pair_architecture_identity(self):
        case = {'guest_sha256': 'same', 'nemu': nemu.nemu_counters(counters())}
        cases = {label + '-' + name: copy.deepcopy(case) for label in nemu.LABELS for name in nemu.CASES}
        nemu.compare_pairs(cases)
        for field in ('guest_pc_checks', 'guest_pc_trace', 'final_memory_bytes'):
            altered = copy.deepcopy(cases)
            altered['on-read-4096']['nemu'][field] = 'different'
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                nemu.compare_pairs(altered)
        cases['on-read-4096']['guest_sha256'] = 'different'
        with self.assertRaises(RuntimeError):
            nemu.compare_pairs(cases)


if __name__ == '__main__':
    unittest.main(verbosity=2)
