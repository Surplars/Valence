#!/usr/bin/env python3
"""Host-only timing batch routing and frozen source contract checks. No RTL runtime."""
import ast
import copy
import hashlib
import json
from pathlib import Path
import re
import tempfile
import unittest
import test_ddr_write_collection_cli as common

FLAGS = ['--registered-pending-store-query', '--aligned-fetch-permission-stage',
         '--registered-canonical-store-event']
FIELDS = ['registeredPendingStoreQuery', 'alignedFetchPermissionStage', 'registeredCanonicalStoreEvent']
ROOT = common.ROOT

class TimingBatchCliTests(unittest.TestCase):
    call = common.WriteCollectionCliTests.call

    def test_exact_maxperf_candidates_preserve_every_prior_option(self):
        contract = json.loads((ROOT/'simulator/gsim/tagged_store_return_board/contract.json').read_text())
        original = contract['native_options'] + ['--internal-line-grant',
            '--concurrent-read-store-prefetch', '--memory-schedule-overlap']
        self.assertEqual(len(original), 43)
        with tempfile.TemporaryDirectory(prefix='timing-batch-cli-') as tmp:
            off = self.call('fpga/next/export.py', ['--output', tmp+'/absent',
                *[x for x in original if x != '--selected']])
            self.assertEqual(set(off['command'][5:]), set(original))
            for name, stages in [('off', []), ('ac', [FLAGS[0], FLAGS[2]]), ('abc', FLAGS)]:
                saved = json.loads((ROOT/f'fpga/next/timing-batch-{name}-profile.json').read_text())
                self.assertEqual(set(saved['native_options']), set(original+stages))
                self.assertEqual(saved['native_option_count'], len(original+stages))
                on = self.call('fpga/next/export.py', ['--output', tmp+'/absent',
                    *[x for x in saved['native_options'] if x != '--selected']])
                self.assertEqual(set(on['command'][5:]), set(original+stages))
                self.assertEqual(len(on['command'][5:]), len(original+stages))
                config = copy.deepcopy(on['configuration'])
                for flag in stages:
                    self.assertIs(config.pop(flag[2:].replace('-', '_')), True)
                    config['name'] = config['name'].replace(flag[1:], '')
                self.assertEqual(config, off['configuration'])
                self.assertTrue(on['configuration']['tagged_store_returns'])
                self.assertEqual(on['configuration']['bscan_chain'], 2)
            self.assertFalse(Path(tmp, 'absent').exists())

    def test_gsim_front_door_forwards_only_explicit_stage_choices(self):
        common_options = ['--virtual-ram-load-precheck', '--canonical-virtual-store-overlap',
            '--frozen-store-proof-transport', '--pending-virtual-store-proof',
            '--lsu-entries=4', '--data-translation-entries=16', '--load-order-older-retire',
            '--pending-virtual-store-proof-slots=2', '--pending-store-early-load-credits=2']
        for stages in ([], [FLAGS[0], FLAGS[2]], FLAGS):
            result = self.call('simulator/gsim/fpga_next_board.py',
                ['--tag', 'timing-batch-cli', '--preflight-only', '--variant', 'selected',
                 *common_options, *stages])
            for flag in FLAGS:
                self.assertEqual(result['plan']['parameters'].count(flag), int(flag in stages))
                self.assertIs(result['plan'][flag[2:].replace('-', '_')], flag in stages)
            self.assertFalse(Path(result['output']).exists())

    def test_duplicate_valued_and_missing_canonical_prerequisite_rejected(self):
        bad = [[FLAGS[2]], [FLAGS[2], '--virtual-ram-load-precheck']]
        for flag in FLAGS[1:]:
            bad.extend([[flag, flag], *[[flag+'='+value] for value in ('true','false','0','1')]])
        with tempfile.TemporaryDirectory(prefix='timing-batch-bad-') as tmp:
            for options in bad:
                self.call('fpga/next/export.py', ['--output', tmp+'/absent', *options], False)
                self.call('simulator/gsim/fpga_next_board.py',
                    ['--tag', 'timing-batch-bad', '--preflight-only', *options], False)
            self.assertFalse(Path(tmp, 'absent').exists())

    def test_frozen_bank_and_final_complete_field_counts(self):
        bank = ROOT/'src/main/scala/core/ooo/PendingVirtualStoreProof.scala'
        source = bank.read_text()
        self.assertEqual(source.count('p: OooParams, val registerQuery: Boolean'), 1)
        qualified = source.replace('p: OooParams, val registerQuery: Boolean',
            'p: OooParams, registerQuery: Boolean')
        self.assertEqual(hashlib.sha256(qualified.encode()).hexdigest(),
            'a489d9bd803730f584ef9c65f15e113276aed38a9f87bb0d0776f42d5b6eb2ce')
        for kind, count in [('OooParams',155), ('FpgaNextConfig',65)]:
            text = (ROOT/f'src/main/scala/core/ooo/{kind}.scala').read_text()
            ctor = text.split('case class '+kind+'(',1)[1].split('\n) {',1)[0]
            fields = re.findall(r'^\s*(\w+):',ctor,re.M)
            self.assertEqual(len(fields), count)
            for field in FIELDS:
                self.assertIn(field+': Boolean = false', ctor)
        for name in ('DataTranslationAdapter','IntegerBackend'):
            self.assertIn('require(registerCanonicalStoreEvent == p.registeredCanonicalStoreEvent,',
                (ROOT/f'src/main/scala/core/ooo/{name}.scala').read_text())
        for name in ('MachineCore','MappedMachineCore'):
            text = (ROOT/f'src/main/scala/core/ooo/{name}.scala').read_text()
            for binding in ('core.io.instructionFaultOffsets.get := io.instructionFaultOffsets.get',
                'io.fetchRequestFrontier.get := core.io.fetchRequestFrontier.get',
                'io.suppressFetchRequest.get := core.io.suppressFetchRequest.get'):
                self.assertIn(binding, text)

    def test_cpu_runner_retains_original_guest_host_services_and_no_old_total_acceptance(self):
        text = (ROOT/'simulator/gsim/timing_batch_cpu.py').read_text()
        ast.parse(text)
        self.assertIn("choices=(1,), default=1", text)
        self.assertIn("baseline must be pristine tracked 1e90 source", text)
        self.assertIn("candidate execution requires a verified fresh baseline receipt", text)
        self.assertIn("row = capture_result(text, work, spec['baseline_cases'][name], actual)", text)
        for name in ('production_probe.h', 'supply_ledger.h', 'passive_supply.h', 'cpu_sv39_bandwidth.S',
            'cpu_hot_bandwidth.ld', 'cpu_passive_bandwidth.cpp'):
            self.assertIn(name, text)
        for old in ('236951','260694','202290','215747','196524','197722'):
            self.assertNotIn(old,text)

if __name__ == '__main__':
    unittest.main()
