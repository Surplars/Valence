# Read-only audit of the two active one-bit payload bus-skew NA entries.
set target [file normalize [lindex $argv 0]]
set out [file normalize [lindex $argv 1]]
file mkdir $out
foreach cmd {synth_design opt_design place_design phys_opt_design route_design write_checkpoint write_bitstream generate_target upgrade_ip set_max_delay set_false_path set_multicycle_path set_bus_skew} {
 if {[llength [info commands $cmd]]} {
  rename $cmd forbidden_$cmd
  proc $cmd {args} {error {SINGLE_BIT_SKEW_READ_ONLY}}
 }
}
if {[catch {
 open_checkpoint $target
 set f [open [file join $out exact-paths.tcllist] w]
 foreach lane {crossing_1 crossing_2} {
  set scope u_soc/crossing/$lane/empty_fifo_4
  set start [get_pins -quiet $scope/storage_ext/Memory_reg_0_15_0_0/DP/CLK]
  set end [get_pins -quiet $scope/output_0_reg/D]
  if {[llength $start]!=1 || [llength $end]!=1} {error "Missing exact single-bit endpoints $scope"}
  set bits [get_pins -of_objects [get_cells -quiet $scope] -filter {REF_PIN_NAME =~ destination_bits*}]
  if {[llength $bits]!=1} {error "Payload is not exactly one bit $scope"}
  set source_clock [get_clocks -of_objects $start]
  set capture_clock [get_clocks -of_objects [get_pins -quiet $scope/output_0_reg/C]]
  set paths [get_timing_paths -quiet -from $start -to $end -delay_type max -max_paths 8 -nworst 8]
  if {![llength $paths]} {error "No actual routed payload timing path $scope"}
  set measurements {}
  foreach path $paths {
   set req [get_property REQUIREMENT $path]
   set slack [get_property SLACK $path]
   set exception [get_property EXCEPTION $path]
   set normalized [string tolower [string map {_ {} - {} { } {}} $exception]]
   if {$req<=0 || $req>3.334 || $slack<0 || ![string match maxdelay* $normalized]} {
    error "Missing or failing actual payload budget $scope requirement=$req slack=$slack exception=$exception"
   }
   lappend measurements [list requirement $req slack $slack exception $exception]
  }
  set row [list scope $scope payload_bits [llength $bits] source [get_property NAME $start] destination [get_property NAME $end] source_primitive [get_property REF_NAME [get_cells -of_objects $start]] source_clocks [get_property NAME $source_clock] capture_clocks [get_property NAME $capture_clock] timing_paths [llength $paths] measurements $measurements]
  puts $f $row
  puts "SINGLE_BIT_PAYLOAD_MAX_DELAY_VERIFIED $row"
  report_timing -from $start -to $end -delay_type max -max_paths 8 -nworst 8 -file [file join $out $lane-max-delay.rpt]
 }
 close $f
 close_design
 puts {SINGLE_BIT_PAYLOAD_AUDIT_COMPLETE_NO_DESIGN_CHANGES}
} reason options]} {
 puts "SINGLE_BIT_PAYLOAD_AUDIT_FAILED $reason"
 puts [dict get $options -errorinfo]
 catch {close $f}
 catch {close_design}
 exit 2
}
exit 0
