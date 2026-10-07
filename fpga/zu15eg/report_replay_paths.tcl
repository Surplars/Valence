# Compare the actual SoC replay->PC cone in preserved OOC synthesis checkpoints.
# No placement/routing and no full-board Fmax claim.
if {$argc != 3} {error "Expected BASELINE_SOC_BLACKBOX_DCP CANDIDATE_SOC_BLACKBOX_DCP OUTPUT_DIR"}
lassign $argv baseline candidate out
file mkdir $out
set_param general.maxThreads 8
foreach kind {baseline candidate} {
    open_checkpoint [set $kind]
    set sources [get_pins -of_objects [get_cells -hier -filter {NAME =~ *backend/orderCheckBeat_reg*}] \
        -filter {REF_PIN_NAME == Q}]
    set targets [get_pins -of_objects [get_cells -hier -filter {NAME =~ platform/core/core/core/pc_reg*}] \
        -filter {REF_PIN_NAME == D}]
    if {![llength $sources] || ![llength $targets]} {error "Missing replay/PC cone"}
    report_timing -from $sources -to $targets -max_paths 20 -delay_type max \
        -file [file join $out ${kind}_replay_pc.rpt]
    set paths [get_timing_paths -from $sources -to $targets -max_paths 1 -delay_type max]
    if {[llength $paths] != 1} {error "Missing timed replay/PC path"}
    puts "REPLAY_COMPARE: $kind delay=[get_property DATAPATH_DELAY $paths] slack=[get_property SLACK $paths]"
    close_design
}
