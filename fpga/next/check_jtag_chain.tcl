# Read-only post-synthesis gate for an enabled BSCANE2 RAM-loader image.
# Source after synth_design/open_checkpoint, before accepting implementation or
# write_bitstream. Arguments are the allocated chain and exact loader primitive
# cell name from THIS synthesized design, never a guessed wildcard.
proc valence_jtag_integer_property {object candidates} {
    set properties [list_property $object]
    foreach property $candidates {
        if {[lsearch -exact $properties $property] >= 0} {
            set value [get_property $property $object]
            if {![string is integer -strict $value] || $value < 1 || $value > 4} {
                error "Unverified BSCAN chain value '$value' for $object/$property"
            }
            return $value
        }
    }
    error "Cannot verify BSCAN chain property for $object"
}
proc valence_assert_jtag_chain {chain expected_cell} {
    if {![string is integer -strict $chain] || $chain < 1 || $chain > 4} {
        error "Explicit BSCAN USER chain in 1..4 is required"
    }
    if {$expected_cell eq "" || [regexp {[\*\?\[\]]} $expected_cell]} {
        error "Provide the exact synthesized loader BSCANE2 cell, not a wildcard"
    }
    set primitives [get_cells -quiet -hierarchical -filter {REF_NAME == BSCANE2}]
    if {[llength $primitives] == 0} {error "No BSCANE2 primitives in the open synthesized design"}
    set owner_found 0
    set owners 0
    foreach primitive $primitives {
        set name [get_property NAME $primitive]
        set allocated [valence_jtag_integer_property $primitive {JTAG_CHAIN CONFIG.JTAG_CHAIN}]
        if {$name eq $expected_cell} {
            if {$allocated != $chain} {error "Loader primitive uses USER$allocated, expected USER$chain"}
            incr owner_found
        }
        if {$allocated == $chain} {
            incr owners
            if {$name ne $expected_cell} {error "USER$chain collision with BSCANE2 $name"}
        }
    }
    if {$owner_found != 1 || $owners != 1} {error "Expected exactly one matching loader BSCANE2 owner"}
    # The debug hub can expose its allocation before/independently of a visible
    # primitive. Never infer a free chain from default settings or instance count.
    foreach hub [get_debug_cores -quiet *dbg_hub*] {
        set allocated [valence_jtag_integer_property $hub {C_USER_SCAN_CHAIN CONFIG.C_USER_SCAN_CHAIN}]
        if {$allocated == $chain} {error "USER$chain collision with debug hub $hub"}
    }
    puts "VALENCE_JTAG_CHAIN_PASS USER$chain $expected_cell"
    return 1
}
