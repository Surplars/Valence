# Explicit300MHz CPU + independent50/125MHz peripheral clocks.
# DDR AXI is CPU-domain boundary; actual AXI CDC/MIG and RGMII IOB are outside.
create_clock -name orbital_i1_cpu -period 3.333333333 [get_ports io_clockIn]
create_clock -name i1_aon -period 20.0 [get_ports io_alwaysOnClock]
create_clock -name i1_uart -period 20.0 [get_ports io_uartClockIn]
create_clock -name i1_mac_tx -period 8.0 [get_ports io_macTxClock]
create_clock -name i1_mac_rx -period 8.0 [get_ports io_macRxClock]
# Recovered RX125MHz is the fastest supported case, not a fixed10/100 PHY clock.
# Zero OOC I/O placeholders are reported separately; not board timing evidence.
set_input_delay 0.0 -clock orbital_i1_cpu [get_ports -filter {DIRECTION == IN && NAME != io_clockIn && NAME != io_alwaysOnClock && NAME != io_uartClockIn && NAME != io_macTxClock && NAME != io_macRxClock && NAME != io_uartRx && NAME !~ io_rgmii_rx*}]
set_input_delay 0.0 -clock i1_mac_rx [get_ports -filter {DIRECTION == IN && NAME =~ io_rgmii_rx*}]
set_input_delay 0.0 -clock i1_uart [get_ports io_uartRx]
set_output_delay 0.0 -clock orbital_i1_cpu [get_ports -filter {DIRECTION == OUT && NAME !~ io_rgmii_tx* && NAME != io_uartTx && NAME !~ io_clockEnabled*}]
set_output_delay 0.0 -clock i1_mac_tx [get_ports -filter {DIRECTION == OUT && NAME =~ io_rgmii_tx*}]
set_output_delay 0.0 -clock i1_uart [get_ports io_uartTx]
set_output_delay 0.0 -clock i1_aon [get_ports -filter {DIRECTION == OUT && NAME =~ io_clockEnabled*}]
