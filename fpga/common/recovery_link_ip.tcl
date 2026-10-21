# Resume from a saved new core checkpoint; never repeat core or IP synthesis.
source [file normalize [lindex $argv 0]]
set extra [file normalize [lindex $argv 1]]
set out [file normalize [lindex $argv 2]]
cd $out
set_param general.maxThreads 8
foreach cmd {synth_design generate_target create_ip launch_runs upgrade_ip opt_design place_design phys_opt_design route_design write_bitstream} {
 if {[llength [info commands $cmd]]} {rename $cmd forbidden_$cmd;proc $cmd {args} {error {RECOVERY_LINK_ONLY}}}
}
if {[catch {
 open_checkpoint [file join $recovery(output) synthesized-core-with-ip-blackboxes.dcp]
 foreach row $recovery(ip_inputs) {
  lassign $row module dcp stub
  set cell [get_cells -quiet -hier -filter "IS_BLACKBOX == TRUE && REF_NAME == $module"]
  if {[llength $cell]!=1} {error "Expected exactly one $module blackbox"}
  puts "LINK_EXISTING $module [get_property NAME $cell]"
  read_checkpoint -cell [get_property NAME $cell] $dcp
 }
 set remaining [get_cells -quiet -hier -filter {IS_BLACKBOX == TRUE}]
 write_checkpoint linked-with-debug-blackbox.dcp
 puts "REMAINING_BLACKBOX name=[get_property NAME $remaining] ref=[get_property REF_NAME $remaining]"
 # Vivado's inserted debug hub has a customized reference name. Match the
 # single previously diagnosed exact instance; read_checkpoint checks ports.
 if {[llength $remaining]!=1 || [get_property NAME $remaining] ne {dbg_hub} || [get_property REF_NAME $remaining] ne {dbg_hub_CV}} {error "Expected exact diagnosed dbg_hub/dbg_hub_CV: [get_property NAME $remaining]"}
 puts "LINK_EXISTING dbg_hub [get_property NAME $remaining]"
 read_checkpoint -cell [get_property NAME $remaining] $extra
 set remaining [get_cells -quiet -hier -filter {IS_BLACKBOX == TRUE}]
 if {[llength $remaining]} {error "Remaining blackboxes: [get_property NAME $remaining]"}
 source [file join $recovery(repo) fpga common recovery_mig_io_contract.tcl]
 recovery_mig_io::apply
 write_checkpoint linked-unqualified.dcp
 report_clocks -file linked-clocks.rpt
 check_timing -verbose -file linked-coverage.rpt
 report_utilization -file linked-utilization.rpt
 foreach {pin expected} {u_soc/cpuClock 3.333 u_soc/fabricClock 4.0 u_soc/rawUartClock 20.0} {
  set clock [get_clocks -quiet -of_objects [get_pins -quiet $pin]]
  if {[llength $clock]!=1 || abs([get_property PERIOD $clock]-$expected)>0.002} {error "Actual clock contract differs at $pin"}
 }
 puts {LINK_PASS_FULL_BOARD_CONSTRAINTS_PENDING_NOT_PHYSICALLY_QUALIFIED}
 close_design
} reason options]} {
 set f [open failure.txt w];puts $f "$reason\n[dict get $options -errorinfo]";close $f
 puts "RECOVERY_LINK_BLOCKED $reason"
 catch {close_design}
 exit 2
}
exit 0
