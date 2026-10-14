#!/usr/bin/env python3
"""Host contract regressions only; real Vivado evaluation is separately required."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('ready73_launch', HERE/'run_timing_ready73.py')
launcher = importlib.util.module_from_spec(spec); spec.loader.exec_module(launcher)

RAW_ANCHOR_CASES = '# Mock only Vivado\'s object/property boundary, retaining all role logic.\nrename valence_mac_roles::property valence_mac_roles::vivado_property\nproc valence_mac_roles::property {cmd name key} {\n    if {![dict exists $::props $name $key]} {error "missing property $name $key"}\n    return [dict get $::props $name $key]\n}\nrename valence_mac_roles::net valence_mac_roles::vivado_net\nproc valence_mac_roles::net {pin} {\n    if {![dict exists $::nets $pin]} {error "missing pin $pin"}\n    return [dict get $::nets $pin]\n}\nrename valence_mac_roles::driver valence_mac_roles::vivado_driver\nproc valence_mac_roles::driver {pin} {\n    set n [net $pin]\n    if {![dict exists $::drivers $n]} {error "missing driver $pin"}\n    return [dict get $::drivers $n]\n}\nproc get_cells {args} {return $::cells}\nproc get_pins {args} {set p [lindex $args end]; if {![dict exists $::nets $p]} {return {}}; return $p}\nproc get_clocks {args} {\n    set p [lindex $args end]\n    if {![dict exists $::nets $p]} {return {}}\n    set n [dict get $::nets $p]\n    if {![dict exists $::clocks $n]} {return {}}\n    return [dict get $::clocks $n]\n}\nproc get_property {key objects} {\n    if {$key eq "NAME"} {return $objects}\n    if {![dict exists $::props $objects $key]} {error "missing clock property $objects $key"}\n    return [dict get $::props $objects $key]\n}\nset E u_soc/board/nativeBank/gmac/encode\nset F u_soc/board/nativeBank/gmac/rawHandoff/falling\nset H u_rgmii\nset W $E/control\nset S $F/sample\nproc setup {} {\n    global E F H W S nets drivers props cells clocks\n    set nets [dict create $H/tx_clock gnd $H/tx_pad_clock pad $W/C raw $W/CLR reset $W/CE power $W/Q rise $E/clock raw $E/reset reset [format {%s/io_rise[4]} $E] rise [format {%s/tx_rise[4]} $H] rise $S/C raw $S/CLR reset $S/CE power $S/Q sample rawdiv/O raw rawdiv/I ref rawdiv/CLR divreset rawdiv/CE power paddiv/O pad paddiv/I ref paddiv/CLR divreset paddiv/CE power]\n    set drivers [dict create rise $W/Q raw rawdiv/O pad paddiv/O]\n    set props [dict create power [dict create TYPE POWER] gnd [dict create TYPE GROUND] reset [dict create TYPE SIGNAL] raw [dict create TYPE SIGNAL] pad [dict create TYPE SIGNAL]]\n    foreach {c edge} [list $W 0 $S 1] {\n        dict set props $c REF_NAME FDCE; dict set props $c INIT 0\n        dict set props $c/C IS_INVERTED $edge; dict set props $c/CLR IS_INVERTED 0\n        dict set props $c/Q REF_PIN_NAME Q\n    }\n    foreach {c ratio} {paddiv 2 rawdiv 4} {\n        dict set props $c REF_NAME BUFGCE_DIV; dict set props $c BUFGCE_DIVIDE $ratio\n        dict set props $c/O REF_PIN_NAME O\n        foreach pin {I CE CLR} {dict set props $c/$pin IS_INVERTED 0}\n    }\n    set clocks [dict create raw rawclock pad padclock ref refclock]\n    foreach {c p w} {rawclock 8 {0 4} padclock 4 {0 2} refclock 2 {0 1}} {\n        dict set props $c PERIOD $p; dict set props $c WAVEFORM $w\n    }\n    set cells [list $W $S]\n}\nset tests 0\nproc case {name edit pass {required 1}} {\n    setup; uplevel #0 $edit\n    set failed [catch {valence_mac_roles::clocks $::H $required} result]\n    if {$failed==$pass} {error "$name unexpected outcome: $result"}\n    incr ::tests\n    puts "PASS $name"\n}\ncase unused_adapter_clock_ground {} 1\ncase real_raw_ground {dict set nets $W/C gnd} 0\ncase raw_wrong_period {dict set props rawclock PERIOD 7.9} 0\ncase pad_wrong_period {dict set props padclock PERIOD 8} 0\ncase ref_wrong_period {dict set props refclock PERIOD 4} 0\ncase raw_wrong_source {dict set nets rawdiv/I other} 0\ncase raw_wrong_reset_epoch {dict set nets rawdiv/CLR other} 0\ncase wrong_divider_ratio {dict set props rawdiv BUFGCE_DIVIDE 2} 0\ncase wrong_divider_primitive {dict set props rawdiv REF_NAME BUFGCE} 0\ncase divider_ce_ground {dict set nets rawdiv/CE gnd} 0\ncase wrong_waveform {dict set props rawclock WAVEFORM {1 5}} 0\ncase missing_encoder_ff {set cells [list $S]} 0\ncase missing_required_falling {set cells [list $W]} 0\ncase historical_off_explicit {set cells [list $W]} 1 0\ncase sample_wrong_clock {dict set nets $S/C pad} 0\ncase sample_wrong_edge {dict set props $S/C IS_INVERTED 0} 0\ncase sample_wrong_reset {dict set nets $S/CLR divreset} 0\ncase sample_wrong_init {dict set props $S INIT 1} 0\ncase sample_ce_ground {dict set nets $S/CE gnd} 0\ncase encoder_wrong_edge {dict set props $W/C IS_INVERTED 1} 0\ncase encoder_wrong_reset {dict set nets $W/CLR wrong_reset} 0\ncase encoder_dynamic_ce {dict set nets $W/CE encoder_enable; dict set props encoder_enable TYPE SIGNAL} 1\ncase witness_not_q {dict set props $W/Q REF_PIN_NAME D} 0\ncase missing_clock {dict unset clocks raw} 0\ncase encoder_copy_wrong_clock {lappend cells $E/copy; dict set props $E/copy REF_NAME FDCE; dict set nets $E/copy/C pad; dict set props $E/copy/C IS_INVERTED 0} 0\ncase same_clock_name_wrong_net {dict set nets $S/C managed; dict set clocks managed rawclock} 0\nforeach pin {I CE CLR} {case divider_inverted_$pin [list dict set props rawdiv/$pin IS_INVERTED 1] 0}\nputs "PASS $tests RAW anchor host controls; actual Vivado still required"\n'

class DriverTests(unittest.TestCase):
    def test_raw_clock_anchor_controls(self):
        script = "source {"+str(HERE/"native_mac_roles.tcl")+"}\n"+RAW_ANCHOR_CASES
        r=subprocess.run(["tclsh"],input=script,text=True,capture_output=True)
        self.assertEqual(r.stderr, "")
        self.assertIn("PASS 29 RAW anchor host controls",r.stdout)

    def test_actual_design_and_debug_stages(self):
        source=(HERE/'run_timing_ready73.tcl').read_text().split('if {[catch {ready73_run} why options]}')[0]
        cases=r'''
proc current_design {} {return design}
proc get_property {key obj} {return [dict get $::p $obj $key]}
proc get_cells {args} {return $::boxes}
set p [dict create design [dict create TOP soc_top_fpga_next_ddr NAME checkpoint_diagnostic_SYNTH_MAPPED_CHAIN_GATE_START PART xczu15eg-ffvb1156-2-i] dbg_hub [dict create NAME dbg_hub REF_NAME dbg_hub_CV ORIG_REF_NAME dbg_hub_CV IS_PRIMITIVE 0]]
ready73_design_identity
set boxes {dbg_hub}
ready73_blackboxes synth
if {![catch {ready73_blackboxes postopt}]} {error "stub survived opt"}
if {![catch {ready73_blackboxes placed}]} {error "stub survived place"}
set boxes {}
ready73_blackboxes postopt
ready73_blackboxes placed
set boxes {dbg_hub}
foreach key {NAME REF_NAME ORIG_REF_NAME IS_PRIMITIVE} {
 set old $p; dict set p dbg_hub $key wrong
 if {![catch {ready73_blackboxes synth}]} {error "wrong stub $key accepted"}
 set p $old
}
foreach key {TOP PART} {
 set old $p; dict set p design $key wrong
 if {![catch ready73_design_identity]} {error "wrong design $key accepted"}
 set p $old
}
puts PASS_STAGE_CONTRACT
'''
        r=subprocess.run(['tclsh'],input=source+cases,text=True,capture_output=True)
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(r.stderr,'')
        self.assertIn('PASS_STAGE_CONTRACT',r.stdout)
    def test_real_nested_source_scope_and_order(self):
        # Execute the real driver procs, actual source/uplevel and real temporary
        # binding/require files. Only Vivado commands and netlist gates are mocks.
        with tempfile.TemporaryDirectory() as d:
            d=Path(d); board=d/'export'/'board'; board.mkdir(parents=True)
            (board/'native-mac-mode.tcl').write_text("""
set mode_prepared 1
proc valence_native_mac_synth_design {args} {lappend ::events synth}
proc valence_native_mac_opt_design {} {lappend ::events opt}
proc valence_native_mac_verify_export {} {if {![info exists ::mode_prepared]} {error {missing global mode}}}
proc valence_native_mac_checkpoint {stage path} {lappend ::events checkpoint_$stage}
""")
            (board/'native_mac_roles.tcl').write_text("""
namespace eval valence_mac_roles {}
proc valence_mac_roles::audit {hier t1 selected required} {
 if {![info exists ::clocks_loaded] || ![info exists ::rate_loaded] || !$required} {error {wrong gate order}}
 lappend ::events roles
 return PASS_MAC_ROLE_SEMANTICS
}
""")
            (board/'require_trispeed.tcl').write_text("""
if {![info exists VALENCE_TRISPEED_MBPS] || $VALENCE_TRISPEED_MBPS!=1000 || ![info exists clocks_loaded]} {error {rate scope/order}}
set rate_loaded 1
set VALENCE_MAC_CONTRACT reviewed_contract
proc valence_mac_registered_level_constraints {contract} {
 if {$contract ne "reviewed_contract"} {error {MAC binding changed}}
 lappend ::events mac_levels
}
proc valence_trispeed_packet_cdc_constraints {root} {
 if {$root ne "u_soc/board/nativeBank/gmac"} {error {MAC root changed}}
 lappend ::events mac_packet
}
lappend events rate
valence_mac_registered_level_constraints $VALENCE_MAC_CONTRACT
""")
            (board/'require_jtag_chain.tcl').write_text("""
if {![info exists VALENCE_JTAG_OWN_CELL] || $VALENCE_JTAG_OWN_CELL ne {loader/bscan}} {error {USER2 scope}}
lappend events user2
""")
            (board/'bscan_timing.tcl').write_text("""
proc valence_apply_bscan_timing {primitive engine fabric profile} {
 if {$primitive ne "loader/bscan" || $engine ne "loader/transport" || $fabric ne "fabric" || $profile ne "zu15eg-user2-tck50-positive-v1"} {error {BSCAN binding changed}}
 lappend ::events bscan_apply
}
proc valence_reapply_bscan_cdc {primitive engine fabric} {lappend ::events bscan_reapply}
proc valence_bscan_qualifiers {primitive engine} {lappend ::events bscan_qualifiers}
proc valence_bscan_phase_handoff {engine} {lappend ::events bscan_handoff}
proc valence_bscan_fault_phase {engine} {lappend ::events bscan_fault}
""")
            binding=d/'binding.tcl' 
            binding.write_text('set READY73_EXPORT {'+str(board.parent)+'}\n'+"""
set READY73_READ_DESIGN {lappend ::events read_design}
set READY73_CONFIGURE_PYTHON {lappend ::events python}
set READY73_SYNTH_ARGS {-part xczu15eg-ffvb1156-2-i}
set READY73_ORIGINAL_CLOCKS {set ::clocks_loaded 1; lappend ::events clocks}
set READY73_CONTROL_CDC {lappend ::events control_cdc}
set READY73_BSCAN_ENGINE loader/transport
set READY73_FABRIC_CLOCK fabric
set VALENCE_JTAG_OWN_CELL loader/bscan
set VALENCE_TRISPEED_MBPS 1000
""")
            output=d/'output'
            prelude="""
set events {}
proc current_design {} {return observed}
proc get_property {key obj} {
 switch $key {TOP {return soc_top_fpga_next_ddr} NAME {return checkpoint_name} PART {return xczu15eg-ffvb1156-2-i} default {error {unexpected property}}}
}
proc get_cells {args} {return {}}
proc place_design {} {lappend ::events place}
proc write_checkpoint {args} {lappend ::events checkpoint_placed}
proc report_timing_summary {args} {}
proc report_utilization {args} {
 set expected {read_design python synth clocks rate mac_levels control_cdc bscan_apply roles user2 checkpoint_synth opt mac_packet control_cdc bscan_reapply mac_levels roles user2 checkpoint_postopt place roles user2 bscan_qualifiers bscan_handoff bscan_fault checkpoint_placed}
 if {$::events ne $expected} {error "Wrong actual sequence: $::events"}
}
"""
            script=prelude+'\nset argv [list {'+str(binding)+'} {'+str(output)+'} {'+str(board.parent)+'}]\nsource {'+str(HERE/'run_timing_ready73.tcl')+'}\n'
            r=subprocess.run(['tclsh'],input=script,text=True,capture_output=True)
            self.assertEqual(r.returncode,0,r.stderr)
            self.assertTrue((output/'evaluation-complete.txt').is_file(),r.stderr)
            self.assertIn('design_name=checkpoint_name',(output/'evaluation-complete.txt').read_text())
            original_binding=binding.read_text()
            for key in ('READY73_BSCAN_ENGINE','READY73_FABRIC_CLOCK','READY73_CONTROL_CDC'):
                binding.write_text('\n'.join(line for line in original_binding.splitlines() if not line.startswith('set '+key+' '))+'\n')
                failed_output=d/('missing-'+key)
                bad=subprocess.run(['tclsh'],input=script.replace(str(output),str(failed_output)),text=True,capture_output=True)
                self.assertEqual(bad.returncode,1)
                self.assertIn('Missing reviewed binding: '+key,bad.stderr)
                self.assertFalse(failed_output.exists())
            binding.write_text(original_binding)

    def test_typed_fifo_boundaries(self):
        script='source {'+str(HERE.parent/'zu15eg/native-gmac-cdc-constraints.tcl')+'}\n'+r"""
set known [list {fifo/output[0]/D} {fifo/storage[0]/CLK}]
proc get_pins {args} {
 set patterns [lindex $args end]; set found {}
 foreach name $::known {
  if {![catch {regexp $patterns $name} matched] && $matched} {lappend found @$name; continue}
  foreach pattern $patterns {if {[regexp $pattern $name]} {lappend found @$name; break}}
 }
 if {[info exists ::mutate_collection]} {
  if {$::mutate_collection eq "extra"} {lappend found @unexpected/pin}
  if {$::mutate_collection eq "missing"} {set found [lrange $found 1 end]}
 }
 return $found
}
proc get_property {key objects} {
 if {$objects eq "@path"} {
  switch $key {STARTPOINT_PIN {return {fifo/storage[0]/CLK}} ENDPOINT_PIN {return {fifo/output[0]/D}} REQUIREMENT {return 8.0} EXCEPTION {return max_delay}}
 }
 set names {}
 foreach object $objects {
  if {[string index $object 0] ne "@"} {error "Untyped object boundary: $object"}
  lappend names [string range $object 1 end]
 }
 if {$key eq "NAME"} {if {[llength $names]==1} {return [lindex $names 0]}; return $names}
 error "Unexpected property $key"
}
proc get_timing_paths {args} {
 foreach option {-from -to} {
  set obj [lindex $args [expr {[lsearch -exact $args $option]+1}]]
  foreach item $obj {if {[string index $item 0] ne "@"} {error "Untyped timing scope"}}
 }
 return @path
}
set scope [dict create starts [list {fifo/storage[0]/CLK}] ends [list {fifo/output[0]/D}] by_end [dict create {fifo/output[0]/D} [list {fifo/storage[0]/CLK}]]]
if {[valence_fifo_payload::check_paths $scope 8.0]!=1} {error "Path coverage changed"}
valence_fifo_payload::objects get_pins [dict get $scope starts]
valence_fifo_payload::objects get_pins [dict get $scope ends]
if {![catch {valence_fifo_payload::objects get_pins [list missing]}]} {error "Missing scope admitted"}
if {![catch {valence_fifo_payload::objects get_pins {}}]} {error "Empty scope admitted"}
valence_fifo_payload::objects get_pins $known
foreach mode {extra missing} {
 set mutate_collection $mode
 if {![catch {valence_fifo_payload::objects get_pins $known}]} {error "Changed collection $mode admitted"}
}
unset mutate_collection
rename valence_fifo_payload::collect valence_fifo_payload::original_collect
proc valence_fifo_payload::collect {hier} {return $::scope}
proc assert_typed_scope {args} {
 foreach option {-from -to} {
  foreach object [lindex $args [expr {[lsearch -exact $args $option]+1}]] {
   if {[string index $object 0] ne "@"} {error "Untyped final constraint scope"}
  }
 }
}
set constraints {}
proc set_max_delay {args} {
 if {[lrange $args 0 1] ne {-datapath_only 8.0}} {error "Changed max-delay budget"}
 assert_typed_scope {*}$args; lappend ::constraints max_delay
}
proc set_bus_skew {args} {
 if {[lindex $args 0] ne "8.0"} {error "Changed skew budget"}
 assert_typed_scope {*}$args; lappend ::constraints bus_skew
}
valence_fifo_payload_constraints fifo 8.0
if {$constraints ne {max_delay bus_skew}} {error "Missing final constraints"}
puts PASS_TYPED_FIFO
"""
        r=subprocess.run(['tclsh'],input=script,text=True,capture_output=True)
        self.assertEqual(r.stderr,'')
        self.assertIn('PASS_TYPED_FIFO',r.stdout)

    def test_fifo_batch_exact_pair_coverage(self):
        script='source {'+str(HERE.parent/'zu15eg/native-gmac-cdc-constraints.tcl')+'}\n'+r"""
# Pin collections are explicit typed tokens; zero additional get_pins calls
# are permitted when the caller supplies the already-resolved collections.
proc get_pins {args} {error "Unexpected repeated object lookup"}
proc get_property {key objects} {
 if {$key eq "NAME"} {return [lmap x $objects {string range $x 1 end}]}
 if {[string index $objects 0] ne "@"} {error "Untyped property"}
 set pair [dict get $::paths $objects]
 if {$objects eq "@b"} {
  if {$::mode eq "fallback_budget" && $key eq "REQUIREMENT"} {return 8.1}
  if {$::mode eq "fallback_nan" && $key eq "REQUIREMENT"} {return NaN}
  if {$::mode eq "fallback_exception" && $key eq "EXCEPTION"} {return {}}
 }
 switch $key {STARTPOINT_PIN {return [lindex $pair 0]} ENDPOINT_PIN {return [lindex $pair 1]} REQUIREMENT {return $::requirement} EXCEPTION {return $::exception}}
 error "Bad property"
}
set paths [dict create @a {s0 e0} @b {s1 e0} @c {s1 e1} @bad {foreign e0}]
set scope [dict create starts {s0 s1} ends {e0 e1} by_end [dict create e0 {s0 s1} e1 s1]]
proc get_timing_paths {args} {
 incr ::queries
 set from [lindex $args [expr {[lsearch -exact $args -from]+1}]]
 set to [lindex $args [expr {[lsearch -exact $args -to]+1}]]
 foreach x [concat $from $to] {if {[string index $x 0] ne "@"} {error "Untyped timing boundary"}}
 if {[llength $from]>1} {
  if {$::mode eq "unexpected"} {return @bad}
  if {$::mode eq "duplicate"} {return {@a @a}}
  if {$::mode eq "single_launch"} {return {@a @c}}
  return {@a @c}
 }
 if {$::mode eq "missing"} {return {}}
 if {$::mode eq "wrongpair"} {return @c}
 foreach path [dict keys $::paths] {
  lassign [dict get $::paths $path] s e
  if {$from eq "@$s" && $to eq "@$e"} {return $path}
 }
 return {}
}
set requirement 8.0; set exception max_delay
set fullscope $scope
set scope [dict create starts {s0 s1} ends {e0 e1} by_end [dict create e0 s0 e1 s1]]
set mode single_launch; set queries 0
if {[valence_fifo_payload::check_paths $scope 8.0 {@s0 @s1} {@e0 @e1}]!=2 || $queries!=1} {error "Unique launches were not one batch"}
set scope $fullscope
foreach mode {normal duplicate} {
 set queries 0
 if {[valence_fifo_payload::check_paths $scope 8.0 {@s0 @s1} {@e0 @e1}]!=3} {error "Lost pair coverage"}
 set wanted [expr {$mode eq "normal" ? 2 : 3}]
 if {$queries!=$wanted} {error "Unexpected query count"}
}
foreach mode {missing wrongpair unexpected fallback_budget fallback_nan fallback_exception} {
 set queries 0
 if {![catch {valence_fifo_payload::check_paths $scope 8.0 {@s0 @s1} {@e0 @e1}}]} {error "Bad pair mode $mode admitted"}
}
set mode normal; set requirement 8.1
if {![catch {valence_fifo_payload::check_paths $scope 8.0 {@s0 @s1} {@e0 @e1}}]} {error "Relaxed budget admitted"}
set requirement NaN
if {![catch {valence_fifo_payload::check_paths $scope 8.0 {@s0 @s1} {@e0 @e1}}]} {error "NaN budget admitted"}
set requirement 8.0; set exception {}
if {![catch {valence_fifo_payload::check_paths $scope 8.0 {@s0 @s1} {@e0 @e1}}]} {error "Missing exception admitted"}
puts PASS_BATCH_EXACT_PAIRS
"""
        r=subprocess.run(['tclsh'],input=script,text=True,capture_output=True)
        self.assertEqual(r.stderr,'')
        self.assertIn('PASS_BATCH_EXACT_PAIRS',r.stdout)

    def test_bscan_rehydrates_assembled_banks(self):
        script='source {'+str(HERE/'bscan_timing.tcl')+'}\n'+r"""
# Query boundary mock records the exact freshly returned collection. A property
# on a bare assembled name without a fresh query fails, as in the observed gate.
set typed {}; set mutate none
proc get_cells {args} {
 set found [lindex $args end]
 if {$::mutate eq "missing"} {set found {}}
 if {$::mutate eq "extra"} {lappend found unexpected_cell}
 set ::typed $found
 return $found
}
proc get_pins {args} {set ::typed [lindex $args end]; return $::typed}
proc get_property {key objects} {
 if {$objects ne $::typed || $objects eq ""} {error "Property needs a fresh typed query"}
 switch $key {NAME {return $objects} REF_NAME {return FDCE} IS_INVERTED {return $::inversion}}
 error "Unexpected BSCAN property"
}
proc get_clocks {args} {
 if {[lindex $args end] ne $::typed} {error "Clock needs typed pin"}
 return valence_bscan_drck
}
rename valence_bscan_bank valence_bscan_original_bank
proc valence_bscan_bank {engine tail count args} {
 if {$tail eq "shift_frame"} {return [list "$engine/shift_frame_reg\[0\]" "$engine/shift_frame_reg\[1\]"]}
 return [list "$engine/${tail}_reg"]
}
set body [info body valence_bscan_phase_handoff]
set a [string first {    set shift_cells {}} $body]
set b [string first {    set hard_reset} $body]
if {$a<0 || $b<=$a} {error "Missing actual shift-bank block"}
proc check_shift {engine} [string range $body $a [expr {$b-1}]]
set inversion 0
check_shift engine
set inversion 1
if {![catch {check_shift engine}]} {error "Wrong shift edge admitted"}
set inversion 0
set names [list {engine/shift_frame_reg[0]} {engine/shift_frame_reg[1]}]
valence_bscan_objects get_cells $names
foreach mutate {missing extra} {
 if {![catch {valence_bscan_objects get_cells $names}]} {error "Changed BSCAN collection admitted"}
}
set mutate none
foreach bad [list {} [list a a] [list {engine/*}]] {
 if {![catch {valence_bscan_objects get_cells $bad}]} {error "Malformed BSCAN collection admitted"}
}
puts PASS_BSCAN_TYPED_BANK
"""
        r=subprocess.run(['tclsh'],input=script,text=True,capture_output=True)
        self.assertEqual(r.stderr,'')
        self.assertIn('PASS_BSCAN_TYPED_BANK',r.stdout)

    def test_ff_pin_polarity_with_empty_cell_properties(self):
        script='source {'+str(HERE/'audit_mac_netlist.tcl')+'}\n'+r"""
set p [dict create ff [dict create NAME ff REF_NAME FDCE INIT 1'b0 IS_SEQUENTIAL 1 ASYNC_REG 1 IS_C_INVERTED {} IS_CLR_INVERTED {}] ff/C [dict create NAME ff/C IS_INVERTED 0] ff/CLR [dict create NAME ff/CLR IS_INVERTED 0] ff/CE [dict create NAME ff/CE] ce [dict create TYPE POWER]]
proc get_cells {args} {return ff}
proc get_pins {args} {set name [lindex $args end]; if {[dict exists $::p $name]} {return $name}; return {}}
proc get_nets {args} {return ce}
proc get_property {key obj} {return [dict get $::p $obj $key]}
rename valence_mac::clock valence_mac::original_clock
proc valence_mac::clock {pin} {return raw}
rename valence_mac::same_net valence_mac::original_same_net
proc valence_mac::same_net {a b} {if {$a ne "ff/CLR" || $b ne "reset"} {error "Wrong reset arc"}}
rename valence_mac::drivers valence_mac::original_drivers
proc valence_mac::drivers {pin} {return reset_driver/Q}
set valence_mac::clocks [dict create raw raw]
valence_mac::ff ff raw 0 reset 1
foreach pin {ff/C ff/CLR} {
 foreach bad {{} 1 1'b1 unknown} {
  dict set p $pin IS_INVERTED $bad
  if {![catch {valence_mac::ff ff raw 0 reset 1}]} {error "Bad pin polarity admitted"}
 }
 dict set p $pin IS_INVERTED 0
 set saved [dict get $p $pin]; dict unset p $pin
 if {![catch {valence_mac::ff ff raw 0 reset 1}]} {error "Missing pin admitted"}
 dict set p $pin $saved
}
dict set p ff/C IS_INVERTED 1'b0
dict set p ff/CLR IS_INVERTED 1'b0
dict set p ff IS_SEQUENTIAL 1'b1
dict set p ff ASYNC_REG 1'b1
valence_mac::ff ff raw 0 reset 1
puts PASS_FF_PIN_POLARITY
"""
        r=subprocess.run(['tclsh'],input=script,text=True,capture_output=True)
        self.assertEqual(r.stderr,'')
        self.assertIn('PASS_FF_PIN_POLARITY',r.stdout)

    def test_rx_buffer_explicit_polarity(self):
        script='source {'+str(HERE.parent/'zu15eg/trispeed_board_constraints.tcl')+'}\n'+r"""
set body [info body valence_trispeed_clock_reset_audit]
set start [string first {    set rxBuffer} $body]
set stop [string first {    set roots} $body]
proc check_rx_buffer {} [string range $body $start [expr {$stop-1}]]
proc get_cells {args} {return @buffer}
proc get_pins {args} {return @[lindex $args end]}
proc get_nets {args} {return @ce_net}
proc get_property {key object} {
 switch $key {NAME {if {$object eq "@buffer"} {return rx_clock_buffer}; return [string range $object 1 end]} REF_NAME {return $::ref} TYPE {return $::ce} IS_INVERTED {return $::inverted}}
 error "Unexpected property"
}
set ref BUFGCE; set ce POWER; set inverted 0
check_rx_buffer
foreach value {{} 1 unknown} {
 set inverted $value
 if {![catch check_rx_buffer]} {error "Bad inversion admitted"}
}
set inverted 0; set ce GROUND
if {![catch check_rx_buffer]} {error "Gated clock admitted"}
set ce POWER; set ref LUT1
if {![catch check_rx_buffer]} {error "Wrong primitive admitted"}
set ref BUFG
check_rx_buffer
puts PASS_RX_BUFFER
"""
        r=subprocess.run(['tclsh'],input=script,text=True,capture_output=True)
        self.assertEqual(r.stderr,'')
        self.assertIn('PASS_RX_BUFFER',r.stdout)

    @patch.object(launcher, 'validate_export')
    def test_error_propagation(self, validated):
        with tempfile.TemporaryDirectory() as d:
            for code in (1,7,-9):
                with patch.object(launcher.subprocess,'run',return_value=subprocess.CompletedProcess([],code)):
                    self.assertEqual(launcher.launch('vivado','binding',Path(d)/'out',Path(d)/'export'),code if code>0 else 137)
            with patch.object(launcher.subprocess,'run',return_value=subprocess.CompletedProcess([],0)):
                self.assertEqual(launcher.launch('vivado','binding',Path(d)/'out',Path(d)/'export'),1)
    def test_original_constraints_before_gates(self):
        t=(HERE/'run_timing_ready73.tcl').read_text()
        self.assertLess(t.index('uplevel #0 $::READY73_ORIGINAL_CLOCKS'),t.index('source [file join $::READY73_EXPORT board require_trispeed.tcl]'))
        self.assertLess(t.index('source [file join $::READY73_EXPORT board require_trispeed.tcl]'),t.index('    ready73_gate synth'))
        self.assertEqual(t.count('board require_trispeed.tcl'),1)
        self.assertIn('exit 1',t)
    def test_checkpoint_api_matches_real_generator(self):
        generator=(HERE/'board_t1.py').read_text()
        self.assertIn('proc valence_native_mac_checkpoint {{stage path}}',generator)
        driver=(HERE/'run_timing_ready73.tcl').read_text()
        self.assertIn('valence_native_mac_checkpoint synth ',driver)
        self.assertIn('valence_native_mac_checkpoint postopt ',driver)
        self.assertNotIn('valence_native_mac_write_checkpoint',driver)
        bscan=(HERE/'bscan_timing.tcl').read_text()
        self.assertIn('proc valence_apply_bscan_timing {primitive engine fabric_clock profile}',bscan)
        self.assertIn('proc valence_reapply_bscan_cdc {primitive engine fabric_clock}',bscan)

    def test_filter_precedes_per_cell_query(self):
        t=(HERE/'native_mac_roles.tcl').read_text()
        region=t.split('foreach c [get_property NAME $cells] {',1)[1]
        self.assertLess(region.index('continue'),region.index('set ref [property'))
        self.assertNotIn('$hier/tx_clock',t)

if __name__=='__main__': unittest.main()
