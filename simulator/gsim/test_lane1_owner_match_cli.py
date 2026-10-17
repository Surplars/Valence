#!/usr/bin/env python3
"""Small front-door and source-boundary checks; no hardware execution."""
import tempfile
import unittest
from pathlib import Path
import test_ddr_write_collection_cli as common

FLAG = '--shared-lane1-owner-match'
ROOT = common.ROOT

class Lane1OwnerMatchCliTests(unittest.TestCase):
    call = common.WriteCollectionCliTests.call

    def test_explicit_export_and_gsim_routing(self):
        with tempfile.TemporaryDirectory(prefix='lane1-owner-cli-') as tmp:
            off = self.call('fpga/next/export.py', ['--output', tmp+'/absent'])
            on = self.call('fpga/next/export.py', ['--output', tmp+'/absent', FLAG])
            self.assertNotIn(FLAG, off['command'])
            self.assertEqual(on['command'], off['command']+[FLAG])
            self.assertTrue(on['configuration']['shared_lane1_owner_match'])
            for flags in ([], [FLAG]):
                result = self.call('simulator/gsim/fpga_next_board.py',
                    ['--tag', 'lane1-owner-cli', '--preflight-only', *flags])
                self.assertEqual(result['plan']['parameters'].count(FLAG), len(flags))
                self.assertIs(result['plan']['shared_lane1_owner_match'], bool(flags))
            self.assertFalse(Path(tmp, 'absent').exists())

    def test_ambiguous_flags_rejected(self):
        bad = [[FLAG, FLAG], *[[FLAG+'='+v] for v in ('true', 'false', '0', '1')]]
        with tempfile.TemporaryDirectory(prefix='lane1-owner-bad-') as tmp:
            for flags in bad:
                self.call('fpga/next/export.py', ['--output', tmp+'/absent', *flags], False)
                self.call('simulator/gsim/fpga_next_board.py',
                    ['--tag', 'lane1-owner-bad', '--preflight-only', *flags], False)

    def test_pure_query_and_final_prf_scope(self):
        rob = (ROOT/'src/main/scala/core/ooo/retire/RenameRob.scala').read_text()
        query = rob.split('\n    val lane1OwnerMatch = if ', 1)[1].split('\n\n', 1)[0]
        self.assertIn('entries(io.complete(1).bits.token.index).tag === io.complete(1).bits.token.tag', query)
        for forbidden in ('valid', 'count', 'head', 'done', 'accepted', 'Reg(', 'RegInit('):
            self.assertNotIn(forbidden, query)
        backend = (ROOT/'src/main/scala/core/ooo/integration/IntegerBackend.scala').read_text()
        self.assertIn('if (p.sharedLane1OwnerMatch && lane == 1) ledger.io.lane1OwnerMatch.get', backend)
        self.assertIn('stage.io.cancel := stage.io.occupied && (killed(ownerIndex) || stale)', backend)
        self.assertIn('assert(queueOwnerMatches === ownerMatches,', backend)
        self.assertIn('!ledger.io.complete(lane).bits.exception && completedEntry.renamed.writesRd', backend)

if __name__ == '__main__':
    unittest.main()
