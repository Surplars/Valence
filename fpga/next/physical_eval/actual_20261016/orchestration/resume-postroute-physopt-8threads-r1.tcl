set out [file join $::root run-postroute-physopt-r1]
cd $out
set rate 1000
set cpuClock [get_clocks -of_objects [get_pins u_soc/clock]]
if {[llength $cpuClock]!=1 || abs([get_property PERIOD $cpuClock]-10.0)>0.001 || abs([get_property PERIOD [get_clocks phy_rx]]-8.0)>0.001} {error {Original1000Mbps live checkpoint clock mismatch}}
set_param general.maxThreads 8
diag_event user_acceleration applied {EXPLICIT8THREADS_NO_ARTIFICIAL_MEMORY_GATE_OS_PROTECTION_UNCHANGED}
set optCommand [list phys_opt_design -placement_opt -routing_opt -critical_cell_opt -hold_fix -path_groups [list [get_property NAME $cpuClock]]]
diag_event postroute_physopt actual_begin [list command $optCommand threads 8 inputSha256 cd45610bbd17f16223260fd7fc678c329b28d1f5b77c872d810928d0c368015f]
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
