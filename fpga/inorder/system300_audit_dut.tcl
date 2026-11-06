set_param general.maxThreads 8
set root [file dirname [info script]]
set output [file join $root audit-dut]
if {[file exists $output]} {error "fresh audit output required"}
file mkdir $output
open_checkpoint [file join $root impl routed.dcp]
set fd [open [file join $output internal_result.tsv] w]
puts $fd "domain\tsetup_ns\thold_ns\tnegative_setup_endpoints\tnegative_hold_endpoints"
foreach {name clk} {cpu i1_cpu300 vpu i1_vpu300 system i1_system300} {
    # Exclude only the top-level port-capture fixture; keep DUT registers and clock backend.
    set cells [filter [all_registers -clock $clk] {NAME =~ unit/* || NAME =~ cpuGate/* || NAME =~ vpuGate/*}]
    if {![llength $cells]} {error "missing DUT registers: $name"}
    set row [list $name]
    set counts {}
    foreach type {max min} {
        set worst [get_timing_paths -from $cells -to $cells -delay_type $type -max_paths 1]
        if {![llength $worst]} {error "missing DUT timing: $name $type"}
        lappend row [get_property SLACK $worst]
        report_timing -from $cells -to $cells -delay_type $type -max_paths 50 -nworst 1 -file [file join $output ${name}_${type}.rpt]
        set paths [get_timing_paths -from $cells -to $cells -delay_type $type -slack_lesser_than 0 -max_paths 100000 -nworst 1]
        if {[llength $paths] >= 100000} {error "endpoint limit reached"}
        lappend counts [llength $paths]
        set pf [open [file join $output ${name}_${type}_endpoints.tsv] w]
        puts $pf "start\tend\tslack_ns\tlogic_levels"
        foreach path $paths {puts $pf "[get_property STARTPOINT_PIN $path]\t[get_property ENDPOINT_PIN $path]\t[get_property SLACK $path]\t[get_property LOGIC_LEVELS $path]"}
        close $pf
    }
    puts $fd [join [concat $row $counts] "\t"]
}
close $fd
puts "SYSTEM_DUT_NEGATIVE_ENDPOINT_AUDIT_DONE"
close_design
