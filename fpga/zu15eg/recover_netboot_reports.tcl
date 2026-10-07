# Read-only report recovery from this candidate's own completed route.
# The implementation succeeded; the old post-route redirect command did not.
if {$argc != 1} {error "Expected PRIVATE_ROOT"}
set root [file normalize [lindex $argv 0]]
set out [file join $root implementation-report-recovery-r1]
if {[file exists [file join $out timing_summary.rpt]]} {error "Preserve prior recovered reports"}
set_param general.maxThreads 8
open_checkpoint [file join $out routed.dcp]
if {[get_property PART [current_design]] ne "xczu15eg-ffvb1156-2-i" ||
    [llength [get_cells -quiet -hier -filter {IS_BLACKBOX}]] ||
    [llength [get_cells -quiet -hier -filter {REF_NAME == FloatingPointSystem}]] != 1} {
    error "Expected resolved actual RV64GC whole-board route"
}
source [file join $root scripts native_quarter_clock_constraints.tcl]
foreach {pin period} {
    u_soc/clock 10.0 u_soc/io_alwaysOnClock 20.0 u_soc/nativeBank/uart/uart/clock 20.0
    u_soc/io_nativeGmac_rawTxClock 8.0 u_rgmii/delay_clock 2.0
    u_rgmii/tx_clock_ddr/CLK 4.0 u_ddr/c0_ddr4_ui_clk 4.0
} {
    set actualClock [get_clocks -of_objects [get_pins $pin]]
    if {[llength $actualClock] != 1 || abs([get_property PERIOD $actualClock] - $period) > 0.001} {error "Actual clock mismatch"}
}
set f [open [file join $root scripts route_network_eco_r2.tcl] r]
set definitions [read $f]; close $f
set start [string first {proc actual_ready_inputs} $definitions]
set end [string first "\nreview_real_delay_ready\n" $definitions $start]
if {$start < 0 || $end < $start} {error "Missing exact calibration cone verifier"}
eval [string range $definitions $start [expr {$end - 1}]]
review_real_delay_ready
set pads [valence_quarter_tx_audit u_rgmii]
set f [open [file join $out quarter_tx_identity.txt] w]
puts $f "PASS_NATIVE_QUARTER_TX_TOPOLOGY SIX_COMMON_CLK250_RESET FIVE_EXACT_D0_D4_PAIRS PHASE_FEEDBACK"
puts $f "ACTUAL_VALIDATED_DATA_PADS=$pads"
puts $f "PASS_REAL_THREE_CONTROLLER_CALIBRATION_READINESS"
close $f
set f [open [file join $root scripts replace_network_candidate.tcl] r]
set body [read $f]; close $f
set start [string first {report_timing_summary -delay_type min_max -report_unconstrained} $body]
if {$start < 0} {error "Missing frozen full report sequence"}
# Every original timing, coverage, bus-skew, route, DRC and physical I/O check
# below this point is retained; none of the implementation commands runs.
eval [string range $body $start end]
