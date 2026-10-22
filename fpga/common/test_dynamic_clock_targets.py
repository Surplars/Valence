"""Tcl contract mocks, not native Vivado timing or per-register evidence."""
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
UART = 'u_soc/peripherals/uart'
AON = 'clk_out1_clk_wiz_common'
FF = UART + '/uart/state_reg[1]/C'


class DynamicClockTargets(unittest.TestCase):
    def run_contract(self, mutation='', board=False, after_first=''):
        harness = r'''
set periods [dict create u_ddr/c0_ddr4_ui_clk 4.0 clk_out1_clk_wiz_common 20.0 mmcm_clkout0 20.0 u_soc/ddrClock 4.0 u_soc/fixedTimer/timer/clock 4.0 u_soc/debugSequence/boundary/crossing/requests/sourceClock 4.0 network_clock/tx_source 8.0 network_clock/tx_pad_source 4.0 network_clock/delay_source 2.0]
set names {}; set writes {}; set masters {}; set pins {}; set clocks {}; set drivers {}; set inverted {}; set sources {}; set queried {}
set leaf_queries 0; set segments_override {}; set net_driver_overrides {}; set ref_overrides {}
set uart u_soc/peripherals/uart
set aon clk_out1_clk_wiz_common
set aon_driver u_clk_wiz/inst/clkout1_buf/O
set gate $uart/gatedClock_gate/buffer
set cells [dict create $gate BUFGCE u_soc/cpu CommonI1CpuTile \
 u_soc/peripherals/uart/uart/not_a_ff LUT1 u_soc/peripherals/uart/uart_extra/outside_reg FDRE]
set ce_type SYNC
foreach pin [dict keys $periods] {dict set pins $pin 1; dict set clocks $pin $pin}
foreach pin [list u_clk_wiz/clk_out1 u_soc/alwaysOnClock $aon_driver $uart/rawClock $uart/gatedClock_gate/rawClock $gate/I $uart/sampledRx_meta_reg/C] {
 dict set pins $pin 1; dict set clocks $pin $aon; dict set drivers $pin $aon_driver
}
foreach pin [list $gate/O $uart/uart/clock] {
 dict set pins $pin 1; dict set clocks $pin $aon; dict set drivers $pin $gate/O
}
foreach bit {0 1} {
 set cell [format {%s/uart/state_reg[%d]} $uart $bit]
 dict set cells $cell FDRE; dict set pins $cell/C 1; dict set clocks $cell/C $aon; dict set drivers $cell/C $gate/O
}
# These aliases exist but are unclocked/grounded: neither may be consulted.
foreach pin {u_soc/rawUartClock u_soc/peripherals/rawUartClock} {dict set pins $pin 1; dict set clocks $pin {}; dict set drivers $pin GND/G}
dict set masters $aon mmcm_clkout0
dict set sources $aon u_clk_wiz/inst/mmcme4_adv_inst/CLKOUT0
proc get_pins {args} {
 global pins drivers queried leaf_queries aon_driver gate net_driver_overrides
 set at [lsearch -exact $args -of_objects]
 if {$at>=0} {
  set result {}
  if {[lindex $args end] eq "REF_PIN_NAME == C"} {
   foreach cell [lindex $args [expr {$at+1}]] {
    if {[dict exists $pins $cell/C]} {lappend result $cell/C; lappend queried $cell/C}
   }
   return $result
  }
  incr leaf_queries
  foreach net [lindex $args [expr {$at+1}]] {
   if {[dict exists $net_driver_overrides $net]} {
    lappend result {*}[dict get $net_driver_overrides $net]
   } elseif {$net in {aon_top aon_leaf}} {
    lappend result $aon_driver
   } elseif {$net in {uart_gate_top uart_gate_leaf}} {
    lappend result $gate/O
   } else {
    set pin [string range $net 4 end]
    if {[dict exists $drivers $pin]} {lappend result {*}[dict get $drivers $pin]}
   }
  }
  return [lsort -unique $result]
 }
 set pattern [lindex $args end]; set result {}
 foreach pin [dict keys $pins] {
  if {([lsearch -exact $args -regexp]>=0 && [regexp $pattern $pin]) || $pattern eq $pin} {
   lappend result $pin; lappend queried $pin
  }
 }
 return $result
}
proc get_cells {args} {
 global cells
 # Match the actual native selector contract, not a preset list of FF objects.
 # Native hierarchical regexp full-path selection returned zero on this DCP.
 set regexp_at [lsearch -exact $args -regexp]
 if {$regexp_at>=0} {
  set pattern [lindex $args [expr {$regexp_at+1}]]
  if {$pattern eq {^u_soc/peripherals/uart/uart/.*$}} {return {}}
  set result {}
  foreach cell [dict keys $cells] {if {[regexp $pattern $cell]} {lappend result $cell}}
  return $result
 }
 set filter_at [lsearch -exact $args -filter]
 set result {}
 if {$filter_at>=0} {
  set filter [lindex $args [expr {$filter_at+1}]]
  if {[string first NAME $filter]>=0 && [string first {&&} $filter]>=0 &&
      $args ne {-quiet -hier -filter {REF_NAME =~ FD* && NAME =~ u_soc/peripherals/uart/uart/*}}} {
   error {unexpected hierarchical cell selector}
  }
  foreach cell [dict keys $cells] {
   set selected 1
   foreach term [split $filter &] {
    set term [string trim $term]; if {$term eq ""} {continue}
    if {![regexp {^(REF_NAME|NAME) =~ (.+)$} $term -> property pattern]} {error {unexpected cell filter}}
    set value [expr {$property eq "NAME" ? $cell : [dict get $cells $cell]}]
    if {![string match $pattern $value]} {set selected 0}
   }
   if {$selected} {lappend result $cell}
  }
 } else {
  foreach cell [dict keys $cells] {if {$cell eq [lindex $args end]} {lappend result $cell}}
 }
 return $result
}
proc get_nets {args} {
 global drivers aon_driver gate segments_override
 set at [lsearch -exact $args -of_objects]
 if {$at<0} {error {unexpected net query}}
 set result {}
 foreach pin [lindex $args [expr {$at+1}]] {
  if {[dict exists $segments_override $pin]} {
   lappend result {*}[dict get $segments_override $pin]
  } elseif {[dict exists $drivers $pin] && [dict get $drivers $pin] eq $aon_driver} {
   lappend result aon_top aon_leaf
  } elseif {[dict exists $drivers $pin] && [dict get $drivers $pin] eq "$gate/O"} {
   lappend result uart_gate_top uart_gate_leaf
  } else {
   # A changed per-pin driver represents a distinct physical net, not an
   # inconsistent driver answer for another pin on the same complete net.
   lappend result net:$pin
  }
 }
 return $result
}
proc get_clocks {args} {
 global clocks periods
 set at [lsearch -exact $args -of_objects]; set result {}
 if {$at>=0} {
  foreach pin [lindex $args [expr {$at+1}]] {
   if {[dict exists $clocks $pin]} {lappend result {*}[dict get $clocks $pin]}
  }
 } else {
  foreach clock [lindex $args end] {if {[dict exists $periods $clock]} {lappend result $clock}}
 }
 return [lsort -unique $result]
}
proc get_property {property object} {
 global periods names masters cells ce_type inverted sources ref_overrides
 if {[llength $object]==1} {set object [lindex $object 0]}
 if {$property eq "PERIOD"} {return [dict get $periods $object]}
 if {$property eq "NAME"} {if {[dict exists $names $object]} {return [dict get $names $object]}; return $object}
 if {$property eq "MASTER_CLOCK"} {if {[dict exists $masters $object]} {return [dict get $masters $object]}; return u_ddr/c0_ddr4_ui_clk}
 if {$property eq "SOURCE_PINS"} {if {[dict exists $sources $object]} {return [dict get $sources $object]}; return {}}
 if {$property eq "IS_INVERTED"} {if {[dict exists $inverted $object]} {return [dict get $inverted $object]}; return 0}
 if {$property eq "REF_NAME"} {if {[dict exists $ref_overrides $object]} {return [dict get $ref_overrides $object]}; return [dict get $cells $object]}
 if {$property eq "CE_TYPE"} {return $ce_type}
 error "unexpected property $property"
}
proc create_generated_clock {args} {
 global periods names writes pins clocks
 set target [lindex $args end]; lappend writes $target
 if {$target ni {cpu_clock/mmcm/CLKOUT0 fabric_clock/mmcm/CLKOUT0}} {error "FIXED_CLOCK_OVERWRITTEN"}
 set src [lindex $args [expr {[lsearch -exact $args -source]+1}]]
 if {$src ne "u_ddr/c0_ddr4_ui_clk"} {error "MASTER_RELATION_CHANGED"}
 set m [lindex $args [expr {[lsearch -exact $args -multiply_by]+1}]]
 set d [lindex $args [expr {[lsearch -exact $args -divide_by]+1}]]
 set name [lindex $args [expr {[lsearch -exact $args -name]+1}]]
 foreach pin [list $target [string map {mmcm/CLKOUT0 managed_buffer/O} $target]] {
  dict set periods $pin [expr {4.0*$d/$m}]; dict set names $pin $name; dict set clocks $pin $pin; dict set pins $pin 1
 }
}
foreach pin {cpu_clock/mmcm/CLKOUT0 fabric_clock/mmcm/CLKOUT0} {dict set pins $pin 1}
proc report_clocks {args} {}
'''
        harness += f'source {{{HERE / "dynamic/synthesis_targets.xdc"}}}\n'
        harness += mutation + '\n'
        if board:
            harness += 'set ::common_board_definitions_only 1\n'
            harness += f'source {{{HERE / "board_audit.tcl"}}}\n'
            harness += r'''
set valence(cpu) i1
set valence(clock_profile) production
proc common_cdc::clock {pin} {
 if {$pin eq "u_soc/cpuClock"} {return cpu_clock/managed_buffer/O}
 if {$pin eq "u_soc/fabricClock"} {return fabric_clock/managed_buffer/O}
 error "unexpected board clock query $pin"
}
proc common_cdc::same_net {a b} {}
'''
            command = 'common_board::cpu'
        else:
            harness += f'source {{{HERE / "dynamic/performance_targets.tcl"}}}\n'
            command = 'native_dynamic_performance_targets'
        checked_commands = command
        if after_first:
            checked_commands += '\n' + after_first + '\n' + command
        harness += f'if {{[catch {{{checked_commands}}} why]}} {{puts "REJECTED: $why"; exit 2}}\n'
        harness += r'''
if {[llength $writes]!=2} {exit 3}
foreach alias {u_soc/rawUartClock u_soc/peripherals/rawUartClock} {
 if {[lsearch -exact $queried $alias]>=0} {error {dead raw UART alias queried}}
}
puts CONTRACT_PASS
puts LEAF_DRIVER_QUERIES=$leaf_queries
'''
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'test.tcl'
            script.write_text(harness)
            return subprocess.run(['tclsh', str(script)], text=True, capture_output=True)

    def assert_rejected(self, mutation, reason, board=False):
        result = self.run_contract(mutation, board=board)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn(reason, result.stdout)
        return result.stdout

    def test_two_exact_pre_synthesis_targets_and_functional_uart(self):
        result = self.run_contract()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('CONTRACT_PASS', result.stdout)
        self.assertIn('CONSOLE_FF_CLOCK_PINS=2 INDIVIDUAL_CLOCK_AND_DRIVER_CHECKS', result.stdout)
        self.assertIn('LEAF_DRIVER_QUERIES=2', result.stdout)
        source = (HERE / 'synthesize.tcl').read_text()
        self.assertLess(source.index('read_xdc $dynamicTargets'), source.index('common_design_step synth_design -top'))
        self.assertLess(source.index('native_dynamic_performance_targets'), source.index('write_checkpoint synthesized.dcp'))
        proof = (HERE / 'dynamic/dynamic_clock_constraints.tcl').read_text()
        self.assertIn('NOT_A_RUNTIME_MEASUREMENT NOT_THE_STA_TARGET', proof)

    def test_relaxed_cpu_and_fabric_targets_rejected_with_actual_period(self):
        for root in ('cpu_clock', 'fabric_clock'):
            with self.subTest(root=root):
                output = self.assert_rejected(f'dict set periods {root}/managed_buffer/O 20.0', 'missing or relaxed')
                self.assertIn('period=20.0', output)

    def test_accidental_fixed_clock_change_rejected(self):
        self.assert_rejected('dict set periods network_clock/tx_source 20.0', 'fixed clock changed')

    def test_changed_fixed_master_relationship_rejected(self):
        self.assert_rejected('dict set masters network_clock/tx_source {}', 'lost UI master')

    def test_missing_functional_anchors_rejected(self):
        for pin in (UART + '/rawClock', UART + '/gatedClock_gate/rawClock',
                    UART + '/gatedClock_gate/buffer/I', UART + '/gatedClock_gate/buffer/O',
                    UART + '/uart/clock', UART + '/sampledRx_meta_reg/C', FF):
            with self.subTest(pin=pin):
                self.assert_rejected(f'dict unset pins {{{pin}}}', f'missing exact clock pin {pin}')

    def test_empty_and_multiclock_functional_anchors_rejected(self):
        for pin in (UART + '/rawClock', UART + '/uart/clock', FF):
            for clocks in ('{}', f'{{{AON} network_clock/tx_source}}'):
                with self.subTest(pin=pin, clocks=clocks):
                    output = self.assert_rejected(f'dict set clocks {{{pin}}} {clocks}', 'expected unique 20 ns clock')
                    self.assertIn('actual=', output)

    def test_different_20ns_clock_cannot_impersonate_aon(self):
        for pin in (UART + '/rawClock', UART + '/uart/clock', FF):
            with self.subTest(pin=pin):
                mutation = f'dict set periods other20 20.0; dict set clocks {{{pin}}} other20'
                output = self.assert_rejected(mutation, 'wrong AON clock')
                self.assertIn('other20(period=20.0)', output)

    def test_aon_wrong_period_and_source_rejected(self):
        self.assert_rejected(f'dict set periods {AON} 10.0', 'fixed clock changed')
        self.assert_rejected(f'dict set sources {AON} wrong_mmcm/CLKOUT0', 'wrong AON clock')

    def test_raw_and_gated_physical_driver_required_per_pin(self):
        for pin in (UART + '/rawClock', UART + '/gatedClock_gate/rawClock',
                    UART + '/sampledRx_meta_reg/C', UART + '/uart/clock', FF):
            for driver in ('{}', 'GND/G', '{unexpected/O duplicate/O}'):
                with self.subTest(pin=pin, driver=driver):
                    self.assert_rejected(f'dict set drivers {{{pin}}} {driver}', 'wrong physical clock driver')
        self.assert_rejected(f'dict set drivers {{{FF}}} u_clk_wiz/inst/clkout1_buf/O', 'wrong physical clock driver')

    def test_uart_master_must_reach_ui_without_cycle(self):
        for mutation in (f'dict set masters {AON} {{}}',
                         f'dict set masters {AON} absent',
                         f'dict set masters mmcm_clkout0 {AON}'):
            with self.subTest(mutation=mutation):
                self.assert_rejected(mutation, 'master')

    def test_gate_type_synchronous_enable_and_clock_polarity_required(self):
        self.assert_rejected('dict set cells $gate BUFG', 'synchronous BUFGCE')
        self.assert_rejected('set ce_type ASYNC', 'synchronous BUFGCE')
        self.assert_rejected(f'dict set inverted {{{FF}}} 1', 'inverted/unknown clock pin')

    def test_empty_console_ff_collection_rejected(self):
        self.assert_rejected('dict for {cell ref} $cells {if {$ref eq "FDRE"} {dict unset cells $cell}}', 'missing console FF')

    def test_selected_console_cell_name_and_type_are_rechecked(self):
        cell = FF.removesuffix('/C')
        for name in ('u_soc/peripherals/uart/uart_extra/outside_reg', UART + '/uart/'):
            with self.subTest(name=name):
                self.assert_rejected(f'dict set names {{{cell}}} {{{name}}}', 'unexpected console FF cell')
        self.assert_rejected(f'dict set ref_overrides {{{cell}}} LUT1', 'unexpected console FF cell')
        self.assert_rejected(f'dict set names {{{cell}}} {{{UART}/uart/state_reg[0]}}', 'duplicate console FF clock pin')

    def test_leaf_driver_cache_uses_complete_sorted_net_collection(self):
        result = self.run_contract(f'dict set segments_override {{{FF}}} {{uart_gate_leaf uart_gate_top}}')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('LEAF_DRIVER_QUERIES=2', result.stdout)
        # A shared first segment alone must not reuse another collection's proof.
        mutation = (f'dict set segments_override {{{FF}}} {{uart_gate_leaf z_changed_leaf}}; '
                    'dict set net_driver_overrides z_changed_leaf wrong/O')
        self.assert_rejected(mutation, 'wrong physical clock driver')

    def test_leaf_driver_cache_does_not_survive_an_invocation(self):
        result = self.run_contract(after_first='dict set net_driver_overrides uart_gate_leaf wrong/O')
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn('wrong physical clock driver', result.stdout)
        self.assertIn('wrong/O', result.stdout)

    def test_board_cpu_uses_same_proof_and_ignores_dead_aliases(self):
        result = self.run_contract(board=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('COMMON_CPU UART50_FUNCTIONAL_CLOCKS_PASS', result.stdout)
        self.assert_rejected(f'dict set clocks {{{FF}}} {{}}', 'COMMON_CPU UART expected unique 20 ns clock', board=True)
        self.assert_rejected(f'dict set masters {AON} {{}}', 'lost UI master', board=True)
        self.assert_rejected(f'dict set drivers {{{FF}}} GND/G', 'wrong physical clock driver', board=True)


if __name__ == '__main__':
    unittest.main()
