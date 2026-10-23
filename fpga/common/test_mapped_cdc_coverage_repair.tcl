# Orchestration tests only. Existing common_cdc structural proofs are reused;
# mapped topology and native exception effectiveness require actual DCP evidence.
source [file join [file dirname [info script]] dynamic mapped_cdc_coverage_repair.tcl]
rename r40_cdc_repair::inspect r40_cdc_repair::actual_inspect
namespace eval common_cdc {}
proc common_cdc::one {command name} {return $name}
proc common_cdc::objects {command names} {return $names}
set fixture [list [dict create label test starts {launch/C} ends {capture/D} pairs {{launch/C capture/D}} budget 4.0 skew 1]]
proc r40_cdc_repair::inspect {} {
    if {$::fault eq "census"} {error "unreviewed mapped graph"}
    if {$::fault eq "drift" && $::writes} {return {changed}}
    return $::fixture
}
proc get_timing_paths args {
    if {$::fault eq "missing" || ($::fault eq "post_missing" && $::writes)} {return {}}
    return path
}
proc get_property {key object} {
    switch $key {
        STARTPOINT_PIN {return launch/C}
        ENDPOINT_PIN {return [expr {$::fault eq "wrong_endpoint" ? "other/D" : "capture/D"}]}
        REQUIREMENT {return [expr {$::fault eq "relaxed" && $::writes ? 5.0 : ($::writes ? 4.0 : 0.129)}]}
        SLACK {
            if {$::fault eq "infinite"} {return Inf}
            if {$::fault eq "nan"} {return NaN}
            return [expr {$::writes && $::fault ne "negative" ? 0.25 : -2.6}]
        }
        EXCEPTION {return [expr {$::writes && $::fault ne "no_exception" ? "MaxDelay Datapath Only" : ""}]}
    }
    error "unexpected property $key"
}
proc set_max_delay args {
    if {$args ne {-datapath_only 4.0 -from launch/C -to capture/D}} {error "changed bound"}
    incr ::writes
}
proc set_bus_skew args {
    if {$args ne {4.0 -from launch/C -to capture/D}} {error "changed skew"}
    incr ::skews
}
proc update_timing {} {}
proc assert {expression message} {if {![uplevel 1 [list expr $expression]]} {error $message}}
foreach bad {Inf -Inf NaN {} bad} {assert {![r40_cdc_repair::finite $bad]} "accepted $bad"}
foreach good {0 -2.6 4.0} {assert {[r40_cdc_repair::finite $good]} "rejected $good"}
set negative 0
foreach fault {census missing wrong_endpoint infinite nan mismatch relaxed negative no_exception post_missing drift} {
    set writes 0; set skews 0; set ::r40_cdc_repair::attempted 0
    set reviewed [expr {$fault eq "mismatch" ? "other" : $fixture}]
    assert {[catch {r40_cdc_repair::apply $reviewed} reason]} "accepted $fault"
    if {$fault in {census missing wrong_endpoint infinite nan mismatch}} {
        assert {$writes==0 && $skews==0} "premature mutation $fault"
    } else {
        assert {$writes==1 && $skews==1} "unexpected mutation count $fault"
        # Restore procedure definition without permitting attempted to reset.
        set state $::r40_cdc_repair::attempted
        source [file join [file dirname [info script]] dynamic mapped_cdc_coverage_repair.tcl]
        assert {$::r40_cdc_repair::attempted==$state} "re-source cleared one-shot"
        assert {[catch {r40_cdc_repair::apply $fixture} why] && [string match *one-shot* $why]} "postfailure retry allowed"
        rename r40_cdc_repair::inspect {}
        proc r40_cdc_repair::inspect {} {
            if {$::fault eq "census"} {error "unreviewed mapped graph"}
            if {$::fault eq "drift" && $::writes} {return {changed}}
            return $::fixture
        }
    }
    incr negative
}
set fault {}; set writes 0; set skews 0; set ::r40_cdc_repair::attempted 0
r40_cdc_repair::apply $fixture
assert {$writes==1 && $skews==1} {positive did not apply both exact bounds}
puts "R40_CDC_REPAIR_CONTROL_PASS positive=1 negative=$negative MOCK_ONLY_NATIVE_PENDING"
