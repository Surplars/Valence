# A small interface-only proof that clock renaming/phase assignment preserves
# dependent constraints and is idempotent. Sentinels are TEST ONLY, not budgets
# used in a real board implementation. No placement, CPU synthesis or bit.
if {$argc!=3} {error "Expected INTERFACE_DCP SOURCE_DIR FRESH_OUT"}
lassign $argv dcp src out
if {[file exists $out]} {error "Preserve prior proof"}
file mkdir $out
cd $out
file copy [info script] executed_reference_check.tcl
file copy [file join $src native_divided_clock_constraints.tcl] tested_clock_constraints.tcl
set_param general.maxThreads 8
open_checkpoint $dcp
create_clock -name ui_interface_proxy -period 4 [get_pins u_ddr/c0_ddr4_ui_clk]
set hier centered_tx_clock.clock_dut
set raw [get_clocks -of_objects [get_pins $hier/raw_div/O]]
set pad [get_clocks -of_objects [get_pins $hier/pad_div/O]]
set forward [get_clocks -of_objects [get_pins $hier/forward_div/O]]
foreach c [list $raw $pad $forward] {if {[llength $c]!=1} {error "Missing automatic divider clock"}}
set_clock_uncertainty -setup 0.037 -from $raw -to $forward
set_clock_uncertainty -hold 0.041 -from $pad -to $forward
set_max_delay 3.141 -from $raw -to $forward
source [file join $src native_divided_clock_constraints.tcl]
valence_divided_tx_clocks $hier
valence_divided_tx_clocks $hier
write_xdc -type timing sentinel_after.xdc
set f [open sentinel_after.xdc r]; set constraints [read $f]; close $f
foreach token {0.037 0.041 3.141} {
    if {![regexp "(?m)^set_(?:clock_uncertainty|max_delay).*${token}.*$" $constraints]} {error "Dependent sentinel disappeared: $token"}
}
foreach old [list $raw $pad $forward] {
    if {[regexp "(?m)^set_(?:clock_uncertainty|max_delay).*get_clocks ${old}\\]" $constraints]} {error "Stale reference to $old"}
}
report_clocks -file clocks.rpt
report_exceptions -file exceptions.rpt
puts "PASS_NATIVE_CLOCK_REFERENCE_RETENTION TEST_SENTINELS_ONLY NO_FULL_BOARD_QUALIFICATION"
close_design
