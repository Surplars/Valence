# One explicitly authorized post-route optimization, preserving the original 1G DCP.
set optInput [file join $::root run-route-r1 routed.dcp]
set out [file join $::root run-postroute-physopt-r1]
if {[file exists $out]} {error {Refusing a second post-route optimization run}}
file mkdir $out
file mkdir [file join $out commands]
cd $out
set rate 1000
diag_event postroute_recovery begin {USER_AUTHORIZED_ONE_PASS_NO_RTL_XDC_EDITS_NO_SYNTH_PLACE_BIT}
if {[llength [get_projects -quiet]]} {close_project}
open_checkpoint $optInput
if {[get_property PART [current_project]] ne {xczu15eg-ffvb1156-2-i} || [get_property REF_NAME [get_cells u_soc]] ne {FpgaNextSocTop}} {error {Post-route input identity mismatch}}
set cpuClock [get_clocks -of_objects [get_pins u_soc/clock]]
if {[llength $cpuClock]!=1 || abs([get_property PERIOD $cpuClock]-10.0)>0.001} {error {Expected original100MHz CPU clock}}
foreach name {phy_rx phy_rx_launch phy_tx_capture} {
 if {[llength [get_clocks $name]]!=1 || abs([get_property PERIOD [get_clocks $name]]-8.0)>0.001} {error {Post-route optimization input is not original1000Mbps}}
}
report_clocks -file input-clocks.rpt
set_param general.maxThreads 4
puts [exec C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe -NoProfile -File [file join $::root orchestration memory_before_physopt.ps1] $out [pid]]
set optCommand [list phys_opt_design -placement_opt -routing_opt -critical_cell_opt -hold_fix -path_groups [list [get_property NAME $cpuClock]]]
diag_event postroute_physopt actual_begin [list command $optCommand threads 4 inputSha256 cd45610bbd17f16223260fd7fc678c329b28d1f5b77c872d810928d0c368015f]
if {[catch {uplevel #0 $optCommand} why options]} {
 diag_event postroute_physopt actual_failed $why
 set f [open physopt-failure.txt w];puts $f $why;puts $f [dict get $options -errorinfo];close $f
 catch {write_checkpoint physopt-failure-preserved.dcp}
 catch {report_timing_summary -delay_type min_max -report_unconstrained -file physopt-failure-timing.rpt}
 error {One-pass post-route optimization failed; state preserved; no automatic retry}
}
diag_event postroute_physopt actual_end
write_checkpoint post-physopt.dcp
diag_event postroute_checkpoint saved
report_route_status -file post-physopt-route-status.rpt
set f [open post-physopt-route-status.rpt r];set status [read $f];close $f
foreach {key label} {routable {routable nets} fully {fully routed nets} errors {nets with routing errors}} {
 if {![regexp [format {# of %s[. ]+:[[:space:]]+([0-9]+)} $label] $status -> value]} {error {Route status unparseable; optimized DCP retained; no blind reroute}}
 set routeCount($key) $value
}
if {$routeCount(routable)!=$routeCount(fully) || $routeCount(errors)!=0} {
 diag_event incremental_repair actual_begin {route_design -preserve -no_psir}
 if {[catch {route_design -preserve -no_psir} why options]} {
  diag_event incremental_repair actual_failed $why
  catch {write_checkpoint incremental-repair-failure-preserved.dcp}
  catch {report_timing_summary -delay_type min_max -report_unconstrained -file incremental-repair-failure-timing.rpt}
  error {Authorized single incremental repair failed; preserved; no loop}
 }
 diag_event incremental_repair actual_end
} else {diag_event incremental_repair not_needed {ALL_ROUTABLE_NETS_FULLY_ROUTED_ZERO_ROUTING_ERRORS}}
write_checkpoint postroute-final.dcp
diag_event postroute_final_checkpoint saved
diag_report [file join $out final-route-status] [list report_route_status -file final-route-status.rpt]
diag_reports postroute-1000 0
set resetPins [get_pins -quiet -hier -filter {REF_PIN_NAME == CLR || REF_PIN_NAME == PRE || REF_PIN_NAME == RST}]
foreach {delay kind} {max recovery min removal} {
 diag_report [file join $out $kind] [list report_timing -to $resetPins -delay_type $delay -max_paths 20 -nworst 1 -input_pins -path_type full_clock_expanded -file [file join $out ${kind}.rpt]]
}
diag_event postroute_reports complete {ONE_PHYSOPT_PASS_NO_BIT_COMPARE_WITH_ORIGINAL_BASELINE}
