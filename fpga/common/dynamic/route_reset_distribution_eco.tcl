# Explicit diagnostic ECO only. Caller must verify immutable input SHA256:
# 126b300ed91b1aa9d5343104bfbc6bcd4a2fffea483d1b68b2cac04f0958acf2
# RX450 routed checkpoint, 79603054 bytes. No bit or timing signoff.
if {$argc != 3} {error {Usage: route-reset-eco.tcl RX450_input.dcp fresh_output_dir reset_distribution_eco.tcl}}
set input [file normalize [lindex $argv 0]]
set out [file normalize [lindex $argv 1]]
set helper [file normalize [lindex $argv 2]]
if {![file isfile $input] || [file size $input]!=79603054 || [file exists $out] || ![file isfile $helper]} {error {Input/helper missing, wrong size, or output not fresh}}
if {[version -short] ne "2025.2"} {error {Vivado 2025.2 required}}
file mkdir $out
cd $out
set_param general.maxThreads 2
source $helper
open_checkpoint $input
# Preserve the ten RX450 delay cells as well as all reset FF identities.
set rx {}
for {set i 0} {$i<5} {incr i} {
    foreach suffix {input_delay extra_delay.output_delay} {
        set name [format {u_rgmii/receive[%d].%s} $i $suffix]
        set c [r38_reset_eco::one [get_cells -quiet -hierarchical -filter [format {NAME == "%s"} $name]] "missing RX450 $name"]
        set attrs {}
        foreach key {REF_NAME LOC BEL DELAY_VALUE DELAY_FORMAT DELAY_TYPE CASCADE REFCLK_FREQUENCY IODELAY_GROUP} {dict set attrs $key [get_property $key $c]}
        r38_reset_eco::require {[dict get $attrs DELAY_VALUE]==450 && [dict get $attrs DELAY_FORMAT] eq "TIME" && [dict get $attrs DELAY_TYPE] eq "FIXED"} "not RX450 input"
        dict set rx $name $attrs
    }
}
set initialRx $rx
puts "R38_RESET_ECO_BEGIN time_ms=[clock milliseconds]"
set plan [r38_reset_eco::apply [file join $out connectivity]]
# Reconnects invalidate only affected routing. Preserve all remaining routes;
# do not unroute global GND, clock trees or unrelated reset consumers.
route_design -preserve
set routed [r38_reset_eco::inspect after]
r38_reset_eco::same_stable [dict get $plan stable] [dict get $routed stable]
dict for {name attrs} $initialRx {
    set c [r38_reset_eco::one [get_cells -quiet -hierarchical -filter [format {NAME == "%s"} $name]] "missing RX cell after route"]
    dict for {key value} $attrs {r38_reset_eco::require {[get_property $key $c] eq $value} "route changed RX450 $name/$key"}
}
set f [open reset-timing.txt {WRONLY CREAT EXCL}]
set worst 1e9
foreach pre [dict get $routed prepins] {
    foreach kind {max min} {
        set paths [get_timing_paths -quiet -from [dict get $routed launch] -to $pre -delay_type $kind -max_paths 1]
        r38_reset_eco::require {[llength $paths]==1} "missing local PRE $pre $kind"
        set slack [get_property SLACK $paths]; set req [get_property REQUIREMENT $paths]
        set expected [expr {$kind eq "max" ? 3.333333333333 : 0.0}]
        r38_reset_eco::require {[string is double -strict $slack] && $slack > -Inf && $slack < Inf &&
            [string is double -strict $req] && abs($req-$expected)<0.002} "nonfinite/wrong local PRE timing"
        r38_reset_eco::require {[get_property STARTPOINT_PIN $paths] eq [get_property NAME [dict get $routed launch]] &&
            [get_property ENDPOINT_PIN $paths] eq [get_property NAME $pre] &&
            [get_property STARTPOINT_CLOCK $paths] eq "cpu_target300" && [get_property ENDPOINT_CLOCK $paths] eq "cpu_target300" &&
            [string tolower [string trim [get_property EXCEPTION $paths]]] in {{} none}} "excepted/wrong local PRE path"
        puts $f [list ENDPOINT [get_property NAME $pre] KIND $kind REQUIREMENT $req SLACK $slack]
        set worst [expr {min($worst,$slack)}]
    }
}
puts $f [list EXACT_LOCAL_PRE 41 MINIMUM_SLACK $worst NO_SIGNOFF 1]; close $f
set qloads {}
dict for {cell state} [dict get $routed stable] {
    if {[dict exists $state loads]} {set qloads [concat $qloads [dict get $state loads]]}
}
# Names are exact existing leaf pins; passing patterns with brackets is avoided.
set qobjects [get_pins -quiet -of_objects [get_nets -quiet -segments -of_objects \
    [get_pins -quiet -of_objects [get_cells -quiet -hierarchical -filter {NAME =~ u_soc/cpuFunctionalReset_cpuResetDistribution/distributed_reg*}] -filter {REF_PIN_NAME == Q}]] -leaf -filter {DIRECTION == IN}]
r38_reset_eco::require {[r38_reset_eco::names $qobjects] eq [lsort $qloads]} "functional reset endpoint census changed"
foreach kind {max min} {
    report_timing -from [dict get $routed launch] -to [dict get $routed prepins] -delay_type $kind -max_paths 41 -nworst 1 -path_type full_clock_expanded -file local-PRE-$kind.rpt
    report_timing -from [dict get $routed cpins] -to $qobjects -delay_type $kind -max_paths 50 -nworst 1 -path_type full_clock_expanded -file functional-reset-$kind.rpt
}
report_route_status -file route-status.rpt
report_drc -file drc.rpt
report_timing_summary -delay_type min_max -report_unconstrained -file timing-summary.rpt
report_clocks -file clocks.rpt
# All constraints are inherited unchanged. Preserve failures for analysis using
# an explicitly UNQUALIFIED name; never rename this as a checked/signoff DCP.
write_checkpoint routed-reset-unqualified.dcp
write_xdc retained-reset.xdc
puts "R38_RESET_ECO_ROUTED_UNQUALIFIED local_PRE_worst=$worst time_ms=[clock milliseconds] REQUIRES_FULL_STA_DRC_RX_REVIEW NO_BITSTREAM"
if {$worst<0} {error {Local distribution PRE timing failed; unqualified checkpoint retained for diagnosis}}
