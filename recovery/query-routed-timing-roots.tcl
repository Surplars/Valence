# One read-only pass over the completed candidate; no implementation or writes to DCP.
set target [file normalize [lindex $argv 0]]
set out [file normalize [lindex $argv 1]]
file mkdir $out
foreach cmd {synth_design opt_design place_design phys_opt_design route_design write_checkpoint write_bitstream generate_target upgrade_ip remove_cell disconnect_net connect_net} {
 if {[llength [info commands $cmd]]} {
  rename $cmd forbidden_$cmd
  proc $cmd {args} {error {ROUTED_TIMING_QUERY_ONLY}}
 }
}
if {[catch {
 open_checkpoint $target
 source [file join [file dirname [file dirname [file normalize [info script]]]] fpga common recovery_mig_io_contract.tcl]
 recovery_mig_io::verify_electrical
 dict for {port expected} $::recovery_mig_io::reference {
  set tail $port
  if {$port eq {clk_in1_p}} {set tail c0_sys_clk_p}
  if {$port eq {clk_in1_n}} {set tail c0_sys_clk_n}
  set pin [get_pins -quiet u_ddr/$tail]
  if {[llength $pin]!=1 || [recovery_mig_io::names [get_ports -quiet -of_objects [get_nets -quiet -segments -of_objects $pin]]] ne [list $port]} {
   error "Routed MIG direct connectivity differs: $port"
  }
 }
 puts {ROUTED_MIG_DIRECT_CONNECTIVITY_MATCH_73_PORTS}
 foreach {role pin period} {cpu u_soc/cpuClock 3.333 fabric u_soc/fabricClock 4.0} {
  set c [get_clocks -quiet -of_objects [get_pins -quiet $pin]]
  if {[llength $c]!=1 || abs([get_property PERIOD $c]-$period)>0.002} {error "Actual clock differs for $role"}
  # Bounded endpoint sampling, not a full hierarchy/pin census.
  set paths [get_timing_paths -quiet -from $c -to $c -delay_type max -max_paths 500 -nworst 1]
  report_timing -of_objects $paths -file [file join $out $role-worst500.rpt]
  puts "ROUTED_ROOT_SAMPLE role=$role clock=$c count=[llength $paths] period=$period"
 }
 set rows {}
 foreach {name source destination} {
  cpu_store_clear {u_soc/cpu/tile/core/addrPacket_address_reg[19]/C} {u_soc/crossing/fifo_4/writeBinary_reg[1]/D}
  dma_rx_issued {u_soc/crossing/fifo_2/valid_reg/C} {u_soc/fabric/packetDma/rxIssued_reg[6]/CE}
  imsic_threshold {u_soc/cpu/tile/imsic/pending_0_0_reg[38]/C} {u_soc/cpu/tile/imsic/threshold_0_reg[4]/CE}
  fabric_ready {u_soc/crossing/fifo_2/destinationRelease/release_0_reg[2]/C} {u_soc/crossing/fifo_4/capturedBinary_reg[3]/CE}
  dcache_result {u_soc/cpu/tile/dcache/coherent/cache/hitBank_reg[0]/C} {u_soc/cpu/tile/dt/result_data_reg[47]/D}
  icache_aligner {u_soc/cpu/tile/icache/coherent/cache/pending_address_reg[17]/C} {u_soc/cpu/tile/aligner/cuts/word_reg[2]/D}
 } {
  set start [get_pins -quiet $source]
  set end [get_pins -quiet $destination]
  set row [list name $name source $source destination $destination start_count [llength $start] end_count [llength $end]]
  if {[llength $start]==1 && [llength $end]==1} {
   set paths [get_timing_paths -quiet -from $start -to $end -delay_type max -max_paths 1]
   lappend row timed_paths [llength $paths]
   if {[llength $paths]} {
    lappend row slack [get_property SLACK $paths] requirement [get_property REQUIREMENT $paths] exception [get_property EXCEPTION $paths]
    report_timing -from $start -to $end -delay_type max -max_paths 1 -file [file join $out original-$name.rpt]
   }
   report_exceptions -from $start -to $end -file [file join $out original-$name-exceptions.rpt]
  }
  lappend rows $row
  puts "ORIGINAL_ROOT_CHECK $row"
 }
 set f [open [file join $out original-roots.tcllist] w]
 foreach row $rows {puts $f $row}
 close $f
 close_design
} reason options]} {
 puts "ROUTED_ROOT_QUERY_FAILED $reason"
 puts [dict get $options -errorinfo]
 exit 2
}
puts {ROUTED_ROOT_QUERY_COMPLETE_NO_DESIGN_CHANGES}
exit 0
