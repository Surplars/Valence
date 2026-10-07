# Polish only this candidate's own complete routed netlist. Preserve the
# first route; never import donor logic or change timing budgets/exceptions.
if {$argc != 1} {error "Expected PRIVATE_CANDIDATE_ROOT"}
set root [file normalize [lindex $argv 0]]
set out [file join $root physical-opt-r1]
if {[file exists $out]} {error "Preserve previous physical optimization"}
file mkdir $out
set_param general.maxThreads 8
open_checkpoint [file join $root implementation routed.dcp]
if {[get_property PART [current_design]] ne "xczu15eg-ffvb1156-2-i" ||
    [llength [get_cells -quiet -hier -filter {IS_BLACKBOX}]] ||
    [llength [get_cells -quiet -hier -filter {REF_NAME == FloatingPointSystem}]] != 1} {
    error "Expected own complete RV64GC route"
}
source [file join $root scripts native_board_constraints.tcl]
set isa rv64gc
cd $out
report_timing -delay_type max -max_paths 10 -input_pins -file before_setup.rpt
set before [get_timing_paths -delay_type max -max_paths 1]
puts "POLISH_BEFORE WNS=[get_property SLACK $before] SOURCE=[get_property STARTPOINT_PIN $before] TARGET=[get_property ENDPOINT_PIN $before]"
phys_opt_design -directive AggressiveExplore
set f [open [file join $root scripts build_native_board.tcl] r]
set body [read $f]; close $f
set needle "\nset quarter \[get_cells -quiet centered_tx_clock.clock_dut/quarter_div\]\n"
set first [string first $needle $body]
if {$first < 0 || [string first $needle $body [expr {$first+1}]] >= 0} {error "Ambiguous frozen final report sequence"}
eval [string range $body [expr {$first+1}] end]
