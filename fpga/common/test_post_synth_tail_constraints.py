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

    def native_export(self, xdc, *, mutation='', failure=False):
        harness = r'''
set queries {}; set native_scope {}; set classes {}; set names {}
set cells {u/held0_reg u/held1_reg u/captured0_reg u/captured1_reg}
set pins {u/held0_reg/C u/held1_reg/C u/captured0_reg/D u/captured1_reg/D}
proc current_instance args {
 if {$args ne {.}} {error {MUTATING_SCOPE_CALL}}
 return $::native_scope
}
proc get_cells args {
 lappend ::queries [list get_cells {*}$args]
 set result {}; set at [lsearch -exact $args -regexp]
 if {$at>=0} {
  foreach c $::cells {if {[regexp [lindex $args [expr {$at+1}]] $c]} {lappend result $c}}
 } else {
  set patterns [lindex $args end]
  foreach c $::cells {
   foreach pattern $patterns {if {$c eq $pattern || [string match $pattern $c]} {lappend result $c; break}}
  }
 }
 return $result
}
proc get_pins args {
 lappend ::queries [list get_pins {*}$args]
 set at [lsearch -exact $args -of_objects]; set result {}
 if {$at>=0} {
  set stem [expr {[string match {* == C} [lindex $args end]] ? {C} : {D}}]
  foreach c [lindex $args [expr {$at+1}]] {if {"$c/$stem" in $::pins} {lappend result $c/$stem}}
 } else {
  foreach p $::pins {if {$p eq [lindex $args end] || [string match [lindex $args end] $p]} {lappend result $p}}
 }
 return $result
}
proc all_fanin args {
 lappend ::queries [list all_fanin {*}$args]
 if {$args ne {-flat -startpoints_only -to u/captured0_reg/D}} {error {UNEXPECTED_FANIN}}
 return {u/held0_reg/C input_port}
}
proc filter args {
 lappend ::queries [list filter {*}$args]
 if {[llength $args]!=2 || [lindex $args 1] ne {REF_PIN_NAME == C || REF_PIN_NAME == CLK}} {error {UNEXPECTED_FILTER}}
 set result {}; foreach p [lindex $args 0] {if {[string match */C $p]} {lappend result $p}}; return $result
}
proc get_property {property objects} {
 set result {}
 foreach object $objects {
  if {$property eq {NAME}} {
   lappend result [expr {[dict exists $::names $object] ? [dict get $::names $object] : $object}]
  } elseif {$property eq {CLASS}} {
   if {[dict exists $::classes $object]} {lappend result [dict get $::classes $object]
   } elseif {$object in $::pins} {lappend result pin
   } elseif {$object in $::cells} {lappend result cell
   } elseif {$object eq {input_port}} {lappend result port
   } else {error {UNKNOWN_OBJECT}}
  } else {error {UNKNOWN_PROPERTY}}
 }
 return $result
}
foreach cmd {set_max_delay set_bus_skew set_false_path set_property read_xdc} {
 proc $cmd args {error {FORBIDDEN_NATIVE_WRITE}}
}
'''
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = root/'input.xdc'; fixture.write_text(xdc)
            output = root/'parsed.json'
            script = root/'run.tcl'
            script.write_text(harness + '\n' + mutation + '\n' +
                f'source {{{HERE / "post_synth_tail_constraints.tcl"}}}\n' +
                f'if {{[catch {{set rows [post_synth_tail_constraints::read_rows {{{fixture}}} 1 1]; post_synth_tail_constraints::write_rows {{{output}}} $rows}} reason]}} {{puts stderr $reason; exit 2}}\n' +
                'puts [format {NATIVE_QUERY_COUNT=%d} [llength $queries]]\n')
            result = subprocess.run(['tclsh',str(script)],capture_output=True,text=True,timeout=15)
            if failure:
                self.assertEqual(result.returncode,2,result.stdout+result.stderr)
                self.assertFalse(output.exists())
                return result.stderr
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            return json.loads(output.read_text())

    def test_native_readonly_bridge_resolves_shared_and_nested_collections(self):
        shared = '''
set _xlnx_shared_i0 [get_pins -of_objects [get_cells -quiet u/held*_reg*] -filter {REF_PIN_NAME == C}]
set _xlnx_shared_i1 [get_pins -of_objects [get_cells -quiet u/captured*_reg*] -filter {REF_PIN_NAME == D}]
set_max_delay -datapath_only -from $_xlnx_shared_i0 -to $_xlnx_shared_i1 8
set_bus_skew -from $_xlnx_shared_i0 -to $_xlnx_shared_i1 8
'''
        nested = '''
set_max_delay -datapath_only -from [filter [all_fanin -flat -startpoints_only -to [get_pins -quiet u/captured0_reg/D]] {REF_PIN_NAME == C || REF_PIN_NAME == CLK}] -to [get_pins -quiet u/captured0_reg/D] 3.333
set_bus_skew -from [filter [all_fanin -flat -startpoints_only -to [get_pins -quiet u/captured0_reg/D]] {REF_PIN_NAME == C || REF_PIN_NAME == CLK}] -to [get_pins -quiet u/captured0_reg/D] 3.333
'''
        result = self.native_export(shared+nested)
        self.assertEqual(result['unsupported'],[])
        self.assertEqual(len(result['rows']),4)
        self.assertEqual(result['rows'][0]['from'],['u/held0_reg/C','u/held1_reg/C'])
        self.assertEqual(result['rows'][2]['from'],['u/held0_reg/C'])
        self.assertEqual(result['rows'][2]['from_type'],'pin')
        self.assertEqual(result['native_query_calls'],7)
        # Valid shared handles persist between constraints, never between reads.
        again = self.native_export('set_bus_skew -from $_xlnx_shared_i0 -to $_xlnx_shared_i1 8\n'+PAIR_B)
        self.assertEqual(len(again['unsupported']),1)
        # A non-root redefinition invalidates the old handle before returning ROOT.
        changed = shared.split('set_max_delay')[0] + 'current_instance vendor\nset _xlnx_shared_i0 [get_cells *]\ncurrent_instance -quiet\n' + shared[shared.index('set_max_delay'):]
        self.assertIn('no selected constraints',self.native_export(changed,failure=True))

    def test_native_debug_request_response_positional_cell_collections(self):
        root = 'u_debug/enabled.transport/bridge'
        mutation = []
        xdc = []
        expected = []
        for source, target, count in (('request_held', 'dest_request', 41),
                                      ('response_held', 's_rsp_payload', 34)):
            for stem, pin in ((source, 'C'), (target, 'D')):
                for bit in range(count):
                    cell = f'{root}/{stem}_reg[{bit}]'
                    mutation.append(f'lappend cells {{{cell}}}; lappend pins {{{cell}/{pin}}}')
            def selector(stem, pin):
                regex = (r'^u_debug/enabled\.transport/bridge/' + stem +
                         r'_reg(\[[0-9]+\])?$')
                return ('[get_pins -quiet -of_objects [get_cells -quiet '
                        '[get_cells -quiet -hierarchical -regexp {' + regex + '}]] '
                        '-filter {REF_PIN_NAME == ' + pin + '}]')
            for command, flag in (('set_max_delay', '-datapath_only '), ('set_bus_skew', '')):
                xdc.append(f'{command} {flag}-from {selector(source, "C")} -to {selector(target, "D")} 8.000')
                expected.append((source, target, count))
        data = self.native_export('\n'.join(xdc), mutation='\n'.join(mutation))
        self.assertEqual(data['unsupported'], [])
        self.assertEqual(len(data['rows']), 4)
        for row, (source, target, count) in zip(data['rows'], expected):
            self.assertEqual(row['from'], sorted(f'{root}/{source}_reg[{i}]/C' for i in range(count)))
            self.assertEqual(row['to'], sorted(f'{root}/{target}_reg[{i}]/D' for i in range(count)))
            self.assertEqual((row['from_type'], row['to_type'], row['budget_ns']), ('pin', 'pin', 8))

    def test_positional_collection_is_only_exact_get_cells_and_cell_typed(self):
        selectors = (
            '[get_cells -quiet [get_pins -of_objects [get_cells -quiet u/held*_reg*] -filter {REF_PIN_NAME == C}]]',
            '[get_cells -quiet [all_fanin -flat -startpoints_only -to [get_pins -quiet u/captured0_reg/D]]]',
            '[get_pins -quiet [get_cells -quiet u/held*_reg*]]',
            '[get_cells -hier [get_cells -quiet u/held*_reg*]]',
            '[get_cells -quiet [get_cells -quiet u/held*_reg*] extra]',
        )
        for selector in selectors:
            with self.subTest(selector=selector):
                data = self.native_export(f'set_bus_skew -from {selector} -to [get_pins u/captured0_reg/D] 8\n'+PAIR_B)
                self.assertEqual(len(data['unsupported']), 1)
                self.assertIn('non-object argument', data['unsupported'][0]['reason'])
                self.assertEqual(len(data['rows']), 2)

    def test_native_bridge_does_not_expose_commands_or_raw_object_arguments(self):
        for selector in ('[all_fanin -flat -startpoints_only -to u/captured0_reg/D]',
                         '[get_pins -of_objects u/held0_reg]',
                         '[filter u/held0_reg/C {REF_PIN_NAME == C || REF_PIN_NAME == CLK}]',
                         '[get_pins [exec forbidden_external_program]]',
                         '[get_pins [source secret.tcl]]',
                         '[get_pins [eval secret]]',
                         '[get_pins [set_property NAME bad object]]',
                         '[get_pins [set arbitrary_var bad]]'):
            with self.subTest(selector=selector):
                data=self.native_export(f'set_bus_skew -from {selector} -to [get_pins u/captured0_reg/D] 8\n'+PAIR_B)
                self.assertEqual(len(data['unsupported']),1)
                self.assertEqual(len(data['rows']),2)
        self.assertIn('requires ROOT',self.native_export(PAIR_B,mutation='set native_scope nested',failure=True))
        data=self.native_export('current_instance vendor\nset_max_delay -from [get_pins *] -to [get_pins *] 8\ncurrent_instance -quiet\n'+PAIR_B)
        self.assertEqual(data['native_query_calls'],0)
        self.assertEqual(data['unsupported'][0]['scope'],'vendor')


if __name__ == "__main__":
    unittest.main()
