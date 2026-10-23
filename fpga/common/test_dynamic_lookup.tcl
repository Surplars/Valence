# Query-count and equivalence controls only; native wall time remains unmeasured.
source [file join [file dirname [info script]] test_dynamic_locked.tcl]
set calls {}
rename get_cells mock_get_cells
proc get_cells args {
    lappend ::calls [list cells {*}$args]
    return [mock_get_cells {*}$args]
}
rename get_pins mock_get_pins
proc get_pins args {
    lappend ::calls [list pins {*}$args]
    return [mock_get_pins {*}$args]
}
proc snapshot {} {return [list $::mock::cuts $::mock::bounds $::mock::queries $::mock::routing]}
proc full_scans {} {
    set count 0
    foreach call $::calls {if {[lsearch -exact $call -hierarchical]>=0} {incr count}}
    return $count
}
set saved [pwd]; set f [file tempfile temporary];close $f;file delete $temporary;file mkdir $temporary
try {
    cd $temporary
    mock::setup; set calls {}; native_dynamic_clock_constraints_impl
    set old [snapshot]; set oldScans [full_scans]
    mock::setup; set calls {}; native_dynamic_clock_constraints
    assert {[snapshot] eq $old} {Lookup optimization changed constraint/timing evidence}
    assert {!$::native_dynamic_lookup::active && $::native_dynamic_lookup::cells eq {} &&
        $::native_dynamic_lookup::owners eq {}} {Successful invocation retained objects}
    set newScans [full_scans]
    assert {$oldScans==180 && $newScans==3} {Unexpected hierarchy query count}
    set ownerQueries {};set scopeQueries 0
    foreach call $calls {
        if {[lsearch -exact $call -filter]>=0 && [lindex $call 0] eq "cells"} {incr scopeQueries}
        if {[lindex $call 0] eq "pins" && [lsearch -exact $call -of_objects]>=0 &&
            [lsearch -exact $call -filter]<0} {
            set owner [lindex $call end]
            assert {![dict exists $ownerQueries $owner]} {Duplicate owner-local pin collection}
            dict set ownerQueries $owner 1
        }
    }
    assert {$scopeQueries==1} {Expected exactly one scoped backend census}
    puts "DYNAMIC_LOOKUP_COUNTS full_hierarchy_old=$oldScans full_hierarchy_new=$newScans local_owners=[dict size $ownerQueries] NO_NATIVE_RUNTIME_CLAIM"
    # Next call must see a changed mapped design, even after a prior success.
    mock::setup; mock::put cpu_clock/mmcm REF_NAME LUT1
    assert {[catch {native_dynamic_clock_constraints} reason]} {Failed to rebuild next invocation}
    assert {!$::native_dynamic_lookup::active && $::native_dynamic_lookup::cells eq {}} {Failure retained lookup objects}
    mock::setup; native_dynamic_clock_constraints
    assert {[snapshot] eq $old} {Retry after failure changed scope}
} finally {native_dynamic_lookup::clear;cd $saved;file delete -force $temporary}
# Existing topology negatives already run in the same scoped lookup lifecycle.
reject {mock::ff {cpu_clock/lock_sync_reg[03]}} {*stage census changed*}
mock::setup;mock::cell cpu_clock_extra/unrelated FDRE;mock::cell another/cpu_clock/register FDRE
native_dynamic_lookup::begin
assert {![dict exists $::native_dynamic_lookup::cells cpu_clock_extra/unrelated]} {Similar root contaminated census}
set first {cpu_clock/lock_sync_reg[0]}
native_dynamic_exact get_pins $first/D
mock::put $first/D NAME renamed/D
assert {[catch {native_dynamic_exact get_pins $first/D} reason] && [string match {*missing/stale*} $reason]} {Stale hit accepted}
native_dynamic_lookup::clear
foreach mode {missing duplicate wrong_owner wrong_class} {
    mock::setup
    switch $mode {
        missing {dict unset ::mock::pins $first/D}
        duplicate {mock::pin $first EXTRA IN GND;mock::put $first/EXTRA NAME $first/D}
        wrong_owner {mock::put $first/D NAME cpu_clock/other/D}
        wrong_class {mock::put $first/D CLASS cell}
    }
    native_dynamic_lookup::begin
    assert {[catch {native_dynamic_exact get_pins $first/D} reason]} "Accepted $mode pin collection"
    native_dynamic_lookup::clear
}
# Explicit batch correspondence failure is not silently accepted.
mock::setup
rename get_property mock_get_property
proc get_property {key objects} {
    if {$key eq "CLASS" && [llength $objects]>1} {return cell}
    return [mock_get_property $key $objects]
}
assert {[catch {native_dynamic_lookup::begin} reason] &&
    [string match {*cardinality*} $reason]} {Truncated batch property accepted}
native_dynamic_lookup::clear
rename get_property {};rename mock_get_property get_property
puts DYNAMIC_LOOKUP_EQUIVALENCE_AND_INVALIDATION_PASS_MOCK_ONLY

# Native-cell handle regression: NAME and the cell object's Tcl representation
# are different. The complete production entry must still select the same pins.
rename get_cells named_get_cells
rename get_pins named_get_pins
rename get_property named_get_property
set opaque_names {}; set opaque_handles {}
proc get_cells args {
    set result {}
    foreach name [named_get_cells {*}$args] {
        if {![dict exists $::opaque_handles $name]} {
            set handle "native_cell#[dict size $::opaque_handles]"
            dict set ::opaque_handles $name $handle
            dict set ::opaque_names $handle $name
        }
        lappend result [dict get $::opaque_handles $name]
    }
    return $result
}
proc decode_cells {objects} {
    set result {}
    foreach object $objects {
        if {[dict exists $::opaque_names $object]} {set object [dict get $::opaque_names $object]}
        lappend result $object
    }
    return $result
}
proc get_property {key objects} {return [named_get_property $key [decode_cells $objects]]}
proc get_pins args {
    set index [lsearch -exact $args -of_objects]
    if {$index >= 0} {
        incr index
        set args [lreplace $args $index $index [decode_cells [lindex $args $index]]]
    }
    return [named_get_pins {*}$args]
}
set saved [pwd]; set f [file tempfile temporary]; close $f; file delete $temporary; file mkdir $temporary
set fixed_body [info body native_dynamic_clock_constraints_impl]
try {
    cd $temporary
    mock::setup; set calls {}; native_dynamic_clock_constraints
    assert {[snapshot] eq $old} {Opaque cell handles changed constraints or timing checks}
    assert {[full_scans] == 3} {Opaque handling added hierarchy scans}
    assert {!$::native_dynamic_lookup::active && $::native_dynamic_lookup::cells eq {}} {Opaque cache leaked}
    # Prove this fixture detects the original concatenation rather than merely
    # accepting both implementations. This temporary procedure is test-only.
    set broken_body [string map [list {$firstName/D} {[lindex $stages 0]/D}] $fixed_body]
    assert {$broken_body ne $fixed_body} {Opaque regression did not mutate implementation}
    proc native_dynamic_clock_constraints_impl {} $broken_body
    mock::setup
    assert {[catch {native_dynamic_clock_constraints} reason] &&
        [string match {*missing exact object native_cell#*} $reason]} {Original opaque concatenation was not rejected}
    assert {!$::native_dynamic_lookup::active && $::native_dynamic_lookup::cells eq {}} {Opaque failure leaked cache}
} finally {
    proc native_dynamic_clock_constraints_impl {} $fixed_body
    native_dynamic_lookup::clear
    cd $saved; file delete -force $temporary
    rename get_cells {}; rename named_get_cells get_cells
    rename get_pins {}; rename named_get_pins get_pins
    rename get_property {}; rename named_get_property get_property
}
puts DYNAMIC_LOOKUP_OPAQUE_CELL_FULL_ENTRY_PASS_MOCK_ONLY
