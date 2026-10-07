# Qualify all reset causes in the UI domain; CPU reset consumes only UI stage 3.
# Args: INPUT_ROUTED_DCP OUTPUT_DIR
if {$argc != 2} {error "Expected INPUT_ROUTED_DCP OUTPUT_DIR"}
lassign $argv input out
file mkdir $out
set_param general.maxThreads 8
open_checkpoint $input
source [file join [file dirname [info script]] audit_reset_cdc.tcl]
audit_board_reset_cdc [file join $out reset_before.txt]
set frozen [dict create]
foreach cell [get_cells -hier -filter {IS_PRIMITIVE && LOC != "" && LOC !~ RPM_*}] {
    dict set frozen [get_property NAME $cell] [list [get_property LOC $cell] [get_property BEL $cell]]
}
set gate [get_cells {reset_pipe[2]_i_1}]
if {[llength $gate] != 1 || [get_property REF_NAME $gate] ne "LUT6"} {error "Unaudited old CPU reset gate"}
set expected [list {ui_reset_pipe_reg[2]/Q} u_clk_wiz/inst/mmcme4_adv_inst/LOCKED \
    u_ddr/inst/div_clk_rst_r1_reg/Q sys_rst_n_IBUF_inst/IBUFCTRL_INST/O \
    button_n_IBUF_inst/IBUFCTRL_INST/O u_ddr/inst/u_ddr4_mem_intfc/u_ddr_cal_top/calDone_gated_reg/Q]
for {set i 0} {$i < 6} {incr i} {
    set pin [get_pins [format {reset_pipe[2]_i_1/I%d} $i]]
    set drivers [get_pins -quiet -leaf -of_objects [get_nets -segments -of_objects $pin] -filter {DIRECTION == OUT}]
    if {[llength $drivers] != 1 || [get_property NAME $drivers] ne [lindex $expected $i]} {error "Old reset input mismatch: $i ($drivers)"}
}
set value [get_property INIT $gate]
if {![regexp {^64'h([0-9A-Fa-f]+)$} $value -> hex]} {error "Cannot parse old reset INIT"}
set old_init [expr "0x$hex"]
for {set i 0} {$i < 64} {incr i} {
    set expected_reset [expr {($i & 1) != 0 || ($i & 2) == 0 || ($i & 4) != 0 || ($i & 8) == 0 || ($i & 16) == 0 || ($i & 32) == 0}]
    if {(($old_init >> $i) & 1) != $expected_reset} {error "Old reset truth table differs at $i"}
}
set cpu_presets [get_pins {reset_pipe_reg[0]/PRE reset_pipe_reg[1]/PRE reset_pipe_reg[2]/PRE}]
set ui_presets [get_pins {ui_reset_pipe_reg[0]/PRE ui_reset_pipe_reg[1]/PRE ui_reset_pipe_reg[2]/PRE}]
set old_cpu_net [get_nets -of_objects [get_pins {reset_pipe_reg[0]/PRE}]]
set old_ui_net [get_nets -of_objects [get_pins {ui_reset_pipe_reg[0]/PRE}]]
foreach {net pins} [list $old_cpu_net $cpu_presets $old_ui_net $ui_presets] {
    set loads [get_pins -quiet -leaf -of_objects [get_nets -segments $net] -filter {DIRECTION == IN}]
    if {[lsort $loads] ne [lsort $pins]} {error "Reset entry net unexpectedly drives functional logic: $net ($loads)"}
}
set locked_net [get_nets -of_objects [get_pins u_clk_wiz/inst/mmcme4_adv_inst/LOCKED]]
set ui_stage_net [get_nets -of_objects [get_pins {ui_reset_pipe_reg[2]/Q}]]
if {[llength $locked_net] != 1 || [llength $ui_stage_net] != 1} {error "Missing existing reset sources"}
# The input DCP was placement-locked, which also sets netlist DONT_TOUCH.
# Temporarily clear ONLY the four audited reset/lock nets and six reset flops.
set mutable_nets [get_nets -segments [list $old_cpu_net $old_ui_net $locked_net $ui_stage_net]]
set mutable_cells [get_cells {reset_pipe_reg[0] reset_pipe_reg[1] reset_pipe_reg[2] ui_reset_pipe_reg[0] ui_reset_pipe_reg[1] ui_reset_pipe_reg[2]}]
set old_dont_touch [dict create]
foreach object [concat $mutable_nets $mutable_cells] {
    dict set old_dont_touch $object [get_property DONT_TOUCH $object]
    set_property DONT_TOUCH FALSE $object
}
create_cell -reference LUT2 ui_reset_qualified_gate
set_property INIT 4'hB [get_cells ui_reset_qualified_gate]
# Independently enumerate reset OR !locked; do not rely on a mnemonic INIT.
for {set i 0} {$i < 4} {incr i} {
    if {((0xB >> $i) & 1) != (($i & 1) != 0 || ($i & 2) == 0)} {error "Qualified-reset truth table fails"}
}
create_net ui_reset_qualified
connect_net -net $old_ui_net -objects [get_pins ui_reset_qualified_gate/I0]
connect_net -hier -net $locked_net -objects [get_pins ui_reset_qualified_gate/I1]
connect_net -net ui_reset_qualified -objects [get_pins ui_reset_qualified_gate/O]
# Rebuild both synchronizer shapes atomically after moving all six PRE pins.
set_property ASYNC_REG FALSE $mutable_cells
disconnect_net -net $old_ui_net -objects $ui_presets
connect_net -net ui_reset_qualified -objects $ui_presets
disconnect_net -net $old_cpu_net -objects $cpu_presets
connect_net -net $ui_stage_net -objects $cpu_presets
set_property ASYNC_REG TRUE $mutable_cells
update_timing
audit_cpu_reset_gate [file join $out reset_gate_audit.txt]
dict for {object value} $old_dont_touch {
    if {$value ne ""} {set_property DONT_TOUCH $value $object}
}
lock_design -level placement
place_design -directive Quick
route_design -preserve
dict for {name expected} $frozen {
    set cell [get_cells $name]
    if {[llength $cell] != 1 || [list [get_property LOC $cell] [get_property BEL $cell]] ne $expected} {
        error "Placement changed during reset qualification ECO: $name"
    }
}
audit_board_reset_cdc [file join $out reset_after.txt]
audit_cpu_reset_gate [file join $out reset_gate_audit.txt]
report_cdc -file [file join $out cdc.rpt]
report_cdc -details -file [file join $out cdc_details.rpt]
set stream [open [file join $out cdc_details.rpt] r]
set cdc [read $stream]
close $stream
if {[regexp -line {^CDC-[0-9]+[ ]+Critical} $cdc]} {error "Critical CDC remains; not releasable"}
write_checkpoint [file join $out routed.dcp]
report_timing_summary -delay_type min_max -report_unconstrained -file [file join $out timing_summary.rpt]
report_route_status -file [file join $out route_status.rpt]
report_bus_skew -file [file join $out bus_skew.rpt]
report_timing -group clk_out1_clk_wiz_ddr -delay_type max -max_paths 20 -file [file join $out cpu_timing_paths.rpt]
puts "RESET_GATE: old 64-case and new 4-case truth tables checked; all original placements preserved."
close_design
