# Read-only detail reports on the currently open design. Shared by new routing
# and cached-checkpoint analysis; no synthesis, timing exceptions or I/O changes.
proc valence_module_path_details {out} {
    file mkdir $out
    set registers [all_registers -cells]
    report_timing -from $registers -to $registers -delay_type max -max_paths 20 \
        -file [file join $out internal_setup_paths.rpt]
    report_timing -from $registers -to $registers -delay_type min -max_paths 10 \
        -file [file join $out internal_hold_paths.rpt]
    set table [open [file join $out path_metrics.tsv] w]
    puts $table "scope\tdelay_type\tslack_ns\tdata_delay_ns\tlogic_levels\tstartpoint\tendpoint"
    foreach type {max min} {
        foreach scope {all internal} {
            if {$scope eq "internal"} {
                set paths [get_timing_paths -from $registers -to $registers -delay_type $type -max_paths 1]
            } else {
                set paths [get_timing_paths -delay_type $type -max_paths 1]
            }
            foreach path $paths {
                puts $table "$scope\t$type\t[get_property SLACK $path]\t[get_property DATAPATH_DELAY $path]\t[get_property LOGIC_LEVELS $path]\t[get_property STARTPOINT_PIN $path]\t[get_property ENDPOINT_PIN $path]"
            }
        }
    }
    close $table
}
