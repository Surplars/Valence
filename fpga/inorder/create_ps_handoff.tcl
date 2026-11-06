set_param general.maxThreads 8
set root [file normalize [lindex $argv 0]]
set scripts [file dirname [file normalize [info script]]]
create_project i1_ps_handoff [file join $root hardware] -part xczu15eg-ffvb1156-2-i
create_bd_design i1_ps_handoff
set ps [create_bd_cell -type ip -vlnv xilinx.com:ip:zynq_ultra_ps_e:3.5 ps]
source [file join $scripts board_ps_preset.tcl]
i1_board_ps_preset $ps
source [file join $scripts board_ps_interfaces.tcl]
i1_configure_ps_interfaces ps
connect_bd_net [get_bd_pins ps/pl_clk0] [get_bd_pins ps/saxihp0_fpd_aclk]
make_bd_intf_pins_external [get_bd_intf_pins ps/S_AXI_HP0_FPD]
make_bd_intf_pins_external [get_bd_intf_pins ps/GPIO_0]
set clockPort [create_bd_port -dir O -type clk plClock]
connect_bd_net $clockPort [get_bd_pins ps/pl_clk0]
set resetPort [create_bd_port -dir O -type rst plResetn]
set_property CONFIG.POLARITY ACTIVE_LOW $resetPort
connect_bd_net $resetPort [get_bd_pins ps/pl_resetn0]
set clockHz [get_property CONFIG.FREQ_HZ [get_bd_pins ps/pl_clk0]]
set_property CONFIG.FREQ_HZ $clockHz [get_bd_intf_ports S_AXI_HP0_FPD_0]
set_property -dict [list CONFIG.FREQ_HZ $clockHz CONFIG.ASSOCIATED_BUSIF S_AXI_HP0_FPD_0 CONFIG.ASSOCIATED_RESET plResetn] $clockPort
assign_bd_address
validate_bd_design
set fd [open [file join $root ps-handoff-configured-properties.txt] w]
foreach name [lsort [list_property $ps]] {
    if {[string match CONFIG.PSU__DDRC* $name] || [string match CONFIG.PSU__CRF_APB__DDR* $name] || [string match CONFIG.PSU__CRL_APB__PL0* $name] || [string match CONFIG.PSU_BANK* $name]} {
        puts $fd "$name=[get_property $name $ps]"
    }
}
close $fd
save_bd_design
set bd [get_files i1_ps_handoff.bd]
generate_target all $bd
set wrapper [make_wrapper -files $bd -top]
add_files -norecurse $wrapper
set_property top i1_ps_handoff_wrapper [current_fileset]
update_compile_order -fileset sources_1
write_hw_platform -fixed -force -file [file join $root i1_ps_handoff.xsa]
puts PASS_SCHEMATIC_PS_XSA_EXPORTED_NOT_BOARD_TESTED
close_project
exit
