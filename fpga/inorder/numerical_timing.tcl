# Synchronous module budgets use the caller's REAL clock. No generated clocks,
# false paths, multicycle exceptions, or unconstrained internal paths are added.
proc valence_i1_numerical_registers {clock root} {
    set registers [all_registers -clock $clock]
    if {$root ne ""} { set registers [filter $registers "NAME =~ ${root}*"] }
    if {[llength $registers] == 0} { error "no clocked registers under numerical module '$root'" }
    return $registers
}

proc valence_i1_apply_numerical_budgets {clock root output} {
    if {[llength [get_clocks -quiet $clock]] != 1} { error "one explicit real numerical clock required" }
    set period [get_property PERIOD [get_clocks $clock]]
    set registers [valence_i1_numerical_registers $clock $root]
    set budget [expr {$period - 0.333}]
    if {$budget <= 0.0} { error "clock period too short for the documented budget reserve" }
    set ledger [open [file join $output module_budget_coverage.csv] w]
    puts $ledger "group,endpoint_registers,max_delay_ns"
    foreach {name patterns} {
        divide_feedback {*quotient_reg* *remainder_reg*}
        numerical_result {*result_reg*}
        numerical_control {*state_reg* *count_reg*}
    } {
        set endpoints {}
        foreach pattern $patterns {
            set endpoints [concat $endpoints [filter $registers "NAME =~ ${root}${pattern}"]]
        }
        set endpoints [lsort -unique $endpoints]
        if {[llength $endpoints] == 0} { error "missing required module timing partition: $name" }
        # A stricter datapath deadline, not a relaxation of the clock/hold contract.
        # Leave normal clock propagation/uncertainty active (no -datapath_only).
        set_max_delay $budget -from $registers -to $endpoints
        group_path -name i1_$name -from $registers -to $endpoints
        puts $ledger "$name,[llength $endpoints],$budget"
    }
    close $ledger
    report_clocks -file [file join $output clocks.rpt]
    report_exceptions -file [file join $output module_exceptions.rpt]
}

proc valence_i1_report_numerical_partitions {clock root output phase} {
    set registers [valence_i1_numerical_registers $clock $root]
    foreach {name patterns} {
        divide_feedback {*quotient_reg* *remainder_reg*}
        numerical_result {*result_reg*}
        numerical_control {*state_reg* *count_reg*}
    } {
        set endpoints {}
        foreach pattern $patterns {
            set endpoints [concat $endpoints [filter $registers "NAME =~ ${root}${pattern}"]]
        }
        set endpoints [lsort -unique $endpoints]
        if {[llength $endpoints] == 0} { error "missing report partition: $name" }
        report_timing -from $registers -to $endpoints -delay_type max -max_paths 10 -nworst 1 \
            -file [file join $output ${phase}_${name}_setup.rpt]
        report_timing -from $registers -to $endpoints -delay_type min -max_paths 10 -nworst 1 \
            -file [file join $output ${phase}_${name}_hold.rpt]
    }
}
