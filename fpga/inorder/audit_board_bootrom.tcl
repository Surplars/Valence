# Fail closed on actual synthesized RAM contents AND the address/data mapping.
# Vivado 2025.1 maps this 512x64 ROM to 1024x36 TDP RAMB36E2:
# port A = word[35:0], port B's second half = word[63:36].
# Do not assume a superficially plausible 32+32 packing or just count RAMs.
proc i1_rom_hex64 {word} {
    # Vivado's Tcl format %x truncates at 32 bits; comparison below is bignum,
    # but evidence must also retain both halves of every word.
    return [format %08x%08x [expr {($word >> 32) & 0xffffffff}] [expr {$word & 0xffffffff}]]
}

proc i1_rom_words {path} {
    set f [open $path r]; set text [string trim [read $f]]; close $f
    set words [split $text \n]
    if {[llength $words] != 512} {error "BOOTROM: expected exactly 512 words"}
    set result {}
    foreach word $words {
        set word [string trim $word]
        if {![regexp {^[0-9a-fA-F]{16}$} $word]} {error "BOOTROM: invalid/unknown hex word"}
        lappend result [expr 0x$word]
    }
    if {[lindex $result 0] == 0} {error "BOOTROM: blank reset instruction"}
    return $result
}

proc i1_rom_init_value {ram property} {
    set value [get_property $property $ram]
    if {![regexp {^256'[hH]([0-9a-fA-F]{64})$} $value -> digits]} {
        error "BOOTROM: invalid/unknown $property on $ram"
    }
    return [expr 0x$digits]
}

proc i1_rom_pin {ram name} {
    set pin [get_pins -quiet -of_objects $ram -filter "REF_PIN_NAME == $name"]
    if {[llength $pin] != 1} {error "BOOTROM: missing primitive pin $name"}
    return $pin
}

proc i1_rom_constant {ram name value} {
    set nets [get_nets -quiet -segments -of_objects [i1_rom_pin $ram $name]]
    set expected [expr {$value ? "POWER" : "GROUND"}]
    if {![llength $nets]} {error "BOOTROM: unconnected constant $name"}
    foreach net $nets {
        if {[get_property TYPE $net] ne $expected} {error "BOOTROM: incorrect $name constant"}
    }
}

proc i1_rom_connection {ram name leaf signal} {
    if {$leaf eq ""} {
        set boundary [get_ports -quiet -filter "NAME == $signal"]
    } else {
        set boundary [get_pins -quiet -of_objects [get_cells $leaf] -filter "REF_PIN_NAME == $signal"]
    }
    if {[llength $boundary] != 1} {error "BOOTROM: missing boundary $leaf/$signal"}
    set wanted [get_nets -quiet -segments -of_objects $boundary]
    set actual [get_nets -quiet -segments -of_objects [i1_rom_pin $ram $name]]
    foreach net $actual {
        if {[lsearch -exact $wanted $net] >= 0} {return}
    }
    error "BOOTROM: mapping mismatch $name -> $leaf/$signal"
}

proc i1_audit_bootrom {golden report {leaf u_soc/soc/fabric/rom/storage_ext}} {
    set expected [i1_rom_words $golden]
    set rams [get_cells -quiet -hier -filter {REF_NAME =~ RAMB*}]
    set selected {}
    foreach ram $rams {
        if {$leaf eq "" || [string first "$leaf/" $ram] == 0} {lappend selected $ram}
    }
    if {[llength $selected] != 1} {error "BOOTROM: expected one actual initialized ROM BRAM, found [llength $selected]"}
    set ram [lindex $selected 0]
    foreach {property value} {REF_NAME RAMB36E2 READ_WIDTH_A 36 READ_WIDTH_B 36
            WRITE_WIDTH_A 36 WRITE_WIDTH_B 36 DOA_REG 0 DOB_REG 0} {
        if {[get_property $property $ram] ne $value} {
            error "BOOTROM: unsupported physical packing $property=[get_property $property $ram], expected $value"
        }
    }
    # Vivado leaves default cell IS_*_INVERTED parameters unset; the resolved
    # primitive pin IS_INVERTED property is the actual netlist polarity.
    foreach pin {CLKARDCLK CLKBWRCLK ENARDEN ENBWREN RSTRAMARSTRAM RSTRAMB RSTREGARSTREG RSTREGB} {
        if {[get_property IS_INVERTED [i1_rom_pin $ram $pin]] ne "0"} {
            error "BOOTROM: unexpected primitive polarity $pin"
        }
    }
    foreach port {ADDRARDADDR ADDRBWRADDR} {
        for {set bit 0} {$bit < 5} {incr bit} {i1_rom_constant $ram [format {%s[%d]} $port $bit] 0}
        for {set bit 0} {$bit < 9} {incr bit} {
            i1_rom_connection $ram [format {%s[%d]} $port [expr {$bit+5}]] $leaf [format {R0_addr[%d]} $bit]
        }
    }
    i1_rom_constant $ram {ADDRARDADDR[14]} 0
    i1_rom_constant $ram {ADDRBWRADDR[14]} 1
    foreach pin {ENARDEN ENBWREN} {i1_rom_constant $ram $pin 1}
    foreach pin {RSTRAMARSTRAM RSTRAMB RSTREGARSTREG RSTREGB} {i1_rom_constant $ram $pin 0}
    foreach {port width} {WEA 4 WEBWE 8} {
        for {set bit 0} {$bit < $width} {incr bit} {i1_rom_constant $ram [format {%s[%d]} $port $bit] 0}
    }
    foreach pin {CLKARDCLK CLKBWRCLK} {i1_rom_connection $ram $pin $leaf R0_clk}
    foreach {port width offset} {DOUTADOUT 32 0 DOUTPADOUTP 4 32 DOUTBDOUT 28 36} {
        for {set bit 0} {$bit < $width} {incr bit} {
            i1_rom_connection $ram [format {%s[%d]} $port $bit] $leaf [format {R0_data[%d]} [expr {$bit+$offset}]]
        }
    }
    set data {}; set parity {}
    for {set n 0} {$n < 128} {incr n} {lappend data [i1_rom_init_value $ram [format INIT_%02X $n]]}
    for {set n 0} {$n < 16} {incr n} {lappend parity [i1_rom_init_value $ram [format INITP_%02X $n]]}
    set actual {}
    for {set n 0} {$n < 512} {incr n} {
        set lo [expr {([lindex $data [expr {$n/8}]] >> (32*($n%8))) & 0xffffffff}]
        set mid [expr {([lindex $parity [expr {$n/64}]] >> (4*($n%64))) & 15}]
        set hi [expr {([lindex $data [expr {64+$n/8}]] >> (32*($n%8))) & 0xfffffff}]
        set word [expr {$lo | ($mid << 32) | ($hi << 36)}]
        if {$word != [lindex $expected $n]} {
            error [format {BOOTROM: content mismatch word=%d byte_offset=0x%x expected=%s actual=%s} \
                $n [expr {$n*8}] [i1_rom_hex64 [lindex $expected $n]] [i1_rom_hex64 $word]]
        }
        lappend actual [i1_rom_hex64 $word]
    }
    set f [open $report w]
    puts $f "I1_BOOTROM_NETLIST_PASS words=512 bytes=4096 address_data_mapping=PASS write_disabled=PASS"
    puts $f "RAM=$ram SOURCE=[file normalize $golden]"
    puts $f [join $actual \n]
    close $f
    puts "I1_BOOTROM_NETLIST_PASS $report"
}
