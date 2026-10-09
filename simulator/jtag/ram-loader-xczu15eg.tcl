# Exact-part offline BSDL profile. This validates supplied values; it does not
# declare/reorder TAPs, infer a PS/DAP topology, or scan an adapter.
# Source: Vivado 2025.1 xczu15eg_ffvb1156.bsd, revision 1.1 Production,
# SHA256 13554c795fac67e7a4ab6fde86a59d6252b48a1ca17501e4dde1680e5b4e2613.
namespace eval valence_ram {
    variable fpga_part ""
    variable fpga_irlen -1
    variable jtag_chain -1
    variable fpga_id_mask 0x0fffffff
}
foreach {setting variable_name} {
    VALENCE_RAM_FPGA_PART fpga_part
    VALENCE_RAM_FPGA_IRLEN fpga_irlen
    VALENCE_RAM_JTAG_CHAIN jtag_chain
} {
    if {[info exists $setting]} {set valence_ram::$variable_name [set $setting]}
}
proc valence_ram::validate_xczu15eg_configuration {} {
    variable fpga_part
    variable fpga_irlen
    variable jtag_chain
    variable user_ir
    variable fpga_id
    variable fpga_id_mask
    if {$fpga_part ne "xczu15eg-ffvb1156-2-i"} {
        error "Explicit VALENCE_RAM_FPGA_PART xczu15eg-ffvb1156-2-i is required; other parts need a reviewed BSDL profile"
    }
    if {![string is integer -strict $fpga_irlen] || $fpga_irlen != 12} {
        error "XCZU15EG requires an explicitly declared 12-bit FPGA IR, not a 5/6-bit inner TAP"
    }
    if {![string is integer -strict $jtag_chain] || $jtag_chain < 1 || $jtag_chain > 4} {
        error "Explicit VALENCE_RAM_JTAG_CHAIN in 2..4 is required"
    }
    if {$jtag_chain == 1} {
        error "USER1 is occupied by dbg_hub in the verified routed checkpoints; choose a reviewed free USER2/3/4"
    }
    set expected [dict get {2 0x903 3 0x922 4 0x923} [expr {$jtag_chain + 0}]]
    set supplied [u32 $user_ir USER_IR]
    if {$supplied != $expected} {
        error [format "USER%d requires full 12-bit opcode 0x%03x; supplied 0x%x (six-bit opcodes are invalid)" $jtag_chain $expected $supplied]
    }
    set supplied_id [u32 $fpga_id FPGA_IDCODE]
    # BSDL IDCODE_REGISTER has XXXX revision bits followed by these 28 fixed
    # bits. Preserve every fixed bit; never mask the part/manufacturer identity.
    if {($supplied_id & 0x0fffffff) != 0x04750093} {
        error "FPGA_IDCODE does not match the XCZU15EG BSDL identity 0x04750093/mask 0x0fffffff"
    }
    if {$fpga_id_mask != 0x0fffffff} {
        error "XCZU15EG IDCODE mask must preserve all 28 BSDL fixed bits"
    }
    return 1
}
