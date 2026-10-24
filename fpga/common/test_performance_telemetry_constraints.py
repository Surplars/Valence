#!/usr/bin/env python3
"""Bounded Tcl collection/control oracle; not a Vivado timing or CDC signoff."""
from pathlib import Path
import subprocess
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

class TelemetryConstraintTests(unittest.TestCase):
    def tcl(self, script, good=True):
        p = subprocess.run(['tclsh'], input='if {[catch {\n'+script+'\n} err]} {puts stderr $err; exit 1}\n',
                           text=True, capture_output=True, timeout=10)
        self.assertEqual(p.returncode == 0, good, p.stdout+p.stderr)
        return p.stdout

    def test_canonical_callers_and_feature_binding(self):
        for name in ('post_synth.tcl', 'post_opt.tcl'):
            text = (HERE/name).read_text()
            self.assertIn('source [file join [file dirname [info script]] performance_telemetry_constraints.tcl]', text)
            self.assertIn('common_performance_telemetry_constraints', text)
        self.assertIn("performance_telemetry=int(m['configuration'].get('performance_telemetry', False))",
                      (HERE/'diagnostic.py').read_text())
        self.assertIn("meta.get('performanceTelemetry', False) is telemetry", (HERE/'board_inputs.py').read_text())
        self.assertIn("'fpga/zu15eg/performance-telemetry-constraints.tcl'", (HERE/'board_inputs.py').read_text())

    def test_exact_sixteen_banks_and_bridge(self):
        stub = '''
set cells {}
for {set d 0} {$d < 2} {incr d} {
 for {set c 0} {$c < 8} {incr c} {
  for {set b 0} {$b < 32} {incr b} {lappend cells [format {u_soc/monitor/domain%d/graySync0_%d_reg[%d]} $d $c $b]}
 }
}
set queries 0; set delays 0; set skews 0; set bridges 0
proc get_cells {args} {
 global cells queries
 if {[lsearch -exact $args -hierarchical]>=0} {incr queries; return $cells}
 return [lindex $args end]
}
proc get_property {prop objects} {return $objects}
proc get_pins {args} {return [lindex $args [expr {[lsearch -exact $args -of_objects]+1}]]}
proc all_fanin {args} {return [lindex $args end]}
proc set_max_delay {args} {global delays; incr delays}
proc set_bus_skew {args} {global skews; incr skews}
proc valence_register_cdc_constraints {hier budget} {
 global bridges; incr bridges
 if {$hier ne "u_soc/monitor/bridge" || $budget!=3.0} {error "wrong bridge scope"}
}
'''
        helper = 'source {'+str(ROOT/'fpga/zu15eg/performance-telemetry-constraints.tcl')+'}\n'
        self.tcl(stub+helper+'''
valence_performance_telemetry_constraints u_soc/monitor 3.0
if {$queries!=1 || $delays!=16 || $skews!=16 || $bridges!=1} {error "wrong bounded coverage"}
''')
        self.tcl(stub+helper+'set cells [lrange $cells 1 end]\nvalence_performance_telemetry_constraints u_soc/monitor 3.0', False)
        self.tcl(stub+helper+'set cells {}\nvalence_performance_telemetry_constraints u_soc/monitor 3.0', False)
        a1 = 'for {set b 0} {$b<32} {incr b} {lappend cells [format {u_soc/monitor/cpuRetireLane1/graySync0_1_reg[%d]} $b]}\n'
        self.tcl(stub+helper+a1+'''
valence_performance_telemetry_constraints u_soc/monitor 3.0 a1-experimental
if {$queries!=1 || $delays!=17 || $skews!=17 || $bridges!=1} {error "wrong A1 coverage"}
''')
        for setup, profile in ((a1, 'i1'), ('', 'a1-experimental'),
                               (a1+'set cells [lrange $cells 1 end]\n', 'a1-experimental'),
                               (a1+'lset cells end [lindex $cells 0]\n', 'a1-experimental'),
                               (a1+'lset cells end {u_soc/monitor/cpuRetireLane1/graySync0_2_reg[31]}\n', 'a1-experimental'),
                               (a1+'lset cells end {u_soc/monitor/cpuRetireLane1/graySync0_1_reg[32]}\n', 'a1-experimental'),
                               (a1, 'unknown')):
            self.tcl(stub+helper+setup+f'''
if {{![catch {{valence_performance_telemetry_constraints u_soc/monitor 3.0 {profile}}}]}} {{error "negative accepted"}}
if {{$delays || $skews || $bridges}} {{error "failed preflight mutated constraints"}}
''')


        for bad in ('{}', '[lrange $objects 1 end]', '[lreplace $objects end end [lindex $objects 0]]'):
            self.tcl(stub+helper+a1+f'''
rename get_pins old_get_pins
proc get_pins {{args}} {{
 set objects [old_get_pins {{*}}$args]
 if {{[lindex $args end] eq "REF_PIN_NAME == D"}} {{return {bad}}}
 return $objects
}}
if {{![catch {{valence_performance_telemetry_constraints u_soc/monitor 3.0 a1-experimental}}]}} {{error "missing D pins accepted"}}
if {{$delays || $skews || $bridges}} {{error "pin preflight mutated constraints"}}
''')

    def test_feature_fail_closed(self):
        body = (HERE/'performance_telemetry_constraints.tcl').read_text()
        # Keep actual caller logic; source its already independently tested helper as a stub.
        body = '\n'.join(x for x in body.splitlines() if not x.startswith('source '))
        stub = '''
set calls 0
proc valence_performance_telemetry_constraints {hier budget {profile i1}} {global calls selected; incr calls; set selected $profile}
proc get_cells {args} {global present; return $present}
'''
        for enabled, present, good in ((1,'u_soc/monitor',True),(1,'',False),(0,'',True),(0,'u_soc/monitor',False)):
            self.tcl(stub+body+f'\nset valence(performance_telemetry) {enabled}\nset present {{{present}}}\ncommon_performance_telemetry_constraints\n', good)
        self.tcl(stub+body+'''
set valence(performance_telemetry) 1
set valence(telemetry_physical_profile) a1-experimental
set present u_soc/monitor
common_performance_telemetry_constraints
if {$calls!=1 || $selected ne "a1-experimental"} {error "A1 profile not forwarded"}
''')
        self.tcl(stub+body+'''
set valence(performance_telemetry) 1
set valence(telemetry_physical_profile) unknown
set present u_soc/monitor
if {![catch {common_performance_telemetry_constraints}]} {error "unknown profile accepted"}
if {$calls} {error "invalid profile mutated"}
''')


if __name__ == '__main__':
    unittest.main()
