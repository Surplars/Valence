proc dump_actual_clocks {name} {set f [open $name w];foreach c [lsort [get_clocks]] {puts $f [list CLOCK $c PERIOD [get_property PERIOD $c] WAVEFORM [get_property WAVEFORM $c] SOURCE_PINS [get_property SOURCE_PINS $c]]};close $f}
# Read-only STA on the same routed implementation. Never run implementation commands.
set routeBase [file join $::root run-postroute-physopt-r1]
try {
 foreach rate {100 10} {
  set out [file join $::root run-final-sta-${rate}-r1]
  cd $out
  diag_event routed_scenario actual_begin [list rateMbps $rate inputSha256 23a4edd50f0c4852f89ffb549f5ba9d2c51dc2019f546479b1dbe538ce102743]
  close_project
  open_checkpoint [file join $routeBase postroute-final.dcp]
  diag_event routed_scenario checkpoint_opened
  reset_timing
  diag_event routed_scenario timing_read_begin
  read_xdc scenario.xdc
  diag_event routed_scenario timing_read_end
  dump_actual_clocks actual-clocks.tcllist
  set period [expr {$rate==100 ? 40.0 : 400.0}]
  set f [open physical-clock-contract.tcllist w];set mismatches 0
  foreach {pin expected} [list u_soc/clock 10.0 u_soc/io_alwaysOnClock 20.0 network_clock/enabled.pad_buffer/O 4.0 network_clock/enabled.raw_div/O 8.0 network_clock/enabled.delay_buffer/O 2.0 rx_clock_buffer/O $period rx_capture_clock_buffer/O $period] {
   set c [get_clocks -quiet -of_objects [get_pins -quiet $pin]]
   set actual {};if {[llength $c]} {set actual [get_property PERIOD $c]}
   set pass [expr {[llength $c]==1 && abs($actual-$expected)<0.001}]
   if {!$pass} {incr mismatches}
   puts $f [list PIN $pin EXPECTED $expected ACTUAL_PERIOD $actual CLOCKS $c PASS $pass]
  }
  foreach name {phy_rx_launch phy_tx_capture} {
   set c [get_clocks -quiet $name];set actual {}
   if {[llength $c]} {set actual [get_property PERIOD $c]}
   set pass [expr {[llength $c]==1 && abs($actual-$period)<0.001}]
   if {!$pass} {incr mismatches}
   puts $f [list CLOCK $name EXPECTED $period ACTUAL_PERIOD $actual PASS $pass]
  }
  close $f
  write_checkpoint scenario-postroute-final.dcp
  diag_event routed_scenario checkpoint_saved [list physicalClockMismatches $mismatches]
  if {$mismatches} {error {Scenario checkpoint retained; physical clock mismatch}}
  diag_event routed_scenario reports_begin
  foreach {name command} [list timing_summary [list report_timing_summary -delay_type min_max -report_unconstrained] clocks [list report_clocks] check_timing [list check_timing -verbose] bus_skew [list report_bus_skew]] {
   if {[diag_report [file join $out $name] [concat $command [list -file [file join $out ${name}.rpt]]]]} {error "Scenario report failed: $name"}
  }
  set cpu [get_clocks -of_objects [get_pins u_soc/clock]]
  foreach {delay mode} {max setup min hold} {
   set opts [list -delay_type $delay -max_paths 10 -nworst 1 -input_pins -path_type full_clock_expanded]
   foreach {name scope} [list global {} cpu [list -from $cpu -to $cpu] rx [list -from [get_ports {eth_rxd[*] eth_rx_ctl}]] tx [list -to [get_ports {eth_txd[*] eth_tx_ctl}]]] {
    if {[diag_report [file join $out ${name}_${mode}] [concat [list report_timing] $scope $opts [list -file [file join $out ${name}_${mode}.rpt]]]]} {error "Scenario timing report failed: $name $mode"}
   }
  }
  set resetPins [get_pins -quiet -hier -filter {REF_PIN_NAME == CLR || REF_PIN_NAME == PRE || REF_PIN_NAME == RST}]
  foreach {delay kind} {max recovery min removal} {
   if {[diag_report [file join $out $kind] [list report_timing -to $resetPins -delay_type $delay -max_paths 10 -nworst 1 -input_pins -path_type full_clock_expanded -file [file join $out ${kind}.rpt]]]} {error "Scenario reset report failed: $kind"}
  }
  diag_event routed_scenario complete [list physicalClockMismatches $mismatches NO_IMPLEMENTATION_COMMANDS 1 NO_BIT 1]
 }
} finally {
 set out $routeBase
 cd $out
}
