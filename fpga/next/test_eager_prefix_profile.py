#!/usr/bin/env python3
"""Explicit optional53 forwarding and exact default52 rollback; no hardware."""
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from test_owner_row_profile import OwnerRowProfileTests
import board_eager_prefix as candidate
import board_final as final


class EagerPrefixProfileTests(OwnerRowProfileTests):
    def test_optional53_preserves52_and_rejects_cli_drift(self):
        base = json.loads((HERE / 'timing-batch-owner-row-profile.json').read_text())['native_options']
        options = json.loads(candidate.MANIFEST.read_text())['native_options']
        self.assertEqual(options, base + [candidate.FLAG])
        self.assertEqual(len(options), 53)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'absent'
            off = self.native(path, base)
            on = self.native(path, options)
            restored = copy.deepcopy(on['configuration'])
            self.assertIs(restored.pop('eager_fetch_prefix_select'), True)
            restored['name'] = restored['name'].replace('-eager-fetch-prefix-select', '')
            self.assertEqual(restored, off['configuration'])
            self.assertNotIn('eager_fetch_prefix_select', off['configuration'])
            self.assertEqual(set(on['command'][5:]), set(options))
            gsim = self.gsim(['--aligned-fetch-permission-stage', candidate.FLAG])
            self.assertTrue(gsim['eager_fetch_prefix_select'])
            self.assertIn(candidate.FLAG, gsim['parameters'])
            for bad in ([candidate.FLAG], ['--aligned-fetch-permission-stage', candidate.FLAG, candidate.FLAG],
                        ['--aligned-fetch-permission-stage', candidate.FLAG[:-1]]):
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit): self.native(path, bad)
                    with self.assertRaises(SystemExit): self.gsim(bad)
            for value in ('', 'true', 'false', '0', '1'):
                bad = ['--aligned-fetch-permission-stage', candidate.FLAG + '=' + value]
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit): self.native(path, bad)
                    with self.assertRaises(SystemExit): self.gsim(bad)

    def test_separate_entry_preserves_final52_t1_user2(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'absent'
            with contextlib.redirect_stdout(io.StringIO()) as stream:
                candidate.main(['--output', str(path)])
            selected = json.loads(stream.getvalue())
            self.assertEqual(len(selected['command'][5:]), 53)
            self.assertIn(candidate.FLAG, selected['command'])
            self.assertIn('--experimental-jtag-bscan=2', selected['command'])
            self.assertEqual(selected['native_mac_mode'], final.exporter_module().board_t1.selection(True))
            with contextlib.redirect_stdout(io.StringIO()) as stream:
                final.main(['--output', str(path)])
            default = json.loads(stream.getvalue())
            self.assertEqual(len(default['command'][5:]), 52)
            self.assertNotIn(candidate.FLAG, default['command'])
            self.assertFalse(default['eager_fetch_prefix_select'])
            self.assertFalse(path.exists())
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                final.main(['--output', str(path), candidate.FLAG])


if __name__ == '__main__':
    unittest.main()
