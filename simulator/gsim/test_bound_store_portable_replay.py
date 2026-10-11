#!/usr/bin/env python3
"""Source-only replay boundary checks. Never invokes Mill, GSIM, or a compiler."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import bound_store_prefetch_cpu as cpu
import bound_store_replay_common as common
from bound_store_service_oracle import verify_service

ROOT = Path(__file__).resolve().parents[2]
GSIM = ROOT / 'simulator/gsim'


class PortableReplayTests(unittest.TestCase):
    def invoke(self, name, *args):
        return subprocess.run([sys.executable, str(GSIM / name), *map(str, args)], cwd=ROOT,
                              text=True, capture_output=True)

    def test_component_object_relink_is_not_an_unbound_reuse_route(self):
        for name in ('pending_store_proof_integration.py', 'bound_head_store_overlap.py', 'translated_frozen_proof.py'):
            result = self.invoke(name, 'relink', '--output', '/unused')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("invalid choice: 'relink'", result.stderr)

    def test_staged_runners_reject_added_generated_inputs_before_compiler(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory);marker = base / 'tool-ran';tool = base / 'tool'
            tool.write_text('#!/bin/sh\ntouch "' + str(marker) + '"\nexit 99\n');tool.chmod(0o755)
            cases = [('pending_store_proof.py', 'bank1', 'asan'),
                     ('pending_store_proof_integration.py', 'transport', 'sanitized'),
                     ('bound_head_store_overlap.py', 'backend', 'sanitized')]
            for script, model, stage in cases:
                out = base / script
                args = ['--output', out, '--models', model, '--mill', tool, '--gsim', tool, '--cxx', tool]
                frozen = self.invoke(script, 'freeze', *args)
                self.assertEqual(frozen.returncode, 0, frozen.stderr)
                folder = out / model;folder.mkdir()
                known = folder / 'Model0.cpp';known.write_text('known generated unit')
                receipt = out / 'receipt.json';state = json.loads(receipt.read_text())
                state['completed_stages'] = ['emit', 'generate']
                state['model_artifacts'] = {model + '/Model0.cpp': common.sha(known)}
                receipt.write_text(json.dumps(state))
                for name in ('Model1.cpp', 'extra.h'):
                    added = folder / name;added.write_text('unbound generated input')
                    result = self.invoke(script, stage, *args)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('unbound model input', result.stderr)
                    self.assertFalse(marker.exists())
                    added.unlink()

    def test_cpu_guard_rejects_extra_generated_inputs_for_both_modes(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory);binding = {}
            for mode in ('old', 'new'):
                folder = out / mode / 'model';folder.mkdir(parents=True)
                source = folder / 'BoardSocGsim0.cpp';source.write_text('known unit')
                binding[str(source.relative_to(out))] = common.sha(source)
            cpu.verify_model_closure(out, binding)
            for mode in ('old', 'new'):
                for name in ('BoardSocGsim1.cpp', 'injected.h'):
                    added = out / mode / 'model' / name;added.write_text('unbound input')
                    with self.subTest(mode=mode, name=name), self.assertRaisesRegex(AssertionError, 'unbound model input'):
                        cpu.verify_model_closure(out, binding)
                    added.unlink()

    def test_generated_model_closure_rejects_extra_translation_unit_or_header(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = root / 'Model0.cpp';original.write_text('known translation unit')
            mapping = {'Model0.cpp': common.sha(original)}
            common.verify_model_inputs(root, mapping)
            for name in ('Model1.cpp', 'unbound.h'):
                added = root / name;added.write_text('unbound input')
                with self.subTest(name=name), self.assertRaisesRegex(AssertionError, 'unbound model input'):
                    common.verify_model_inputs(root, mapping)
                added.unlink()

    def test_compact_frozen_reference_and_source_only_wrapper(self):
        import translated_frozen_proof as compact
        compact.validate_source(ROOT)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in (compact.REFERENCE, compact.BINDING, 'src/test/scala/ooo/PendingStoreProofGsim.scala'):
                target = root / name;target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((ROOT / name).read_bytes())
            ref = root / compact.REFERENCE;ref.write_bytes(ref.read_bytes() + b'// changed\n')
            with self.assertRaisesRegex(AssertionError, 'frozen independent reference drift'):
                compact.validate_source(root)

    def test_component_preflight_creates_no_output_and_runs_no_tool(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            marker = base / 'must-not-exist'
            tool = base / 'tool'
            tool.write_text('#!/bin/sh\ntouch "' + str(marker) + '"\nexit 99\n')
            tool.chmod(0o755)
            for name in ('pending_store_proof.py', 'pending_store_proof_integration.py',
                         'bound_head_store_overlap.py', 'read_prefetch_store_hold.py', 'translated_frozen_proof.py'):
                output = base / name
                positional = [] if name == 'read_prefetch_store_hold.py' else ['freeze']
                result = self.invoke(name, *positional, '--output', output, '--mill', tool,
                                     '--gsim', tool, '--cxx', tool, '--preflight-only')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)['status'], 'PREFLIGHT_ONLY_NO_EXECUTION')
                self.assertFalse(output.exists())
                self.assertFalse(marker.exists())

    def test_fresh_freeze_and_missing_stage_do_not_run_tools(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);tool=base/'tool';marker=base/'must-not-run'
            tool.write_text('#!/bin/sh\ntouch "'+str(marker)+'"\nexit 99\n');tool.chmod(0o755)
            output=base/'evidence'
            paths=['--output',output,'--mill',tool,'--gsim',tool,'--cxx',tool]
            frozen=self.invoke('pending_store_proof.py','freeze',*paths)
            self.assertEqual(frozen.returncode,0,frozen.stderr)
            receipt=json.loads((output/'receipt.json').read_text())
            self.assertEqual(receipt['status'],'SOURCE_FROZEN')
            self.assertNotIn('grant',receipt)
            failed=self.invoke('pending_store_proof.py','generate',*paths)
            self.assertNotEqual(failed.returncode,0)
            self.assertIn('missing stage: emit',failed.stderr)
            self.assertFalse(marker.exists())
            self.assertFalse((output/'run-grant.json').exists())

    def test_missing_cpu_artifacts_request_exact_files_before_output_or_tools(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / 'output'
            result = self.invoke('bound_store_prefetch_cpu.py', '--reference-root', directory,
                                 '--output', out, '--preflight-only')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('missing immutable reference artifacts', result.stderr)
            self.assertIn('contract.json sha256=031c88da37dee48c0', result.stderr)
            self.assertFalse(out.exists())

    def test_artifact_request_is_complete_without_tools(self):
        result = self.invoke('bound_store_prefetch_cpu.py', '--list-required')
        self.assertEqual(result.returncode, 0, result.stderr)
        request = json.loads(result.stdout)
        self.assertEqual(request['status'], 'EXTERNAL_ARTIFACT_REQUEST')
        self.assertEqual(len(request['files']), 7)
        self.assertTrue(all(len(value) == 64 for value in request['files'].values()))
        self.assertTrue(all(not Path(name).is_absolute() for name in request['files']))

    def test_historical_receipts_are_not_model_reuse_grants(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'receipt.json'
            path.write_text(json.dumps({'schema': 'read-prefetch-store-hold-component-v1',
                                       'status': 'PASS_COMPONENT_ONLY'}))
            with self.assertRaisesRegex(ValueError, 'historical receipt is evidence only'):
                common.verified_receipt(directory, common.sha(path))
            with self.assertRaisesRegex(ValueError, 'digest mismatch'):
                common.verified_receipt(directory, '0' * 64)
            with self.assertRaisesRegex(ValueError, 'external reuse needs'):
                common.verified_receipt(directory, None)

    def test_source_closure_catches_untracked_scala_and_freezes_helper(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('build.mill', '.mill-version', '.mill-jvm-opts'):
                (root / name).write_text(name)
            helper = root / 'helper.py';helper.write_text('source binding helper')
            with patch.object(common, '__file__', str(helper)):
                first = common.source_inputs(root)
                added = root / 'src/test/scala/Untracked.scala';added.parent.mkdir(parents=True)
                added.write_text('class Untracked')
                second = common.source_inputs(root)
            self.assertNotEqual(first, second)
            self.assertIn('src/test/scala/Untracked.scala', second)
            self.assertIn('helper.py', second)

    def test_artifact_drift_and_unsafe_paths_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory);artifact = root / 'model.o';artifact.write_bytes(b'old')
            mapping = {'model.o': common.sha(artifact)}
            common.verify_artifacts(root, mapping)
            artifact.write_bytes(b'new')
            with self.assertRaisesRegex(AssertionError, 'artifact drift'):
                common.verify_artifacts(root, mapping)
            with self.assertRaisesRegex(AssertionError, 'unsafe artifact path'):
                common.verify_artifacts(root, {'../model.o': '0' * 64})

    def test_model_reuse_rejects_unbound_extra_units(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);obj=root/'Model0.o';obj.write_bytes(b'bound')
            mapping={obj.name:common.sha(obj)}
            common.verify_model_inputs(root,mapping)
            (root/'Model1.o').write_bytes(b'unknown')
            with self.assertRaisesRegex(AssertionError,'unbound model input'):
                common.verify_model_inputs(root,mapping)

    def test_reuse_binds_actual_compiler_dependency_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);header=root/'header.h';header.write_text('old header')
            dep=root/'unit.d';dep.write_text('unit.o: '+str(header)+'\n')
            binding={};common.record_dependencies(dep,root,binding)
            common.check_dependencies(binding)
            header.write_text('changed header')
            with self.assertRaisesRegex(AssertionError,'compiler dependency drift'):
                common.check_dependencies(binding)
            with self.assertRaisesRegex(AssertionError,'captured compiler dependencies'):
                common.check_dependencies({})

    def test_reference_digest_drift_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory);file = root/'contract.json';file.write_text('{}')
            manifest = {'contract.json': common.sha(file)}
            cpu.checked_references(root, manifest)
            file.write_text('{"altered":true}')
            with self.assertRaisesRegex(ValueError, 'reference digest mismatch'):
                cpu.checked_references(root, manifest)

    def test_parse_rejects_duplicate_records_and_fields(self):
        with self.assertRaises(AssertionError):cpu.parse('PASS a=1\nPASS a=1', 'PASS')
        with self.assertRaises(AssertionError):cpu.parse('PASS a=1 a=2', 'PASS')
        self.assertEqual(cpu.parse('PASS a=1 b=2', 'PASS'), {'a': '1', 'b': '2'})

    def test_fresh_old_backend_keeps_overlap_disabled(self):
        import bound_head_store_overlap as overlap
        self.assertEqual(overlap.MODELS['oldbackend'][2], ['1', '0'])
        self.assertEqual(overlap.MODELS['backend'][2], ['1', '1'])

    def test_cpu_capture_rejects_reply_oracle_and_field_universe_changes(self):
        row = {'result': {k: '1' for k in ('mode', 'op', 'bytes', 'reps', 'retired', 'pc_hash', 'loads', 'stores', 'lsu_capacity', 'cycles', 'clean_tail')},
               'perf': {}, 'oracle': {'checked_replies': '1', 'checksum': '0'},
               'fabric': {'samples': '100', 'unexpected_mmio_dma_jtag_frame': '0'},
               'counts': {'req_fire': '1'}, 'ledger': {'blocks': '0'},
               'adoption': {'attached': '1', 'actual_cpu_response': '1'}}
        for i in range(105 - sum(len(row[k]) for k in ('result', 'perf', 'oracle', 'fabric'))):
            row['perf']['counter_' + str(i)] = '0'
        prefixes = {'result': 'CPU_SV39_RESULT', 'perf': 'BOARD_IPC', 'oracle': 'CPU_SV39_PASS',
                    'fabric': 'FABRIC_IDLE_PASS', 'counts': 'PASSIVE_SUPPLY_COUNTS', 'ledger': 'LEDGER_PASS', 'adoption': 'ADOPTION_PASS'}
        def text(value):return '\n'.join(prefixes[k] + ' ' + ' '.join(n+'='+v for n,v in fields.items()) for k,fields in value.items())
        with tempfile.TemporaryDirectory() as directory:
            work=Path(directory)
            for name in ('axi-events.tsv','supply-events.tsv'):(work/name).write_text('trace')
            cpu.capture(text(row), work, row)
            exact_reference=copy.deepcopy(row);exact_reference['raw']={name:common.sha(work/name) for name in ('axi-events.tsv','supply-events.tsv')}
            cpu.capture(text(row),work,exact_reference,exact=True)
            (work/'supply-events.tsv').write_text('changed supply trace')
            with self.assertRaisesRegex(AssertionError,'complete trace changed: supply-events.tsv'):
                cpu.capture(text(row),work,exact_reference,exact=True)
            exact_reference['raw'].pop('supply-events.tsv')
            with self.assertRaisesRegex(AssertionError,'lacks complete AXI/supply'):
                cpu.capture(text(row),work,exact_reference,exact=True)
            altered=copy.deepcopy(row);altered['oracle']['checked_replies']='0'
            with self.assertRaisesRegex(AssertionError, 'final-byte/reply'):
                cpu.capture(text(altered), work, row)
            altered=copy.deepcopy(row);altered['perf']['unknown_counter']=altered['perf'].pop('counter_0')
            with self.assertRaisesRegex(AssertionError, 'field universe'):
                cpu.capture(text(altered), work, row)

    def test_fixed_burst_oracle_rejects_interleaving_early_return_and_bad_last(self):
        # Trace format: index, cycle, channel, channel-specific payload.
        good=['0\t0\t0\t256\t1\t1\t3', '1\t1\t0\t512\t2\t0\t3',
              '2\t32\t2\t1\t10\t0\t0\t256', '3\t33\t2\t1\t11\t1\t0\t264',
              '4\t34\t2\t2\t12\t1\t0\t512']
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'trace.tsv';path.write_text('\n'.join(good))
            self.assertEqual(verify_service(path)['transactions'], 2)
            for changed in ([*good[:3], good[4], good[3]],
                            [*good[:2], good[2].replace('\t32\t','\t31\t'), *good[3:]],
                            [*good[:2],good[2].replace('\t10\t0\t','\t10\t1\t'),*good[3:]]):
                path.write_text('\n'.join(changed))
                with self.assertRaises(AssertionError):verify_service(path)


if __name__ == '__main__':
    unittest.main()
