#!/usr/bin/env python3
"""Static export/manifest checks only. No Scala, GSIM, CPU or RTL execution."""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
FLAG = '--predecoded-head-drain'
spec = importlib.util.spec_from_file_location('head_drain_export', ROOT / 'fpga/next/export.py')
export = importlib.util.module_from_spec(spec)
spec.loader.exec_module(export)


def options(name):
    return json.loads((ROOT / 'fpga/next' / name).read_text())['native_options']


class HeadDrainCliTests(unittest.TestCase):
    def preflight(self, native):
        # --selected is export.py's default. It is explicit in the native vector.
        args = [arg for arg in native if arg != '--selected']
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'never-created'
            stdout = io.StringIO()
            with mock.patch.object(export.subprocess, 'run', side_effect=AssertionError('no emission allowed')), \
                    mock.patch.object(export.subprocess, 'check_output', return_value='0' * 40), \
                    contextlib.redirect_stdout(stdout):
                export.main(['--output', str(output), *args])
            self.assertFalse(output.exists())
            value = json.loads(stdout.getvalue())
            self.assertEqual(value['status'], 'PREFLIGHT_ONLY')
            self.assertFalse(value['physical_qualification'])
            self.assertEqual(value['command'][:4], ['mill', '-i', 'IonSoC.test.runMain', 'ooo.FpgaNextMain'])
            actual = value['command'][5:]
            self.assertEqual(len(actual), len(set(actual)))
            self.assertEqual(set(actual), set(native))
            return value

    def test_independent_default52_and_single_flag53(self):
        path = ROOT / 'fpga/next/timing-batch-owner-row-profile.json'
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),
                         '32063adb7dd598ea5fcd014eee71c02d599139a59bf69287598f780a35d6d923')
        default = options(path.name)
        self.assertEqual(len(default), 52)
        before = self.preflight(default)
        after = self.preflight([*default, FLAG])
        self.assertFalse(before['predecoded_head_drain'])
        self.assertNotIn('predecoded_head_drain', before['configuration'])
        self.assertTrue(after['predecoded_head_drain'])
        self.assertEqual(after['configuration']['name'].count('-predecoded-head-drain'), 1)
        self.assertEqual(after['configuration']['name'].replace('-predecoded-head-drain', ''),
                         before['configuration']['name'])
        expected = {**before['configuration'], 'predecoded_head_drain': True,
                    'name': after['configuration']['name']}
        self.assertEqual(after['configuration'], expected)
        self.assertFalse(after['eager_fetch_prefix_select'])

    def test_future_lru54_plus_flag55_is_parameter_compatibility_only(self):
        default = options('timing-batch-owner-row-profile.json')
        future = options('timing-batch-home-future-lru-profile.json')
        self.assertEqual(future, [*default, '--future-home-way-reservation', '--store-prefetch-lru-victim'])
        value = self.preflight([*future, FLAG])
        self.assertEqual(len(value['command'][5:]), 55)
        self.assertTrue(value['predecoded_head_drain'])
        self.assertTrue(value['configuration']['future_home_way_reservation'])
        self.assertTrue(value['configuration']['store_prefetch_lru_victim'])
        self.assertFalse(value['eager_fetch_prefix_select'])

    def test_rejected_spellings_never_emit_or_create_output(self):
        invalid = [[FLAG, FLAG], [FLAG[:-1]], [FLAG + 's'], ['--predecoded_head_drain']]
        invalid += [[FLAG + '=' + value] for value in ('', 'true', 'false', '0', '1')]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'absent'
            for args in invalid:
                with self.subTest(args=args), mock.patch.object(export.subprocess, 'run') as run, \
                        mock.patch.object(export, 'sources') as sources, \
                        contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    export.main(['--output', str(output), *args])
                run.assert_not_called()
                sources.assert_not_called()
                self.assertFalse(output.exists())

    def test_new_logic_and_native_actual_audit_are_in_export_source_fingerprint(self):
        actual = export.sources()
        for name in ('src/main/scala/core/ooo/HeadDrainClass.scala',
                     'src/main/scala/core/ooo/IntegerBackend.scala',
                     'src/main/scala/core/ooo/OooParams.scala',
                     'src/main/scala/core/ooo/FpgaNextConfig.scala',
                     'src/main/scala/core/ooo/BoardSocTop.scala',
                     'src/test/scala/ooo/FpgaNextProfileMain.scala',
                     'src/test/scala/ooo/HeadDrainActualAudit.scala'):
            self.assertEqual(actual[name], hashlib.sha256((ROOT / name).read_bytes()).hexdigest())


if __name__ == '__main__':
    unittest.main()
