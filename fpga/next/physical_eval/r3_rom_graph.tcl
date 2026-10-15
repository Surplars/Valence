# Read-only ROM primitive graph. No content-based bank ordering assumptions.
proc r3_rom_actual_dump {path} {
    r3_rom_dump $path
    set memory $::V_ROM_ROOT/memory
    set object [get_cells [r3_one get_cells $memory]]
    set f [open $path.graph.tsv w]
    set seen {}
    foreach pin [get_pins -quiet -of_objects $object] {
        set name [get_property NAME $pin]
        set relative [string range $name [expr {[string length $memory]+1}] end]
        set nets [get_nets -quiet -segments -of_objects $pin]
        if {![llength $nets]} {error "Disconnected ROM boundary pin $name"}
        set net [lindex [lsort [get_property NAME $nets]] 0]
        puts $f "PORT\t$relative\t[get_property DIRECTION $pin]\t$net"
        if {$net ni $seen} {
            lappend seen $net
            puts $f "NET\t$net\t[get_property TYPE [get_nets $net]]"
        }
    }
    set cells [get_cells -quiet -hier -filter "NAME =~ $memory/* && IS_PRIMITIVE == 1"]
    foreach cell [lsort -dictionary $cells] {
        set name [get_property NAME $cell]
        puts $f "CELL\t$name\t[get_property REF_NAME $cell]"
        foreach prop [lsort [list_property $cell]] {
            if {[regexp {^INIT$|^(INIT|INITP)_[0-9A-Fa-f]+$|^READ_WIDTH_[AB]$|^WRITE_WIDTH_[AB]$|^RAM_MODE$|^DO[AB]_REG$|^RAM_EXTENSION_[AB]$} $prop]} {
                puts $f "PROP\t$name\t$prop\t[get_property $prop $cell]"
            }
        }
        foreach pin [get_pins -quiet -of_objects $cell] {
            set nets [get_nets -quiet -segments -of_objects $pin]
            if {![llength $nets]} {continue}
            set net [lindex [lsort [get_property NAME $nets]] 0]
            puts $f "PIN\t$name\t[get_property REF_PIN_NAME $pin]\t[get_property DIRECTION $pin]\t$net"
            if {$net ni $seen} {
                lappend seen $net
                puts $f "NET\t$net\t[get_property TYPE [get_nets $net]]"
            }
        }
    }
    close $f
}
