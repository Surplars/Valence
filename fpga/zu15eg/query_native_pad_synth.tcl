# Read-only primitive mapping diagnostic. No constraint, netlist or DCP write.
if {$argc!=2} {error "Expected EXISTING_POST_SYNTH_DCP FRESH_REPORT"}
lassign $argv dcp output
if {![file exists $dcp] || [file exists $output]} {error "Existing checkpoint and fresh report required"}
open_checkpoint $dcp
set report [open $output w]
foreach property [list_property [current_design]] {
    puts $report "DESIGN $property = [get_property $property [current_design]]"
}
if {![catch {current_fileset} fileset]} {
    foreach property {NAME TOP DESIGN_MODE} {
        if {$property in [list_property $fileset]} {
            puts $report "FILESET $property = [get_property $property $fileset]"
        }
    }
}
foreach cell [get_cells -hier -filter {REF_NAME == OSERDESE3 || NAME == phase_high_reg}] {
    puts $report "CELL $cell"
    puts "CELL $cell"
    foreach property {REF_NAME DATA_WIDTH ODDR_MODE OSERDES_D_BYPASS IS_CLK_INVERTED IS_CLKDIV_INVERTED IS_RST_INVERTED IS_C_INVERTED INIT} {
        if {$property in [list_property $cell]} {
            set value [get_property $property $cell]
            puts $report "$property = $value"
            puts "$property = $value"
        }
    }
    foreach pin [get_pins -of_objects $cell] {
        puts $report "PIN [get_property REF_PIN_NAME $pin] NET [get_nets -of_objects $pin]"
    }
}
close $report
close_project
puts "READ_ONLY_PAD_SYNTH_DIAGNOSTIC_COMPLETE"
