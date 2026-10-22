# Synthetic Vivado-command doubles. Not a native checkpoint qualification.
set ::common_board_definitions_only 1
source [file join [file dirname [info script]] board_audit.tcl]
set properties [dict create \
    root [dict create NAME root IS_BLACKBOX 0] \
    root/rom [dict create NAME root/rom REF_NAME RAMB36E2 \
        READ_WIDTH_A 9 READ_WIDTH_B 9 WRITE_WIDTH_A 9 WRITE_WIDTH_B 9 \
        DOA_REG 0 DOB_REG 0 EN_ECC_READ FALSE EN_ECC_WRITE FALSE EN_ECC_PIPE FALSE \
        CASCADE_ORDER_A NONE CASCADE_ORDER_B NONE ENADDRENA FALSE ENADDRENB FALSE \
        RDADDRCHANGEA FALSE RDADDRCHANGEB FALSE] \
    root/douta [dict create NAME root/douta REF_PIN_NAME douta DIRECTION OUT] \
    root/rom/CASDOUTA31 [dict create NAME root/rom/CASDOUTA31 REF_PIN_NAME {CASDOUTA[31]} DIRECTION OUT] \
    root/rom/DOUTA0 [dict create NAME root/rom/DOUTA0 REF_PIN_NAME {DOUTADOUT[0]} DIRECTION OUT] \
    root/rom/ADDR0 [dict create NAME root/rom/ADDR0 REF_PIN_NAME {ADDRARDADDR[0]} DIRECTION IN] \
    data [dict create NAME data TYPE SIGNAL] \
    ground [dict create NAME ground TYPE GROUND]]
for {set i 0} {$i < 128} {incr i} {dict set properties root/rom [format INIT_%02X $i] "256'h0"}
for {set i 0} {$i < 16} {incr i} {dict set properties root/rom [format INITP_%02X $i] "256'h0"}
set connections [dict create root/douta data root/rom/DOUTA0 data root/rom/ADDR0 ground]
proc get_property {key object} {return [dict get $::properties $object $key]}
proc get_cells {args} {
    if {[lsearch -exact $args -filter] >= 0} {return root/rom}
    return root
}
proc get_pins {args} {
    if {[lindex $args end] eq "root"} {return root/douta}
    return {root/rom/CASDOUTA31 root/rom/DOUTA0 root/rom/ADDR0}
}
proc get_nets {args} {
    set pin [lindex $args end]
    if {[dict exists $::connections $pin]} {return [dict get $::connections $pin]}
    return {}
}
proc fails {script expected} {
    if {![catch {uplevel 1 $script} reason] || ![string match $expected $reason]} {
        error "Expected failure $expected, got $reason"
    }
}
set f [file tempfile path]; close $f
try {
    common_board::rom_dump root $path
    set f [open $path]; set result [read $f]; close $f
    foreach expected {{"CASDOUTA[31]":null} {"DOUTADOUT[0]":"data"} {"ADDRARDADDR[0]":"ground"} {"CASCADE_ORDER_A":"NONE"} {"EN_ECC_PIPE":"FALSE"} {"INITP_0F":"256'h0"}} {
        if {[string first $expected $result] < 0} {error "Missing export $expected"}
    }
    fails {common_board::net root/rom/CASDOUTA31} {*disconnected net*}
    dict unset connections root/rom/ADDR0
    fails {common_board::rom_dump root $path} {*disconnected net*ADDR0}
    dict set connections root/rom/ADDR0 ground
    dict unset connections root/douta
    fails {common_board::rom_dump root $path} {*disconnected net*root/douta}
    dict set connections root/douta data
    dict set properties root IS_BLACKBOX 1
    fails {common_board::rom_dump root $path} {*unimplemented IP*}
    # Delayed invocation must use the decoder adjacent to this exporter, not
    # an older copy inside the immutable hardware-input root.
    rename common_board::rom_dump common_board::real_rom_dump
    proc common_board::rom_dump {args} {}
    proc exec {args} {set ::decoder_argv $args; return COMMON_ROM_CONTENT_MAPPING_PASS}
    array set ::valence [list python python3 root /frozen/hardware rom /frozen/rom.bin out /unused]
    common_board::rom
    if {[lindex $::decoder_argv 1] ne "-E" ||
        [lindex $::decoder_argv 2] ne [file join $::common_board::script_dir rom_audit.py]} {
        error "ROM decoder did not use the same audit-tool overlay: $::decoder_argv"
    }
} finally {file delete $path}
puts COMMON_ROM_EXPORT_TEST_PASS
