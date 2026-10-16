set root [file normalize [lindex $argv 0]]
set rate [lindex $argv 1]
if {$rate ni {100 10}} {error {Explicit100/10 scenario required}}
set out [file join $root run-r28-scenario-${rate}]
cd $out
set V_SOC_ROOT u_soc
proc diag_event {stage status {detail {}}} {
 set stamp [clock format [clock seconds] -gmt 1 -format {%Y-%m-%dT%H:%M:%SZ}]
 set f [open events.tsv a];puts $f [join [list $stamp [pid] $stage $status $detail] \t];close $f
 puts "DIAG_EVENT $stamp PID=[pid] $stage $status $detail";flush stdout
}
proc dump_actual_clocks {name} {
 set f [open $name w]
 foreach c [lsort [get_clocks]] {
  set row [list clock [get_property NAME $c]]
  foreach p {PERIOD WAVEFORM MASTER_CLOCK SOURCE SOURCE_PINS IS_GENERATED IS_USER_GENERATED} {lappend row $p [get_property $p $c]}
  puts $f $row
 }
 close $f
}
source report-procedures.tcl
set_param general.maxThreads 4
diag_event recovery begin {EXACT_PLACED_DCP_NO_SYNTH_OPT_PLACE_ROUTE_BIT}
set code [catch {
 open_checkpoint [file join $root run-r7 placed.dcp]
 dump_actual_clocks actual-clocks-before.tcllist
 set waiverObjects [get_waivers -type ALL -quiet]
 set waiverNames {};if {[llength $waiverObjects]} {set waiverNames [lsort [get_property NAME $waiverObjects]]}
 diag_event scenario timing_reload_begin [list retainedWaivers [llength $waiverNames]]
 # Preserve the auto-clock name reservations; compare actual physical pins.
 reset_timing
 if {[llength $waiverNames]==0} {
  diag_event scenario full_waiver_recipe_fallback {No_observable_checkpoint_waivers_keep_all_original_commands}
  read_xdc [file join $root run-r24-scenario-${rate} scenario.xdc]
 } else {read_xdc scenario.xdc}
 dump_actual_clocks actual-clocks-after.tcllist
 set waiverObjects [get_waivers -type ALL -quiet]
 set afterWaivers {};if {[llength $waiverObjects]} {set afterWaivers [lsort [get_property NAME $waiverObjects]]}
 set waiverSame [expr {$waiverNames eq $afterWaivers}]
 diag_event scenario timing_reload_end [list waiverObjectsUnchanged $waiverSame]
 write_checkpoint scenario-loaded.dcp
 diag_event scenario checkpoint_saved
 # All observations precede validation. A mismatch is recorded, not a reason
 # to discard the live scene or prevent reports from being exported.
 set period [expr {$rate==100 ? 40.0 : 400.0}]
 set f [open physical-clock-contract.tcllist w];set mismatches 0
 foreach {pin expected} [list u_soc/clock 10.0 u_soc/io_alwaysOnClock 20.0 u_soc/board/nativeBank/uart/uart/clock 20.0 network_clock/enabled.pad_buffer/O 4.0 network_clock/enabled.raw_div/O 8.0 network_clock/enabled.delay_buffer/O 2.0 rx_clock_buffer/O $period rx_capture_clock_buffer/O $period] {
  set c [get_clocks -quiet -of_objects [get_pins -quiet $pin]]
  set actual {};set names {}
  if {[llength $c]} {set actual [get_property PERIOD $c];set names [get_property NAME $c]}
  set pass [expr {[llength $c]==1 && abs($actual-$expected)<0.001}]
  if {!$pass} {incr mismatches}
  puts $f [list PIN $pin EXPECTED $expected CLOCKS $names ACTUAL_PERIOD $actual PASS $pass]
 }
 foreach name {phy_rx_launch phy_tx_capture} {
  set c [get_clocks -quiet $name];set actual {}
  if {[llength $c]} {set actual [get_property PERIOD $c]}
  set pass [expr {[llength $c]==1 && abs($actual-$period)<0.001}]
  if {!$pass} {incr mismatches}
  puts $f [list EXPLICIT_MEDIA_CLOCK $name EXPECTED $period ACTUAL_PERIOD $actual PASS $pass]
 }
 close $f
 diag_event scenario physical_clock_observations [list mismatches $mismatches waiverObjectsUnchanged $waiverSame]
 diag_event reports begin
 diag_reports placed-${rate} 0
 diag_event reports complete [list physicalClockMismatches $mismatches waiverObjectsUnchanged $waiverSame]
} why options]
if {$code} {
 set f [open failure.txt w];puts $f $why;puts $f [dict get $options -errorinfo];close $f
 diag_event recovery failed_retained $why
} else {diag_event recovery complete_retained {REPORTS_SAVED_NO_ROUTE_NO_BIT}}
# Retain this already loaded scenario for small follow-up commands.
while {![file exists SESSION_EXIT.txt]} {
 foreach command [lsort [glob -nocomplain commands/*.tcl]] {
  if {[file exists ${command}.started]} {continue}
  set f [open ${command}.started w];puts $f [clock seconds];close $f
  diag_event command begin $command
  if {[catch {source $command} why options]} {
   set f [open ${command}.error.txt w];puts $f $why;puts $f [dict get $options -errorinfo];close $f
   diag_event command failed $why
  } else {diag_event command complete $command}
 }
 after 1000
}
exit 0
