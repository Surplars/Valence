# Report both sides of the opt-in replay register; NOT a routed Fmax result.
if {$argc != 2} {error "Expected STAGED_SOC_BLACKBOX_DCP OUT_DIR"}
lassign $argv candidate out
file mkdir $out
set_param general.maxThreads 8
open_checkpoint $candidate
set checked [get_pins -of_objects [get_cells -hier -filter {NAME =~ *backend/orderCheckBeat_reg*}] \
    -filter {REF_PIN_NAME == Q}]
set stage [get_cells -hier -filter {NAME =~ *backend/replayPending*_reg*}]
set stage_inputs [get_pins -of_objects $stage -filter {REF_PIN_NAME == D || REF_PIN_NAME == CE}]
set stage_outputs [get_pins -of_objects $stage -filter {REF_PIN_NAME == Q}]
set pc [get_pins -of_objects [get_cells -hier -filter {NAME =~ platform/core/core/core/pc_reg*}] \
    -filter {REF_PIN_NAME == D}]
foreach pins {checked stage_inputs stage_outputs pc} {
    if {![llength [set $pins]]} {error "Missing pipeline boundary: $pins"}
}
set bypass [get_timing_paths -quiet -from $checked -to $pc -max_paths 1]
if {[llength $bypass]} {error "Replay stage has a combinational orderCheckBeat->PC bypass"}
foreach kind {overlap_to_stage stage_to_pc} {
    set sources [expr {$kind eq "overlap_to_stage" ? $checked : $stage_outputs}]
    set targets [expr {$kind eq "overlap_to_stage" ? $stage_inputs : $pc}]
    report_timing -from $sources -to $targets -max_paths 20 -delay_type max \
        -file [file join $out ${kind}.rpt]
    set paths [get_timing_paths -from $sources -to $targets -max_paths 1 -delay_type max]
    if {[llength $paths] != 1} {error "Missing pipeline leg: $kind"}
    puts "REPLAY_STAGE: $kind delay=[get_property DATAPATH_DELAY $paths] slack=[get_property SLACK $paths]"
}
close_design
