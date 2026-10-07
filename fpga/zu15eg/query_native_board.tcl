if {$argc != 2} {error "Expected SYNTH_DCP FRESH_REPORT_DIR"}
lassign $argv dcp out
file mkdir $out
set_param general.maxThreads 8
open_checkpoint $dcp
report_utilization -hierarchical -file [file join $out utilization.rpt]
report_clocks -file [file join $out clocks.rpt]
report_io -file [file join $out io.rpt]
foreach release [get_cells -quiet -hier -filter {REF_NAME =~ CdcResetRelease*}] {
    set stages [get_cells -quiet "$release/stages_reg*"]
    puts "RESET_TOPOLOGY $release stages=[llength $stages] $stages"
    if {[llength $stages] != 3} {
        set children [get_cells -hier -filter "NAME =~ $release/* && IS_PRIMITIVE == 1"]
        foreach cell $children {puts "RESET_CHILD $cell [get_property REF_NAME $cell]"}
        set outpins [get_pins -of_objects $release -filter {DIRECTION == OUT}]
        foreach pin $outpins {puts "RESET_DRIVERS $pin [all_fanin -flat -startpoints_only -to $pin]"}
    }
}
puts "FUNCTIONAL_BLACKBOXES [get_cells -quiet -hier -filter {IS_BLACKBOX}]"
close_design
