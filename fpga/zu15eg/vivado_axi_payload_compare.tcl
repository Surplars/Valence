# Frozen bridge-only A/B input. The parent must authorize/notify local execution.
# vivado -mode batch -source vivado_axi_payload_compare.tcl \
#   -tclargs INPUT.sv FRESH_OUTPUT_DIRECTORY synth|route
# Zero external delays make the two variants comparable, not board-qualified.
if {$argc != 3} { error "usage: INPUT.sv FRESH_OUTPUT_DIRECTORY synth|route" }
set input [file normalize [lindex $argv 0]]
set output [file normalize [lindex $argv 1]]
set stage [lindex $argv 2]
if {$stage ni {synth route}} { error "stage must be synth or route" }
if {![file isfile $input] || [file extension $input] ne ".sv"} { error "missing frozen SystemVerilog input" }
if {[file exists $output]} { error "output already exists; preserve prior evidence and choose a fresh directory" }
set part xczu15eg-ffvb1156-2-i
if {[llength [get_parts -quiet $part]] != 1} { error "required exact FPGA part is not installed" }
file mkdir $output
create_project -in_memory -part $part
set_param general.maxThreads 2
read_verilog -sv $input
synth_design -top TileLinkAxi4Bridge -part $part -mode out_of_context -flatten_hierarchy none
create_clock -name bridge_clock -period 10.000 [get_ports clock]
set inputs [get_ports -quiet -filter {DIRECTION == IN && NAME != clock && NAME != reset}]
set outputs [get_ports -quiet -filter {DIRECTION == OUT}]
set_input_delay -clock bridge_clock 0.000 $inputs
set_output_delay -clock bridge_clock 0.000 $outputs

proc record_bridge {directory label} {
    report_utilization -hierarchical -file [file join $directory ${label}_utilization.rpt]
    report_timing_summary -report_unconstrained -file [file join $directory ${label}_timing.rpt]
    report_timing -delay_type max -max_paths 30 -file [file join $directory ${label}_setup_paths.rpt]
    report_timing -delay_type min -max_paths 30 -file [file join $directory ${label}_hold_paths.rpt]
    report_drc -file [file join $directory ${label}_drc.rpt]
    redirect -file [file join $directory ${label}_check_timing.rpt] { check_timing -verbose }
    set fp [open [file join $directory ${label}_ram_primitives.txt] w]
    puts $fp "Primitive and INIT inventory; inference/replication requires review."
    foreach cell [get_cells -hierarchical -filter {IS_PRIMITIVE == 1}] {
        set ref [get_property REF_NAME $cell]
        if {![regexp {^(RAM|URAM|ROM)} $ref]} { continue }
        puts $fp [list cell $cell primitive $ref]
        foreach prop [lsort [list_property $cell]] {
            if {[string match "INIT*" $prop]} {
                puts $fp [list $prop [get_property $prop $cell]]
            }
        }
    }
    close $fp
    write_checkpoint [file join $directory ${label}.dcp]
}
record_bridge $output post_synth
if {$stage eq "route"} {
    opt_design
    place_design
    route_design
    record_bridge $output post_route
}
set note [open [file join $output SCOPE.txt] w]
puts $note "Input: $input"
puts $note "Part: $part; clock 10ns; zero boundary I/O budgets."
puts $note "Tool: [version -short]"
puts $note "Component comparison only. Full SoC CPU100MHz/CDC/RGMII/board timing remains unqualified."
puts $note "No bitstream generated. Inspect RAM replication, setup, hold and unconstrained paths."
close $note
