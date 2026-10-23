# Native implementation only. No frozen-run admission, collect, seal, or bitstream.
proc native_constraints {phase} {
    global native
    foreach entry $native($phase) {
        lassign $entry kind path
        if {$kind eq "xdc"} {read_xdc $path} else {source $path}
    }
}
proc native_identity {} {
    global native
    if {[get_property PART [current_design]] ne $native(part) || [get_property TOP [current_design]] ne $native(top)} {
        error "Checkpoint part/TOP mismatch"
    }
}
proc native_clocks {} {
    global native
    foreach requirement $native(clock_requirements) {
        lassign $requirement name period
        set pins [get_pins -quiet $name]
        if {[llength $pins]!=1} {error "Missing or ambiguous required clock pin $name"}
        set clocks [get_clocks -quiet -of_objects $pins]
        if {[llength $clocks]!=1} {error "Missing or ambiguous required clock at $name"}
        set actual [get_property PERIOD $clocks]
        if {![string is double -strict $actual] || abs($actual-$period)>0.002} {
            error "Required timing period changed at $name: $actual, expected $period"
        }
    }
}
proc native_main {} {
    global argv native
    if {[llength $argv]!=1} {error "Use native_diagnostic.py run MANIFEST FRESH_OUTPUT"}
    # Remove commands, do not keep a callable renamed bitstream alias.
    foreach command {write_bitstream write_device_image} {
        if {[llength [info commands $command]]} {rename $command {}}
        proc ::$command {args} {error "DIAGNOSTIC_UNQUALIFIED_NO_BITSTREAM"}
    }
    source [lindex $argv 0]
    if {[version -short] ne $native(vivado_version)} {error "Vivado version differs from input manifest"}
    set_param general.maxThreads $native(threads)
    if {[get_param general.maxThreads]<$native(threads)} {error "Thread setting not honored"}
    puts "DIAGNOSTIC_UNQUALIFIED_NO_BITSTREAM requested_threads=$native(threads) active_workers=UNMEASURED"
    set stage $native(stage)
    if {$stage eq "fresh"} {
        create_project -in_memory -part $native(part)
        set_property XPM_LIBRARIES {XPM_MEMORY} [current_project]
        foreach ip $native(ips) {read_ip [lindex $ip 0]}
        # read_ip imports generated products in-memory. Check actual registered
        # DCP paths, not a copied project's stale STATUS/NEEDS_REFRESH properties.
        set registered {}
        foreach file [get_files -all -quiet -filter {FILE_TYPE == "Design Checkpoint"}] {
            lappend registered [file normalize [get_property NAME $file]]
        }
        foreach ip $native(ips) {
            if {[lsearch -exact $registered [file normalize [lindex $ip 1]]]<0} {
                error "Expected existing IP DCP was not registered by read_ip: [lindex $ip 1]"
            }
        }
        set_property verilog_define $native(defines) [current_fileset]
        set_property include_dirs $native(include_dirs) [current_fileset]
        foreach path $native(rtl) {read_verilog -sv $path}
        foreach path $native(pre_synth_xdc) {read_xdc $path}
        foreach path $native(late_synth_xdc) {
            read_xdc $path
            set_property PROCESSING_ORDER LATE [get_files $path]
        }
        synth_design -top $native(top) -part $native(part) -flatten_hierarchy none
        write_checkpoint raw-unqualified.dcp
        set stage raw
    } else {
        open_checkpoint $native(checkpoint)
    }
    native_identity
    if {$stage eq "raw"} {
        native_constraints post_synth
        native_clocks
        write_checkpoint synthesized-unqualified.dcp
        set stage synthesized
    }
    if {$stage eq "synthesized"} {
        native_clocks
        opt_design
        write_checkpoint optimized-raw-unqualified.dcp
        set stage optimized-raw
    }
    if {$stage eq "optimized-raw"} {
        native_constraints post_opt
        native_clocks
        write_checkpoint optimized-unqualified.dcp
        set stage optimized
    }
    if {$stage eq "optimized"} {
        native_constraints preplace
        native_clocks
        place_design
        write_checkpoint placed-unqualified.dcp
        set stage placed
    }
    if {$stage eq "placed" && $native(phys_opt)} {
        native_clocks
        phys_opt_design
        write_checkpoint physical-unqualified.dcp
        set stage physical
    }
    if {$stage in {placed physical}} {
        native_constraints pre_route
        native_clocks
        route_design
        write_checkpoint routed-unqualified.dcp
        set stage routed
    } elseif {$stage eq "routed"} {
        # Report-only resume, never resynthesize or reroute.
        write_checkpoint routed-unqualified.dcp
    }
    if {$stage ne "routed"} {error "Unknown or incomplete native stage $stage"}
    native_clocks
    report_timing_summary -delay_type min_max -report_unconstrained -file timing.rpt
    check_timing -verbose -file coverage.rpt
    report_clocks -file clocks.rpt
    report_route_status -file route.rpt
    report_drc -file drc.rpt
    report_cdc -details -file cdc.rpt
    report_bus_skew -file bus-skew.rpt
    report_utilization -file utilization.rpt
    set f [open native-complete.txt {WRONLY CREAT EXCL}]
    puts $f "DIAGNOSTIC_UNQUALIFIED_NO_BITSTREAM; commands returned, not timing/DRC/CDC/functional acceptance"
    close $f
}
if {[catch {native_main} reason options]} {
    puts stderr "$reason\n[dict get $options -errorinfo]"
    exit 1
}
exit 0
