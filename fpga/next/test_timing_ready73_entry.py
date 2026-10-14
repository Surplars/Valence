#!/usr/bin/env python3
"""Pure source/configuration and negative contract tests; no native or CPU emission."""
import contextlib
import copy
import importlib.util
import io
import json
import re
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent


def load(name):
    spec = importlib.util.spec_from_file_location('combined_test_' + name, HERE / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TimingClosureEntryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.entry = load('board_timing_ready73')
        cls.exporter = load('export')
        cls.profile = cls.entry.load_profile()
        cls.profile['native_options'] = cls.profile['on_options']
        cls.profile['native_main'] = cls.entry.NATIVE_MAIN

    def fixture(self, directory):
        p = self.profile
        docs = {'profile.json': p['on_profile'],
                'actual-product-field-order.json': {k: p[k + '_fields'] for k in ('core', 'profile')},
                'actual-timing-closure.json': self.entry.expected(p, 'on', 'timing_audit'),
                'timing-ready73-entry.json': self.entry.completion(p)}
        for file, key in [('actual-held-alu-forwarding.json', 'held'), ('actual-resident-memory.json', 'resident'), ('actual-mac-raw-handoff.json', 'mac')]:
            docs[file] = self.entry.expected(p, 'on', 'existing_audits')[key]
        (directory / 'options.txt').write_text(''.join(x + '\n' for x in p['on_options']))
        for name, value in docs.items():
            (directory / name).write_text(json.dumps(value) + '\n')
        return docs

    def command(self, output):
        p = self.profile
        # Model only the unchanged generic writer's canonical order, not hardware.
        opts = [x for x in p['native_options'] if x != '--held-alu-issue-forwarding']
        index = opts.index('--posted-younger-load-seal-deferral')
        opts.insert(index, '--held-alu-issue-forwarding')
        return ['mill', '-i', 'IonSoC.test.runMain', 'ooo.FpgaNextMain', str(output / 'rtl'), *opts]

    def test_exact_named_profile_and_original_domains(self):
        p = self.profile
        self.assertEqual(len(p['on_options']), 73)
        self.assertEqual(p['on_options'][-2:], ['--registered-load-result-ready', '--tri-speed-raw-clock-handoff'])
        self.assertEqual(len(p['core_fields']), 177)
        self.assertEqual(len(p['profile_fields']), 94)
        self.assertIs(p['on_profile']['profile']['triSpeedRawClockHandoff'], True)
        self.assertEqual(p['physical_options'], ['--native-mac-local-pad-reset-release', '--native-mac-register-selected-half'])

    def test_exact_generic_option_set_rebound_to_tested_order(self):
        out = Path('/uncreated/combined-test')
        for emit in (False, True):
            raw = self.entry.export_arguments(self.profile, out, emit)
            bound = self.entry.bind_native_command(self.command(out), raw, out, emit)
            self.assertEqual(bound[3], 'ooo.TimingReady73NativeMain')
            self.assertEqual(bound[5:], self.profile['native_options'])

    def test_command_missing_duplicate_substituted_options_rejected(self):
        out = Path('/uncreated/combined-test')
        raw = self.entry.export_arguments(self.profile, out)
        original = self.command(out)
        variants = [original[:-1], original + [original[-1]],
                    [*original[:-1], '--reference'],
                    [*original[:3], 'ooo.OtherMain', *original[4:]]]
        for bad in variants:
            with self.subTest(bad=bad[-2:]), self.assertRaises(RuntimeError):
                self.entry.bind_native_command(bad, raw, out, False)

    def test_raw_option_omission_reorder_or_override_rejected(self):
        out = Path('/uncreated/combined-test')
        raw = self.entry.export_arguments(self.profile, out)
        for bad in [raw[:-1], raw + ['--rob-entries=32'], raw + ['--tri-speed-raw-clock-handoff'],
                    raw[:2] + list(reversed(raw[2:]))]:
            with self.subTest(bad=bad[-2:]), self.assertRaises(RuntimeError):
                self.entry.bind_native_command(self.command(out), bad, out, False)

    def test_named_preflight_exact_command_no_output_or_compiler(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'unused'
            stream = io.StringIO()
            with mock.patch.object(subprocess, 'run', side_effect=AssertionError('no compiler or simulator')):
                with mock.patch.object(subprocess, 'check_output', side_effect=subprocess.CalledProcessError(128, ['git'])):
                    with contextlib.redirect_stdout(stream):
                        self.exporter.main(self.entry.export_arguments(self.profile, out), named_entry=self.entry.NAME)
            result = json.loads(stream.getvalue())
            self.assertEqual(result['status'], 'PREFLIGHT_ONLY')
            self.assertEqual(result['profile'], self.entry.NAME)
            self.assertEqual(result['command'][3], self.profile['native_main'])
            self.assertEqual(result['command'][5:], self.profile['native_options'])
            self.assertFalse(out.exists())

    def test_unknown_named_entry_rejected(self):
        with self.assertRaisesRegex(ValueError, 'unknown strict named'):
            self.exporter.main([], named_entry='nearly-the-combination')

    def test_wrapper_rejects_unknown_raw_mac_override(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.entry.main(['--output', '/uncreated/combo', '--tri-speed-raw-clock-handoff'])

    def test_complete_native_fixture_matches_but_is_not_hardware_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.fixture(directory)
            self.entry.validate_native_output(directory)

    def test_native_full_profile_type_capacity_and_feature_drift_rejected(self):
        for key, value in [('heldAluIssueForwarding', False), ('residentMemoryPayloadReuse', False),
                           ('postedYoungerLoadSealDeferral', False), ('robEntries', 32), ('renameWidth', True)]:
            with self.subTest(key=key), tempfile.TemporaryDirectory() as tmp:
                directory = Path(tmp)
                docs = self.fixture(directory)
                bad = copy.deepcopy(docs['profile.json'])
                bad['core'][key] = value
                (directory / 'profile.json').write_text(json.dumps(bad))
                with self.assertRaises(RuntimeError):
                    self.entry.validate_native_output(directory)

    def test_actual_core_backend_ledger_mismatch_rejected(self):
        for filename in ['actual-held-alu-forwarding.json', 'actual-resident-memory.json']:
            for leaf in ['core', 'backend', 'ledger']:
                with self.subTest(filename=filename, leaf=leaf), tempfile.TemporaryDirectory() as tmp:
                    directory = Path(tmp)
                    docs = self.fixture(directory)
                    bad = copy.deepcopy(docs[filename]); bad[leaf]['heldAluIssueForwarding'] = False
                    (directory / filename).write_text(json.dumps(bad))
                    with self.assertRaises(RuntimeError):
                        self.entry.validate_native_output(directory)

    def test_raw_mac_selector_and_field_order_drift_rejected(self):
        mutations = [('actual-mac-raw-handoff.json', 'triSpeedRawClockHandoff', False),
                     ('actual-resident-memory.json', 'residentSelectorCount', 0),
                     ('actual-resident-memory.json', 'ordinarySelectorCount', 1),
                     ('actual-resident-memory.json', 'executionStages', 3)]
        for filename, key, value in mutations:
            with self.subTest(filename=filename, key=key), tempfile.TemporaryDirectory() as tmp:
                directory = Path(tmp); docs = self.fixture(directory)
                bad = copy.deepcopy(docs[filename]); bad[key] = value
                (directory / filename).write_text(json.dumps(bad))
                with self.assertRaises(RuntimeError): self.entry.validate_native_output(directory)
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp); docs = self.fixture(directory)
            bad = copy.deepcopy(docs['actual-product-field-order.json']); bad['core'].reverse()
            (directory / 'actual-product-field-order.json').write_text(json.dumps(bad))
            with self.assertRaises(RuntimeError): self.entry.validate_native_output(directory)

    def mocked_native_export(self, output, mutation=None):
        """Test exporter orchestration only; all emitted JSON/SV below are explicit fixtures."""
        calls = []
        def fake_native(command, **kwargs):
            calls.append(command)
            self.assertEqual(command[:4], ['mill', '-i', 'IonSoC.test.runMain', self.profile['native_main']])
            self.assertEqual(command[5:], self.profile['native_options'])
            rtl = Path(command[4]); rtl.mkdir()
            docs = self.fixture(rtl)
            if mutation is not None:
                mutation(docs)
                for name, value in docs.items():
                    (rtl / name).write_text(json.dumps(value) + '\n')
            # A port-name stub exercises the existing wrapper/file-list guards only.
            # This is not Chisel output and is never compiled or used as hardware evidence.
            wrapper = self.exporter.bscan_board_wrapper((HERE / 'soc_top_fpga_next_ddr.sv').read_text())
            instance = re.search(r'\bFpgaNextSocTop\s+u_soc\s*\((.*?)\);', wrapper, re.S)
            ports = re.findall(r'\.([A-Za-z_][A-Za-z0-9_$]*)\s*\(', instance.group(1))
            (rtl / 'FpgaNextSocTop.sv').write_text('// MOCKED ORCHESTRATION FIXTURE; NOT REAL RTL\n' +
                'module FpgaNextSocTop (' + ', '.join('input wire ' + n for n in ports) + '); endmodule\n')
            for name in ['ValenceJtagDebugPort.sv', 'ValenceBscanDebugPort.sv', 'ValenceMacRawFallingSample.sv']:
                (rtl / name).write_text('// MOCKED RESOURCE FIXTURE; NOT REAL RTL\n')
            kwargs['stdout'].write('MOCKED_NATIVE_PROCESS_ONLY; NO CHISEL, FIRTOOL, CPU OR VIVADO\n')
            return subprocess.CompletedProcess(command, 0)
        with mock.patch.object(subprocess, 'run', side_effect=fake_native):
            with mock.patch.object(subprocess, 'check_output', side_effect=subprocess.CalledProcessError(128, ['git'])):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.entry.main(['--output', str(output), '--emit'])
        self.assertEqual(len(calls), 1)
        return json.loads((output / 'receipt.json').read_text())

    def test_mocked_emit_exercises_complete_writer_audits_and_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'mocked-export-not-hardware'
            receipt = self.mocked_native_export(output)
            self.assertEqual(receipt['status'], 'PASS_RTL_EXPORT_ONLY')
            self.assertEqual(receipt['named_entry'], self.entry.NAME)
            self.assertIs(receipt['complete_combined_constructor_verified'], True)
            self.assertIs(receipt['tri_speed_raw_clock_handoff'], True)
            self.assertIs(receipt['complete_timing_constructor_verified'], True)
            self.assertEqual(receipt['cpu_qualification'], 'PASS_BOUNDED_COPY_NEMU_PMP_ACTUAL_HELD_CAUSAL')
            self.assertIs(receipt['resident_memory_payload_reuse'], True)
            self.assertIs(receipt['physical_qualification'], False)
            self.assertEqual(receipt['command'][5:], self.profile['native_options'])
            self.assertEqual(receipt['required_post_synthesis_gate']['status'], 'NOT_RUN_NO_VIVADO')
            self.assertIn('ValenceMacRawFallingSample.sv', (output / 'synthesis-files.f').read_text())
            self.assertIn('MOCKED_NATIVE_PROCESS_ONLY', (output / 'elaborate.log').read_text())
            mode = self.exporter.board_t1.verify(output)
            self.assertIs(mode['applied_to_synthesized_design'], False)
            self.assertIs(mode['physical_qualification'], False)

    def test_mocked_emit_rejects_old_audit_and_new_full_profile_conflicts(self):
        def held_bad(docs):
            docs['actual-held-alu-forwarding.json'] = copy.deepcopy(docs['actual-held-alu-forwarding.json'])
            docs['actual-held-alu-forwarding.json']['heldAluIssueForwarding'] = False
        def resident_bad(docs):
            docs['actual-resident-memory.json'] = copy.deepcopy(docs['actual-resident-memory.json'])
            docs['actual-resident-memory.json']['residentSelectorCount'] = 0
        def full_bad(docs):
            docs['profile.json'] = copy.deepcopy(docs['profile.json'])
            docs['profile.json']['unapproved_top_level_value'] = True
        for name, mutation, diagnostic in [('held', held_bad, 'actual held ALU constructor'),
                ('resident', resident_bad, 'selector count'), ('complete', full_bad, 'actual full native profile')]:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                output = Path(tmp) / ('mocked-' + name + '-not-hardware')
                with self.assertRaisesRegex(RuntimeError, diagnostic):
                    self.mocked_native_export(output, mutation)
                receipt = json.loads((output / 'receipt.json').read_text())
                self.assertEqual(receipt['status'], 'FAIL')
                self.assertIs(receipt['physical_qualification'], False)
                self.assertNotIn('complete_combined_constructor_verified', receipt)

    def test_historical_bridge_stays_fail_closed(self):
        with self.assertRaisesRegex(RuntimeError, 'source closure'):
            load('resident_memory_source_bridge').checked_sources()

    def test_new_generic_flags_are_not_a_backdoor(self):
        for flag in ['--registered-load-result-ready', '--frozen-store-checked-flow']:
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                self.exporter.main(['--output', '/uncreated/generic', flag])

    def test_full_declared_types_and_new_actual_fields_fail_closed(self):
        bridge = load('timing_ready73_source_bridge')
        contract = bridge.checked_sources()
        for kind, key in [('core', 'registeredLoadResultReady'), ('profile', 'frozenStoreCheckedFlow')]:
            values = copy.deepcopy(self.profile['on_profile'][kind]); values[key] = 1
            with self.assertRaisesRegex(RuntimeError, 'parameter type'):
                bridge.validate_parameter_types(values, kind, contract)
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp); docs = self.fixture(directory)
            docs['actual-timing-closure.json']['unexpected'] = True
            (directory / 'actual-timing-closure.json').write_text(json.dumps(docs['actual-timing-closure.json']))
            with self.assertRaisesRegex(RuntimeError, 'timing constructor'):
                self.entry.validate_native_output(directory)

    def test_source_byte_and_manifest_corruption_fail_closed(self):
        bridge = load('timing_ready73_source_bridge')
        original_sha = bridge.sha
        for filename in ['timing-ready73-source-compat.json', 'OooParams.scala']:
            def corrupt(path):
                return '0' * 64 if path.name == filename else original_sha(path)
            with mock.patch.object(bridge, 'sha', side_effect=corrupt), self.assertRaises(RuntimeError):
                bridge.checked_sources()

    def test_complete_declared_name_order_type_drift_rejected(self):
        bridge = load('timing_ready73_source_bridge')
        prior = bridge.helper()
        original = prior.ordered_fields
        for mutation in ['order', 'missing', 'type']:
            def altered(path, name):
                fields = copy.deepcopy(original(path, name))
                if mutation == 'order': fields.reverse()
                elif mutation == 'missing': fields.pop()
                else: fields[-1]['type'] = 'Int'
                return fields
            with mock.patch.object(bridge, 'helper', return_value=prior), mock.patch.object(prior, 'ordered_fields', side_effect=altered), self.assertRaisesRegex(RuntimeError, 'ordered names/types'):
                bridge.checked_sources()


if __name__ == '__main__':
    unittest.main(verbosity=2)
