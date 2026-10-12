"""Source/export negatives; these tests do not claim HDL or physical execution."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT/path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


check = module("bscan_check", "simulator/jtag/bscan_check.py")
integration = module("bscan_integration", "fpga/next/bscan_integration.py")


class BscanQualificationTests(unittest.TestCase):
    def test_current_structure(self):
        check.check_structure(check.RTL.read_text())

    def test_live_control_mutants_rejected(self):
        text = check.RTL.read_text()
        mutants = {
            "raw_sel": text.replace('end else if (update_selected)', 'end else if (bscan_sel && source_reset_n)'),
            "raw_ack": text.replace('if (update_toggle == update_ack)', 'if (update_toggle == update_seen)'),
            "raw_release": text.replace('always @(posedge bscan_update or negedge update_reset_n)',
                                         'always @(posedge bscan_update or negedge work_reset_n)'),
            "negative_qualifier": text.replace('always @(posedge bscan_tck or negedge update_reset_n)',
                                               'always @(negedge bscan_tck or negedge update_reset_n)'),
        }
        for name, mutant in mutants.items():
            with self.subTest(name=name), self.assertRaises(AssertionError):
                check.check_structure(mutant)

    def test_phase_handoff_and_functional_reset_bypasses_rejected(self):
        text = check.RTL.read_text()
        mutants = {
            "raw_drck_reset": text.replace('always @(posedge bscan_drck or negedge source_reset_n)',
                                             'always @(posedge bscan_drck or negedge work_reset_n)'),
            "raw_hard_reset": text.replace('always @(negedge bscan_tck or negedge hard_reset_n)',
                                             'always @(negedge bscan_tck or negedge raw_reset_n)'),
            "payload_bypass": text.replace('.s_req_payload(handoff_frame[40:0])',
                                            '.s_req_payload(update_frame[40:0])'),
            "toggle_bypass": text.replace('update_sync <= {update_sync[0], handoff_toggle};',
                                           'update_sync <= {update_sync[0], update_toggle};'),
        }
        for name, mutant in mutants.items():
            with self.subTest(name=name), self.assertRaises(AssertionError):
                check.check_structure(mutant)

    def test_dmi_loader_crc_and_host_protocol_are_outside_patch(self):
        # The export must keep the selected custom 64-bit USER2 profile explicit.
        profile = json.loads((ROOT/'fpga/next/bscan-timing-profile.json').read_text())
        self.assertEqual(profile['frame_bits'], 64)
        self.assertEqual(profile['user_chain'], 2)
        self.assertEqual(profile['part'], 'xczu15eg-ffvb1156-2-i')
        released = json.loads((ROOT/'fpga/next/board-release-profile.json').read_text())
        self.assertIn('xczu15eg-ffvb1156-2-i', json.dumps(released))
        self.assertFalse(profile['physical_qualification'])
        self.assertEqual(profile['clocks']['update']['edges'], [2, 3, 4])
        self.assertEqual(profile['clocks']['tck']['period_ns'], 50.0)
        self.assertEqual(profile['clocks']['tck']['waveform_ns'], [0, 25])
        self.assertEqual(profile['clocks']['all_related_pairs_setup_uncertainty_ns'], 0.1)
        self.assertEqual(profile['clocks']['all_related_pairs_hold_uncertainty_ns'], 0.1)
        self.assertFalse(profile['clocks']['primitive_clock_delay_added_as_waveform_shift'])

    def test_export_stages_self_contained_source_bound_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            result = integration.stage(ROOT, out, 2)
            contract = json.loads((out/result['path']).read_text())
            self.assertEqual(result['sha256'], integration.sha(out/result['path']))
            self.assertEqual(contract['status'], 'STAGED_NOT_APPLIED_NOT_PHYSICAL_SIGNOFF')
            self.assertFalse(contract['physical_qualification'])
            self.assertEqual(contract['rtl_source_sha256'], integration.sha(check.RTL))
            self.assertIn('board/check_jtag_chain.tcl', contract['files'])
            for name, binding in contract['files'].items():
                self.assertEqual(integration.sha(out/name), integration.sha(ROOT/binding['source']))
                self.assertEqual(binding['sha256'], binding['source_sha256'])
            self.assertIn('$fabric_clock', contract['reapply_after_opt_design'])
            self.assertIn('$exact_primitive', contract['apply_after_synthesis'])

    def test_actual_exporter_binds_timing_inputs(self):
        export = module("bscan_export_source_test", "fpga/next/export.py")
        source_hashes = export.sources()
        for path in integration.INPUTS:
            self.assertEqual(source_hashes[path], integration.sha(ROOT/path))
        self.assertEqual(source_hashes["src/main/resources/debug/ValenceBscanDebugPort.sv"], integration.sha(check.RTL))

    def test_other_chains_never_inherit_zu15eg_user2_clock_claim(self):
        for chain in (1, 3, 4):
            with tempfile.TemporaryDirectory() as tmp:
                result = integration.stage(ROOT, Path(tmp), chain)
                self.assertEqual(result['status'], 'UNSUPPORTED_CHAIN_REQUIRES_REVIEW')
                self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_timing_source_preserves_all_related_paths(self):
        text = (ROOT/'fpga/next/bscan_timing.tcl').read_text()
        commands = [line.strip() for line in text.splitlines() if not line.lstrip().startswith('#')]
        self.assertEqual(sum(line.startswith('set_false_path ') for line in commands), 1)
        self.assertIn('set_false_path -to $async_pins', commands)
        self.assertFalse(any(line.startswith(('set_clock_groups ', 'set_multicycle_path ')) for line in commands))
        self.assertIn('set_clock_uncertainty -setup 0.100 -from $clocks -to $clocks', commands)
        self.assertIn('set_clock_uncertainty -hold 0.100 -from $clocks -to $clocks', commands)
        self.assertIn('set_max_delay -datapath_only 8.000 -from $launch -to $capture', commands)
        self.assertIn('Live same-edge BSCAN control feeds UPDATE', text)
        self.assertIn('functional reset', text)
        self.assertIn('all_fanin -flat -to $targets', text)


if __name__ == '__main__':
    unittest.main()
