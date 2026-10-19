# Chisel's readmemh block is synthesis-disabled unless explicitly enabled.
# A Memory Initialization Files entry alone does NOT enable that block.
proc i1_configure_board_mem {} {
    set fileset [get_filesets sources_1]
    set defines [get_property VERILOG_DEFINE $fileset]
    foreach define $defines {
        if {[string match RANDOMIZE* $define] || [string match ENABLE_INITIAL_REG_* $define]} {
            error "Refuse random register/memory initialization in the physical board"
        }
        if {[string match ENABLE_INITIAL_MEM_=* $define]} {
            error "Use the exact ENABLE_INITIAL_MEM_ macro, not a valued alias"
        }
    }
    if {[lsearch -exact $defines ENABLE_INITIAL_MEM_] < 0} {lappend defines ENABLE_INITIAL_MEM_}
    set_property VERILOG_DEFINE $defines $fileset
    if {[lsearch -exact [get_property VERILOG_DEFINE $fileset] ENABLE_INITIAL_MEM_] < 0} {
        error "BootROM initialization macro did not bind to synthesis sources"
    }
}
