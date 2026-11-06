# Apply after the board PS preset, in the board BD. DDR timing and
# PS boot settings belong to that preset; this fragment configures PL links.
proc i1_configure_ps_interfaces {ps_cell} {
    set ps [get_bd_cells $ps_cell]
    # Keep the PS configurator count and the HDL width consistent through BD propagation.
    set_property -dict [list \
        CONFIG.PSU__USE__S_AXI_GP2 {1} \
        CONFIG.PSU__SAXIGP2__DATA_WIDTH {64} \
        CONFIG.PSU__GPIO_EMIO__PERIPHERAL__ENABLE {1} \
        CONFIG.PSU__GPIO_EMIO__PERIPHERAL__IO {3} \
        CONFIG.PSU__GPIO_EMIO_WIDTH {3} \
        CONFIG.PSU__ENET3__PERIPHERAL__ENABLE {1} \
        CONFIG.PSU__ENET3__PERIPHERAL__IO {MIO 64 .. 75} \
        CONFIG.PSU__ENET3__GRP_MDIO__ENABLE {1} \
        CONFIG.PSU__ENET3__GRP_MDIO__IO {MIO 76 .. 77}] $ps
}

# Call with existing BD clock/reset objects, after adding the exported PL RTL
# and I1PsPlBoundary.v to the project. Board PS DDR/boot preset is a precondition.
# CPU/VPU sources are independent; systemClock must continue during cold hold.
proc i1_attach_ps_pl {ps_cell pl_name cpu_clock vpu_clock system_clock cold_reset} {
    i1_configure_ps_interfaces $ps_cell
    set pl [create_bd_cell -type module -reference I1PsPlBoundary $pl_name]
    connect_bd_intf_net [get_bd_intf_pins $pl_name/M_AXI_HP] [get_bd_intf_pins $ps_cell/S_AXI_HP0_FPD]
    connect_bd_net $system_clock [get_bd_pins $pl_name/systemClock] [get_bd_pins $ps_cell/saxihp0_fpd_aclk]
    connect_bd_net $cpu_clock [get_bd_pins $pl_name/rawCpuClock]
    connect_bd_net $vpu_clock [get_bd_pins $pl_name/rawVpuClock]
    connect_bd_net $cold_reset [get_bd_pins $pl_name/boardColdReset]
    connect_bd_intf_net [get_bd_intf_pins $ps_cell/GPIO_0] [get_bd_intf_pins $pl_name/PS_GPIO]
    return $pl
}
