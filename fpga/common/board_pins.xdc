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


# User workbook: XCZU15EG-F V1.0管脚定义.xls, MIPI & PL ETH!A17:C31.
# All RGMII pins match manufacturer 12_UDP_TEST/pin.xdc. Management pins
# cross-checked against carrier J5 p4 and core BANK66 p6. Earlier Y9/Y11
# transcription was WRONG: MDC=Y1 (L22N), reset=Y2 (L22P); Y11 is VCCO.
set_property PACKAGE_PIN Y1 [get_ports {eth_mdc}]
set_property PACKAGE_PIN Y12 [get_ports {eth_mdio}]
set_property PACKAGE_PIN Y2 [get_ports {eth_reset_gate}]
set_property PACKAGE_PIN AA7 [get_ports {eth_rxc}]
set_property PACKAGE_PIN AB9 [get_ports {eth_rx_ctl}]
set_property PACKAGE_PIN AC4 [get_ports {eth_rxd[0]}]
set_property PACKAGE_PIN AB4 [get_ports {eth_rxd[1]}]
set_property PACKAGE_PIN AB10 [get_ports {eth_rxd[2]}]
set_property PACKAGE_PIN AB11 [get_ports {eth_rxd[3]}]
set_property PACKAGE_PIN AC8 [get_ports {eth_txc}]
set_property PACKAGE_PIN AB8 [get_ports {eth_tx_ctl}]
set_property PACKAGE_PIN AC11 [get_ports {eth_txd[0]}]
set_property PACKAGE_PIN AC12 [get_ports {eth_txd[1]}]
set_property PACKAGE_PIN AA6 [get_ports {eth_txd[2]}]
set_property PACKAGE_PIN AA12 [get_ports {eth_txd[3]}]
set_property IOSTANDARD LVCMOS18 [get_ports {eth_mdc eth_mdio eth_reset_gate eth_rxc eth_rx_ctl eth_rxd[*] eth_txc eth_tx_ctl eth_txd[*]}]
set_property DRIVE 8 [get_ports {eth_txc eth_tx_ctl eth_txd[*] eth_mdc eth_reset_gate}]
set_property SLEW FAST [get_ports {eth_txc eth_tx_ctl eth_txd[*]}]
# This fixed workbook pad is BITSLICE0 of an RX-calibrated byte. The board
# top now holds PHY reset and TX reset until aggregated IDELAYCTRL RDY;
# PHY release additionally waits 10ms. Short actual-source reset xsim and
# inherited guard must be rechecked on this common wrapper. Acknowledge only this pad,
# not a blanket DRC severity downgrade or permanent calibration bypass.
set_property UNAVAILABLE_DURING_CALIBRATION TRUE [get_ports {eth_txd[1]}]
# External 1.5k MDIO pull-up exists; IOBUF releases read/turnaround. No fake
# permanent linkUp, no fabricated PHY reference clock or 10G constraints.
