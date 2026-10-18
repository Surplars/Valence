# Actual Vivado netlist tests, not simulation of an independently loaded array.
if {$argc != 4} {error "usage: bootrom_netlist.tcl INITIALIZED_LEAF_DCP OLD_BOARD_DCP HEX FRESH_OUTPUT"}
lassign $argv leafDcp oldDcp golden out
if {[file exists $out]} {error "fresh test output required"}
file mkdir $out
source [file join [file dirname [info script]] .. audit_board_bootrom.tcl]
proc expect_rom_rejection {label script expected} {
    if {![catch {uplevel 1 $script} message] || [string first $expected $message] < 0} {
        error "negative control $label failed: $message"
    }
    puts "I1_BOOTROM_NEGATIVE_PASS $label: $message"
}
open_checkpoint $leafDcp
i1_audit_bootrom $golden [file join $out leaf-positive.txt] ""
set ram [get_cells -hier -filter {REF_NAME == RAMB36E2}]
set saved [get_property INIT_00 $ram]
# Tcl format %x is limited to machine width on some Tcl releases: preserve
# all 256 bits by changing only the final hex nibble in the original string.
set last [string index $saved end]
scan $last %x nibble
set changed [string replace $saved end end [format %x [expr {$nibble ^ 1}]]]
set_property INIT_00 $changed $ram
expect_rom_rejection changed_init {i1_audit_bootrom $golden [file join $out invalid.txt] ""} {content mismatch word=0}
set_property INIT_00 $saved $ram
foreach property {INITP_00 INIT_40} {
    set saved [get_property $property $ram]
    scan [string index $saved end] %x nibble
    set_property $property [string replace $saved end end [format %x [expr {$nibble ^ 1}]]] $ram
    expect_rom_rejection changed_upper_word {i1_audit_bootrom $golden [file join $out invalid.txt] ""} {content mismatch word=0}
    set_property $property $saved $ram
}
expect_rom_rejection swapped_data {i1_rom_connection $ram {DOUTADOUT[0]} "" {R0_data[1]}} {mapping mismatch}
expect_rom_rejection wrong_address_bank {i1_rom_constant $ram {ADDRBWRADDR[14]} 0} {incorrect}
set_property DOA_REG 1 $ram
expect_rom_rejection changed_latency {i1_audit_bootrom $golden [file join $out invalid.txt] ""} {unsupported physical packing}
set_property DOA_REG 0 $ram
i1_audit_bootrom $golden [file join $out leaf-restored.txt] ""
close_design
open_checkpoint $oldDcp
expect_rom_rejection old_missing_rom {i1_audit_bootrom $golden [file join $out invalid.txt]} {expected one actual initialized ROM BRAM, found 0}
close_design
set f [open [file join $out result.txt] w]
puts $f "PASS_REAL_NETLIST_BOOTROM_GATE positive=2 negatives=7 low32_parity_upper28_checked=1 old_delivered_rom_rejected=1"
close $f
