#!/usr/bin/env python3
"""Host-only explicit query-stage routing; no Scala or backend qualification."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
import test_ddr_write_collection_cli as common

FLAG='--registered-pending-store-query'
PREREQUISITES=['--virtual-ram-load-precheck','--canonical-virtual-store-overlap',
 '--frozen-store-proof-transport','--pending-virtual-store-proof',
 '--lsu-entries=4','--data-translation-entries=16','--load-order-older-retire']

class RegisteredPendingStoreQueryCliTests(unittest.TestCase):
    call=common.WriteCollectionCliTests.call
    def test_stage_is_only_explicit_delta_for_both_rows(self):
        with tempfile.TemporaryDirectory(prefix='query-stage-cli-') as tmp:
            for rows in (1,2):
                options=PREREQUISITES+[f'--pending-virtual-store-proof-slots={rows}']
                native=['--output',tmp+'/absent',*options]
                board=['--tag','query-stage-cli','--preflight-only','--variant','selected',*options]
                off=self.call('fpga/next/export.py',native)
                on=self.call('fpga/next/export.py',native+[FLAG])
                board_off=self.call('simulator/gsim/fpga_next_board.py',board)
                board_on=self.call('simulator/gsim/fpga_next_board.py',board+[FLAG])
                self.assertEqual(on['command'].count(FLAG),1)
                self.assertEqual([x for x in on['command'] if x!=FLAG],off['command'])
                # The board driver omits explicit default rows=1; normalize only that old behavior.
                normalize=lambda xs:[x for x in xs if x!='--pending-virtual-store-proof-slots=1']
                self.assertEqual(normalize(on['command'][5:]),normalize(board_on['plan']['parameters']))
                config=copy.deepcopy(on['configuration'])
                self.assertIs(config.pop('registered_pending_store_query'),True)
                config['name']=config['name'].replace('-registered-pending-store-query','')
                self.assertEqual(config,off['configuration'])
                plan=copy.deepcopy(board_on['plan'])
                self.assertIs(plan['registered_pending_store_query'],True)
                plan['registered_pending_store_query']=False;plan['parameters'].remove(FLAG)
                self.assertEqual(plan,board_off['plan'])
                self.assertFalse(Path(board_on['output']).exists())
            self.assertFalse(Path(tmp,'absent').exists())
    def test_prerequisite_duplicates_and_valued_forms_fail_closed(self):
        cases=[[FLAG],[*PREREQUISITES,FLAG,FLAG],
            *[[*PREREQUISITES,FLAG+'='+v] for v in ['true','false','0','1']],
            [*[p for p in PREREQUISITES if p!='--pending-virtual-store-proof'],FLAG]]
        with tempfile.TemporaryDirectory(prefix='query-stage-cli-bad-') as tmp:
            for options in cases:
                self.call('fpga/next/export.py',['--output',tmp+'/absent',*options],False)
                self.call('simulator/gsim/fpga_next_board.py',
                    ['--tag','query-stage-cli-bad','--preflight-only',*options],False)
            self.assertFalse(Path(tmp,'absent').exists())
    def test_complete_saved_native_profile_only_adds_stage(self):
        profile=json.loads((common.ROOT/'fpga/next/board-dual-proof-credit-profile-v1.json').read_text())
        options=[o for o in profile['native_options'] if o!='--selected']
        with tempfile.TemporaryDirectory(prefix='query-stage-full-cli-') as tmp:
            args=['--output',tmp+'/absent',*options]
            off=self.call('fpga/next/export.py',args)
            on=self.call('fpga/next/export.py',args+[FLAG])
            self.assertEqual([x for x in on['command'] if x!=FLAG],off['command'])
            config=copy.deepcopy(on['configuration']);self.assertIs(config.pop('registered_pending_store_query'),True)
            config['name']=config['name'].replace('-registered-pending-store-query','')
            self.assertEqual(config,off['configuration'])
            self.assertNotIn('registered_pending_store_query',off['configuration'])
            self.assertFalse(Path(tmp,'absent').exists())

    def test_exact_current_maxperf_keeps_tagged_returns_and_all_43_options(self):
        contract=json.loads((common.ROOT/'simulator/gsim/tagged_store_return_board/contract.json').read_text())
        expected=contract['native_options']+['--internal-line-grant',
            '--concurrent-read-store-prefetch','--memory-schedule-overlap']
        self.assertEqual(len(expected),43)
        options=[o for o in expected if o!='--selected']
        with tempfile.TemporaryDirectory(prefix='query-stage-maxperf-cli-') as tmp:
            args=['--output',tmp+'/absent',*options]
            off=self.call('fpga/next/export.py',args)
            on=self.call('fpga/next/export.py',args+[FLAG])
            self.assertEqual(set(off['command'][5:]),set(expected))
            self.assertEqual(len(off['command'][5:]),43)
            self.assertEqual(on['command'].count(FLAG),1)
            self.assertEqual([x for x in on['command'] if x!=FLAG],off['command'])
            self.assertTrue(off['configuration']['tagged_store_returns'])
            config=copy.deepcopy(on['configuration']);self.assertIs(config.pop('registered_pending_store_query'),True)
            config['name']=config['name'].replace('-registered-pending-store-query','')
            self.assertEqual(config,off['configuration'])
            self.assertFalse(Path(tmp,'absent').exists())


if __name__=='__main__':unittest.main()
