#!/usr/bin/env python3
"""Host-only acceptance/rejection checks. Never launches Java or a simulator."""
import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("lifecycle", HERE / "run_r16_lifecycle.py")
life = importlib.util.module_from_spec(spec)
spec.loader.exec_module(life)

class LifecycleTests(unittest.TestCase):
    def test_catalog_and_public_sources(self):
        data, ext = life.catalog()
        life.gate.check_hashes(life.gate.PUBLIC_ROOT, data["publicInputs"])
        self.assertEqual([c["counts"]["cycles"] for c in ext["historicalCases"]], [454, 461, 486, 189])
        self.assertEqual(len(data["publicTestInputs"]), 3)
        self.assertEqual(ext["relocatedPublicRuntime"], "NOT_RUN")

    def test_counts_and_conservation(self):
        _, ext = life.catalog()
        for case in ext["historicalCases"]:
            counts = case["counts"]
            text = 'RESULT ' + ' '.join(f'{k}={v}' for k,v in counts.items())
            self.assertEqual(life.gate.check_runtime(0, text, counts), counts)
            with self.assertRaises(ValueError):
                life.gate.check_runtime(1, text, counts)
            with self.assertRaises(ValueError):
                life.gate.check_runtime(0, text.replace('cycles=', 'wrong='), counts)
            with self.assertRaises(ValueError):
                life.gate.check_runtime(0, 'AddressSanitizer\n' + text, counts)

    def test_negative_requires_oracle_and_exact_trace(self):
        with tempfile.TemporaryDirectory() as temp:
            trace = Path(temp) / 'trace'
            trace.write_text('synthetic host-unit-test only\n')
            ext = {'negativeTraceSha256': life.gate.sha(trace)}
            life.check_negative(1, 'BOUND diagnostic\nFAIL independent row payload mismatch\n', trace, ext)
            for code, text in [(0, 'FAIL independent row payload mismatch'), (1, 'FAIL timeout'),
                               (1, 'AddressSanitizer\nFAIL independent row payload mismatch'),
                               (1, 'RESULT x=1\nFAIL independent row payload mismatch')]:
                with self.assertRaises(ValueError):
                    life.check_negative(code, text, trace, ext)
            trace.write_text('different failure point')
            with self.assertRaises(ValueError):
                life.check_negative(1, 'FAIL independent row payload mismatch', trace, ext)

    def test_trace_width_order_and_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            trace = Path(temp) / 'trace'
            lines = ['0 status', ' '.join(['0']*276), ' '.join(['0']*145)]
            trace.write_text('\n'.join(lines)+'\n')
            case = {'counts': {'cycles': 1}, 'trace_sha256': life.gate.sha(trace)}
            life.check_trace(trace, case)
            for altered in [lines[:-1], ['1 status', *lines[1:]], [lines[0], '0', lines[2]],
                            [*lines[:2], '0'], [lines[0], lines[1].replace('0', '1', 1), lines[2]]]:
                trace.write_text('\n'.join(altered)+'\n')
                with self.assertRaises(ValueError):
                    life.check_trace(trace, case)

    def test_negative_source_is_only_one_catalog_change(self):
        positive, ext = life.catalog()
        negative, _ = life.catalog(True)
        differing = [key for key in positive['sources'] if positive['sources'][key] != negative['sources'][key]]
        self.assertEqual(differing, [ext['mutation']['source']])
        self.assertEqual(positive['publicInputs'], negative['publicInputs'])

if __name__ == '__main__':
    unittest.main()
