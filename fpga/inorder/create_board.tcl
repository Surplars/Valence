set_param general.maxThreads 8
set root [file normalize [lindex $argv 0]]
create_project i1_board [file join $root hardware] -part xczu15eg-ffvb1156-2-i
set_property source_mgmt_mode All [current_project]
add_files -norecurse [glob -directory [file join $root rtl] *.sv]
add_files -norecurse [file join $root I1PsPlBoundary.v]
update_compile_order -fileset sources_1
create_bd_design i1_board
set ps [create_bd_cell -type ip -vlnv xilinx.com:ip:zynq_ultra_ps_e:3.5 ps]
source [file join $root board_ps_preset.tcl]
i1_board_ps_preset $ps
source [file join $root board_ps_interfaces.tcl]
set inputHz [get_property CONFIG.FREQ_HZ [get_bd_pins ps/pl_clk0]]
set cw [create_bd_cell -type ip -vlnv xilinx.com:ip:clk_wiz:6.0 clocks]
# Raw CPU/VPU MMCM outputs feed the existing managed BUFGCEs directly.
# The system output alone has an always-on global buffer in the clock wizard.
set_property -dict [list CONFIG.PRIM_IN_FREQ [expr {$inputHz / 1000000.0}] \
    CONFIG.PRIM_SOURCE {No_buffer} CONFIG.NUM_OUT_CLKS {3} \
    CONFIG.CLKOUT1_REQUESTED_OUT_FREQ {300.0} CONFIG.CLKOUT1_DRIVES {No_buffer} \
    CONFIG.CLKOUT2_USED {true} CONFIG.CLKOUT2_REQUESTED_OUT_FREQ {300.0} CONFIG.CLKOUT2_DRIVES {No_buffer} \
    CONFIG.CLKOUT3_USED {true} CONFIG.CLKOUT3_REQUESTED_OUT_FREQ {300.0} CONFIG.CLKOUT3_DRIVES {BUFG} \
    CONFIG.USE_RESET {true} CONFIG.RESET_TYPE {ACTIVE_LOW} CONFIG.USE_LOCKED {true}] $cw
connect_bd_net [get_bd_pins ps/pl_clk0] [get_bd_pins clocks/clk_in1]
connect_bd_net [get_bd_pins ps/pl_resetn0] [get_bd_pins clocks/resetn]
set reset [create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset:5.0 coldReset]
set_property -dict [list CONFIG.C_EXT_RESET_HIGH {0} CONFIG.C_AUX_RESET_HIGH {0}] $reset
connect_bd_net [get_bd_pins clocks/clk_out3] [get_bd_pins coldReset/slowest_sync_clk]
connect_bd_net [get_bd_pins clocks/locked] [get_bd_pins coldReset/dcm_locked]
connect_bd_net [get_bd_pins ps/pl_resetn0] [get_bd_pins coldReset/ext_reset_in]
set zero [create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant:1.1 zero]
set_property CONFIG.CONST_VAL {0} $zero
# Unused active-low auxiliary reset is held HIGH; debug reset is active high.
set one [create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant:1.1 one]
set_property CONFIG.CONST_VAL {1} $one
connect_bd_net [get_bd_pins one/dout] [get_bd_pins coldReset/aux_reset_in]
connect_bd_net [get_bd_pins zero/dout] [get_bd_pins coldReset/mb_debug_sys_rst]
set pl [i1_attach_ps_pl ps valence [get_bd_pins clocks/clk_out1] [get_bd_pins clocks/clk_out2] \
    [get_bd_pins clocks/clk_out3] [get_bd_pins coldReset/peripheral_reset]]
connect_bd_net [get_bd_pins zero/dout] [get_bd_pins valence/externalIrq] [get_bd_pins valence/wakeCpu] [get_bd_pins valence/wakeVpu]
set rx [create_bd_port -dir I uartRx]
set tx [create_bd_port -dir O uartTx]
connect_bd_net $rx [get_bd_pins valence/uartRx]
connect_bd_net $tx [get_bd_pins valence/uartTx]
assign_bd_address
validate_bd_design
if {[get_property CONFIG.C_AUX_RESET_HIGH $reset] != 0} {error "Auxiliary reset must be active low with its constant-high inactive input"}
save_bd_design
set bd [get_files i1_board.bd]
generate_target all $bd
set wrapper [make_wrapper -files $bd -top]
add_files -norecurse $wrapper
set_property top i1_board_wrapper [current_fileset]
update_compile_order -fileset sources_1
# No off-chip DDR pins, MIG, external PL clock or standalone PL hot reset.
set fd [open [file join $root board-pins.xdc] w]
puts $fd {set_property PACKAGE_PIN E15 [get_ports uartRx]}
puts $fd {set_property PACKAGE_PIN D15 [get_ports uartTx]}
puts $fd {set_property IOSTANDARD LVCMOS33 [get_ports {uartRx uartTx}]}
close $fd
add_files -fileset constrs_1 [file join $root board-pins.xdc]
set fd [open [file join $root board-bd-contract.txt] w]
foreach n {ps/pl_clk0 clocks/clk_out1 clocks/clk_out2 clocks/clk_out3 valence/systemClock ps/saxihp0_fpd_aclk} {
    puts $fd "$n Hz=[get_property CONFIG.FREQ_HZ [get_bd_pins $n]]"
}
puts $fd "GPIO=[get_bd_intf_nets -of_objects [get_bd_intf_pins valence/PS_GPIO]]"
puts $fd "HP0=[get_bd_intf_nets -of_objects [get_bd_intf_pins valence/M_AXI_HP]]"
close $fd
write_hw_platform -fixed -force -file [file join $root i1_board-preimplementation.xsa]
puts PASS_FULL_BOARD_BD_PREPARED_NOT_IMPLEMENTED
close_project
exit
