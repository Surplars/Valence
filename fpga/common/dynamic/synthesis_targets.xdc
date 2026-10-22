# Timing requirements, NOT runtime MMCM programming. Loaded before synth_design.
# Only the two actual managed-domain source pins are overridden. DDR/UI, AON,
# UART, network and debug clocks retain their original definitions/relationships.
# Boot hardware is still D10/M40/O20=50MHz; native measurements prove that fact.
create_generated_clock -name cpu_target300 -source [get_pins u_ddr/c0_ddr4_ui_clk] -multiply_by 6 -divide_by 5 [get_pins cpu_clock/mmcm/CLKOUT0]
create_generated_clock -name fabric_target250 -source [get_pins u_ddr/c0_ddr4_ui_clk] -multiply_by 1 -divide_by 1 [get_pins fabric_clock/mmcm/CLKOUT0]
