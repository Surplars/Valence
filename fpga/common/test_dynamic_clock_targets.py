"""Tcl contract mocks, not native Vivado timing evidence."""
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent

class DynamicClockTargets(unittest.TestCase):
    def run_contract(self, mutation=''):
        harness = r'''
set periods [dict create u_ddr/c0_ddr4_ui_clk 4.0 u_clk_wiz/clk_out1 20.0 u_soc/alwaysOnClock 20.0 u_soc/rawUartClock 20.0 u_soc/ddrClock 4.0 u_soc/fixedTimer/timer/clock 4.0 u_soc/debugSequence/boundary/crossing/requests/sourceClock 4.0 network_clock/tx_source 8.0 network_clock/tx_pad_source 4.0 network_clock/delay_source 2.0]
set names {};set writes {};set masters {}
proc get_pins {args} {return [lindex $args end]}
proc get_clocks {args} {return [lindex $args end]}
proc get_property {property object} {
 global periods names masters
 if {$property eq "PERIOD"} {return [dict get $periods $object]}
 if {$property eq "NAME"} {if {[dict exists $names $object]} {return [dict get $names $object]};return $object}
 if {$property eq "MASTER_CLOCK"} {if {[dict exists $masters $object]} {return [dict get $masters $object]};return u_ddr/c0_ddr4_ui_clk}
 error "unexpected property"
}
proc create_generated_clock {args} {
 global periods names writes
 set target [lindex $args end];lappend writes $target
 if {$target ni {cpu_clock/mmcm/CLKOUT0 fabric_clock/mmcm/CLKOUT0}} {error "FIXED_CLOCK_OVERWRITTEN"}
 set src [lindex $args [expr {[lsearch -exact $args -source]+1}]]
 if {$src ne "u_ddr/c0_ddr4_ui_clk"} {error "MASTER_RELATION_CHANGED"}
 set m [lindex $args [expr {[lsearch -exact $args -multiply_by]+1}]]
 set d [lindex $args [expr {[lsearch -exact $args -divide_by]+1}]]
 set name [lindex $args [expr {[lsearch -exact $args -name]+1}]]
 foreach pin [list $target [string map {mmcm/CLKOUT0 managed_buffer/O} $target]] {
  dict set periods $pin [expr {4.0*$d/$m}];dict set names $pin $name
 }
}
proc report_clocks {args} {}
'''
        harness += f'source {{{HERE / "dynamic/synthesis_targets.xdc"}}}\n'
        harness += mutation + '\n'
        harness += f'source {{{HERE / "dynamic/performance_targets.tcl"}}}\n'
        harness += 'if {[catch {native_dynamic_performance_targets} why]} {puts "REJECTED: $why";exit 2}\n'
        harness += 'if {[llength $writes]!=2} {exit 3}\nputs CONTRACT_PASS\n'
        with tempfile.TemporaryDirectory() as d:
            script = Path(d)/'test.tcl';script.write_text(harness)
            return subprocess.run(['tclsh', str(script)], text=True, capture_output=True)

    def test_two_exact_pre_synthesis_targets_and_fixed_clocks(self):
        p = self.run_contract()
        self.assertEqual(p.returncode, 0, p.stdout+p.stderr)
        self.assertIn('CONTRACT_PASS', p.stdout)
        source = (HERE/'synthesize.tcl').read_text()
        self.assertLess(source.index('read_xdc $dynamicTargets'), source.index('common_design_step synth_design -top'))
        self.assertLess(source.index('native_dynamic_performance_targets'), source.index('write_checkpoint synthesized.dcp'))
        proof = (HERE/'dynamic/dynamic_clock_constraints.tcl').read_text()
        self.assertIn('NOT_A_RUNTIME_MEASUREMENT NOT_THE_STA_TARGET', proof)

    def test_relaxed_cpu_target_rejected(self):
        p = self.run_contract('dict set periods cpu_clock/managed_buffer/O 20.0')
        self.assertEqual(p.returncode, 2)
        self.assertIn('missing or relaxed', p.stdout)

    def test_relaxed_fabric_target_rejected(self):
        p = self.run_contract('dict set periods fabric_clock/managed_buffer/O 20.0')
        self.assertEqual(p.returncode, 2)
        self.assertIn('missing or relaxed', p.stdout)

    def test_accidental_fixed_clock_change_rejected(self):
        p = self.run_contract('dict set periods network_clock/tx_source 20.0')
        self.assertEqual(p.returncode, 2)
        self.assertIn('fixed clock changed', p.stdout)

    def test_changed_fixed_master_relationship_rejected(self):
        p = self.run_contract('dict set masters network_clock/tx_source {}')
        self.assertEqual(p.returncode, 2)
        self.assertIn('lost UI master', p.stdout)
