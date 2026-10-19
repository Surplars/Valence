# Capture exact, successfully applied scoped constraints; no wildcard certificates.
proc common_skew_begin {} {
    set ::common_skew_rows {}
    rename set_bus_skew ::common_native_set_bus_skew
    proc ::set_bus_skew {args} {
        set result [::common_native_set_bus_skew {*}$args]
        set from [lsearch -exact $args -from]; set to [lsearch -exact $args -to]
        if {$from < 0 || $to < 0 || ![string is double -strict [lindex $args 0]] || [lindex $args 0] <= 0} {
            error "Unrecognized scoped bus-skew command"
        }
        set starts [get_property NAME [lindex $args [expr {$from+1}]]]
        set ends [get_property NAME [lindex $args [expr {$to+1}]]]
        if {![llength $starts] || ![llength $ends]} {error "Empty scoped bus-skew endpoints"}
        set s [lmap name [lsort $starts] {common_json $name}]
        set e [lmap name [lsort $ends] {common_json $name}]
        lappend ::common_skew_rows [format {{"budget_ns":%s,"from":[%s],"to":[%s]}} [lindex $args 0] [join $s ,] [join $e ,]]
        return $result
    }
}
proc common_skew_end {} {
    rename set_bus_skew {}; rename ::common_native_set_bus_skew set_bus_skew
    if {![llength $::common_skew_rows]} {error "No bounded bus-skew scopes applied"}
    common_log bus-skew-scope.json [format {{"profile_sha256":"%s","phase":"%s","scopes":[%s]}} \
        $::valence(profile_sha256) $::valence(phase) [join $::common_skew_rows ,]]
}
