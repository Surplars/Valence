if {$argc != 2} { error {usage: CHECKPOINT OUTPUT_DIRECTORY} }
set checkpoint [lindex $argv 0]
set out [lindex $argv 1]
file mkdir $out
set_param general.maxThreads 8
open_checkpoint $checkpoint
set cpu [get_clocks clk_out1_clk_wiz_ddr]
if {[llength $cpu] != 1 || abs([get_property PERIOD $cpu] - 10.0) > 0.001} {
    error {Expected existing 100 MHz board constraints}
}
report_timing -group clk_out1_clk_wiz_ddr -max_paths 80 -nworst 1 -input_pins -file [file join $out cpu_paths.rpt]
set table [open [file join $out cpu_paths.tsv] w]
puts $table "slack\tstartpoint\tendpoint\tlogic_levels\tdata_delay"
foreach path [get_timing_paths -group clk_out1_clk_wiz_ddr -max_paths 200 -nworst 1] {
    puts $table "[get_property SLACK $path]\t[get_property STARTPOINT_PIN $path]\t[get_property ENDPOINT_PIN $path]\t[get_property LOGIC_LEVELS $path]\t[get_property DATAPATH_DELAY $path]"
}
close $table
set registers [all_registers -clock $cpu -cells]
set families [open [file join $out path_families.tsv] w]
puts $families "family\tslack\tstartpoint\tendpoint\tlogic_levels\tdata_delay"
foreach {name pattern} {
    checked {*core/adapter/checked*/*}
    responses {*core/*responses/*}
    predictor {*core/*predictor/*}
    return_stack {*returnStack/*}
    prediction_packet {*predictionTraining/*}
    memory_address {*backend/stagedMemoryAddress*}
    walkers {*physicalData_walkers*}
    frontend {*frontend/*}
    core_pc {*core/core/core/pc_reg*}
    backend {*core/core/core/backend/*}
} {
    set cells [filter $registers "NAME =~ $pattern"]
    if {[llength $cells] > 0} {
        set pins [get_pins -quiet -of_objects $cells -filter {REF_PIN_NAME == D || REF_PIN_NAME == CE}]
        if {[llength $pins] > 0} {
            report_timing -to $pins -max_paths 8 -nworst 1 -input_pins -file [file join $out ${name}_paths.rpt]
            foreach path [get_timing_paths -to $pins -max_paths 1] {
                puts $families "$name\t[get_property SLACK $path]\t[get_property STARTPOINT_PIN $path]\t[get_property ENDPOINT_PIN $path]\t[get_property LOGIC_LEVELS $path]\t[get_property DATAPATH_DELAY $path]"
            }
        }
    }
}
close $families
close_design
exit
