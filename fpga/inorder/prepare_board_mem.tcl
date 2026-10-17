# Project synthesis runs in its own directory: bind the actual ROM image there.
set root [file normalize [file join [file dirname [info script]] ..]]
set source [file join $root rtl bootrom.hex]
set target [file join [pwd] bootrom.hex]
if {![file isfile $source]} {error "Missing actual I1 ROM initialization"}
if {[file exists $target]} {
    set f [open $source]; set expected [read $f]; close $f
    set f [open $target]; set actual [read $f]; close $f
    if {$expected ne $actual} {error "Refuse a stale/different ROM image"}
} else {
    file copy $source $target
}
puts "I1_BOARD_ROM_BOUND $target"
