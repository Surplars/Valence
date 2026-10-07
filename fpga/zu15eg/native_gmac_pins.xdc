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
# both removed-RDY-guard negative cases pass. Acknowledge only this pad,
# not a blanket DRC severity downgrade or permanent calibration bypass.
set_property UNAVAILABLE_DURING_CALIBRATION TRUE [get_ports {eth_txd[1]}]
# External 1.5k MDIO pull-up exists; IOBUF releases read/turnaround. No fake
# permanent linkUp, no fabricated PHY reference clock or 10G constraints.
create_clock -name phy_rx -period 8.000 -waveform {0 4} [get_ports eth_rxc]
set_clock_uncertainty 0.100 [get_clocks phy_rx]
# Realtek RTL8211F datasheet rev1.4 Table60: RX internal delay supplies >=1.2ns
# setup/hold. Reserve 0.25ns for relative PCB/connector skew in EACH direction.
# Previous data changes -3.05 .. -0.95ns; NEXT data changes +0.95..+3.05.
# A virtual DDR launch at +2ns with +/-1.05ns is the SAME pad eye on both
# edges, but expresses the next transition for hold (not the previous one).
# Board routing budget is an explicit assumption, NOT measured board timing.
create_clock -name phy_rx_launch -period 8.000 -waveform {2 6}
set_input_delay -clock phy_rx_launch -max 1.050 [get_ports {eth_rxd[*] eth_rx_ctl}]
set_input_delay -clock phy_rx_launch -min -1.050 [get_ports {eth_rxd[*] eth_rx_ctl}]
set_input_delay -clock phy_rx_launch -clock_fall -add_delay -max 1.050 [get_ports {eth_rxd[*] eth_rx_ctl}]
set_input_delay -clock phy_rx_launch -clock_fall -add_delay -min -1.050 [get_ports {eth_rxd[*] eth_rx_ctl}]
# TX timing is applied by valence_native_tx_constraints in the board Tcl
# helper after read_xdc. XDC does not support Tcl if/proc control flow.
# The helper selects the physical TX90 or legacy PHY-delayed contract.
