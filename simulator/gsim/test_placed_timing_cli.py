#!/usr/bin/env python3
"""Strict CLI closure only; never launches Scala, native tools, or hardware models."""
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from test_head_drain_cli import HeadDrainCliTests, export, options

FIELDS = ('retirement_intent', 'fetch_address_before_pmp', 'queued_head_selection',
          'aligned_next_line_pmp', 'register_probe_lookup', 'local_address_ranges')
FLAGS = tuple('--' + field.replace('_', '-') for field in FIELDS)


class PlacedTimingCliTests(HeadDrainCliTests):
    def test_all_flags_preserve_default52_and_round_trip_once(self):
        base = options('timing-batch-owner-row-profile.json')
        before = self.preflight(base)
        after = self.preflight([*base, '--predecoded-head-drain', *FLAGS])
        for field in FIELDS:
            self.assertFalse(before[field])
            self.assertNotIn(field, before['configuration'])
            self.assertTrue(after[field])
            self.assertTrue(after['configuration'][field])
        expected = {**before['configuration'], **dict.fromkeys(FIELDS, True),
                    'predecoded_head_drain': True, 'name': after['configuration']['name']}
        self.assertEqual(after['configuration'], expected)
        self.assertEqual(len(after['command'][5:]), 59)
        self.assertFalse(after['eager_fetch_prefix_select'])
        self.assertFalse(after['configuration'].get('future_home_way_reservation', False))
        self.assertFalse(after['configuration'].get('store_prefetch_lru_victim', False))

    def test_every_new_flag_is_strict_before_sources_or_emission(self):
        invalid = []
        for flag in FLAGS:
            invalid += [[flag, flag], [flag + 's'], [flag.replace('-', '_')]]
            invalid += [[flag + '=' + value] for value in ('', 'true', 'false', '0', '1')]
        invalid += [['--fetch-address-before-pmp'], ['--queued-head-selection']]
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

    def test_exact_profile_bridge_and_both_audits_are_fingerprinted(self):
        actual = export.sources()
        for name in ('PlacedTimingProfileBridge.scala', 'PlacedTimingActualAudit.scala',
                     'RetirementIntentActualAudit.scala'):
            self.assertIn('src/test/scala/ooo/' + name, actual)


if __name__ == '__main__':
    unittest.main()
