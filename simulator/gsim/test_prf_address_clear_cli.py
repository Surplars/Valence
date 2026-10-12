#!/usr/bin/env python3
"""Public flag forwarding and strict default-OFF compatibility; no hardware run."""
import json
import tempfile
import unittest
from pathlib import Path
import test_ddr_write_collection_cli as common

FLAG = '--direct-rank1-memory-source-ids'
class Rank1PrfAddressCliTests(unittest.TestCase):
    call = common.WriteCollectionCliTests.call
    def test_explicit_export_and_gsim_routing(self):
        with tempfile.TemporaryDirectory(prefix='rank1-prf-cli-') as tmp:
            off = self.call('fpga/next/export.py', ['--output', tmp+'/absent'])
            on = self.call('fpga/next/export.py', ['--output', tmp+'/absent', FLAG])
            self.assertNotIn(FLAG, off['command'])
            self.assertEqual(on['command'], off['command']+[FLAG])
            self.assertFalse(off['configuration'].get('direct_rank1_memory_source_ids', False))
            self.assertTrue(on['configuration']['direct_rank1_memory_source_ids'])
            for flags in ([], [FLAG]):
                result = self.call('simulator/gsim/fpga_next_board.py',
                    ['--tag', 'rank1-prf-cli', '--preflight-only', *flags])
                self.assertEqual(result['plan']['parameters'].count(FLAG), len(flags))
                self.assertIs(result['plan']['direct_rank1_memory_source_ids'], bool(flags))
            self.assertFalse(Path(tmp, 'absent').exists())
    def test_ambiguous_flags_rejected(self):
        bad = [[FLAG, FLAG], *[[FLAG+'='+v] for v in ('true', 'false', '0', '1')]]
        with tempfile.TemporaryDirectory(prefix='rank1-prf-bad-') as tmp:
            for flags in bad:
                self.call('fpga/next/export.py', ['--output', tmp+'/absent', *flags], False)
                self.call('simulator/gsim/fpga_next_board.py',
                    ['--tag', 'rank1-prf-bad', '--preflight-only', *flags], False)
    def test_old_profiles_remain_explicitly_off(self):
        root=common.ROOT
        for name in ('timing-batch-abc-profile.json','timing-batch-abc-lane1-owner-profile.json'):
            old=json.loads((root/'fpga/next'/name).read_text())
            self.assertNotIn(FLAG,old['native_options'])
        source=(root/'src/main/scala/core/ooo/OooParams.scala').read_text()
        self.assertIn('directRank1MemorySourceIds: Boolean = false',source)
        self.assertIn('p.directRank1MemorySourceIds && rank == 1',
            (root/'src/main/scala/core/ooo/IntegerBackend.scala').read_text())
if __name__=='__main__': unittest.main()
