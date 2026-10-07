# Derived from the original ZU15EG board.xdc pin map.
# MIG owns the differential input; its generated XDC specifies DIFF_SSTL12.
set_property PACKAGE_PIN F15 [get_ports button_n]
set_property PACKAGE_PIN F16 [get_ports sys_rst_n]
set_property IOSTANDARD LVCMOS33 [get_ports {button_n sys_rst_n}]
set_property PACKAGE_PIN AL8 [get_ports clk_in1_p]
set_property PACKAGE_PIN AL7 [get_ports clk_in1_n]
set_property IOSTANDARD DIFF_SSTL12 [get_ports {clk_in1_p clk_in1_n}]
set_property PACKAGE_PIN D15 [get_ports uart_txd]
set_property PACKAGE_PIN E15 [get_ports uart_rxd]
set_property IOSTANDARD LVCMOS33 [get_ports {uart_rxd uart_txd}]
set_property DRIVE 12 [get_ports uart_txd]
set_property PACKAGE_PIN D16 [get_ports led]
set_property IOSTANDARD LVCMOS33 [get_ports led]
set_property DRIVE 12 [get_ports led]

# UART RX is asynchronous to clk_soc. The RTL already provides two flip-flops;
# identify them to Vivado so implementation preserves and co-locates the chain.
# Do not false-path rxMeta -> rxSync or any synchronous SoC data path.
# Cardinality validation belongs in the batch Tcl/GSIM flow, not in declarative XDC.
set_property ASYNC_REG TRUE [get_cells -quiet -hier -filter {NAME =~ */uart/rxMeta_reg || NAME =~ */uart/rxSync_reg}]

# Board-local async-assert/sync-release reset synchronizers.
# These six PRE inputs are asynchronous by construction; ONLY their recovery/
# removal checks are excepted. Synchronizer D/Q and functional reset paths remain timed.
# audit_reset_cdc.tcl verifies all six FDPEs, ASYNC_REG, common PRE, direct Q->D,
# constant first D, destination clocks and absence of functional early-stage fanout.
# This follows the XPM_CDC_ASYNC_RST constraint model, not a whole clock-group cut.
set_false_path -to [get_pins -quiet -of_objects [get_cells -quiet {reset_pipe_reg[0] reset_pipe_reg[1] reset_pipe_reg[2] ui_reset_pipe_reg[0] ui_reset_pipe_reg[1] ui_reset_pipe_reg[2]}] -filter {REF_PIN_NAME == PRE}]
