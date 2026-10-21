source [file join [file dirname [info script]] common_cdc.tcl]
proc assert {condition text} {if {![uplevel 1 [list expr $condition]]} {error $text}}
proc common_cdc::one {kind name} {return $name}
proc common_cdc::clock {pin} {return [expr {[string match */sourceClock $pin] ? "src" : "dst"}]}
proc common_cdc::ff {name clock args} {if {$clock ne $::control_clock} {error {wrong test control clock}}}
set ::control_clock dst
set ::has_bits 0;set ::has_storage 0;set ::ref FDCE;set ::state fifo/valid_reg
proc get_pins {args} {if {$::has_bits} {return fifo/destination_bits0};return {}}
proc get_cells {args} {
 set query [lindex $args end]
 if {[string match {*storage_ext*} $query]} {if {$::has_storage} {return fifo/storage_ext};return {}}
 return $::state
}
proc get_property {key object} {
 if {$key eq {NAME}} {return $object}
 if {$key eq {REF_NAME}} {return [expr {$object eq "fifo" ? "HeldResponseCdcDataFifo" : $::ref}]}
 if {$key eq {INIT}} {return {1'b0}}
 error "unexpected property $key"
}
assert {[common_cdc::payload_absent fifo]==1} {valid-only zero-payload specialization not proved}
set ::has_bits 1
assert {[common_cdc::payload_absent fifo]==0} {retained data port accepted as absent}
set ::has_bits 0;set ::has_storage 1
assert {[common_cdc::payload_absent fifo]==0} {retained storage module accepted}
set ::has_storage 0;set ::ref RAM32M
assert {[common_cdc::payload_absent fifo]==0} {payload RAM accepted}
set ::ref FDCE;set ::state fifo/data_reg
assert {[common_cdc::payload_absent fifo]==0} {unreviewed functional state accepted}
set ::state fifo/full_reg;set ::control_clock src
assert {[common_cdc::payload_absent fifo]==1} {source-domain full flag rejected}
set ::control_clock dst
assert {[catch {common_cdc::payload_absent fifo}]} {full flag with wrong clock accepted}
puts COMMON_PAYLOAD_ABSENCE_CONTROLS_PASS_GRAY_PROOF_SEPARATELY_REQUIRED
