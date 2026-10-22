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
    variable scope {}
    variable mode {}
    variable scope_changes 0
    variable unsupported {}
    variable selected_counts {}
}

# UG835 current_instance paths are relative to the current instance. An omitted
# argument resets to the design top; this data-only alias never changes Vivado.
proc post_synth_tail_constraints::instance {args} {
    variable scope; variable mode; variable scope_changes
    if {$mode ne {scope}} {error "TAIL_RETAINED scope change inside constraint"}
    if {[llength $args] && [lindex $args 0] eq {-quiet}} {set args [lrange $args 1 end]}
    if {![llength $args]} {set scope {}} elseif {[llength $args] == 1} {
        set path [lindex $args 0]
        regsub -all {\[[0-9]+\]} $path {} plain
        if {$path eq {} || [string match -* $path] || [string index $path 0] eq {/} ||
            [regexp {[\x00-\x20\x7f*?\\\[\]]} $plain]} {
            error "TAIL_RETAINED unsupported current_instance path: $path"
        }
        set parts [expr {$scope eq {} ? {} : [split $scope /]}]
        foreach part [split $path /] {
            if {$part eq {}} {error "TAIL_RETAINED empty instance path component"}
            if {$part eq {.}} {continue}
            if {$part eq {..}} {
                if {![llength $parts]} {error "TAIL_RETAINED instance path above design top"}
                set parts [lrange $parts 0 end-1]
            } else {lappend parts $part}
        }
        set scope [join $parts /]
    } else {error "TAIL_RETAINED unsupported current_instance arguments"}
    incr scope_changes
    return $scope
}

# These are literal names emitted by native write_xdc, not a live object query.
# Only explicit object lists are supported. Never broaden an unfamiliar selector
# into a glob, hierarchy/filter query, or custom netlist traversal.
proc post_synth_tail_constraints::objects {type args} {
    variable selectors; variable scope; variable mode
    if {$mode ne {constraint}} {error "TAIL_RETAINED selector inside scope statement"}
    if {[llength $args] == 2 && [lindex $args 0] eq {-quiet}} {
        set args [lrange $args 1 end]
    }
    if {[llength $args] != 1 || [string match -* [lindex $args 0]]} {
        error "TAIL_RETAINED unsupported $type selector"
    }
    set names [lindex $args 0]
    if {![llength $names]} {error "TAIL_RETAINED empty $type selector"}
    set absolute {}
    foreach name $names {
        if {[string index $name 0] eq {/} || [regexp {(^|/)\.\.?(/|$)} $name]} {
            error "TAIL_RETAINED unsupported $type path: $name"
        }
        if {$scope ne {} && $type in {pin cell net}} {set name $scope/$name}
        # Numeric bus subscripts are exact Vivado names, not wildcard ranges.
        regsub -all {\[[0-9]+\]} $name {} plain
        if {$name eq {} || ($type eq {pin} && [string first / $name] < 1) ||
            [regexp {[\x00-\x1f\x7f*?\\\[\]]} $plain]} {
            error "TAIL_RETAINED nonliteral $type selector: $name"
        }
        lappend absolute $name
    }
    set names $absolute
    if {[llength [lsort -unique $names]] != [llength $names]} {
        error "TAIL_RETAINED duplicate $type names"
    }
    set token __tail_objects_[dict size $selectors]
    dict set selectors $token [dict create type $type names [lsort $names]]
    return $token
}

# This alias only records data. It never calls a live set_* command.
proc post_synth_tail_constraints::capture {kind args} {
    variable selectors; variable rows; variable mode
    if {$mode ne {constraint}} {error "TAIL_RETAINED constraint inside scope statement"}
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

proc post_synth_tail_constraints::read_rows {path {record_unsupported 0}} {
    variable selectors; variable rows; variable scope; variable mode; variable scope_changes
    variable unsupported; variable selected_counts
    set rows {}; set selectors {}; set scope {}; set mode {}; set scope_changes 0
    set unsupported {}; set selected_counts [dict create max_delay 0 bus_skew 0]
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
    interp alias $child current_instance {} post_synth_tail_constraints::instance
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
            if {[regexp {^(?:::)?(?:current_scope|current_design|set_hierarchy_separator)(?:\s|;|$)} $statement]} {
                error "TAIL_RETAINED unsupported scope context at line $start"
            }
            if {[regexp {^(?:::)?current_instance(?:\s|;|$)} $statement]} {
                set mode scope; set before $scope_changes
                if {[catch {interp eval $child $statement} detail] || $scope_changes != $before + 1} {
                    error "TAIL_RETAINED unsupported scope statement at line $start: $detail"
                }
            } elseif {[regexp {^(?:::)?set_(bus_skew|max_delay)(?:\s|$)} $statement -> kind]} {
                dict incr selected_counts $kind
                set mode constraint; set selectors {}; set before [llength $rows]
                set failed [catch {interp eval $child $statement} detail]
                if {$failed || [llength $rows] != $before + 1} {
                    if {!$failed} {set detail {expected one selected command}}
                    set rows [lrange $rows 0 [expr {$before-1}]]
                    if {!$record_unsupported} {
                        error "TAIL_RETAINED unsupported selected statement at line $start: $detail"
                    }
                    # Not qualified or silently discarded: full original-scope
                    # coverage is separately mandatory before any checked DCP.
                    lappend unsupported [dict create line $start scope $scope kind $kind reason $detail]
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
    variable unsupported; variable selected_counts
    set encoded {}; set rejected {}
    foreach item $unsupported {
        lappend rejected [format {{"line":%d,"scope":%s,"kind":%s,"reason":%s}} \
            [dict get $item line] [json_string [dict get $item scope]] \
            [json_string [dict get $item kind]] [json_string [dict get $item reason]]]
    }
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
        puts $handle [format {{"schema_version":1,"coverage":"original_literal_scope_presence_only","rows":[%s],"unsupported":[%s],"selected_counts":{"max_delay":%d,"bus_skew":%d}}} \
            [join $encoded ,] [join $rejected ,] [dict get $selected_counts max_delay] [dict get $selected_counts bus_skew]]
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
    set rows [post_synth_tail_constraints::read_rows $xdc 1]
    post_synth_tail_constraints::write_rows $json $rows
    return $json
}
