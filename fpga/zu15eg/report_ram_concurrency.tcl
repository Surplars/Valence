# Read a verified candidate checkpoint and report it without changing its design.
# No clock/exception changes, implementation reruns, checkpoint writes or bit output.
# vivado -mode batch -source report_ram_concurrency.tcl -tclargs VERIFIED.dcp FRESH_REPORT_DIR
if {$argc != 2} { error "usage: VERIFIED_CHECKPOINT.dcp FRESH_REPORT_DIR" }
set checkpoint [file normalize [lindex $argv 0]]
set output [file normalize [lindex $argv 1]]
if {![file isfile $checkpoint]} { error "missing verified checkpoint" }
if {[file exists $output]} { error "report directory exists; preserve old evidence" }
file mkdir $output
open_checkpoint $checkpoint
report_utilization -hierarchical -file [file join $output utilization.rpt]
report_timing_summary -report_unconstrained -file [file join $output timing_summary.rpt]
report_timing -delay_type max -max_paths 100 -file [file join $output setup_paths.rpt]
report_timing -delay_type min -max_paths 100 -file [file join $output hold_paths.rpt]
report_clocks -file [file join $output clocks.rpt]
report_clock_interaction -file [file join $output clock_interaction.rpt]
report_cdc -details -file [file join $output cdc.rpt]
report_drc -file [file join $output drc.rpt]
redirect -file [file join $output check_timing.rpt] { check_timing -verbose }

set fp [open [file join $output ram_primitives_and_init.txt] w]
set count 0
foreach cell [get_cells -hierarchical -filter {IS_PRIMITIVE == 1}] {
    set ref [get_property REF_NAME $cell]
    if {![regexp {^(RAM|URAM|ROM)} $ref]} { continue }
    incr count
    puts $fp [list cell $cell primitive $ref]
    foreach prop [lsort [list_property $cell]] {
        if {[string match "INIT*" $prop]} {
            puts $fp [list $prop [get_property $prop $cell]]
        }
    }
}
close $fp
set fp [open [file join $output REVIEW_REQUIRED.txt] w]
puts $fp "Checkpoint: $checkpoint"
puts $fp "Tool: [version -short]"
puts $fp "RAM/ROM primitive instances: $count"
puts $fp "No automatic timing or resource PASS is asserted."
puts $fp "Identify exact LVT PRF, home tag and bridge payload hierarchies in the raw reports."
puts $fp "Check replication/read ports and register fallbacks; verify assertion-only tag read pruning."
puts $fp "Compare matched baseline/candidate inputs, setup/hold/pulse width, unconstrained paths and CDC."
puts $fp "Keep actual CPU100/AON50/UART50/MAC125/DDR250 constraints; old route is not new CPU evidence."
puts $fp "ROM INIT/INITP values still require comparison with the verified52592-byte image."
close $fp
close_design
