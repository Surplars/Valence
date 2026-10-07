# TEST-ONLY sentinel budgets. Never consumed as production timing constraints.
if {$argc!=3} {error "Expected INTERFACE_DCP SOURCE_DIR FRESH_OUT"}
lassign $argv dcp src out
if {[file exists $out]} {error "Preserve previous proof"}
file mkdir $out
cd $out
file copy [info script] executed_reference_check.tcl
file copy [file join $src native_quarter_clock_constraints.tcl] tested_clock_constraints.tcl
set_param general.maxThreads 8
open_checkpoint $dcp
set proxy [get_clocks -quiet quarter_structure_proxy]
if {[llength $proxy]!=1} {error "Require known interface-only clock proxy"}
# This DCP contains only the test's primary quarter proxy, no production
# constraints. Vivado has no remove_clocks command. Clear this isolated
# timing view before defining the real interface source, then ADD sentinels.
if {[llength [get_clocks]]!=1} {error "Do not clear any non-proxy constraint set"}
reset_timing
create_clock -name ui_interface_proxy -period 4 [get_pins u_ddr/c0_ddr4_ui_clk]
set hier centered_tx_clock.clock_dut
set raw [get_clocks -of_objects [get_pins $hier/raw_div/O]]
set pad [get_clocks -of_objects [get_pins $hier/quarter_div/O]]
foreach c [list $raw $pad] {if {[llength $c]!=1} {error "Missing actual automatic divider clock"}}
set_clock_uncertainty -setup 0.037 -from $raw -to $pad
set_clock_uncertainty -hold 0.041 -from $pad -to $raw
set_max_delay 3.141 -from $raw -to $pad
source [file join $src native_quarter_clock_constraints.tcl]
valence_quarter_tx_clocks $hier
valence_quarter_tx_clocks $hier
valence_quarter_tx_audit u_rgmii
write_xdc -type timing sentinel_after.xdc
set f [open sentinel_after.xdc r]; set constraints [read $f]; close $f
foreach token {0.037 0.041 3.141} {
    if {![regexp "(?m)^set_(?:clock_uncertainty|max_delay).*${token}.*$" $constraints]} {error "Dependent sentinel disappeared: $token"}
}
foreach old [list $raw $pad] {
    if {[regexp "(?m)^set_(?:clock_uncertainty|max_delay).*get_clocks ${old}\\]" $constraints]} {error "Stale reference to $old"}
}
report_clocks -file clocks.rpt
report_exceptions -file exceptions.rpt
puts "PASS_NATIVE_QUARTER_CLOCK_REFERENCE_RETENTION TEST_SENTINELS_ONLY NO_FULL_BOARD_QUALIFICATION"
close_design
