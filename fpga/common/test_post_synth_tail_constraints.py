"""Mock native-XDC retention contract, not checkpoint or Vivado qualification.

Production checkpoint/provenance binding and original-scope comparison belong to
the parent resume verifier. Here, a tiny exact fixture oracle checks that losses,
budget changes, and reassociated endpoints remain visible in exported evidence.
"""
from collections import Counter
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import resume_diagnostic


HERE = Path(__file__).resolve().parent
PAIR_A = r"""
set_bus_skew 8.000 -from [get_pins -quiet [list {u/a_reg[1]/Q} {u/a_reg[0]/Q}]] \
    -to [get_pins {u/b_reg[1]/D u/b_reg[0]/D}]
set_max_delay -datapath_only -from [get_pins {u/a_reg[0]/Q u/a_reg[1]/Q}] \
    -to [get_pins {u/b_reg[0]/D u/b_reg[1]/D}] 8.000
"""
PAIR_B = """
set_bus_skew -from [get_pins {u/c/Q}] -to [get_pins {u/d/D}] 3.333
set_max_delay 3.333 -datapath_only -from [get_pins {u/c/Q}] -to [get_pins {u/d/D}]
"""
EXPECTED_SCOPES = [
    {"budget_ns": 8, "from": ["u/a_reg[0]/Q", "u/a_reg[1]/Q"],
     "to": ["u/b_reg[0]/D", "u/b_reg[1]/D"]},
    {"budget_ns": 3.333, "from": ["u/c/Q"], "to": ["u/d/D"]},
]


def scope_key(row):
    return row["budget_ns"], tuple(sorted(row["from"])), tuple(sorted(row["to"]))


def fixture_matches(rows):
    expected = Counter(map(scope_key, EXPECTED_SCOPES))
    for kind in ("bus_skew", "max_delay"):
        actual = Counter(scope_key(row) for row in rows
                         if row["kind"] == kind and row["from_type"] == "pin"
                         and row["to_type"] == "pin"
                         and (kind != "max_delay" or row["datapath_only"] is True))
        if actual != expected:
            return False
    return True


@unittest.skipUnless(shutil.which("tclsh"), "Tcl unavailable")
class PostSynthTailConstraintsTests(unittest.TestCase):
    def export(self, xdc, *, failure=False, with_details=False):
        with tempfile.TemporaryDirectory(prefix="tail-retention-") as temp:
            root = Path(temp)
            fixture = root / "input.xdc"
            fixture.write_text(xdc)
            output = root / "output"
            output.mkdir()
            proc = subprocess.run(
                ["tclsh", str(HERE / "test_post_synth_tail_constraints.tcl"),
                 str(fixture), str(output)],
                text=True, capture_output=True, timeout=15,
            )
            evidence = output / "tail-retained-constraints.json"
            if failure:
                self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                self.assertFalse(evidence.exists(), "Failure must not publish rows")
                self.assertNotIn("Forbidden live", proc.stderr)
                return proc.stderr
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn("TAIL_RETAINED_MOCK_PASS NOT_NATIVE_QUALIFIED", proc.stdout)
            self.assertEqual((output / "tail-retained.xdc").read_text(), xdc)
            data = json.loads(evidence.read_text())
            self.assertEqual(data["schema_version"], 1)
            return data if with_details else data["rows"]

    def test_complete_rows_preserve_association_budget_and_read_only_contract(self):
        rows = self.export(PAIR_A + PAIR_B)
        self.assertTrue(fixture_matches(rows))
        self.assertEqual(len(rows), 4)
        self.assertFalse(rows[0]["datapath_only"])
        self.assertEqual(rows[0]["from"], EXPECTED_SCOPES[0]["from"])

    def test_unrelated_xdc_is_never_executed(self):
        ignored = """
set ::outside_mutation 1
create_clock -period 20 [get_ports clk]
exec forbidden_external_program
if {1} {
    set_property BAD VALUE [get_cells *]
}
"""
        self.assertTrue(fixture_matches(self.export(ignored + PAIR_A + PAIR_B)))

    def test_exact_other_object_types_are_inert_and_typed(self):
        other = """
set_max_delay 20 -datapath_only -from [get_ports uart_rx] -to [get_pins {u/sample/D}]
set_max_delay 10 -from [get_clocks clk] -to [get_cells {u/cell}]
set_max_delay 2 -from [get_nets {u/LOCKED}] -to [get_ports ready]
"""
        rows = self.export(PAIR_A + PAIR_B + other)
        self.assertTrue(fixture_matches(rows))
        self.assertEqual([(r["from_type"], r["to_type"]) for r in rows[-3:]],
                         [("port", "pin"), ("clock", "cell"), ("net", "port")])

    def test_lost_changed_and_duplicate_scopes_remain_detectable(self):
        for changed in [
            PAIR_A,
            (PAIR_A + PAIR_B).replace("3.333", "3.334"),
            (PAIR_A + PAIR_B).replace("u/d/D", "u/other/D"),
            (PAIR_A + PAIR_B).replace("-datapath_only", ""),
            PAIR_A + PAIR_B + PAIR_B,
        ]:
            with self.subTest(changed=changed):
                self.assertFalse(fixture_matches(self.export(changed)))

    def test_unknown_or_nonliteral_selector_fails_closed(self):
        for selector in [
            "[all_fanin -to u/c/D]", "[get_pins -hierarchical u/c/Q]",
            "[get_pins -filter {NAME == u/c/Q}]", "[get_pins {u/*/Q}]",
            "[get_cells {u/*}]", "[get_ports -regexp {uart.*}]",
            "[get_pins {u/a_reg[0:7]/Q}]", "[get_pins {}]",
            "[get_pins {u/c/Q u/c/Q}]", "{u/c/Q}",
            "[get_pins [exec forbidden_external_program]]",
            "[get_pins [set variable u/c/Q]]", "[get_pins [expr 1+1]]",
        ]:
            with self.subTest(selector=selector):
                self.assertIn("TAIL_RETAINED", self.export(
                    f"set_bus_skew 8 -from {selector} -to [get_pins {{u/d/D}}]\n",
                    failure=True))

    def test_malformed_selected_rows_fail_closed(self):
        for row in [
            "set_bus_skew 8 -from [get_pins {u/c/Q}]",
            "set_bus_skew 8 -from [get_pins {u/c/Q}] -from [get_pins {u/c/Q}] -to [get_pins {u/d/D}]",
            "set_bus_skew 8 -rise_from [get_pins {u/c/Q}] -to [get_pins {u/d/D}]",
            "set_max_delay 8 -reset_path -from [get_pins {u/c/Q}] -to [get_pins {u/d/D}]",
            "set_bus_skew NaN -from [get_pins {u/c/Q}] -to [get_pins {u/d/D}]",
            "set_bus_skew Inf -from [get_pins {u/c/Q}] -to [get_pins {u/d/D}]",
            "set_bus_skew 0 -from [get_pins {u/c/Q}] -to [get_pins {u/d/D}]",
            "set_bus_skew 8 -from [get_pins {u/c/Q}] -to [get_pins {u/d/D}] ; set_property BAD VALUE u/c",
            "set_bus_skew 8 -from [get_pins {u/c/Q}] -to [get_pins {u/d/D}] ; "
            "set_bus_skew 8 -from [get_pins {u/c/Q}] -to [get_pins {u/d/D}]",
            "set_bus_skew 8 -from [get_pins {u/c/Q}] -to [get_pins {u/d/D}",
        ]:
            with self.subTest(row=row):
                self.assertIn("TAIL_RETAINED", self.export(row + "\n", failure=True))

    def test_no_selected_constraints_fails_closed(self):
        self.assertIn("no selected constraints", self.export("# empty\n", failure=True))

    def test_json_escaping_and_complete_multiline_statements(self):
        xdc = r'''
set_bus_skew 8 -from [get_pins {
    {u/quoted"name/Q}
    u/other/Q
}] -to [get_pins {u/d/D}];# native ordinal comment
'''
        rows = self.export(xdc)
        self.assertEqual(rows[0]["from"], ['u/other/Q', 'u/quoted"name/Q'])

    def test_comment_continuations_are_not_selected(self):
        comment = "# ignored comment \\\nset_bus_skew 99 -from [get_pins *] -to [get_pins *]\n"
        self.assertTrue(fixture_matches(self.export(comment + PAIR_A + PAIR_B)))

    def test_changed_object_type_cannot_match_pin_scope(self):
        changed = (PAIR_A + PAIR_B).replace("[get_pins {u/c/Q}]", "[get_cells {u/c/Q}]")
        self.assertFalse(fixture_matches(self.export(changed)))

    def test_native_scope_resets_and_relative_pin_names_are_preserved(self):
        scoped = "current_instance u_ddr/inst/microblaze_I/U0\n"
        scoped += "set_false_path -through [get_ports -scoped_to_current_instance Reset]\n"
        scoped += "current_instance -quiet\n"
        self.assertTrue(fixture_matches(self.export(scoped + PAIR_A + PAIR_B)))
        relative = (PAIR_A + PAIR_B).replace('u/', '')
        self.assertTrue(fixture_matches(self.export('current_instance u\n' + relative)))
        rows = self.export('current_instance u/nested\n' + PAIR_A + PAIR_B)
        self.assertFalse(fixture_matches(rows))
        self.assertEqual(rows[0]['from'][0], 'u/nested/u/a_reg[0]/Q')

    def test_relative_scope_changes_and_root_reset_are_not_global_aliases(self):
        prefix = 'current_instance u\ncurrent_instance child\ncurrent_instance ..\ncurrent_instance .\n'
        self.assertTrue(fixture_matches(self.export(prefix + (PAIR_A + PAIR_B).replace('u/', ''))))
        self.assertTrue(fixture_matches(self.export('current_instance u/child\ncurrent_instance\n' + PAIR_A + PAIR_B)))
        rows = self.export('current_instance u\ncurrent_instance child\n' + PAIR_B)
        self.assertEqual(rows[0]['from'], ['u/child/u/c/Q'])

    def test_unknown_or_executable_scope_forms_fail_closed(self):
        for context in ('::current_scope u/nested', 'current_instance -unknown u',
                        'current_instance ..', 'current_instance /u',
                        'current_instance u//child', 'current_instance {u/*}',
                        'current_instance [get_cells u]',
                        'current_instance [exec forbidden_external_program]',
                        'current_instance u; current_instance -quiet',
                        'current_instance u; set ::outside_mutation 1'):
            with self.subTest(context=context):
                self.assertIn('TAIL_RETAINED', self.export(context + '\n' + PAIR_A + PAIR_B, failure=True))
        selected = PAIR_B.replace('[get_pins {u/c/Q}]', '[get_pins [current_instance u]]')
        self.assertIn('TAIL_RETAINED', self.export(selected, failure=True))

    def test_unsupported_native_rows_are_recorded_without_hiding_required_scopes(self):
        other = """
current_instance u_ddr/inst
set_max_delay -from [get_pins */vendor/C] -to [get_pins */sync/D] 5
current_instance -quiet
set_max_delay -from [filter [all_fanin -to [get_pins x/D]] {REF_PIN_NAME == C}] -to [get_pins x/D] 3.333
set_max_delay -from $_xlnx_shared_i0 -to $_xlnx_shared_i1 8
set_bus_skew -from $_xlnx_shared_i0 -to $_xlnx_shared_i1 8
"""
        data = self.export(other + PAIR_A + PAIR_B, with_details=True)
        self.assertTrue(fixture_matches(data['rows']))
        self.assertEqual(data['selected_counts'], {'max_delay': 5, 'bus_skew': 3})
        self.assertEqual(len(data['unsupported']), 4)
        self.assertEqual(data['unsupported'][0]['scope'], 'u_ddr/inst')
        self.assertTrue(all(item['line'] > 0 and item['reason'] for item in data['unsupported']))
        self.assertFalse(fixture_matches(self.export(other + PAIR_A)))

    def test_text_preview_uses_same_parser_and_exact_original_scope_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            out = root / 'diagnostic-run/synthesis'
            out.mkdir(parents=True)
            scope = out / 'bus-skew-scope.json'
            scope.write_text(json.dumps({'scopes': EXPECTED_SCOPES}))
            xdc = root / 'saved-native.xdc'
            xdc.write_text('current_instance u_ddr/inst\ncurrent_instance -quiet\n' + PAIR_A + PAIR_B)
            bound = (resume_diagnostic.sha(scope), scope.stat().st_size)
            with patch.dict(resume_diagnostic.TAIL_BOUND, bus_skew_scope=bound):
                result = resume_diagnostic.retained_text_check(root, xdc, root/'preview.json', resume_diagnostic.sha(xdc))
                self.assertEqual(result['retained_bus_scopes'], 2)
                self.assertFalse(result['falsepath_or_exception_dominance_proven'])
                with self.assertRaisesRegex(ValueError, 'Preserve existing'):
                    resume_diagnostic.retained_text_check(root, xdc, root/'preview.json', resume_diagnostic.sha(xdc))
                with self.assertRaisesRegex(ValueError, 'SHA256 mismatch'):
                    resume_diagnostic.retained_text_check(root, xdc, root/'bad-hash.json', '0'*64)
                xdc.write_text(PAIR_A + PAIR_B.replace('3.333', '3.334'))
                with self.assertRaisesRegex(ValueError, 'not retained'):
                    resume_diagnostic.retained_text_check(root, xdc, root/'missing.json', resume_diagnostic.sha(xdc))
            self.assertFalse((out/'synthesized.dcp').exists())
            self.assertFalse((out/'diagnostic-stage.json').exists())

    def test_scope_state_does_not_leak_between_reads(self):
        self.export('current_instance nested\n' + PAIR_A + PAIR_B)
        self.assertTrue(fixture_matches(self.export(PAIR_A + PAIR_B)))


if __name__ == "__main__":
    unittest.main()
