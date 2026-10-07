# Repair only newly imported UART hold paths; all other routes/placement are preserved.
# Args: INPUT_ROUTED_DCP OUTPUT_DIR
if {$argc != 2} {error "Expected INPUT_ROUTED_DCP OUTPUT_DIR"}
lassign $argv input out
file mkdir $out
set_param general.maxThreads 8
open_checkpoint $input
set frozen [dict create]
foreach cell [get_cells -hier -filter {IS_PRIMITIVE && LOC != "" && LOC !~ RPM_*}] {
    dict set frozen [get_property NAME $cell] [list [get_property LOC $cell] [get_property BEL $cell]]
}
report_timing -delay_type min -slack_lesser_than 0 -max_paths 200 -file [file join $out hold_before.rpt]
set bad [get_timing_paths -quiet -delay_type min -slack_lesser_than 0 -max_paths 200]
if {![llength $bad]} {error "No hold violation; repair not warranted"}
set repair_nets {}
foreach path $bad {
    set endpoint [get_property ENDPOINT_PIN $path]
    set net [get_nets -of_objects [get_pins $endpoint]]
    if {[llength $net] != 1 || ![string match u_soc/platform/uart/* [get_property NAME $net]]} {
        error "Hold failure is outside the UART partition: $endpoint"
    }
    foreach pin [get_pins -quiet -leaf -of_objects [get_nets -segments $net]] {
        set cell [get_cells -of_objects $pin]
        if {![string match u_soc/platform/uart/* [get_property NAME $cell]]} {
            error "Repair would alter a non-UART load/driver: $pin"
        }
    }
    lappend repair_nets $net
}
set repair_nets [lsort -unique $repair_nets]
puts "UART_HOLD: reroute [llength $repair_nets] audited UART-only nets"
lock_design -level placement
route_design -unroute -nets $repair_nets
route_design -preserve
dict for {name expected} $frozen {
    set cell [get_cells $name]
    if {[llength $cell] != 1 ||
        [list [get_property LOC $cell] [get_property BEL $cell]] ne $expected} {
        error "Placement changed during route-only hold repair: $name"
    }
}
write_checkpoint [file join $out routed.dcp]
report_timing_summary -delay_type min_max -report_unconstrained -file [file join $out timing_summary.rpt]
report_route_status -file [file join $out route_status.rpt]
report_bus_skew -file [file join $out bus_skew.rpt]
report_timing -group clk_out1_clk_wiz_ddr -delay_type max -max_paths 20 -file [file join $out cpu_timing_paths.rpt]
puts "UART_HOLD: REPAIR COMPLETE; RELEASE SIGNOFF STILL REQUIRED"
close_design
