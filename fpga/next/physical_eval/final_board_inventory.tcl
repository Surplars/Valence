# Contract checks on the current placed design; no new exceptions.
set f [open final_board_contract.txt w]
set violations {}
foreach {pin period} {u_ddr/c0_ddr4_ui_clk 4 u_soc/clock 10 u_soc/io_alwaysOnClock 20 u_soc/board/nativeBank/uart/uart/clock 20 u_soc/io_nativeGmac_rawTxClock 8 u_rgmii/delay_clock 2 u_rgmii/tx_pad_clock 4} {
 set pins [get_pins -quiet $pin]
 set clocks [get_clocks -quiet -of_objects $pins]
 puts $f "CLOCK $pin clocks=$clocks"
 if {[llength $pins]!=1 || [llength $clocks]!=1} {lappend violations "Missing exact clock at $pin";continue}
 set p [get_property PERIOD $clocks]
 puts $f "PERIOD $pin expected=$period actual=$p"
 if {abs($p-$period)>0.001} {lappend violations "Clock period mismatch at $pin"}
}
foreach port [get_ports] {
 set package [get_property PACKAGE_PIN $port]
 set standard [get_property IOSTANDARD $port]
 puts $f "PORT $port PIN=$package STANDARD=$standard"
 if {$package eq "" || $standard in {"" DEFAULT}} {lappend violations "Unbound port $port"}
}
foreach {port pin} {eth_mdc Y1 eth_reset_gate Y2 eth_mdio Y12 eth_rxc AA7 eth_txc AC8} {
 if {[get_property PACKAGE_PIN [get_ports $port]] ne $pin} {lappend violations "Pin mismatch $port"}
}
foreach pin {u_soc/board/nativeBank/gmac/sourceClock u_soc/board/nativeBank/gmac/rawTxClock u_soc/board/nativeBank/gmac/rawRxClock u_soc/board/nativeBank/gmac/txManaged_gate/managedClock u_soc/board/nativeBank/gmac/rxManaged_gate/managedClock} {
 puts $f "MAC_DOMAIN $pin [get_clocks -quiet -of_objects [get_pins -quiet $pin]]"
}
foreach cell [get_cells -hier -filter {REF_NAME =~ IDELAYE3 || REF_NAME =~ ODELAYE3 || REF_NAME =~ OSERDESE3 || REF_NAME =~ ISERDESE3 || REF_NAME =~ IDDRE1}] {
 puts $f "IO_PRIMITIVE $cell [get_property REF_NAME $cell] LOC=[get_property LOC $cell]"
 foreach prop {DELAY_VALUE DELAY_TYPE DELAY_FORMAT REFCLK_FREQUENCY DATA_WIDTH} {
  if {[lsearch -exact [list_property $cell] $prop]>=0} {puts $f "  $prop=[get_property $prop $cell]"}
 }
}
puts $f "CONTRACT_VIOLATIONS $violations"
close $f
if {[llength $violations]} {error "Final board contract violations: $violations"}
puts "FINAL_BOARD_CLOCK_AND_PIN_INVENTORY_PASS_NO_NEW_CONSTRAINTS"
source [file join $root scripts r3_jtag_finish.tcl]
