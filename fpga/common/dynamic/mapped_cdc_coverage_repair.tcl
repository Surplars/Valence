# Explicit R40 analysis-only repair. Source common_cdc.tcl first. Never calls
# collect, changes clocks, cuts resets, or relaxes the original 4 ns budget.
# First inspect and review the returned plan against the same routed DCP; then
# pass that exact Tcl value to apply. A changed graph requires a new review.
namespace eval r40_cdc_repair {
    if {![info exists attempted]} {variable attempted 0}
}
proc r40_cdc_repair::need {condition message} {
    if {![uplevel 1 [list expr $condition]]} {error "R40_CDC $message"}
}
proc r40_cdc_repair::finite {value} {
    return [expr {![catch {expr {double($value)>-Inf && double($value)<Inf}} ok] && $ok}]
}
proc r40_cdc_repair::inspect {} {
    need {[llength [info commands ::common_cdc::register_payload]]==1} "source common_cdc.tcl first"
    need {[get_property PART [current_design]] eq "xczu15eg-ffvb1156-2-i" &&
        [get_property TOP [current_design]] eq "soc_top_common_ddr"} "wrong design"
    set fabric [common_cdc::clock fabric_clock/managed_buffer/O]
    set fixed [common_cdc::clock u_ddr/inst/u_ddr4_infrastructure/u_bufg_divClk/O]
    set aon [common_cdc::clock u_clk_wiz/clk_out1]
    need {$fabric eq "fabric_target250" && [llength [lsort -unique [list $fabric $fixed $aon]]]==3} "clock identities changed"
    foreach {clock minimum maximum} [list $fabric 4.0 100.0 $fixed 4.0 4.0 $aon 20.0 20.0] {
        set period [get_property PERIOD [get_clocks -quiet $clock]]
        need {[finite $period] && $period >= $minimum-0.002 && $period <= $maximum+0.002} "clock period outside reviewed range $clock"
    }
    set scopes {}
    set h u_soc/peripherals/rateCmu/bridge
    common_cdc::expect_clock $h/sourceClock $fabric
    common_cdc::expect_clock $h/destinationClock $aon
    common_cdc::same_net $h/commonReset u_soc/commonColdReset
    # Reuse the retained-bit census and exact direct launch-Q -> capture-D proof.
    # Constant capture inputs are proved constants, not silently omitted bits.
    lappend scopes [common_cdc::register_payload $h responseHeld reply {data 64 error 1} $aon $fabric]
    # Also prove the two-stage notification path on which held-data stability
    # relies. The reviewed RTL admits no next request before reply consumption.
    common_cdc::pair $h/responseSync/stages_reg\[0\] $h/responseSync/stages_reg\[1\] $fabric
    need {[common_cdc::drivers $h/responseSync/stages_reg\[0\]/D] eq [list $h/responseToggle_reg/Q]} "response notification bypass"
    common_cdc::ff $h/responseToggle_reg $aon
    # All five DDR write-pointer MSBs were absent from the saved exception lists.
    # Re-prove each entire five-bit Gray bus, including MSB/binary merging and
    # sole stage0->stage1 fanout; never infer the missing bit's driver by name.
    foreach {fifo source destination} [list empty_fifo $fabric $fixed empty_fifo_1 $fabric $fixed \
        empty_fifo_2 $fixed $fabric empty_fifo_3 $fabric $fixed empty_fifo_4 $fixed $fabric] {
        set h u_soc/ddrCrossing/$fifo
        common_cdc::expect_clock $h/sourceClock $source
        common_cdc::expect_clock $h/destinationClock $destination
        common_cdc::same_net $h/commonReset u_soc/commonColdReset
        lappend scopes [common_cdc::gray $h write]
    }
    set normalized {}
    foreach scope $scopes {
        need {[dict get $scope budget]>=3.998 && [llength [dict get $scope starts]]>0 &&
            [llength [dict get $scope starts]]==[llength [dict get $scope ends]]} "invalid scoped census"
        dict set scope budget 4.0
        # Save actual source/capture pairs as well as the existing full-bus scope.
        set pairs {}
        foreach end [dict get $scope ends] {
            set drivers [common_cdc::drivers $end]
            need {[llength $drivers]==1} "ambiguous data driver $end"
            set start [file dirname [lindex $drivers 0]]/C
            need {$start in [dict get $scope starts]} "unowned data driver $end"
            lappend pairs [list $start $end]
        }
        dict set scope pairs [lsort $pairs]
        lappend normalized $scope
    }
    return $normalized
}
proc r40_cdc_repair::timing {plan phase bounded} {
    set evidence {}
    foreach scope $plan {
        foreach pair [dict get $scope pairs] {
            lassign $pair start end
            set paths [get_timing_paths -quiet -from [common_cdc::one get_pins $start] \
                -to [common_cdc::one get_pins $end] -delay_type max -max_paths 1]
            need {[llength $paths]==1} "missing max path $start -> $end"
            set req [get_property REQUIREMENT $paths]; set slack [get_property SLACK $paths]
            set exception [string tolower [get_property EXCEPTION $paths]]
            need {[finite $req] && [finite $slack]} "nonfinite path $end"
            need {[get_property STARTPOINT_PIN $paths] eq $start && [get_property ENDPOINT_PIN $paths] eq $end} "wrong path identity $end"
            if {$bounded} {
                need {$req>0 && $req<=4.001 && [string match maxdelay* $exception]} "missing/relaxed datapath bound $end"
                need {$slack>=0} "real bounded data failure $end slack=$slack"
            }
            lappend evidence [list $start $end $req $slack $exception]
            puts [list R40_CDC_PATH phase=$phase from=$start to=$end requirement=$req slack=$slack exception=$exception]
        }
    }
    return $evidence
}
proc r40_cdc_repair::apply {reviewedPlan} {
    variable attempted
    need {!$attempted} "one-shot: reopen original DCP after any mutation attempt"
    set plan [inspect]
    need {$plan eq $reviewedPlan} "mapped census differs from independently reviewed plan"
    set before [timing $plan before 0]
    # Mark before the first constraint mutation; re-source cannot reset this.
    set attempted 1
    foreach scope $plan {
        set starts [common_cdc::objects get_pins [dict get $scope starts]]
        set ends [common_cdc::objects get_pins [dict get $scope ends]]
        set_max_delay -datapath_only 4.0 -from $starts -to $ends
        set_bus_skew 4.0 -from $starts -to $ends
    }
    update_timing
    need {[inspect] eq $plan} "mapped graph changed during constraint repair"
    set after [timing $plan after 1]
    puts "R40_CDC_COVERAGE_REPAIRED scopes=6 BUDGET_NS=4 NO_FALSE_PATH NO_CLOCK_CHANGE NOT_SIGNOFF"
    return [dict create plan $plan before $before after $after]
}
