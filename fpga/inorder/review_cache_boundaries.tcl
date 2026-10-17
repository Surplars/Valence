# Read-only boundary queries from the already routed board. Never implement,
# alter clocks/exceptions or write a checkpoint/bit in this script.
if {$argc != 1} {error "usage: review_cache_boundaries.tcl EXISTING_BOARD_ROOT"}
set root [file normalize [lindex $argv 0]]
set out [file join $root reports boundaries-r1]
if {[file exists $out]} {error "Preserve existing boundary reports"}
file mkdir $out
set_param general.maxThreads 8
open_checkpoint [file join $root reports real_board_routed.dcp]
if {[get_property PART [current_design]] ne "xczu15eg-ffvb1156-2-i"} {error "Wrong physical part"}
set cpu [get_clocks -of_objects [get_pins u_soc/io_clockIn]]
if {[llength $cpu] != 1 || abs([get_property PERIOD $cpu] - 3.333) > 0.002} {
    error "Keep the actual CPU300 clock"
}
set f [open [file join $out boundaries.tsv] w]
puts $f "boundary\ttarget_count\tslack_ns\tstartpoint\tendpoint"
proc boundary {name targets} {
    global f out
    if {[llength $targets] == 0} {error "Actual boundary missing: $name"}
    set p [get_timing_paths -to $targets -delay_type max -max_paths 1]
    if {[llength $p] != 1} {error "Actual boundary untimed: $name"}
    puts $f "$name\t[llength $targets]\t[get_property SLACK $p]\t[get_property STARTPOINT_PIN $p]\t[get_property ENDPOINT_PIN $p]"
    report_timing -to $targets -delay_type max -max_paths 5 -input_pins \
        -file [file join $out [format "%s.rpt" $name]]
}
set rams [get_cells -hier -filter {REF_NAME == RAMB36E2 && NAME =~ u_soc/soc/core/dcache/coherent/cache/dataWays*}]
if {[llength $rams] != 16} {error "Expected sixteen actual D-cache per-way BRAMs"}
boundary D_BRAM_CONTROL [get_pins -of_objects $rams -filter {
    REF_PIN_NAME == ENARDEN || REF_PIN_NAME == ENBWREN ||
    REF_PIN_NAME =~ WEA* || REF_PIN_NAME =~ WEBWE*}]
boundary D_BRAM_ADDRESS [get_pins -of_objects $rams -filter {REF_PIN_NAME =~ ADDR*}]
foreach {name pattern} {
    D_TAG_CAPTURE u_soc/soc/core/dcache/coherent/cache/victimTags*
    D_RETURN u_soc/soc/core/dt/result_data_reg*
    IT_PTE_RETURN u_soc/soc/core/it/pte_reg*
    FPU_CAPTURE u_soc/soc/core/core/execute/captured*
} {
    boundary $name [get_cells -hier -filter "IS_SEQUENTIAL && NAME =~ $pattern"]
}
close $f
puts "I1_BOUNDARY_REVIEW_COMPLETE SAME_ROUTED_DCP NO_DESIGN_CHANGES"
close_design
