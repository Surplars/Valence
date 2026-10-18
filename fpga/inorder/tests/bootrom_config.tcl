# Fast pure Tcl test of project macro configuration, no Vivado run.
source [file join [file dirname [info script]] .. configure_board_mem.tcl]
proc get_filesets {name} {return $name}
proc get_property {key object} {return $::test_defines}
proc set_property {key value object} {set ::test_defines $value}
set test_defines {EXISTING_FEATURE=1}
i1_configure_board_mem
if {$test_defines ne {EXISTING_FEATURE=1 ENABLE_INITIAL_MEM_}} {error "macro not preserved/enabled"}
i1_configure_board_mem
if {[llength $test_defines] != 2} {error "macro duplicated"}
foreach bad {RANDOMIZE_MEM_INIT RANDOMIZE_REG_INIT ENABLE_INITIAL_REG_ ENABLE_INITIAL_MEM_=0} {
    set test_defines [list $bad]
    if {![catch {i1_configure_board_mem} message]} {error "unsafe macro accepted: $bad"}
}
set test_defines {}
i1_configure_board_mem
if {$test_defines ne {ENABLE_INITIAL_MEM_}} {error "fresh synthesis child macro missing"}
puts "I1_BOOTROM_CONFIG_PASS preserve_idempotent_child_and_unsafe_defines"
