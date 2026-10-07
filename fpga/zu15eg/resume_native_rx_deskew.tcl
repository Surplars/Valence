# Continue the already-created peripheral ECO; never recreate/synthesize CPU.
if {$argc != 2} {error "Expected MODIFIED_DCP FRESH_OUTPUT_DIR"}
lassign $argv dcp out
if {[file exists $out]} {error "Preserve existing evidence"}
file mkdir $out
cd $out
file copy [info script] executed_resume.tcl
set_param general.maxThreads 8
open_checkpoint $dcp
set frozen [dict create]
foreach cell [get_cells -hier -filter {IS_PRIMITIVE && LOC != "" && LOC !~ RPM_*}] {
    if {$cell ne "native_rx_feedback_buffer"} {
        dict set frozen $cell [list [get_property LOC $cell] [get_property BEL $cell]]
    }
}
set region [get_clock_regions -of_objects [get_sites -of_objects [get_package_pins AA7]]]
set occupiedSlots {}
foreach cell [get_cells -hier -filter {REF_NAME == BUFGCE && LOC != ""}] {
    if {$cell eq "native_rx_feedback_buffer"} {continue}
    set loc [get_property LOC $cell]
    puts "EXISTING_BUFG $cell $loc"
    if {[regexp {BUFGCE_X0Y([0-9]+)} $loc -> n]} {lappend occupiedSlots [expr {$n%24}]}
}
set candidates {}
foreach site [lsort -dictionary [get_sites -of_objects $region -filter {SITE_TYPE == BUFGCE}]] {
    if {[llength [get_cells -quiet -of_objects $site]]!=0} {continue}
    if {[regexp {BUFGCE_X0Y([0-9]+)} $site -> n] && [expr {$n%24}] ni $occupiedSlots} {
        lappend candidates $site
    }
}
# Prefer unused track slots, but actual update_clock_routing is the authority;
# slot-number exclusion is only a placement search heuristic, never signoff.
if {[llength $candidates]==0} {error "No free RX feedback candidate"}
set success 0
foreach site $candidates {
    puts "RX_FEEDBACK_SITE_TRY $site"
    set_property IS_LOC_FIXED FALSE [get_cells native_rx_feedback_buffer]
    place_cell [list native_rx_feedback_buffer $site]
    if {![catch {update_clock_routing} detail]} {set success 1; break}
    puts "RX_FEEDBACK_SITE_REJECTED $site $detail"
}
if {!$success} {error "No legal local RX feedback route; preserve CPU"}
write_checkpoint clocks_updated.dcp
route_design -preserve
dict for {name expected} $frozen {
    if {[list [get_property LOC [get_cells $name]] [get_property BEL [get_cells $name]]] ne $expected} {error "Original placement changed: $name"}
}
puts "ORIGINAL_PLACEMENTS_PRESERVED [dict size $frozen]"
set rxClock [get_clocks -of_objects [get_pins {u_rgmii/receive[0].rx_ddr/C}]]
if {[llength $rxClock]!=1 || abs([get_property PERIOD $rxClock]-8.0)>0.001} {error "RX sampling clock missing"}
puts "VALID_RX_SAMPLING_CLOCK $rxClock [get_property PERIOD $rxClock]"
write_checkpoint routed.dcp
report_timing_summary -delay_type min_max -report_unconstrained -file timing_summary.rpt
report_timing_summary -delay_type min_max -datasheet -input_pins -file timing_datasheet.rpt
report_timing -from [get_ports {eth_rxd[*] eth_rx_ctl}] -delay_type min_max -max_paths 10 -input_pins -file rx_io.rpt
report_timing -to [get_ports {eth_txd[*] eth_tx_ctl}] -delay_type min_max -max_paths 10 -input_pins -file tx_io.rpt
report_timing -delay_type min -slack_lesser_than 0 -max_paths 30 -input_pins -file failing_hold.rpt
report_bus_skew -warn_on_violation -file bus_skew.rpt
report_cdc -details -file cdc.rpt
report_route_status -file route_status.rpt
report_clocks -file clocks.rpt
check_timing -verbose -file check_timing.rpt
report_drc -file drc.rpt
puts "NATIVE_RX_DESKEW_RESUME_COMPLETE NO_BIT_GENERATED"
close_design
