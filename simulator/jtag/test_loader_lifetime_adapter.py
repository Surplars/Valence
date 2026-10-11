"""Exact-fixture adapter checks. Supply VALENCE_BOARD_LOADER_FIXTURE for positives."""
import importlib.util
import os
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('loader_lifetime_adapter', Path(__file__).with_name('lower_board_loader_for_icarus.py'))
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)
FIXTURE = os.environ.get('VALENCE_BOARD_LOADER_FIXTURE')


class LoaderLifetimeTests(unittest.TestCase):
    def test_unknown_original_rejected(self):
        with self.assertRaisesRegex(ValueError, 'unreviewed loader fixture'):
            adapter.lower('module Anything; endmodule\n')

    def test_unreviewed_output_rejected(self):
        with self.assertRaisesRegex(ValueError, 'initializer projection'):
            adapter.verify_adapted('logic temporary;\n')

    @unittest.skipUnless(FIXTURE, 'source-bound board loader fixture is optional and never generated here')
    def test_positive_exact_fixture_and_assignment_proof(self):
        result, receipt = adapter.lower(Path(FIXTURE).read_text())
        self.assertEqual(receipt['original_sha256'], adapter.REVIEWED_SHA256)
        self.assertEqual(receipt['adapted_sha256'], adapter.ADAPTED_SHA256)
        self.assertEqual(receipt['automatic_declarations'], 78)
        self.assertEqual(receipt['per_entry_initializers'], 5)
        self.assertFalse(receipt['source_rtl_modified'])
        self.assertFalse(receipt['production_timeout_changed'])
        self.assertIn("ticks == 20'hF423F", result)
        self.assertNotIn('automatic', result)
        adapter.verify_adapted(result)

    @unittest.skipUnless(FIXTURE, 'source-bound board loader fixture is optional and never generated here')
    def test_delay_or_source_drift_rejected(self):
        text = Path(FIXTURE).read_text()
        for mutant in (text+'\n', text.replace('always @(posedge clock) begin', 'always @(posedge clock) begin #1;'),
                       text.replace('automatic logic        busy;', 'automatic logic        busy = busy;')):
            with self.subTest(mutant=mutant[:20]), self.assertRaisesRegex(ValueError, 'unreviewed loader fixture'):
                adapter.lower(mutant)

    @unittest.skipUnless(FIXTURE, 'source-bound board loader fixture is optional and never generated here')
    def test_dropped_or_reordered_entry_initializers_rejected(self):
        result, _ = adapter.lower(Path(FIXTURE).read_text())
        first = "      _GEN_42 = io_memory_request_ready & offered;"
        second = "      _GEN_43 = ~_GEN_42 & offered;"
        self.assertIn(first+'\n'+second, result)
        for mutant in (result.replace(first, ''), result.replace(first+'\n'+second, second+'\n'+first),
                       result.replace("    _GEN_9 = sbError == 3'h0;", '')):
            with self.assertRaisesRegex(ValueError, 'initializer projection'):
                adapter.verify_adapted(mutant)


if __name__ == '__main__':
    unittest.main()
