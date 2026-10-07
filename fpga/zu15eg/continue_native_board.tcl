# Continue this candidate's own complete, clean pre-placement checkpoint.
# Fallback after a donor incremental-read cache failure; no synthesis repeats,
# donor netlist import, clock changes, timing relaxation or waived tool errors.
if {$argc != 1} {error "Expected PRIVATE_CANDIDATE_ROOT"}
set root [file normalize [lindex $argv 0]]
set out [file join $root implementation]
set isa rv64gc
if {![file isfile [file join $out optimized.dcp]] || [file exists [file join $out placed.dcp]] ||
    [file exists [file join $out routed.dcp]]} {error "Expected own optimized checkpoint and fresh place/route"}
set_param general.maxThreads 8
cd $out
open_checkpoint optimized.dcp
if {[get_property PART [current_design]] ne "xczu15eg-ffvb1156-2-i" ||
    [llength [get_cells -quiet -hier -filter {IS_BLACKBOX}]] ||
    [llength [get_cells -quiet -hier -filter {REF_NAME == FloatingPointSystem}]] != 1} {
    error "Expected own resolved full RV64GC SoC"
}
source [file join $root scripts native_board_constraints.tcl]
foreach {pin period} {u_soc/clock 10.0 u_soc/io_alwaysOnClock 20.0
    u_soc/nativeBank/uart/uart/clock 20.0 u_soc/io_nativeGmac_rawTxClock 8.0
    u_rgmii/delay_clock 2.0 u_rgmii/tx_clock_ddr/CLK 4.0 u_ddr/c0_ddr4_ui_clk 4.0} {
    set clock [get_clocks -quiet -of_objects [get_pins $pin]]
    if {[llength $clock] != 1 || abs([get_property PERIOD $clock]-$period)>0.001} {error "Actual clock mismatch: $pin"}
}
set f [open [file join $root scripts build_native_board.tcl] r]
set body [read $f]; close $f
set needle "\nplace_design -directive Explore\n"
set first [string first $needle $body]
if {$first < 0 || [string first $needle $body [expr {$first+1}]] >= 0} {error "Ambiguous frozen place/report sequence"}
puts "CONTINUE_OWN_DDR2G_OPTIMIZED_CHECKPOINT NO_DONOR_LOGIC_NO_INCREMENTAL_CACHE_NO_TIMING_RELAXATION"
eval [string range $body [expr {$first+1}] end]
