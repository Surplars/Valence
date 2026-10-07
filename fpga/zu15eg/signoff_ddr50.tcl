if {$argc != 2} {error "Expected ROUTED_DCP REPORT_DIR"}
lassign $argv dcp report_dir
set report_dir [file normalize $report_dir]
set_param general.maxThreads 8
open_checkpoint $dcp
report_bus_skew -file [file join $report_dir bus_skew.rpt]
check_timing -verbose -file [file join $report_dir check_timing.rpt]
set out [open [file join $report_dir region_tieoff_audit.txt] w]
set pins [get_pins -quiet {u_axi_cdc/s_axi_awregion* u_axi_cdc/s_axi_arregion*}]
if {[llength $pins] != 8} {error "Expected exactly 8 REGION input pins"}
foreach pin $pins {
    set net [get_nets -of_objects $pin]
    puts $out "$pin: $net ([get_property TYPE $net])"
    if {[get_property TYPE $net] ne "GROUND"} {error "REGION is not grounded: $pin"}
}
close $out
close_design
