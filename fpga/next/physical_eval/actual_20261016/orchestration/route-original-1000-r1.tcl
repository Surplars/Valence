# User explicitly authorized one normal timing-driven route, no bit generation.
set routeRoot $::root
set routeInput [file join $routeRoot run-r7 placed.dcp]
set out [file join $routeRoot run-route-r1]
if {[file exists $out]} {error {Preserve prior route evidence; refusing duplicate route}}
file mkdir $out
file mkdir [file join $out commands]
cd $out
set rate 1000
diag_event route_recovery begin {USER_AUTHORIZED_ORIGINAL_1000_PLACED_ECFBAB7A_NO_SYNTH_NO_PLACE_NO_RTL_OR_CONSTRAINT_EDITS_NO_BIT}
close_project
open_checkpoint $routeInput
if {[get_property PART [current_project]] ne {xczu15eg-ffvb1156-2-i} || [get_property REF_NAME [get_cells u_soc]] ne {FpgaNextSocTop}} {error {Route input live identity mismatch}}
set f [open input-clock-contract.tcllist w]
try {
 foreach {pin expected} {u_soc/clock 10 u_soc/io_alwaysOnClock 20 network_clock/enabled.pad_buffer/O 4 network_clock/enabled.raw_div/O 8 network_clock/enabled.delay_buffer/O 2 rx_clock_buffer/O 8 rx_capture_clock_buffer/O 8} {
  set c [get_clocks -of_objects [get_pins $pin]]
  set period [get_property PERIOD $c]
  puts $f [list PIN $pin CLOCK [get_property NAME $c] PERIOD $period EXPECTED $expected]
  if {[llength $c]!=1 || abs($period-$expected)>0.001} {error "Wrong actual1000Mbps route input clock: $pin"}
 }
 foreach name {phy_rx phy_rx_launch phy_tx_capture} {
  set c [get_clocks $name]
  puts $f [list CLOCK $name PERIOD [get_property PERIOD $c] WAVEFORM [get_property WAVEFORM $c] SOURCE_PINS [get_property SOURCE_PINS $c]]
  if {[llength $c]!=1 || abs([get_property PERIOD $c]-8.0)>0.001} {error "Wrong media scenario for route: $name"}
 }
} finally {close $f}
report_clocks -file clocks-before-route.rpt
puts [exec C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe -NoProfile -File [file join $routeRoot orchestration memory_before_route.ps1] $routeRoot [pid]]
source route-threads.tcl
diag_event route actual_begin [list command {route_design -directive Default} threads [get_param general.maxThreads] inputSha256 ecfbab7a1b97414e6a27772553f828b99f90a38855c13ca865a7e1cb642f4264]
set failed [catch {route_design -directive Default} why options]
if {$failed} {
 diag_event route actual_failed $why
 set f [open route-failure.txt w];puts $f $why;puts $f [dict get $options -errorinfo];close $f
 catch {write_checkpoint route-failure-preserved.dcp}
 catch {report_route_status -file route-failure-status.rpt}
 catch {report_timing_summary -delay_type min_max -report_unconstrained -file route-failure-timing.rpt}
 error {Route failed; live design and original placed DCP retained; no automatic reroute}
}
diag_event route actual_end
write_checkpoint routed.dcp
diag_event routed_checkpoint saved
diag_report [file join $out route-status] [list report_route_status -file [file join $out route-status.rpt]]
diag_reports routed-1000 0
set resetPins [get_pins -quiet -hier -filter {REF_PIN_NAME == CLR || REF_PIN_NAME == PRE || REF_PIN_NAME == RST}]
foreach {delay kind} {max recovery min removal} {
 diag_report [file join $out ${kind}-all-reset] [list report_timing -to $resetPins -delay_type $delay -max_paths 40 -nworst 3 -input_pins -path_type full_clock_expanded -file [file join $out ${kind}-all-reset.rpt]]
}
diag_event route_reports complete {NO_BIT_GENERATED_REVIEW_ROUTED_DCP_AND_REPORTS}
