# Read-only retention evidence from an already-open, exact failed checkpoint.
# This does not re-collect CDC topology, apply constraints, or run timing analysis.
# The caller must bind the checkpoint, producer/log, and original skew JSON before
# comparing every original scope against these rows. Scalar CDC scopes absent
# from that JSON remain exact-DCP/source-provenance-bound, not topology re-proven.
# AMD UG835 2023.2 documents both export options used below:
# https://docs.amd.com/r/2023.2-English/ug835-vivado-tcl-commands/write_xdc
namespace eval post_synth_tail_constraints {
    variable selectors {}
    variable rows {}
}

# These are literal names emitted by native write_xdc, not a live object query.
# Only explicit object lists are supported. Never broaden an unfamiliar selector
# into a glob, hierarchy/filter query, or custom netlist traversal.
proc post_synth_tail_constraints::objects {type args} {
    variable selectors
    if {[llength $args] == 2 && [lindex $args 0] eq {-quiet}} {
        set args [lrange $args 1 end]
    }
    if {[llength $args] != 1 || [string match -* [lindex $args 0]]} {
        error "TAIL_RETAINED unsupported $type selector"
    }
    set names [lindex $args 0]
    if {![llength $names]} {error "TAIL_RETAINED empty $type selector"}
    foreach name $names {
        # Numeric bus subscripts are exact Vivado names, not wildcard ranges.
        regsub -all {\[[0-9]+\]} $name {} plain
        if {$name eq {} || ($type eq {pin} && [string first / $name] < 1) ||
            [regexp {[\x00-\x1f\x7f*?\\\[\]]} $plain]} {
            error "TAIL_RETAINED nonliteral $type selector: $name"
        }
    }
    if {[llength [lsort -unique $names]] != [llength $names]} {
        error "TAIL_RETAINED duplicate $type names"
    }
    set token __tail_objects_[dict size $selectors]
    dict set selectors $token [dict create type $type names [lsort $names]]
    return $token
}

# This alias only records data. It never calls a live set_* command.
proc post_synth_tail_constraints::capture {kind args} {
    variable selectors; variable rows
    set options {}; set budget {}; set datapath 0
    for {set i 0} {$i < [llength $args]} {incr i} {
        set word [lindex $args $i]
        if {$word in {-from -to}} {
            if {[dict exists $options $word] || $i + 1 >= [llength $args]} {
                error "TAIL_RETAINED missing/duplicate $word"
            }
            dict set options $word [lindex $args [incr i]]
        } elseif {$word eq {-datapath_only} && $kind eq {max_delay} && !$datapath} {
            set datapath 1
        } elseif {$budget eq {} &&
                  [regexp {^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?$} $word] &&
                  [string is double -strict $word] && $word > 0 && $word < Inf} {
            # Preserve the native decimal budget without a floating-point rewrite.
            set budget $word
        } else {
            error "TAIL_RETAINED unsupported $kind argument: $word"
        }
    }
    if {$budget eq {} || [dict size $options] != 2 || [dict size $selectors] != 2} {
        error "TAIL_RETAINED incomplete $kind row"
    }
    set from [dict get $options -from]; set to [dict get $options -to]
    if {$from eq $to || ![dict exists $selectors $from] || ![dict exists $selectors $to]} {
        error "TAIL_RETAINED endpoints must be two explicit object selectors"
    }
    lappend rows [dict create kind $kind budget_ns $budget \
        from [dict get $selectors $from names] to [dict get $selectors $to names] \
        from_type [dict get $selectors $from type] to_type [dict get $selectors $to type] \
        datapath_only $datapath]
    return {}
}

proc post_synth_tail_constraints::read_rows {path} {
    variable selectors; variable rows
    set rows {}; set selectors {}
    set child [interp create -safe]
    # Even Tcl's safe interpreter has control-flow and mutation commands we do
    # not need. Hide everything except data-only list construction. No unknown,
    # eval, source, set, interp, exec, file, live setters, or design queries.
    foreach command [interp eval $child {info commands}] {
        if {$command ni {list concat}} {interp hide $child $command}
    }
    foreach {command type} {get_pins pin get_ports port get_clocks clock get_cells cell get_nets net} {
        interp alias $child $command {} post_synth_tail_constraints::objects $type
    }
    interp alias $child set_bus_skew {} post_synth_tail_constraints::capture bus_skew
    interp alias $child set_max_delay {} post_synth_tail_constraints::capture max_delay
    set handle [open $path r]
    try {
        set pending {}; set line_number 0; set start 1
        while {[gets $handle line] >= 0} {
            incr line_number
            if {$pending eq {}} {set start $line_number}
            append pending $line \n
            if {![info complete $pending]} {continue}
            set statement [string trimleft $pending]
            if {[regexp {^(?:::)?current_(instance|scope)(?:\s|;|$)} $statement]} {
                error "TAIL_RETAINED unsupported scope context at line $start"
            }
            if {[regexp {^(?:::)?set_(bus_skew|max_delay)(?:\s|$)} $statement]} {
                set selectors {}; set before [llength $rows]
                if {[catch {interp eval $child $statement} detail]} {
                    error "TAIL_RETAINED unsupported selected statement at line $start: $detail"
                }
                if {[llength $rows] != $before + 1} {
                    error "TAIL_RETAINED expected one selected command at line $start"
                }
            }
            # All other complete statements, including comments, are not run.
            set pending {}
        }
        if {$pending ne {}} {error "TAIL_RETAINED incomplete XDC statement at line $start"}
        if {![llength $rows]} {error "TAIL_RETAINED no selected constraints exported"}
        return $rows
    } finally {
        close $handle
        interp delete $child
    }
}

proc post_synth_tail_constraints::json_string {value} {
    return \"[string map [list \\ \\\\ \" \\\" \n \\n \r \\r \t \\t] $value]\"
}

proc post_synth_tail_constraints::write_rows {path data} {
    set encoded {}
    foreach row $data {
        set from {}; foreach name [dict get $row from] {lappend from [json_string $name]}
        set to {}; foreach name [dict get $row to] {lappend to [json_string $name]}
        lappend encoded [format {{"kind":"%s","budget_ns":%s,"from":[%s],"to":[%s],"from_type":"%s","to_type":"%s","datapath_only":%s}} \
            [dict get $row kind] [dict get $row budget_ns] [join $from ,] [join $to ,] \
            [dict get $row from_type] [dict get $row to_type] \
            [expr {[dict get $row datapath_only] ? {true} : {false}}]]
    }
    set handle [open $path {WRONLY CREAT EXCL}]
    try {
        puts $handle [format {{"schema_version":1,"rows":[%s]}} [join $encoded ,]]
    } finally {close $handle}
}

# Source defines this entry point but performs no export or design operation.
# Fresh output paths prevent accidentally accepting stale or partial evidence.
proc post_synth_tail_retained_constraints {} {
    set xdc [file join [pwd] tail-retained.xdc]
    set json [file join [pwd] tail-retained-constraints.json]
    if {[file exists $xdc] || [file exists $json]} {
        error "TAIL_RETAINED outputs already exist; use a fresh stage directory"
    }
    write_xdc -constraints valid -type timing $xdc
    set rows [post_synth_tail_constraints::read_rows $xdc]
    post_synth_tail_constraints::write_rows $json $rows
    return $json
}
