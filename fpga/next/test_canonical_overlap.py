"""Host-only public option, complete preset, prerequisite and reversal checks."""
import contextlib
import copy
import io
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import export as exporter
import performance


class CanonicalOverlapOptions(unittest.TestCase):
    def preflight(self, entry, *flags):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'uncreated'
            capture = io.StringIO()
            with contextlib.redirect_stdout(capture):
                entry(['--output', str(output), *flags])
            self.assertFalse(output.exists())
            result = json.loads(capture.getvalue())
            result['command'][4] = 'OUTPUT'
            return result

    def test_recommendations_on_and_independent_v2_fallback_is_one_field(self):
        for controls in ((), ('--disable-posted',), ('--disable-posted-prefetch',)):
            off = self.preflight(performance.main, *controls, '--disable-canonical-store-overlap')
            on = self.preflight(performance.main, *controls)
            self.assertFalse(off['canonical_virtual_store_overlap'])
            self.assertTrue(on['canonical_virtual_store_overlap'])
            self.assertEqual(on['command'], off['command'] + ['--canonical-virtual-store-overlap'])
            adjusted = copy.deepcopy(on['configuration'])
            self.assertTrue(adjusted.pop('canonical_virtual_store_overlap'))
            adjusted['name'] = adjusted['name'].replace('-canonical-virtual-store-overlap', '')
            expected = dict(off['configuration'])
            self.assertFalse(expected.pop('canonical_virtual_store_overlap'))
            self.assertEqual(adjusted, expected)

    def test_board_preflight_has_same_default_guard_and_single_treatment(self):
        script = Path(__file__).resolve().parents[2] / 'simulator/gsim/fpga_next_board.py'
        base = [sys.executable, '-B', str(script), '--tag', 'canonical-cli-only', '--preflight-only',
                '--variant', 'selected']
        invalid = subprocess.run(base + ['--canonical-virtual-store-overlap'], capture_output=True, text=True)
        self.assertEqual(invalid.returncode, 2)
        self.assertIn('requires --virtual-ram-load-precheck', invalid.stderr)
        base += ['--virtual-ram-load-precheck']
        off = json.loads(subprocess.check_output(base, text=True))['plan']
        on = json.loads(subprocess.check_output(base + ['--canonical-virtual-store-overlap'], text=True))['plan']
        self.assertTrue(on['canonical_virtual_store_overlap'])
        on['canonical_virtual_store_overlap'] = False
        self.assertEqual(on['parameters'].pop(), '--canonical-virtual-store-overlap')
        self.assertEqual(on, off)

    def test_generic_path_requires_explicit_precheck_before_source_scan_or_emit(self):
        with mock.patch.object(exporter, 'sources') as sources, \
                mock.patch.object(exporter.subprocess, 'run') as emit, \
                contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                exporter.main(['--output', 'uncreated', '--canonical-virtual-store-overlap', '--emit'])
            self.assertEqual(error.exception.code, 2)
            sources.assert_not_called()
            emit.assert_not_called()

    def test_generic_legal_two_and_four_owners_do_not_imply_other_features(self):
        for owners in ('2', '4'):
            value = self.preflight(exporter.main, '--canonical-virtual-store-overlap',
                '--virtual-ram-load-precheck', '--lsu-entries', owners)
            self.assertTrue(value['configuration']['canonical_virtual_store_overlap'])
            self.assertEqual(value['configuration']['lsu_entries'], int(owners))
            for flag in ('posted_store_merge', 'posted_prefetch_coexistence', 'posted_prefetch_head_offer',
                         'translated_response_empty_flow', 'prechecked_data_flow'):
                self.assertFalse(value['configuration'][flag])

    def test_omitted_treatment_cannot_inherit_on_profile_qualification(self):
        original = exporter.main
        def dropped(args, expected_profile_sha256=None):
            return original([arg for arg in args if arg != '--canonical-virtual-store-overlap'],
                            expected_profile_sha256)
        with mock.patch.object(exporter, 'main', side_effect=dropped), \
                mock.patch.object(exporter, 'sources') as sources, \
                contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                performance.main(['--output', 'uncreated'])
            sources.assert_not_called()


if __name__ == '__main__':
    unittest.main()
