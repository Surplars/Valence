# Parser and polarity-mapping unit controls only; no physical qualification.
set ::common_board_definitions_only 1
source [file join [file dirname [info script]] board_audit.tcl]
proc assert {c message} {if {![uplevel 1 [list expr $c]]} {error $message}}
set fixture {1. checking no_input_delay (2)
Ports:
uart_rxd
eth_mdio
2. checking partial_input_delay (0)
3. checking no_output_delay (1)
led
4. checking partial_output_delay (0)
}
set parsed [common_board::io_report $fixture {uart_rxd eth_mdio led unexpected}]
assert {[dict get $parsed no_input_delay] eq {uart_rxd eth_mdio}} {lost exact input ports}
assert {[catch {common_board::io_report [string map {(2) (3)} $fixture] {uart_rxd eth_mdio led}}]} {incomplete listing accepted}
assert {[catch {common_board::io_report [string map {uart_rxd unknown_pad} $fixture] {uart_rxd eth_mdio led}}]} {unknown port accepted}
assert {[catch {common_board::io_report [string map {{partial_output_delay (0)} {partial_output_delay (1)
led}} $fixture] {uart_rxd eth_mdio led}}]} {partial delay accepted}
assert {[catch {common_board::io_report [string map {{checking no_input_delay} {unsupported report header}} $fixture] {uart_rxd eth_mdio led}}]} {missing section accepted}
puts COMMON_IO_PARSER_AND_NEGATIVE_CONTROLS_PASS_NOT_PHYSICAL_EVIDENCE
rename common_cdc::drivers common_cdc::real_drivers
rename common_cdc::one common_cdc::real_one
proc common_cdc::drivers {pin} {return [dict get $::mock_drivers $pin]}
proc common_cdc::one {command name} {return $name}
proc get_cells {args} {return [string range [lindex $args end] 0 end-2]}
proc get_property {property object} {
    if {$property eq "IS_INVERTED"} {return $::mock_inverted}
    if {$property eq "REF_NAME"} {return LUT1}
    if {$property eq "REF_PIN_NAME"} {return O}
    if {$property eq "INIT"} {return $::mock_init}
    if {$property eq "NAME"} {return $object}
    error "unexpected mock property $property"
}
set releases [dict create release/Q ui_clk]
set mock_drivers [dict create functional/CLR release/Q]; set mock_inverted 0
assert {[common_board::reset_source functional/CLR $releases] eq "release/Q"} {direct reset rejected}
set mock_drivers [dict create functional/CLR mapped/O mapped/I0 release/Q]; set mock_init 2'h2
assert {[common_board::reset_source functional/CLR $releases] eq "release/Q"} {LUT1 buffer rejected}
set mock_init 2'h1; set mock_inverted 1
assert {[common_board::reset_source functional/CLR $releases] eq "release/Q"} {proved balanced inversion rejected}
set mock_inverted 0
assert {[catch {common_board::reset_source functional/CLR $releases}]} {wrong assertion polarity accepted}
set mock_init 2'h0
assert {[catch {common_board::reset_source functional/CLR $releases}]} {constant LUT reset incorrectly accepted}
puts COMMON_RESET_MAPPED_POLARITY_POSITIVE_AND_NEGATIVE_CONTROLS_PASS
