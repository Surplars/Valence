# Caller must SHA256-verify immutable input before launching this script:
# a4c0da88d92de9762051d0a0abf69965a5ae4163cfb0645080c0587e6b0ae55a
# 79990654 bytes; R38 RX450 + CPU-reset ECO, performance targets 300/250.
# Physical diagnostic only; no bitstream, exception or mode-constraint changes.
if {$argc!=3} {error {Usage: route_tx_reset_placement.tcl input.dcp fresh_output_dir helper.tcl}}
set input [file normalize [lindex $argv 0]]
set out [file normalize [lindex $argv 1]]
set helper [file normalize [lindex $argv 2]]
if {![file isfile $input] || [file size $input]!=79990654 || [file exists $out] || ![file isfile $helper]} {error {Input/helper/size/fresh-directory guard failed}}
if {[version -short] ne "2025.2"} {error {Vivado 2025.2 required}}
file mkdir $out; cd $out
set_param general.maxThreads 2
source $helper
open_checkpoint $input
# Explicitly time both physical corners, before and after. No exceptions added.
proc tx_timing {state prefix} {
    set f [open $prefix.tcllist {WRONLY CREAT EXCL}]; set worst 1e9; set count 0
    set stages [dict get $state stages]; set pairs {}
    for {set i 0} {$i<2} {incr i} {
        lappend pairs [list chain [dict get [lindex $stages $i] C] [dict get [lindex $stages [expr {$i+1}]] D]]
    }
    foreach p [dict get $state endpoints] {lappend pairs [list functional [dict get [lindex $stages 2] C] $p]}
    foreach pair $pairs {
        lassign $pair scope from to
        foreach kind {max min} {
            foreach corner {Slow Fast} {
                set p [get_timing_paths -quiet -from $from -to $to -delay_type $kind -corner $corner -max_paths 1]
                r38_tx_place::need {[llength $p]==1} "missing $scope $kind $corner path to $to"
                set slack [get_property SLACK $p]; set req [get_property REQUIREMENT $p]
                r38_tx_place::need {[string is double -strict $slack] && $slack>-Inf && $slack<Inf && [string is double -strict $req] && $req>-Inf && $req<Inf} "nonfinite path"
                r38_tx_place::need {[get_property STARTPOINT_PIN $p] eq [get_property NAME $from] && [get_property ENDPOINT_PIN $p] eq [get_property NAME $to] && [get_property STARTPOINT_CLOCK $p] eq "valence_tx_raw_div" && [get_property ENDPOINT_CLOCK $p] eq [expr {$scope eq "chain" ? "valence_tx_raw_div" : "valence_tx_quarter_div"}] && [string tolower [string trim [get_property EXCEPTION $p]]] in {{} none}} "wrong/excepted path $to"
                puts $f [list SCOPE $scope TO [get_property NAME $to] KIND $kind CORNER $corner REQUIREMENT $req SLACK $slack]
                if {$scope eq "functional"} {set worst [expr {min($worst,$slack)}]}
                if {$scope eq "chain"} {r38_tx_place::need {$slack>=0} "synchronizer chain timing failed"}
                incr count
            }
        }
    }
    # Mapped ODDRE1 is OSERDESE3. These six RST pins have no native STA path
    # in this exact input. Preserve/log that limitation; never call it a PASS.
    foreach to [dict get $state oserdes] {
        foreach kind {max min} {
            set p [get_timing_paths -quiet -from [dict get [lindex $stages 2] C] -to $to -delay_type $kind -max_paths 1]
            puts $f [list OSERDES_RST [get_property NAME $to] KIND $kind NATIVE_PATH_COUNT [llength $p] QUALIFIED 0]
            r38_tx_place::need {[llength $p]==0} "OSERDES arc scope changed; review required"
        }
    }
    puts $f [list TIMED_PATHS $count FUNCTIONAL_WORST $worst NO_SIGNOFF 1]; close $f
    return $worst
}
set before [r38_tx_place::inspect before]
puts "R38_TX_PRECHECK_BEGIN time_ms=[clock milliseconds]"
tx_timing $before timing-before
# Record all existing exceptions; this script never sources or rewrites them.
write_xdc inherited-before.xdc
set plan [r38_tx_place::apply connectivity]
route_design -preserve
set after [r38_tx_place::inspect after]
r38_tx_place::need {[dict get $plan stable] eq [dict get $after stable]} "route changed protected topology/roots"
set worst [tx_timing $after timing-after]
foreach kind {max min} {
    report_timing -from [dict get [lindex [dict get $after stages] 2] C] -to [dict get $after endpoints] -delay_type $kind -max_paths 13 -nworst 1 -path_type full_clock_expanded -file tx-functional-$kind.rpt
    set pre {}; foreach s [dict get $after stages] {lappend pre [dict get $s PRE]}
    report_timing -to $pre -delay_type $kind -max_paths 3 -nworst 1 -path_type full_clock_expanded -file tx-entry-$kind.rpt
}
report_route_status -file route-status.rpt
report_drc -file drc.rpt
report_timing_summary -delay_type min_max -report_unconstrained -file timing-summary.rpt
report_clocks -file clocks.rpt
write_checkpoint routed-tx-reset-placement-unqualified.dcp
write_xdc inherited-after.xdc
puts "R38_TX_PLACEMENT_UNQUALIFIED functional_worst=$worst time_ms=[clock milliseconds] ENTRY_PRE_STILL_TIMED REQUIRES_FULL_STA_RX_DRC_REVIEW NO_BITSTREAM"
if {$worst<0} {error {TX functional reset still fails; diagnostic checkpoint retained, not qualified}}
