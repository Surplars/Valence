# New core synthesis plus insertion of three unchanged, existing OOC IP DCPs.
source [file normalize [lindex $argv 0]]
cd $recovery(output)
set_param general.maxThreads 8
foreach cmd {generate_target create_ip create_ip_run launch_runs upgrade_ip opt_design place_design phys_opt_design route_design write_bitstream} {
 if {[llength [info commands $cmd]]} {rename $cmd forbidden_$cmd;proc $cmd {args} {error {RECOVERY_SYNTH_ONLY_REUSE_IP_NO_IMPLEMENTATION}}}
}
proc note {text} {puts $text;flush stdout;set f [open stages.txt a];puts $f "$text [clock format [clock seconds] -gmt true -format {%Y-%m-%dT%H:%M:%SZ}]";close $f}
if {[catch {
 create_project recovery_board [file join $recovery(output) project] -part xczu15eg-ffvb1156-2-i
 set_property XPM_LIBRARIES {XPM_MEMORY} [current_project]
 foreach source $recovery(rtl) {read_verilog -sv $source}
 foreach row $recovery(ip_inputs) {
  lassign $row module dcp stub
  if {![file isfile $dcp] || ![file isfile $stub]} {error "Missing existing IP product $module"}
  read_verilog $stub
  note "REUSE_IP_BLACKBOX_INTERFACE $module"
 }
 foreach xdc $recovery(xdc) {read_xdc $xdc}
 note {START synth_design RECOVERY_R1_NOT_R2 CPU300 FABRIC250}
 synth_design -top soc_top_common_ddr -part xczu15eg-ffvb1156-2-i -flatten_hierarchy none
 note {FINISHED synth_design CORE_IP_BLACKBOXES_PENDING}
 write_checkpoint synthesized-core-with-ip-blackboxes.dcp
 foreach row $recovery(ip_inputs) {
  lassign $row module dcp stub
  set cell [get_cells -quiet -hier -filter "IS_BLACKBOX == TRUE && REF_NAME == $module"]
  if {[llength $cell]!=1} {error "Expected one IP blackbox for $module; found [llength $cell]"}
  set name [get_property NAME $cell]
  note "READ_EXISTING_IP_DCP $module cell=$name"
  read_checkpoint -cell $name $dcp
 }
 set remaining [get_cells -quiet -hier -filter {IS_BLACKBOX == TRUE}]
 if {[llength $remaining]} {error "Additional IP products required; remaining blackboxes: [get_property NAME $remaining]"}
 write_checkpoint synthesized-unqualified.dcp
 report_utilization -file synthesis-utilization.rpt
 report_clocks -file synthesis-clocks.rpt
 check_timing -verbose -file synthesis-coverage.rpt
 foreach {pin expected} {u_soc/cpuClock 3.333 u_soc/fabricClock 4.0 u_soc/rawUartClock 20.0} {
  set clock [get_clocks -quiet -of_objects [get_pins -quiet $pin]]
  if {[llength $clock]!=1 || abs([get_property PERIOD $clock]-$expected)>0.002} {error "Actual clock contract differs at $pin"}
 }
 note {SYNTHESIZED_RECOVERY_R1_FULL_CONSTRAINT_MAPPING_PENDING_NO_PLACE_NO_ROUTE_NO_BIT}
 set f [open STATUS.txt w];puts $f {SYNTHESIZED_RECOVERY_R1_FULL_CONSTRAINT_MAPPING_PENDING_NO_PLACE_NO_ROUTE_NO_BIT};close $f
 close_project
} reason options]} {
 set f [open failure.txt w];puts $f "$reason\n[dict get $options -errorinfo]";close $f
 puts "RECOVERY_SYNTHESIS_BLOCKED $reason"
 catch {close_project}
 exit 2
}
exit 0
